# cdd-arxml-consistency

Cross-check a **CANdelaStudio CDD** (diagnostic database) against an
**AUTOSAR ECU configuration ARXML**.

The CDD is what the diagnostic tester is built from. The ARXML is what the ECU
actually runs. When they disagree nothing throws, the tester still connects, and
the ECU answers `0x31 requestOutOfRange` — or the session opens and the DID
reads back the wrong length.

Zero dependencies, standard library only, read-only.

## Why this exists

There is no off-the-shelf tool for this. `canmatrix` reads system-description
ARXML (`CAN-CLUSTER` / `FRAME`), never ECUC configuration; ODX tooling works on
ODX, not on a CDD-versus-ECUC pair; the usual AUTOSAR linters check one file for
internal consistency and have no notion of the other side. Writing a generic
ECUC reader is unglamorous work, which is exactly why nobody did it.

## Install

```bash
openclaw skills install /path/to/autosar-agent-skills/skills/cdd-arxml-consistency
```

Nothing else. Python 3.8+, no `pip install`.

## Use

```bash
S=~/.openclaw/workspace/skills/cdd-arxml-consistency/scripts/cdd_arxml_check.py

python3 $S probe   <cdd> <arxml>                     # what each side actually contains
python3 $S check   <cdd> <arxml>                     # full comparison
python3 $S check   <cdd> <arxml> --json              # machine readable
python3 $S check   <cdd> <arxml> --min-severity warn # errors and warnings only
python3 $S matrix  <cdd> <arxml> -o inventory.csv    # per-item ledger for a supplier
python3 $S selftest                                  # verify the tool before trusting it
```

Exit codes: `0` no errors, `1` errors present, `2` bad arguments or unreadable
file — so it drops straight into CI.

## What it compares

25 check codes: 10 error / 12 warn / 3 info. Full list in
`references/checks.md` (中文) and `references/checks.en.md` (English).

| Area | What is cross-checked |
|---|---|
| DIDs | `DcmDspDidIdentifier` against the CDD `DIDS` entries |
| DTCs | `DemDtcValue` against the CDD instance records |
| Routines | `DcmDspRoutineIdentifier` against `rtn`-class instances |
| CAN addressing | `CAN.ReqCanId` / `ResCanId` / `ReqCanIdFunc` against CanIf PDUs |
| Timing | P2 / P2* / S3 / STmin / BlockSize |
| Sessions | `DcmDspSessionRow` levels against `ses`-class instances |
| Security | `DcmDspSecurityRow` levels against `sec`-class instances |

## Three things that are easy to get wrong

**1. Names are useless for matching.** A DID is matched by its numeric id, never
by name. `Vehicle_Identification_Number` and `Did_0xF190` are the same DID and
share no substring. Name matching fails silently: nothing looks missing, the
match simply returns nothing.

**2. A CDD carries DTCs in two unrelated places.** `RECORDDTPOOL` is the
fault-memory pool; `DIAGINST/RECORDDATAOBJ/RECORD` is what the diagnostic
instances actually reference. On one real project those two lists had **zero**
overlap — 37 versus 129. Comparing the pool against Dem reports "73 DTCs
unconfigured", which is completely wrong. The tool compares the
instance-referenced population and raises `CDX-043` to explain the mismatch.

**3. `STATICVALUE` on a security instance is the sub-function, not the level.**

```xml
<QUAL><TUV>SeedLevel1</TUV></QUAL>   ← the level is here
<STATICVALUE v='1'/>                  ← this is the sub-function (requestSeed)
```

Reading it as the level turns one level into two phantom levels, and then a
correct ARXML with a single security row is reported as "level 2 missing". The
tool derives the level from the name first.

## Deciding which side is wrong

A diff tells you two files disagree. It does not tell you which one to edit —
and editing the wrong one wastes a flash cycle and leaves the defect in place.

For diagnostic CAN ids, the tool reads `Can/CanConfigSet/CanHwFilter`
(`CanHwFilterCode` + `CanHwFilterMask`). That filter is the only place that
states, in hardware, which ids the ECU will even look at:

```
match when (frame_id & mask) == (code & mask)
```

If the filter admits the CDD's id and not CanIf's, the PDU config is what is
wrong, and the message says so. Real case: CDD `0x738`, CanIf `0x72F`, filter
mask `0x7FE` accepting only `0x738` — **CanIf is the one to fix**.

Same idea for timing: both sides are converted to integer milliseconds with a
`±1 ms` tolerance, because the CDD states `50` and AUTOSAR states `0.05`, and
binary float cannot represent `0.05` exactly — an equality test would flag every
P2 value in the file.

## Verification

```bash
python3 scripts/cdd_arxml_check.py selftest   # 6 error / 4 warn / 3 info, 13 codes
python3 scripts/test_contract.py              # docs ↔ code, both directions
```

`selftest` builds a synthetic CDD/ARXML pair with planted defects and asserts
both the per-severity totals and the exact code set. The fixture models the real
container shapes — a fixture that differs structurally validates a code path
that does not exist, and then the self-test passes while the tool is broken on
real files.

`test_contract.py` asserts that every documented code is emitted, every emitted
code is documented, and the severities agree — in both language versions.

## Not covered

Stated explicitly, because "23 checks passed" is not "the diagnostics are
correct":

- DID data length and structure (the CDD `STRUCTURE` tree vs `DcmDspData`)
- Service / sub-function session and security dependencies (`trans` vs `DcmDsdServiceSessionRef`)
- Which NRC applies to which service — only the NRC lists are counted
- Security access algorithms — only seed/key length and level
- Snapshot and extended-data record contents
- Physical/functional N_SA / N_TA consistency (read from CanTp, not cross-checked)
- DBC / communication matrices — that is `arxml-dbc-consistency` and `dbc-matrix-audit`

## Related skills

```
cdd-arxml-consistency   CDD ↔ ARXML    (diagnostic spec ↔ ECU diagnostic config)   ← this
arxml-dbc-consistency   DBC ↔ ARXML    (communication matrix ↔ ECU comms config)
dbc-matrix-audit        single-DBC lint and version diff
```

No overlap; use them together. Diagnostic-path problems start here,
communication-path problems start with `arxml-dbc-consistency`.

## License

MIT.
