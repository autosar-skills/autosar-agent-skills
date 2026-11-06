---
name: cdd-arxml-consistency
description: |
  Cross-check a CANdelaStudio CDD diagnostic database against an AUTOSAR Classic ECU configuration ARXML — data identifiers, DTCs, routines, diagnostic CAN addressing, sessions, security access, and P2/S3/STmin timing.
  Use when the user asks to: validate a CDD against an ARXML, check a diagnostic configuration, find why the tester cannot connect, explain an unexpected 0x31 requestOutOfRange, verify Dcm/Dem/CanIf/CanTp settings, or confirm the diagnostic spec matches what the ECU actually runs.
  Trigger phrases: "cdd and arxml don't match", "validate this cdd", "diagnostic database check", "DID mismatch", "DTC mismatch", "wrong diagnostic address", "tester cannot connect", "0x31 requestOutOfRange", "cannot read DID", "diagnostic spec differs from ecu", "candela check", "P2 timeout", "security access mismatch", "ecuconfig.xml".
homepage: https://me.tech-harry.top/blog/cdd-arxml-consistency.html
license: MIT
metadata:
  version: 1.1.0
  author: autosar-skills
  tags: [autosar, uds, cdd, candela, arxml, diagnostics, dcm, dem, embedded, consistency]
---

# CDD ↔ ARXML Consistency Check

The CDD is the spec the **tester** implements. The ARXML is what the ECU **actually
runs**. When they disagree, nothing fails to compile, the tester still connects —
and then the ECU answers `0x31 requestOutOfRange`, or the session opens but the
DID comes back the wrong length.

Zero dependencies, standard library only. Read-only: the input files are never
modified.

## Step 0 — Pick the mode

| What the user says | Where it goes |
|---|---|
| "these two files don't match", "compare them", "validate it" | `check` (default) |
| "what's in there", "did it parse", "show me what you read" | `probe` |
| "export a table", "give the supplier a list", "which DIDs are missing" | `matrix` |
| "can you even run this", "verify the tool first" | `selftest` |
| Only one file given | **Do not ask which one** — say both are needed: CDD + ARXML |
| Mentions DBC / communication matrix | **Not this skill** — that is `dbc-matrix-audit` |

**Never ask "which checks do you want".** All 25 run in one pass; the user wants
a verdict, not a menu.

## Step 1 — Before running

1. **Argument order**: CDD first (root element `<CANDELA>`), ARXML second (AUTOSAR
   namespace). Reversed arguments fail loudly with an explanation — do not guess.
2. **`probe` first on large files.** Both sides can exceed 5 MB. `probe` parses
   without comparing, so a few seconds tell you whether anything was read at all.
3. **Encoding is handled**: UTF-8 → GB18030 → latin-1, tried in order. The CDD's
   `<!DOCTYPE ... SYSTEM 'candela.dtd'>` is stripped; a missing DTD is fine.

```bash
SKILL=skills/cdd-arxml-consistency

# what each side actually contains
python3 $SKILL/scripts/cdd_arxml_check.py probe <cdd> <arxml>

# full comparison
python3 $SKILL/scripts/cdd_arxml_check.py check <cdd> <arxml>
```

## Step 2 — Run it

### check (default)

```bash
python3 $SKILL/scripts/cdd_arxml_check.py check <cdd> <arxml>
python3 $SKILL/scripts/cdd_arxml_check.py check <cdd> <arxml> --json            # machine readable
python3 $SKILL/scripts/cdd_arxml_check.py check <cdd> <arxml> --min-severity warn
```

Exit codes: `0` no errors ｜ `1` errors found ｜ `2` bad arguments or unreadable
file. Drop it straight into CI.

### matrix (per-item inventory)

```bash
python3 $SKILL/scripts/cdd_arxml_check.py matrix <cdd> <arxml> -o inventory.csv
```

One row per DID / DTC / routine, with a `state` column of `both` / `cdd_only` /
`arxml_only` / `arxml_unused`. Hand it to the supplier as-is.

### selftest (verify the tool before trusting it)

```bash
python3 $SKILL/scripts/cdd_arxml_check.py selftest
```

Two synthetic fixtures:

1. **A configured CDD with 11 planted defects** → expect `6 error, 4 warn, 3 info`
   and all 13 codes triggered.
2. **A CDD saved from a template with the CAN tab left empty** → must trigger
   `CDX-013`/`CDX-025` and must **not** trigger `CDX-010/011/012/020/021/022`
   (there is nothing to disagree with).

The second fixture guards against a clean-looking report rather than a crash:
eight checks skip themselves, the totals stay small, and not one line says they
never ran.

## Step 3 — Read the result out

**Order matters**: worst finding first, then the tally, then the detail.

1. **One-line verdict**: `N error, M warn, K info`, plus whether this is safe to
   flash or sign off. Any error → "do not flash or release diagnostics from this".
2. **Every error, one at a time**: symptom → consequence → which side to change.
   - `CDX-010/011/012` **decide which side is wrong** (using the hardware
     acceptance filter as tie-breaker). Follow the stated direction; do not
     change both files.
   - `CDX-013` means **the attributes were never configured**. That is not
     "inconsistent", it is "not comparable". Say explicitly that
     `CDX-010/011/012` did not run — otherwise the user reads "1 error" as
     "addresses were checked and were slightly off". The `0x700/0x750/0x600`
     quoted are CANdelaStudio template defaults, not this ECU's addresses.
   - `CDX-001/004/006` mean "the CDD has it, the ECU does not": the tester sends
     the request and the ECU rejects it.
   - `CDX-020/030/031` mean "ECU behaviour disagrees with the spec" — usually the
     ARXML is behind.
3. **Merge the warns**: more than three of the same code → one line with the
   first few ids and a total. Do not flood the terminal.
4. **Only useful info**: `CDX-043` (the CDD disagrees with itself about its DTC
   list) must be relayed, because it explains why the two sides' counts differ.
   Without it the user assumes the tool mis-parsed.
5. **Next step**: which file is authoritative, who changes what, what to re-run.

**`CDX-025` on its own**: the codes it names (`CDX-020~024`) genuinely did not
run. "No timing problems found" is wrong; "timing was not compared" is right.

**Do not:**
- Report `0 error` as "the configuration is correct" — say "these 25 checks found
  nothing", and list what is not covered (Step 4).
- Inflate a warn into an error, or call the whole config bad because warns are many.

## Step 4 — What it cannot see (state this every time)

Not covered, and the report has to say so — otherwise "25 checks passed" reads as
"the diagnostics are correct":

| Not covered | Why |
|---|---|
| DID data length and structure | The CDD `STRUCTURE` expansion is not compared bit-for-bit against `DcmDspData` |
| Session/security dependency per service | The CDD `trans` table is not cross-checked against `DcmDsdServiceSessionRef` |
| Negative response code usage | Only the two NRC lists are counted, not which service must return which NRC |
| Security access algorithm | Seed/key lengths and levels only, not the algorithm |
| Snapshot / extended record contents | Only DTC presence is compared, not the fields inside the record |
| Physical/functional N_SA/N_TA | Read from CanTp, but not matched item-by-item against the CDD address scheme |
| DBC / communication matrix | That is `arxml-dbc-consistency` and `dbc-matrix-audit` |
| Whether the CDD's values are *correct* | Only "configured" vs "not configured" is decidable. A wrong value whose filter happens to accept it will not be caught |

Three **known false positives**:
- Projects using `0x29 Authentication` instead of `0x27 SecurityAccess` may trip
  `CDX-031`.
- CDDs that record DTCs only in `RECORDDTPOOL` make `CDX-004` undercount — read
  `CDX-043` before drawing a conclusion.
- A CDD saved from a template with the CAN page still empty makes `CDX-013`/
  `CDX-025` quote template defaults. That is a signal the **spec is unfinished**,
  not a tool error, and not a reason to edit the ARXML.

## Sample output

```
[E] CDX-010  Physical request CAN id mismatch: CDD 0x738 / CanIf 0x72F  [CAN ID]
      CanIf's CanIfRxPduCfg_Phys_Req is 0x72F (1839); the CDD's CAN.ReqCanId
      is 0x738 (1848). They differ by 9. The tester sends what the CDD says,
      the ECU listens on what CanIf says — the request never reaches Dcm.
      The hardware acceptance filter contains 0x738 and not 0x72F, so the
      controller only hands 0x738 frames upward.
      Therefore the wrong side is CanIf's CanIfRxPduCfg_Phys_Req (should be
      0x738), not the CDD.
```

Read the last three sentences: not "the two files disagree", but "CanIf is wrong,
and here is the evidence". That is the difference between this tool and a diff.

## Where this sits

```
cdd-arxml-consistency   CDD ↔ ARXML  (diagnostic spec ↔ ECU diagnostic config)  ← this skill
arxml-dbc-consistency   DBC ↔ ARXML  (communication matrix ↔ ECU comms config)
dbc-matrix-audit        single-DBC static audit and version diff
```

The three do not overlap and compose. Diagnostic-link problems start here;
communication-link problems start with `arxml-dbc-consistency`.

All 25 codes, with the decision logic behind each, are in
`references/checks.md` (Chinese) and `references/checks.en.md` (English).

## Links

- Source and issues: https://github.com/autosar-skills/autosar-agent-skills
- Sibling skills: `arxml-dbc-consistency`, `dbc-matrix-audit`
