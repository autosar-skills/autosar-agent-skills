# Agensi listing — cdd-arxml-consistency

Submission record. Edit here first on the next revision, then re-submit.

## Version reconciliation

| | |
|---|---|
| Marketplace status | `not submitted` — first submission 2026-11-06 |
| Live package | none yet |
| Repo HEAD package | `dist/agensi/cdd-arxml-consistency.zip` |
| Build | `python3 tools/pack_marketplace.py --skill cdd-arxml-consistency` |

Review takes 24-48h. 3 total skills: 2 live/pending, 1 new.

Keep the hash in step: every content change invalidates the recorded sha, so rebuild
and re-record in the same commit that changes the package.

---

## Name

```
CDD ARXML Consistency
```

## Summary (128 chars, limit 300)

```
Cross-check a CANdelaStudio CDD against an AUTOSAR ECU's Dcm/Dem/CanIf config — 25 checks, and it says which side is wrong.
```

## Categories

Primary: **Code Quality & Review**
Secondary: **Testing & Debugging**

## Tags

```
code-review, testing, embedded, automotive, autosar, uds, diagnostics, cdd, candela, arxml, dcm, dem
```

## Pricing

**Free.** The repository is public and a paid listing needs payout setup and KYC
first. Free is the better first step.

## Full description

Diagnostic configuration fails quietly. Nothing throws. The ECU boots, the tester
connects, the session opens — and then a request comes back `0x31 requestOutOfRange`,
or the DID replies with a payload three bytes shorter than the spec says, or the
security level the production line needs simply is not there.

All of it compiles. None of it logs.

The two sides are written by different people in different tools:

- the **CDD** is the diagnostic specification, written in CANdelaStudio — what the
  tester is built from
- the **ARXML** is the ECU configuration — the Dcm / Dem / CanIf / CanTp containers
  that actually run on the ECU

This skill compares them across 25 checks, using one standard-library Python script.
No lxml, no cantools, nothing to install, and it never modifies the files you pass in.

## What it does

- **DIDs** — in the spec but not configured (the tester sends, the ECU rejects), or
  configured but absent from the spec (the ECU answers something nobody documents)
- **DTCs** — the same, plus a check for the CDD disagreeing with itself about its
  own fault list
- **Routines** — an erase or check-integrity routine the flashing sequence will call
  into an ECU that never registered it
- **Diagnostic CAN addressing** — physical request, functional request, response
- **Timing** — P2 / P2\* per session, S3, STmin, block size
- **Sessions and security** — a session or a security level defined in the spec with
  no counterpart in Dcm, which means every service protected by it is locked forever

## Three things that are easy to get wrong

**It does not guess which file is wrong — it proves it.**

When a CAN ID disagrees, the obvious report is "CDD says 0x738, CanIf says 0x72F".
That is a diff, not a verdict, and it leaves the reader to change whichever file
they happen to own — half the time the wrong one. This tool reads the hardware
acceptance filters (`Can/CanConfigSet/CanHwFilter`, `Code` + `Mask`) and evaluates:

```
accepts(frame_id) := (frame_id & mask) == (code & mask)
```

If the filter accepts the CDD's id and rejects CanIf's, the controller will never
hand those frames upward and **CanIf is wrong**. The report says so, names the
parameter, and gives the value it should be. Real case: 51 filters, exactly one
accepts `0x738` (mask `0x7FE`), none accepts `0x72F`. Two independent
confirmations — the CanTp `N_SA/N_TA` of `56 = 0x38` is the low byte of `0x738`.

**"Not configured" is not "no problem".**

A CDD carries diagnostic addresses in two different places: attribute *instances*
under `<ECU>` (this ECU's configuration) and attribute *definitions* under
`DEFATTS/ECUATTS` (the CANdelaStudio template defaults). Save a template as a new
project, leave the CAN tab empty, and only the second exists.

An earlier build of this tool skipped all eight addressing and timing checks in that
situation — and the report simply never mentioned CAN ids. Which reads exactly like
"CAN ids are fine". A run where every DID, DTC and routine matched looked like a
complete review, while the addressing had never been filled in at all.

The numbers are worse than "missing": the template defaults are `0x700` / `0x600` /
`0x750`, so exporting ODX from that CDD makes the tester send requests to `0x700` —
an address no ECU on that bus is listening on.

The fix is not "fall back to the template value and compare anyway" — that produces a
confident verdict about the wrong number. The gap itself is reported: `CDX-013`
(error) and `CDX-025` (warn), each naming the checks that did not run, and each
labelling the DEFATTS numbers as template values.

**Bit-level detail is left to the layers that own it.**

This tool does not claim to verify DID payload structure, the service/session/security
dependency matrix, NRC usage per service, or the security algorithm. Those are listed
in every report as not covered, so that "25 checks passed" cannot be read as "the
diagnostics are correct".

## How it is used

1. `probe` — what each side actually contains. Run this first on 5 MB files: it takes
   a second and tells you whether anything parsed at all
2. `check` — the full comparison; exits `1` on errors, so it drops into CI
3. `matrix` — per-item inventory CSV with a `both` / `cdd_only` / `arxml_only` /
   `arxml_unused` column, for handing to a supplier
4. `selftest` — two built-in fixtures so you can confirm it works before pointing it
   at a real project

## Verification

25 check codes, asserted in both the Chinese and English documentation against the
code that emits them, in both directions: documented but never emitted fails the
build, and so does emitted but not written down. Severity mismatches fail too.

Two self-test fixtures. The first has 11 planted defect classes and asserts both the
code set and the finding counts. The second is a CDD with the CAN tab left empty —
it asserts that `CDX-013`/`CDX-025` fire *and* that `CDX-010/011/012/020/021/022` do
not, because "no comparable attributes" must not be reported as "attributes disagree".

Checked against two unrelated tier-1 supplier projects. The second one is what found
the silent-skip bug: its CDD was a template save with an empty CAN page, and the
first report came back looking clean.

Zero dependencies, MIT licensed, no network calls, no telemetry, read-only. Source
and issue tracker: https://github.com/autosar-skills/autosar-agent-skills

## Why not just prompt it

A general model comparing 129 DTCs and 53 DIDs will lose track of which side a
mismatch came from, and has no way to consult a hardware acceptance filter. This skill
does the set arithmetic and the mask evaluation in deterministic code and leaves the
judgement to the agent.

## Known limitations

Physical request / functional request / response CAN ids, P2/P2\*/S3/STmin/BS,
DIDs, DTCs, routines, sessions and security levels only. DID data length and
structure, the service-session-security dependency matrix, NRC usage ranges, the
security algorithm itself, snapshot and extended-data record contents, and item-by-item
N_SA/N_TA matching against the CDD address scheme are **not** covered — and every report
says so. `0x29 Authentication` projects may false-positive the security check.
`.ldf` / `.kcd` / `.odx` are not read. Communication-matrix work is the companion
`arxml-dbc-consistency` and `dbc-matrix-audit` skills.

## Demo — the request

```
Validate this CDD against the ECU configuration before we hand it to the test house:
EHV_LCU.cdd and ecuconfig.xml

Tell me what would actually break on the bench, not just what differs.
```

## Demo — the result

```
DID     CDD 38 / Dcm 60 交集 38
DTC     CDD 129 / Dem 129 交集 129
例程    CDD 4 / Dcm 4 交集 4
会话    CDD 3 / Dcm 3
安全    CDD 1 / Dcm 1
summary: 1 error, 2 warn, 3 info
```

### The error

```
[E] CDX-010  Physical request CAN id mismatch: CDD 0x738 / CanIf 0x72F  [CAN ID]
      CanIf's CanIfRxPduCfg_Phys_Req is 0x72F (1839); the CDD's CAN.ReqCanId is
      0x738 (1848). They differ by 9. The tester sends what the CDD says, the ECU
      listens on what CanIf says — the request never reaches Dcm.
      The hardware acceptance filter contains 0x738 and not 0x72F, so the controller
      only hands 0x738 frames upward.
      Therefore the wrong side is CanIf's CanIfRxPduCfg_Phys_Req (should be 0x738),
      not the CDD.
```

129 DTCs and 38 DIDs match exactly. The single thing that would have failed on the
bench is a nine-count difference in one CAN id — and the report states which file to
open.

### The second project

A CDD saved from a template with the CAN page empty:

```
summary: 3 error, 3 warn, 2 info
[E] CDX-013  CDD lacks 3 diagnostic CAN addresses; related comparison skipped
[E] CDX-006  3 routines in the CDD, not configured in Dcm
[E] CDX-031  1 security level defined in the CDD only
[W] CDX-025  CDD lacks 5 timing parameters; related comparison skipped
```

`0xF001 CheckProgrammingIntegrity`, `0xFF00 eraseMemory` and
`0xFF01 CheckProgrammingDependencies` are in the spec but not in Dcm — the flashing
sequence would call `31 01 FF00` and get `0x31` back. Meanwhile `0xDF20`/`0xDF21`
(key injection routines) are configured in Dcm and deliberately absent from the
after-sales spec, which is the correct direction.

## Compatibility note

```
Works with any agent that reads SKILL.md — Claude Code, Codex CLI, Cursor, GitHub Copilot, Gemini CLI. Requires Python 3.8+; standard library only, nothing to install, no network access, no API keys.
```

## Required tools & software

```
Python 3.8+ (standard library only, nothing to install)
```
