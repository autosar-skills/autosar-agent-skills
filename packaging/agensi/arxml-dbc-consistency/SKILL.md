---
name: arxml-dbc-consistency
description: |
  Cross-check an AUTOSAR Classic ECU configuration ARXML (Com / PduR / CanIf / CanDrv ECUC containers) against a DBC communication matrix — CAN ID binding, DLC, bit geometry, byte order, init value, cycle time, PduR routing, PDU direction.
  Use when the user asks to: validate an ARXML against a DBC, check an AUTOSAR communication stack configuration, find why a signal never arrives or a frame is never sent, verify Com/PduR/CanIf settings, or confirm ECU configuration matches the communication matrix.
  Trigger phrases: "validate this arxml", "arxml and dbc don't match", "communication stack check", "check my Com config", "signal not received", "frame not transmitted", "integration desync", "no signals after importing the dbc", "puhua arxml", "vector arxml", "ECUC check", "PduR routing".
license: MIT
metadata:
  version: 1.1.0
  author: autosar-skills
  tags: [autosar, can, dbc, arxml, ecuc, com, pdur, canif, embedded, consistency]
---

# ARXML ↔ DBC Consistency Check

Zero dependencies, standard library only. Every subcommand runs through one script:

```bash
python3 <skill>/scripts/arxml_dbc_check.py <subcommand> ...
```

`<skill>` is the directory containing this file.

## Step 0 — Decide the mode

Pick from what the user said. Do **not** ask.

| User mentions | Run |
|---|---|
| what is in this arxml, structure, can it be parsed, first time seeing this file | `probe` |
| validate, check, do they match, is this configured right, give me a report | `check` |
| inventory, cross-reference table, send to supplier, Excel | `matrix` |
| already got `AXD-000`, or no Com IPdu extracted | back to `probe` (Step 2) |

**Always `probe` a new ARXML before `check`.** Vendors differ wildly in container names,
parameter names, and where signals hang. A blind `check` reporting "0 frames / 0 signals"
means parsing failed — not that the configuration is empty.

## Step 1 — Confirm the inputs

Two files: an ARXML (ECUC configuration, not a system description) and a DBC.

```bash
file <arxml> <dbc>
```

- The ARXML must contain `ECUC-MODULE-CONFIGURATION-VALUES`. If it does not, it is a
  **system description** ARXML (`CAN-CLUSTER` / `FRAME` only) with no Com/PduR/CanIf
  configuration — say so and ask for the ECU configuration instead.
- A GBK DBC needs no transcoding; the script reads multiple encodings internally.

## Step 2 — probe

```bash
python3 <skill>/scripts/arxml_dbc_check.py probe <arxml>
```

Three things to read:

1. **modules** — must contain `Com` `PduR` `CanIf` `Can`. A missing one means the ARXML is
   incomplete; that layer's checks are skipped and recorded in `notes`.
2. **per-layer counts** — `Com IPdu 0` or `signals 0` means extraction failed.
3. **notes** — anything the script had to guess. **Empty `notes` is the good outcome**, not
   swallowed output.

If extraction fails, inspect what the vendor actually used instead of guessing field names:

```bash
python3 <skill>/scripts/arxml_dbc_check.py probe <arxml> --json | python3 -m json.tool | head -60
grep -o '<DEFINITION-REF[^>]*>[^<]*</DEFINITION-REF>' <arxml> | sed 's/.*\///;s/<.*//' | sort -u | head -40
```

Known vendor differences, all handled:

- signals under `ISignalToIPduMapping` (AUTOSAR 4.x standard) or `ComSignal` (older / EB style)
- geometry parameter named `START-POSITION` or `ComBitPosition`
- length from `ComIPduSize` / `ComIPduLength` / inferred from `CanIfTxPduDlc`
- parameters tagged `-PARAM-VALUE` or `-PARAMETER-VALUE`
- Com signal names suffixed with the PDU name, which itself starts with `IPDU_`

If none of these apply, paste the `grep` output back to the user — do not invent a field name.

## Step 3 — check

```bash
# let the script infer which DBC nodes this configuration covers
python3 <skill>/scripts/arxml_dbc_check.py check <arxml> <dbc>

# force a node, only when you deliberately want single-node behaviour
python3 <skill>/scripts/arxml_dbc_check.py check <arxml> <dbc> --node <node>
```

Run **without** `--node` first. One MCU often covers both sides of the vehicle
(`ECU_L` + `ECU_R`); forcing a single node makes the opposite side look like a direction error.

### Single-ECU view vs whole-network matrix

The two shapes need opposite judgements, and the script tells them apart automatically:

| DBC shape | Detection | Behaviour |
|---|---|---|
| Single-ECU view | few frames, `BU_:` mostly this ECU | every frame must be configured, else `AXD-001` / `AXD-006` |
| Whole-network matrix | many frames, `BU_:` full of foreign nodes | only frames this ECU sends or receives are judged; the rest are skipped silently |

"This ECU is involved" means the frame's `tx_node` is this ECU, **or** any signal's receiver
list contains it (receivers are the comma-separated tail of an `SG_` line).

So a whole-network matrix producing hundreds of errors is usually **not** a broken
configuration — check whether the ECU nodes were detected first. If the header says
`ECU 节点 (未识别)`, pass `--node`.

### Bus coverage

One ARXML often drives several CAN buses. For each bus the script reports how many of its PDUs
hit the DBC: at 20% or more it is compared normally, below that it is skipped with an
`AXD-026` info only. The header prints this verbatim — quote it in your report and name the
skipped bus, otherwise the user assumes everything was covered:

```
总线    CANIF_CTR_BCAN 16/21 比对 | CANIF_CTR_PCAN 0/32 跳过
```

In `--json` this is `bus_coverage: {bus: {hit, total, in_scope}}`.

Exit codes: `0` no errors, `1` errors found (CI-ready), `2` bad arguments or unreadable file.
`--no-fail` forces 0, `--json` emits structured output, `--min-severity` filters.

## Step 4 — Report

Fixed three parts:

1. **Verdict** — error count, ship-or-not, and which ECU nodes were detected. Say explicitly
   when direction checks were skipped.
2. **Evidence** — errors, then warnings, then infos, quoting the original lines. Collapse runs
   of more than five under one code into a single sentence ("38 signals missing, all in the
   DLP projection feature set"); do not read them out one by one.
3. **Needs a human** — what the tool cannot see (Step 5).

Translate codes into symptoms. Never report a bare code:

| Code | Say this |
|---|---|
| `AXD-001` | frame exists in the matrix but not in the stack — neither side will ever see it |
| `AXD-005` | length disagreement, the whole frame gets rejected |
| `AXD-008` | value is decoded from the wrong bits — wrong numbers, no error at runtime |
| `AXD-009` | endianness flipped, values scrambled |
| `AXD-011` | sender and receiver see different values until the first update (DBC is authoritative) |
| `AXD-015` | Com is not connected to the layers below, nothing flows |
| `AXD-018` | two signals claim the same bits, one of them is always wrong |
| `AXD-022` | TX/RX swapped, the frame never reaches the right buffer |

Rule of thumb: **anything that breaks bench testing but passes compilation is an error.**

## Step 5 — What the tool cannot check

- **SignalGroups / composite signals** — DBC `SIG_GROUP_` vs Com `ComSignalGroup` is not compared
- **Multiplexed signals** — a mux matrix can false-positive `AXD-018`; confirm the overlap is
  not inside separate mux branches
- **CRC / rolling counter** — existence only; algorithms and DataIDs are not verified
- **Com UpdateBit / Timeout** — not compared against the DBC
- **SecOC / E2E** — not covered at all
- **Cross-PDU packing (TP segmentation)** — single-frame DLC only; TP needs manual review

## Step 6 — Inventory

```bash
python3 <skill>/scripts/arxml_dbc_check.py matrix <arxml> <dbc> --csv inventory.csv
```

Use this when the user says "send it to the supplier" or "make me a comparison table".

`status` column values:

| Value | Meaning |
|---|---|
| `OK` | name and bit geometry both match |
| `名字漂移` | identical after ignoring case and underscores, already normalised |
| `几何不同` | start position or occupied bit set differs |
| `位宽不同` | signal length differs |
| `字节序不同` | byte order differs |
| `只有DBC` | in the DBC, not configured in Com — a real gap |
| `只有ARXML` | in Com, not defined in the DBC — a real surplus |
| `E2E信号未配` | checksum / rolling counter, written by the E2E library — not a difference |
| `整帧字节数组` | Com covers the frame with one OPAQUE signal; equivalent modelling |
| `不比对` | NM / diagnostic / TP link, or a bus outside this DBC |

Only the first seven need action.

## Self-test

```bash
python3 <skill>/scripts/arxml_dbc_check.py selftest   # expect 13 error / 2 warn / 1 info
python3 <skill>/scripts/test_contract.py              # documented codes vs implemented codes
```

`selftest` asserts both the code set **and** the counts. If you change the demo fixtures,
update both numbers — a drifted fixture is supposed to fail, not print "pass".

## Check codes

**error**: `AXD-001` `AXD-003` `AXD-004` `AXD-005` `AXD-006` `AXD-008` `AXD-009` `AXD-010`
`AXD-011` `AXD-014` `AXD-015` `AXD-016` `AXD-017` `AXD-018` `AXD-022` `AXD-023` `AXD-025`

**warn**: `AXD-000` `AXD-002` `AXD-007` `AXD-012` `AXD-019` `AXD-020`

**info**: `AXD-021` `AXD-024` `AXD-026`

Bit geometry derivation, matching strategy, bus coverage and known limitations:
`references/checks.en.md` (English) / `references/checks.md` (中文).

## Exit codes

`0` no errors ｜ `1` errors present ｜ `2` bad arguments or unreadable file

## Limitations

- Read-only; never modifies any file
- AUTOSAR 4.x ECUC only; 3.x partially compatible
- Does not read `.xdm` / `.ldf` / `.kcd`
- No DBC-side static linting — that is what `dbc-matrix-audit` does; the two compose
