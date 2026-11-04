---
name: dbc-matrix-audit
description: |
  Audit, lint, diff and decode CAN / CAN FD communication matrices in DBC format, using one zero-dependency script.
  Use when the user asks to: audit a DBC file, check a communication matrix, find overlapping or out-of-range signals, find missing value tables, check left/right signal symmetry, look for naming drift, decode a raw CAN frame, export a signal inventory, or compare two versions of a DBC.
  Trigger phrases: "analyze this dbc", "communication matrix", "dbc check", "CAN matrix audit", "signal overlap", "signal out of range", "left right asymmetric", "naming drift", "dbc garbled", "GBK encoding", "value table missing", "decode this frame", "compare two dbc", "version diff", "what changed between these versions".
license: MIT
metadata:
  version: 1.3.0
  author: autosar-skills
  tags: [autosar, can, canfd, dbc, communication-matrix, lint, embedded]
---

# DBC Matrix Audit

Zero dependencies, standard library only. Every subcommand runs through one script:

```bash
python3 <skill>/scripts/dbc_analyze.py <subcommand> ...
```

`<skill>` is the directory containing this file.

## Step 0 — Decide the mode

Pick directly from the user's wording. **Do not ask a clarifying question.** When several rows match, run them top to bottom.

| If the user mentions | Run |
|---|---|
| overview, how many frames, how many signals, which nodes | `info` |
| list of messages, which frames exist, who sends them | `messages` |
| signals in one frame, what is in 0x1D2, what does this mean | `signals --frame` |
| check, audit, review, anything wrong, take a look | `lint` |
| compare, two versions, what changed in the upgrade, differences | `diff` |
| decode this frame, these bytes, what value is 0x... | `decode` |
| export, for the supplier, Excel, inventory | `export --csv` |
| garbled, GBK, Chinese turned into question marks, mojibake | `fix-encoding` |

If **both** "check" and "compare" appear, run `diff` first. A change to something already shipped outranks a flaw in something not yet shipped.

## Step 1 — Probe the scale first

```bash
python3 <skill>/scripts/dbc_analyze.py info <dbc>
```

This gives message count, signal count, node count and bus load. **Above 500 signals, do not run `signals` unfiltered** — narrow with `--frame` or use `export`.

## Step 2 — Encoding before anything else

When `lint` reports `ENC-001` (not valid UTF-8), **transcode first, then re-run lint**:

```bash
python3 <skill>/scripts/dbc_analyze.py fix-encoding <dbc> <dbc>_utf8.dbc
python3 <skill>/scripts/dbc_analyze.py lint <dbc>_utf8.dbc
```

Reason: in a GBK file every `CM_` comment is bad bytes. Bit-field checks still work, but **anything that depends on comments stops being reliable** — including CRC data id extraction and signal descriptions. Reading the output without transcoding first turns "cannot read the comment" into "the comment is missing", and then you recommend adding comments that were already there.

Use the transcoded file for every later command.

**⚠️ After transcoding, a clean `lint` does not mean the original file is fine.**
`ENC-001` is an error-level finding — a real defect in the original file that the transcode step repaired. If you lint only the transcoded file and report "0 errors", the user concludes the original was always clean. **The report must state that the original was GBK and was transcoded before auditing.** See Step 4.

The same applies to `diff`: **transcode both files first**, otherwise comment-level differences (including CRC data ids) cannot be read.

### Verify the tooling works

On first use, or when the environment looks wrong, check against the bundled examples:

```bash
python3 <skill>/scripts/dbc_analyze.py lint <skill>/examples/demo.dbc           # expect 0 error 0 warn
python3 <skill>/scripts/dbc_analyze.py lint <skill>/examples/demo_broken.dbc   # expect all 10 defect codes (4 error / 4 warn / 2 info)
```

## Step 3 — Run

### lint

```bash
python3 <skill>/scripts/dbc_analyze.py lint <dbc>
python3 <skill>/scripts/dbc_analyze.py lint <dbc> --json          # for scripts
python3 <skill>/scripts/dbc_analyze.py lint <dbc> --min-severity warn
```

Exit code is 1 when errors are present (usable directly in CI).

### diff

```bash
python3 <skill>/scripts/dbc_analyze.py diff <baseline/old> <target/new>
```

The first positional argument is the **baseline**. Reverse the order and every direction in the output reverses (`0x457 -> 0x46B` becomes `0x46B -> 0x457`).

Running the comparison in the opposite direction is a good check: both sides should report the same number of errors. If they differ, there is a one-sided addition or removal worth looking at separately.

### decode

```bash
python3 <skill>/scripts/dbc_analyze.py decode <dbc> 0x1D2 1234052a00000000
```

The hex payload may be shorter than the DLC (missing bytes are zero-filled) but never longer.

### export

```bash
python3 <skill>/scripts/dbc_analyze.py export <dbc> --csv inventory.csv
```

Use this whenever the user says "send it to the supplier" or asks for a spreadsheet. Do not hand-build a table.

## Step 4 — Interpret and report

**Translate every error into the symptom it causes.** The user does not care about the code `BIT-001`; they care why a lamp does not light.

| Code | Say it as |
|---|---|
| `BIT-001` | Two signals fight over one bit; both ends run normally and the value is silently wrong |
| `SYM-001` | One side is missing a signal; code on the other side reads a default of 0 |
| `TYP-001` | Code written against one side's spelling gets nothing from the other side |
| `ENC-001` | Vector tolerates it; Python and CI break on it |
| `DIF-CRC` | The receiver's checksum fails and the whole frame is rejected; the symptom is "the module ignores us", not an error |
| `DIF-ID` | Routing tables and filters still point at the old address; the frame is received by nobody |
| `DIF-REN` | Code looking up the old name silently gets nothing; no error is raised |

**Report in three fixed parts:**

1. **Conclusion** — how many errors, can this ship. **If a transcode happened, state that the original was GBK.**
2. **Evidence** — paste the key tool output verbatim.
3. **Needs confirmation** — what the tool cannot see and a human must check (below).

Group warnings by type and report them in bulk ("26 signals removed, all in the DLP projection feature"). Do not read them one by one. Info-level findings get one line or are omitted.

**Self-check**: if the report says "0 errors", go back and look at the source encoding. A clean report over a GBK original is a missed error.

## What the tool cannot see

`lint` only inspects single-file structure. The following can only be found by cross-checking with `diff` and `messages`, and **not being reported does not mean they are absent**:

- **A node declared but never transmitting** — present in `BU_`, never appears as a transmitter in any `BO_`
- **The same frame name carrying different CAN ids** — two matrices disagree on the address
- **A version log that does not match the file** — changelog stops at V1.2 while the filename says V1.4
- **A changelog claiming messages the file does not contain** — records and file disconnected
- **An attribute blanket-filled with one value** — e.g. `GenSigASIL` is 5 everywhere, which is not a real safety analysis

Rule of thumb: **report anything that would make integration behave wrongly while compiling cleanly.**

## Check codes

**error**: `ENC-001` `BIT-001` `RNG-001` `DLC-001`
**warn**: `ENU-001` `SYM-001` `TYP-001` `DUP-001`
**info**: `STA-001` `NOD-001` `VAL-001`

**diff error**: `DIF-GEO` geometry moved / `DIF-DLC` length changed / `DIF-REN` renamed / `DIF-ID` CAN id moved / `DIF-CRC` data id changed
**diff warn**: `DIF-DEL` removed / `DIF-SCL` scaling / `DIF-RNG` range or unit / `DIF-VAL` value table / `DIF-CYC` cycle time / `DIF-TX` transmitter / `DIF-TYP` send type
**diff info**: `DIF-ADD` added / `DIF-CMT` comment only

Detection detail, false-positive notes and known limits: `references/checks.md`

## Exit codes

`0` no errors ｜ `1` errors present ｜ `2` bad arguments or file problem

`--no-fail` forces exit 0.

## Limits

- Read-only; nothing is written back except `fix-encoding`
- DBC only — does not parse `.arxml` / `.ldf` / `.kcd`
- Symmetry checks are naming heuristics: frame names must look like `X_L_Y` / `X_R_Y` or `X_A_Y` / `X_B_Y`
- Does not verify CRC or rolling-counter algorithms, only whether they exist
- Multiplexed signals are not modelled; matrices using mux will produce `BIT-001` false positives

## Examples

`examples/demo.dbc` — 20 messages / 167 signals, 0 error 0 warn
`examples/demo_broken.dbc` — the same matrix with 10 defect classes planted, deliberately GBK

Both are synthetic and contain no real vehicle, supplier or personal data.
