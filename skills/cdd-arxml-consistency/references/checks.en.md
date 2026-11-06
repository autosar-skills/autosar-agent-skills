# Check reference — cdd-arxml-consistency

**25 check codes**: **10 error / 12 warn / 3 info**.

Severity:
- **error** — the diagnostic will fail or read the wrong value; flashing or
  signing off on this will cause a problem.
- **warn** — it runs, but the spec and the implementation disagree. Turns into
  a problem eventually.
- **info** — a fact for orientation, not a defect.

---

## 1. Data identifiers (DID)

| Code | Severity | Test | Consequence and which side to fix |
|---|---|---|---|
| `CDX-001` | error | DID in the CDD `DIDS`, absent from Dcm `DcmDspDid` | The tester reads per spec, the ECU answers `0x31`. **Fix the ARXML** |
| `CDX-002` | warn | DID in `DcmDspDid`, absent from the CDD | The ECU supports it, the spec does not describe it. **Fix the CDD** |
| `CDX-003` | warn | On both sides, but `DcmDspDidUsed=false` | Container exists but is disabled; reads still answer `0x31` |

**Matching key**: the numeric `DcmDspDidIdentifier` against the CDD's decimal
`<DID n='...'>`. Numeric on both sides, **never by name** — names drift between
suppliers, and a name-based match fails silently rather than loudly.

---

## 2. Diagnostic trouble codes (DTC)

| Code | Severity | Test | Consequence and which side to fix |
|---|---|---|---|
| `CDX-004` | error | DTC referenced by a CDD diagnostic instance, absent from `DemDTC` | The spec can read its parameters; the ECU never sets it. **Fix the ARXML** |
| `CDX-005` | warn | DTC in `DemDTC`, absent from the CDD | The ECU sets it, the tester cannot interpret it. **Fix the CDD** |
| `CDX-043` | info | The CDD disagrees with itself between `RECORDDTPOOL` and its instance records | Explains a count mismatch; **not** an instruction to add DTCs |

### Why `CDX-043` has to exist

A CANdela export carries DTCs in two unrelated places:

```
ECUDOC/RECORDDTPOOL/RECORDDT/RECORD        ← fault-memory pool (template/planning)
ECUDOC/…/DIAGINST/RECORDDATAOBJ/RECORD     ← what the diagnostic instances reference
```

These are not the same list. On one real project: 37 in the pool, 129 referenced
by instances, **overlap 0**. Comparing the pool against Dem would have produced
"all 73 DTCs are unconfigured", which is completely wrong.

So:
- Only the instance-referenced population is compared against Dem.
- When the two differ, `CDX-043` reports it in one of two wordings:
  - overlap > 0 → "self-contradictory", with the difference in both directions;
  - overlap == 0 → "completely disjoint", stating clearly that these are two
    different kinds of list, not a gap.

---

## 3. Routines

| Code | Severity | Test | Consequence and which side to fix |
|---|---|---|---|
| `CDX-006` | error | Routine id in the CDD, absent from `DcmDspRoutine` | The diagnostic sequence fails on call. **Fix the ARXML** |
| `CDX-007` | warn | Routine id in `DcmDspRoutine`, absent from the CDD | Not specified; the tester never calls it. **Fix the CDD** |

ARXML side reads `DcmDspRoutineIdentifier`; the CDD side reads the
`STATICVALUE` of an `rtn`-class instance.

---

## 4. Diagnostic CAN addressing

| Code | Severity | CDD attribute | CanIf role | Consequence |
|---|---|---|---|---|
| `CDX-010` | error | `CAN.ReqCanId` | `phys_req` | Requests never reach Dcm |
| `CDX-011` | warn | `CAN.ReqCanIdFunc` | `func_req` | Functional addressing (e.g. OBD broadcast) breaks |
| `CDX-012` | error | `CAN.ResCanId` | `resp` | The ECU answers, the tester never sees it |
| `CDX-013` | error | All three missing | — | The three rows above never ran; not a pass |

### Role detection

CanIf PDU naming varies per supplier, so roles are detected by keyword, not by
an expected name:

- name contains `func` → functional request
- name contains `phys`, `physical` or `phy` → physical request
  (`DiagPhyReq_LDLP`-style abbreviations are common)
- name contains `resp` → response

The value is read from `CanIfRxPduCanId` / `CanIfTxPduCanId`.

### Why `CDX-013` has to exist

This one is a bug the tool shipped with, not a hypothetical.

`CAN.ReqCanId` and friends reach a CDD from two different places:

1. an attribute **instance** under `<ECU>` — `<UNS attrref='_...' v='1848'/>`;
   this is the configuration for this ECU
2. an attribute **definition** under `DEFATTS/ECUATTS` —
   `<UNSDEF id='_...' v='1792'>`; this is the template default

Save a template as a new project, leave the CAN tab empty, and only (2) exists.
The parser finds no attribute value, and the `CDX-010/011/012` branches each
`continue`. **Nothing about CAN ids appears in the report at all.**

That is the trap: "the report never mentioned CAN ids" and "the CAN ids are
fine" produce the same output. A run where every DID, DTC and routine matches
reads like a complete review, while the addressing was never filled in.

`CDX-013` turns the gap into an error and labels the `DEFATTS` numbers as
**template values**, not configuration — exporting ODX from them makes the
tester send requests to `0x700`.

`CDX-025` covers the five timing attributes. It stays a warn: an unset P2 does
not make the CDD unusable, but the reader has to know that `CDX-020~024` did
not run.

### Deciding which side is wrong

This is what separates the tool from a plain diff. It does not guess — it reads
`Can/CanConfigSet/CanHwFilter` (`CanHwFilterCode` + `CanHwFilterMask`):

```
match when (frame_id & mask) == (code & mask)
```

Five outcomes:

| Filter state | Verdict |
|---|---|
| Accepts the CDD id, rejects the CanIf id | **CanIf is wrong**, should be the CDD id |
| Accepts the CanIf id, rejects the CDD id | **The CDD is wrong**, should be the CanIf id |
| Accepts both (mask has don't-care bits) | Cannot decide; needs a human |
| Accepts neither | The filter is wrong too; check all three |
| No `CanHwFilter` in the ARXML | Cannot decide; needs a human |

Real case: CDD `0x738`, CanIf `0x72F`, filter accepts only `0x738` (mask
`0x7FE`) — **CanIf is the wrong one**. The fix direction is stated, not guessed.

---

## 5. Timing

| Code | Severity | Test | Consequence |
|---|---|---|---|
| `CDX-020` | error | Session `DcmDspSessionP2ServerMax` ≠ CDD `CAN.P2Server` | ECU answers later than the tester waits → no response |
| `CDX-021` | warn | `P2StarServerMax` ≠ `CAN.P2ExServer` | Different timeout after `0x78`; flashing aborts mid-way |
| `CDX-022` | warn | Within the CDD: `S3Client < S3Server` | Session drops back to Default periodically |
| `CDX-023` | warn | `CanTpSTmin` ≠ CDD `CAN.StMin` | Multi-frame transfers drop frames |
| `CDX-024` | warn | `CanTpBs` ≠ CDD `CAN.Blocksize` | Flow-control cadence misaligns |
| `CDX-025` | warn | Any of the five attributes above is missing | `CDX-020~024` did not run; not a pass |

### Why timings compare as integer milliseconds

The CDD states `50` (milliseconds), AUTOSAR states `0.05` (seconds). Binary
floating point cannot represent `0.05` exactly, so an equality test flags
**every P2 value in the file**. Both sides are converted to integer
milliseconds with a `±1 ms` tolerance.

`CDX-022` is an internal consistency check on the CDD alone — it catches a typo
in the specification itself, independent of the ARXML.

---

## 6. Sessions and security access

| Code | Severity | Test | Consequence and which side to fix |
|---|---|---|---|
| `CDX-030` | error | Session level only in the CDD, no `DcmDspSessionRow` | Switching answers `0x12`. **Fix the ARXML** |
| `CDX-031` | error | Security level only in the CDD, no `DcmDspSecurityRow` | All protected services at that level are unreachable. **Fix the ARXML** |
| `CDX-032` | warn | Seed and key lengths differ at the same level | Most stacks require equal lengths; confirm with the supplier |

### The security-level parsing trap

A CDD `sec` instance looks like this:

```xml
<DIAGINST tmplref="...">
  <QUAL><TUV>SeedLevel1</TUV></QUAL>      ← the level lives here (Level1)
  <STATICVALUE v='1'/>                     ← this is the sub-function (1 = requestSeed)
</DIAGINST>
<DIAGINST tmplref="...">
  <QUAL><TUV>KeyLevel1</TUV></QUAL>
  <STATICVALUE v='2'/>                     ← sub-function again (2 = sendKey)
</DIAGINST>
```

**`STATICVALUE` is the sub-function, not the level.** Reading it as the level
turns one level into two phantom levels, and then a perfectly correct ARXML with
a single `DcmDspSecurityRow` is reported as "level 2 missing".

Resolution order (`security_level_from_name()`):

1. an explicit `Level<N>` in the name (`SeedLevel1` → 1)
2. the whole name is numeric (`Level_1` → 1)
3. only then fall back to the sub-function value

---

## 7. Sanity

| Code | Severity | Test | Meaning |
|---|---|---|---|
| `CDX-040` | error | Nothing at all was compared | **Not a pass**: wrong file or unexpected structure — run `probe` first |
| `CDX-041` | warn | Duplicate identifier on one side | Last definition wins; behaviour depends on the tool |
| `CDX-042` | info | File overview | Protocol, DTD version, encodings, module count |
| `CDX-044` | info | Service coverage | How many CDD protocol services resolve to a SID, which ones cannot be mapped, and which services Dcm configures explicitly |

`CDX-040` is the safety gate: `0 error` only means something when something was
actually compared. If DID / DTC / CAN id / session are all empty, the tool fails
loudly instead of reporting success.

---

## 8. Code list (asserted against the code in both directions)

```
error (10) CDX-001 004 006 010 012 013 020 030 031 040
warn  (12) CDX-002 003 005 007 011 021 022 023 024 025 032 041
info  (3)  CDX-042 043 044
```

`scripts/test_contract.py` asserts that this file and the implementation agree
in both directions: documented but not emitted → red; emitted but not
documented → also red; severity mismatch → also red.

---

## 9. Known false positives

| Situation | Symptom | Handling |
|---|---|---|
| `0x29 Authentication` used instead of `0x27` | `CDX-031` may misfire | Confirm and ignore until 0x29 is supported |
| The CDD keeps DTCs in `RECORDDTPOOL` only | `CDX-004` count is too high | Read `CDX-043` before drawing conclusions |
| The same DID defined in several CDD entries (per session) | `CDX-041` reports a duplicate | Legitimate modelling, not a defect |
| No `CanHwFilter` configured | `CDX-010` says it cannot decide | Expected; decide manually |
