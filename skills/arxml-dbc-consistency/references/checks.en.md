# Check codes — details

26 check codes. `error` blocks flashing/bench testing, `warn` needs a human decision,
`info` is informational only.

## Layering and the real topology

The binding key is the **CAN ID**, not the name. In a real AUTOSAR config Com and CanIf
are **not** directly connected:

```
DBC frame ──CanId──> CanIf PDU ──CanIfXxxPduRef──> EcuC Pdu(X)
                          ──PduR route──> EcuC Pdu(COM_X)
                          ──ComPduIdRef──> Com IPdu
```

```
              ┌── CanDrv   CanController / CanHardwareObject
DBC frame ────┼── CanIf    CanIfTxPduCfg / CanIfRxPduCfg
              ├── PduR     PduRRoutingPath (IF / TP)
              └── Com      ComIPdu / ComSignal / ISignalToIPduMapping
```

Matching by name is wrong: `IPDU_COM_TP_Param` and the DBC frame
`Diag_CalData` share no name similarity, yet they are the same link via
`COM_TP_Param → CanTp_TP_Param → 0x9B`.

## Error level

| Code | Meaning | Symptom |
|---|---|---|
| `AXD-001` | DBC frame has no CanIf PDU (COM links only) | neither side accepts the frame, it is dropped silently |
| `AXD-003` | CanIf DLC ≠ DBC DLC (TP / diagnostic frames exempt) | PDU truncated or over-read |
| `AXD-004` | standard vs extended frame type mismatch | frame never received; also fires when CanHardwareObject covers no such ID type |
| `AXD-005` | Com IPdu length ≠ DBC DLC (TP exempt) | wrong pack length, whole frame rejected |
| `AXD-006` | DBC signal missing from Com (includes a whole IPdu missing; E2E signals exempt) | that signal never updates |
| `AXD-008` | bit geometry mismatch | value decoded from the wrong bits — wrong numbers, no runtime error |
| `AXD-009` | byte order mismatch | big/little endian flipped, values scrambled |
| `AXD-010` | bit width or signedness mismatch | signed read as unsigned, negative values become large positives |
| `AXD-011` | init value mismatch (**DBC `GenSigStartValue` is authoritative**) | sender and receiver see different values until the first update (e.g. headlamp levelling start angle) |
| `AXD-014` | PduR route points at a non-existent PDU | route dead, only surfaces at link time or runtime |
| `AXD-015` | Com / CanIf PDU has no PduR route | layers disconnected, no data flows |
| `AXD-016` | DBC marks CAN FD, CanIf configured as classic | FD frame sent as classic, payload lost. **Either side can be wrong**: if the frame's signals genuinely span more than 8 bytes, FD is a fact and the flag is what is wrong; if the frame does not belong to this ECU at all, it is a DBC content problem |
| `AXD-017` | signal crosses the IPdu boundary | writes into neighbouring bytes |
| `AXD-018` | bit overlap between signals inside Com | two signals claim the same bits, one is always wrong |
| `AXD-022` | CanIf TX/RX contradicts the DBC sender | frame never reaches the right buffer |
| `AXD-023` | DBC has no frames, or no PDU falls inside its coverage | wrong DBC file or bus backtracking failed — the run compared nothing |
| `AXD-025` | the same CAN ID has several CanIf configs **and one of them is self-contradictory** (classic frame configured with > 8 bytes) | that copy can never work |

## Warn level

| Code | Meaning | When it can be ignored |
|---|---|---|
| `AXD-000` | no Com IPdu extracted from the ARXML | never — means `probe` is not working yet |
| `AXD-002` | CanIf PDU's CAN ID is absent from the DBC | diagnostic frames, NM frames, private frames the DBC does not list |
| `AXD-007` | Com signal / IPdu absent from the DBC | dead config, or the DBC lags the code |
| `AXD-012` | cycle time mismatch | only reported after trying s/ms conversions |
| `AXD-019` | name drift (case / underscore only) | better not to ignore — hand-written code reading the old name silently gets 0 |
| `AXD-020` | Com direction contradicts the DBC sender | possible when two ECUs share one Com config |
| `AXD-025` | the same CAN ID has several CanIf configs, but each is internally consistent | **normal when two projects are merged into one ARXML** (CAN IDs happen to collide); confirm and move on |

## Info level

| Code | Meaning |
|---|---|
| `AXD-021` | baud rate value is suspiciously small — probably kbps rather than bps |
| `AXD-024` | NM / diagnostic / TP frame does not go through Com — normal topology, listed so you confirm the module is configured |
| `AXD-026` | the bus this CanIf PDU lives on is outside this DBC's coverage (see "Bus coverage") |

## Bit geometry: there is only one correct formula

**AUTOSAR's `START-POSITION` / `ComBitPosition` always stores the signal's LSB**, in flat
numbering (bit0 = LSB of byte0), **independent of byte order**.

The only difference from DBC is this: for big-endian signals the DBC uses **sawtooth
numbering** and its start position is the **MSB**. So convert as "walk back `len-1` steps to
find the MSB, then walk the sawtooth across the whole signal".

```python
def motorola_msb_from_lsb(lsb, length):
    pos = lsb
    for _ in range(length - 1):
        pos = pos - 15 if pos % 8 == 7 else pos + 1
    return pos

def motorola_bits(msb, length):
    bits, pos = set(), msb
    for _ in range(length):
        bits.add(pos)
        pos = pos + 15 if pos % 8 == 0 else pos - 1
    return bits
```

Little-endian signals simply use `range(start, start+length)`.

### Why not "try both conventions"

An early version assumed the industry had two competing conventions (MSB-first vs LSB-first)
and accepted a match from either. **That design is wrong** for two reasons:

1. **It launders real defects.** When a start position is genuinely wrong, the other
   interpretation sometimes matches by coincidence, hiding the bug.
2. **The measurements do not support it.** Grouped per PDU, `Scene_Sync` is 100%
   sawtooth (MSB) and `Node_Info` / `Time_Info` are 100% flat. It looks like two schools
   coexist — but with a single LSB→MSB back-off the result is **215/215 signals, zero
   failures**. The split was an illusion; the earlier formula simply had its direction reversed.

On one real Puhua project: single formula 215/215; the old dual-convention implementation
153 hits / 61 failures.

## Three real modelling differences

All three came out of running against real vendor files. Home-made demo data never covered
them, which is why the self-test stayed green while the tool was unusable.

### 1. The parameter tag is `-PARAM-VALUE`, not `-PARAMETER-VALUE`

Real files use `ECUC-NUMERICAL-PARAM-VALUE` / `ECUC-TEXTUAL-PARAM-VALUE`.
The script accepts both, but **reading only the long form yields no parameters at all** —
every CAN ID, DLC and length comes back as `None`, while `probe` still prints container
counts, so it looks like "the file has no configuration".

### 2. ComSignal names carry a PDU suffix

Vendors name signals `<signal>_<PDU name>`, e.g.
`ECU_R_FRTurnLampOnSt_IPDU_COM_ECU_R_St`. Note the PDU name itself starts with `IPDU_`, so
the real suffix is `_IPDU_COM_ECU_R_St` (long) or `_COM_ECU_R_St` (short). Both must be
stripped, and only on a full match, so signals that legitimately contain `_IPDU_` survive.

Skip this and nothing matches: hundreds of false `AXD-006` / `AXD-007`.

### 3. Three signal classes do not go through Com and must not be reported missing

| Class | Handled by | Treatment |
|---|---|---|
| E2E signals (Checksum / RollingCounter / CRC / AliveCounter) | written by the E2E library outside Com | not configured in Com is normal — exempt |
| Whole-frame OPAQUE / `UINT8_DYN` | Com covers the frame with one byte-array signal | DBC models it split; semantically equivalent — skip per-signal comparison |
| NM / diagnostic / TP frames | CanNm / Dcm / CanTp internally | never pass through Com — emit `AXD-024` info |

## Bus coverage

One ARXML often drives several CAN buses. The script backtracks each PDU's bus via
`CanIfBufferCfg → CanIfBufferHthRef → CanIfHthCfg → CanIfHthCanCtrlIdRef`
(RX goes `CanIfRxPduHrhIdRef → CanIfHrhCfg`), then computes each bus's hit rate against the DBC:

- **>= 20%**: the bus is inside this DBC's coverage, compare normally
- **< 20%**: this DBC does not describe that network — skip the whole bus, emit `AXD-026` info only

Measured on a Puhua project: `CANIF_CTR_PCAN` 0/32 (private CAN, not in the DBC);
`CANIF_CTR_BCAN` 16/21 (body CAN).

**The report must name the skipped bus** and ask for the matching DBC, otherwise the user
assumes the check covered everything.

## Matching strategy

1. **CanIf**: exact match on `CanIfRxPduCanId` / `CanIfTxPduCanId` against the DBC CAN ID.
   A `0x80000000` flag bit is stripped and the frame treated as extended.
2. **Com**: walk the PduR route `dest↔src` both ways looking for the `COM_`-prefixed EcuC
   Pdu, then land on the Com IPdu via `ComPduIdRef`.
3. **Direction**: the DBC `BO_` sender is compared against the set of nodes this config
   covers. Multi-node is supported — when one MCU drives both sides, the opposite side's
   frames are not misjudged as direction errors.
4. **Names**: exact name first. If exact is missing, a match after stripping non-alphanumeric
   characters is reported as name drift (`AXD-019`) and then compared geometrically, so a
   genuine geometry bug is not hidden behind a rename.

## Known limitations

- Read-only; never modifies any file
- AUTOSAR 4.x ECUC structure only
- Does not parse `.xdm` (EB tresos DataModel2), `.ldf` / `.kcd`
- `ComSignalGroup` is not parsed: grouped signals are not compared per-signal
- No validation of CRC / rolling-counter algorithms or E2E DataIDs
- Not multiplex-aware (a matrix with mux may false-positive `AXD-018`)
- `ComTxModeTimePeriod` is written in seconds or milliseconds depending on the vendor; the
  rule tries three interpretations before reporting, so `AXD-012` has a higher miss rate
  than the other rules
- TP frames are only checked for connectivity; segmentation parameters (BS / STmin) are not
  validated
- No static DBC-side checks (bit overlap, out-of-range) — that is `dbc-matrix-audit`'s job
