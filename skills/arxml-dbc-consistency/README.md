# ARXML ↔ DBC Consistency Check

Cross-check an AUTOSAR Classic ECU configuration ARXML against a DBC communication matrix,
with a single zero-dependency Python script.

Compiles cleanly, fails on the bench — that is the class of defect this targets. A frame
exists in the matrix but not in the stack; a signal is decoded from bits that belong to its
neighbour; a start position is off by three bits so the value is wrong but nothing raises.
None of these show up until the two ECUs are talking to each other.

```bash
python3 scripts/arxml_dbc_check.py probe   ecuconfig.xml
python3 scripts/arxml_dbc_check.py check   ecuconfig.xml matrix.dbc
python3 scripts/arxml_dbc_check.py matrix  ecuconfig.xml matrix.dbc --csv inventory.csv
python3 scripts/arxml_dbc_check.py selftest
```

Python 3.8+. Standard library only — no lxml, no cantools, nothing to install.

## What it checks

26 codes across the four layers, bound by **CAN ID** and the real PduR routing chain
(`DBC frame → CanIf PDU → EcuC Pdu → PduR route → EcuC Pdu(COM) → Com IPdu`), not by name.
Name-based matching is provably wrong: `IPDU_COM_TP_Param` and the frame
`Diag_CalData` share no name similarity and are the same link.

| Area | Examples |
|---|---|
| Binding | frame in the matrix but missing from CanIf / Com |
| Length | CanIf DLC, Com IPdu length, signal crossing the PDU boundary |
| Bit geometry | start position, occupied bit set, bit width, signedness |
| Encoding | byte order, init value, cycle time |
| Routing | dangling PduR reference, Com or CanIf PDU with no route |
| Direction | CanIf TX/RX against the DBC sender |
| FD | DBC says CAN FD but the PDU is configured as classic |
| Sanity | wrong DBC file, duplicate CAN IDs, bus outside the DBC's coverage |

## Bit geometry: one formula

AUTOSAR's `ComBitPosition` always stores the signal's **LSB** in flat numbering, independent
of byte order. A DBC big-endian signal uses sawtooth numbering with the **MSB** as its start,
so conversion walks back `len-1` steps first:

```python
def motorola_msb_from_lsb(lsb, length):
    pos = lsb
    for _ in range(length - 1):
        pos = pos - 15 if pos % 8 == 7 else pos + 1
    return pos
```

Measured on a real project: 215/215 signals match, zero failures. An earlier design that
tried "either convention, pass if one matches" scored 153/215 and — worse — laundered genuine
start-position bugs, because a wrong start sometimes matches under the other interpretation.

## Two shapes of DBC

A single-ECU DBC means every frame should be configured here. A whole-network matrix
(dozens of frames, many foreign nodes in `BU_:`) does not: most frames are one node talking to
a third, and belong nowhere in this ECU.

The script decides per frame whether this ECU sends it (`tx_node`) or receives it (its name
appears in a signal's receiver list), and only judges those. Measured on an 11-node, 91-frame
matrix, the naive "every frame must be configured" rule produced 99 false errors out of 105 —
the report was unusable and the real defects were buried.

## Bus coverage

One ARXML often drives several buses. Per bus, the script reports how many PDUs hit the DBC:
20% or more is compared, below that the bus is skipped with an info note, and the header says
so — a check that silently covered one bus out of two is worse than no check.

```
总线    CANIF_CTR_BCAN 16/21 比对 | CANIF_CTR_PCAN 0/32 跳过
```

## Output

- `check` — human report, exit 1 on errors, CI-ready; `--json` for structured output
- `matrix` — per-signal inventory CSV for suppliers, with a `status` column that separates
  real gaps from legitimate modelling differences (E2E signals written by the library, one
  OPAQUE signal covering a whole frame, NM / diagnostic / TP links)

## What it does not do

SignalGroups, multiplexed frames (can false-positive the overlap check), CRC and
rolling-counter algorithms, E2E DataIDs, SecOC, TP segmentation parameters, `.xdm` / `.ldf` /
`.kcd`. DBC-side static linting belongs to [dbc-matrix-audit](../dbc-matrix-audit/) — the two
compose.

## Verification

```bash
python3 scripts/arxml_dbc_check.py selftest   # 13 error / 2 warn / 1 info, asserts codes and counts
python3 scripts/test_contract.py              # documented codes == implemented codes, both languages
```

The self-test asserts the code set **and** the counts, so a drifted fixture fails rather than
printing "pass". Check codes are asserted in both `references/checks.md` and
`references/checks.en.md`, so a code added to one language and not the other fails too.

Validated against three unrelated vendor projects (Puhua, 厂商标 B/某 Cortex-M 控制器, and a whole-network
matrix), which is where the six real parsing bugs, the pseudo-frame handling and the
multi-config selection rule came from. Every parsing assumption that held for one vendor broke
on another.

MIT licensed. Read-only: it never modifies the files you pass in.
