# Agensi listing — arxml-dbc-consistency

Submission record. Edit here first on the next revision, then re-submit.

Status: **Pending Review — submitted 2026-11-05 11:29** (2 total skills: 1 live, 1 pending).
Review takes 24-48h. Listing: `ARXML DBC Consistency`, Free.
Package: `dist/agensi/arxml-dbc-consistency.zip`, sha256 `e55258f44a7858311c7dd20893e6da06a021cbfb997b1b7cd73bbcb5fd2a14b5`
Build with `python3 tools/pack_marketplace.py --skill arxml-dbc-consistency`.
That hash only reproduces on the commit it was built from — rebuild and re-record it after
any content change.

---

## Name

```
ARXML DBC Consistency
```

## Summary (128 chars, limit 300)

```
Cross-check an AUTOSAR ECUC configuration against a DBC matrix — 26 checks on binding, bit geometry, byte order, routing.
```

## Categories

Primary: **Code Quality & Review**
Secondary: **Testing & Debugging**

## Tags

```
code-review, testing, embedded, can-bus, python, autosar, arxml, dbc, ecuc, can-fd, automotive
```

## Pricing

**Free.** Same reasoning as the DBC skill: the repository is public, a paid listing needs
payout setup and KYC first, and a free listing is the better first step.

## Full description

An AUTOSAR communication stack fails differently from ordinary software. Nothing throws. The
frame is in the matrix but not in CanIf, so neither side ever sees it. A signal's start
position is off by three bits, so the value that arrives is wrong and nothing reports it. A
CAN ID is right but the PDU is configured classic while the matrix says FD, so the 32-byte
payload is truncated on the wire.

Every one of those compiles cleanly and only shows up when two ECUs are talking.

This skill reads the ECU configuration ARXML (the Com / PduR / CanIf / CanDrv ECUC
containers) and the DBC matrix, and reports the 26 classes of disagreement between them —
using one standard-library Python script. No lxml, no cantools, nothing to install.

## What it does

- **Binding** — a frame in the matrix with no CanIf PDU, or a signal with no Com counterpart
- **Length** — CanIf DLC, Com IPdu length, a signal crossing the PDU boundary
- **Bit geometry** — start position, occupied bit set, bit width, signedness
- **Encoding** — byte order, init value, cycle time
- **Routing** — a PduR route pointing at a PDU that does not exist, or a PDU with no route at all
- **Direction** — a PDU configured TX where the matrix says this ECU is the receiver
- **FD** — matrix says CAN FD, PDU configured as classic (payload silently truncated)
- **Sanity** — the wrong DBC file supplied, duplicate CAN IDs, a bus outside the DBC's coverage

## Three things that are easy to get wrong, and what this does instead

- **Binding by name does not work.** Com and CanIf are not directly connected in a real
  configuration: the chain is `DBC frame → CanIf PDU → EcuC Pdu → PduR route → EcuC Pdu(COM)
  → Com IPdu`. `IPDU_COM_TP_Param` and the DBC frame `Diag_CalData` share no
  name similarity and are the same link. The tool binds on CAN ID and follows the routing.
- **One bit-geometry formula, not two.** AUTOSAR's `ComBitPosition` always stores the signal's
  LSB in flat numbering, independent of byte order; a DBC big-endian signal uses sawtooth
  numbering with the MSB as its start. Convert by walking back `length-1` steps. An earlier
  version tried "either convention, accept whichever matches" — it scored 153/215 on a real
  project and silently laundered genuine start-position bugs, because a wrong start sometimes
  matches under the other reading.
- **A whole-network matrix is not a single-ECU matrix.** Many frames in a network-wide DBC are
  one node talking to a third; they belong nowhere in this ECU. Judging every frame as "must be
  configured here" produced 99 false errors out of 105 on an 11-node, 91-frame matrix, burying
  every real defect. The tool decides per frame whether this ECU sends or receives it, and only
  judges those.

## How it is used

1. `probe` — what containers and parameters the vendor actually used. Run this first: vendors
   differ in container names, parameter names and where signals hang, and a blind check on an
   unparsed file reports "0 signals" rather than "parse failed"
2. `check` — the full comparison; exits 1 on errors, so it drops into CI
3. `matrix` — per-signal inventory CSV for a supplier, with a status column that separates real
   gaps from legitimate modelling differences
4. `selftest` — built-in fixture with ten planted defect classes, so you can confirm it works
   before pointing it at a real project

## Verification

26 check codes, asserted in both the Chinese and the English documentation against the code
that emits them — a code documented in one language and not the other fails the build. The
self-test asserts both the code set and the finding counts, so a drifted fixture fails instead
of printing "pass".

Developed against three unrelated vendor projects (a Puhua ECU configuration, an 厂商标 B 某 Cortex-M 控制器
configuration, and a whole-network matrix). Every parsing assumption that held for one vendor
broke on another; six parsing bugs, the CANdb++ pseudo-frame handling and the duplicate-CAN-ID
selection rule all came from those files, none from synthetic data.

Zero dependencies, MIT licensed, no network calls, no telemetry, read-only — it never modifies
the files you pass in. Source and issue tracker:
https://github.com/autosar-skills/autosar-agent-skills

## Why not just prompt it

A general model reading 480 signals across 70 Com PDUs will estimate bit positions and lose
track of which PDU a signal belongs to. This skill does the arithmetic in deterministic code
and leaves the judgement to the agent, so the findings are computed rather than plausible.

## Known limitations

Com/PduR/CanIf/CanDrv ECUC containers only — not system-description ARXML. SignalGroups and
multiplexed frames are not modelled, so a mux matrix can false-positive the overlap check. CRC
and rolling-counter algorithms are not verified, only whether the signals exist. SecOC and E2E
DataIDs are not covered. TP frames are checked for connectivity only, not segmentation
parameters. `.xdm` / `.ldf` / `.kcd` are not read. DBC-side static linting is out of scope —
that is the companion `dbc-matrix-audit` skill.

## Demo — the request

```
Validate this ECU configuration against the communication matrix before we flash it:
ecuconfig.xml and matrix.dbc

Tell me what actually blocks bench testing, and what is just the DBC being out of date.
```

## Demo — the result

Run against the skill's own bundled fixture (10 planted defects, synthetic — no customer data):

```
帧      DBC 4 / Com 3 / CanIf 4 / 路由 2
总线    (未知总线) 3/4 比对
summary: 13 error, 2 warn, 1 info
```

### Errors (excerpt)

| Code | What is wrong | Symptom |
|---|---|---|
| `AXD-001` | frame `MissingFrame` (0x300) has no CanIf PDU | neither side ever sees it |
| `AXD-003` | `CanIfTxPduCfg_100` DLC 7 vs matrix 8 | PDU truncated or over-read |
| `AXD-006` | `ProjDistortionSwitch` missing from the Com IPdu | that signal never updates |
| `AXD-008` | `ProjBrtnsAdjstReq` claims bits `[0,1,8..13]`, matrix says `[0..7]` | value decoded from the wrong bits — wrong, silently |
| `AXD-009` | `SigA` byte order BIG vs matrix LITTLE | values scrambled |
| `AXD-015` | `IPDU_COM_TestFrame` has no PduR route | nothing flows between Com and the layers below |
| `AXD-018` | bit 20 claimed by two signals | one of them is always wrong |

```
[E] AXD-008  IPDU_COM_ProjCfg.ProjBrtnsAdjstReq 位几何不一致
      Com: start=20 len=14 [big-lsb-flat] 占用 bits=[0, 1, 8, 9, 10, 11, 12, 13]…
            DBC: start=7 len=14 占用 bits=[0, 1, 2, 3, 4, 5, 6, 7]…

[E] AXD-018  IPDU_COM_ProjCfg 内信号位重叠：bit 20 被 'ProjBrtnsAdjstReq'
             与 'ProjectionAngleAdjstReq' 同时占用
```

The AXD-008 and AXD-018 lines are the same defect seen from two sides: the start position is
wrong, so the signal spills into its neighbour's bits. Nothing in the file says so — only the
geometry does.

## A real result worth quoting

On a real 11-node, 91-frame network matrix the first version of this tool produced **105
errors**, of which 99 were false: most frames in a network-wide DBC are other nodes talking to
each other. After the relevance fix the same files report **61 errors, 15 warnings**, and the
surviving findings are the ones that matter — four frames this ECU should receive but has no
configuration for, one CAN ID configured as classic while carrying 32 bytes, one signal whose
init value disagrees with the matrix (headlamp levelling start angle 0.0 vs 63.0), one swapped
TX/RX, one bit-geometry mismatch.

A report with a hundred plausible-looking lines is worse than no report.

## Compatibility note

```
Works with any agent that reads SKILL.md — Claude Code, Codex CLI, Cursor, GitHub Copilot, Gemini CLI. Requires Python 3.8+; standard library only, nothing to install, no network access, no API keys.
```

## Required tools & software

```
Python 3.8+ (standard library only, nothing to install)
```

## Permissions (to be re-verified against the built ZIP)

| Tool | Expected | Reason |
|---|---|---|
| Terminal / Shell | on | runs a Python script |
| Read Files | on | reads the ARXML and DBC you point it at |
| Write Files | on | only when you pass `--csv` to `matrix` |
| Browser | off | not needed |
| Network Access | off | no calls at all |
| Environment Variables | off | not needed |

File scopes: `**/*.xml`, `**/*.arxml`, `**/*.dbc`, `*.csv`

## Documentation URL

```
https://github.com/autosar-skills/autosar-agent-skills
```

---

## Notes for the next revision

- The demo output above is from the bundled fixture, deliberately, so no customer
  configuration appears in the listing. Real-project numbers are quoted only as aggregates
  with the identifying details removed.
- The "105 errors, 99 false" line is kept because it is the most honest thing that can be said
  about this tool: the first version was confidently wrong, and the fix is the reason to trust
  the current one.
