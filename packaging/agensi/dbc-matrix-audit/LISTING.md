# Agensi listing — dbc-matrix-audit

Submission record. Edit here first on the next revision, then re-submit.

## Version reconciliation

| | |
|---|---|
| Marketplace status | `Live` — approved, first submission 2026-11-04 |
| Live package | sha256 `a38e3186e71937560005bdfb3bf2c75997de9e303d4b73d95e2948dc1d3271cb` |
| Repo HEAD package | sha256 `7e7709703f9feb9fa9640e6f8abc9b4c722c66e2cf392692599d88db57f21a3b` |
| Delta | `homepage:` frontmatter + a `## Links` section (blog write-up, repo). Docs only — no code, no behaviour, no check codes change. |
| Build | `python3 tools/pack_marketplace.py --skill dbc-matrix-audit` |

The live listing is one revision behind on documentation. That is deliberate: re-submitting a
live skill spends another review cycle, and nothing an agent does depends on those links.
Re-submit only when there is a reason to ship code, and carry this delta at the same time.

Note on reproducibility: `3d29d2ac…` reproduces only on the commit that was live at submission.
`8b27f44` later fixed the packaged examples README, and the `Links` section was added after
that, so rebuilding on HEAD gives a different hash. The build itself is deterministic — build
from a given commit and you get the same bytes every time.

---

## Name

```
DBC Matrix Audit
```

## Summary (128 chars, limit 300)

```
Lint, diff and decode CAN / CAN FD DBC matrices with zero dependencies — 11 structural checks, 14 revision-diff codes, CI-ready.
```

## Categories

Primary: **Code Quality & Review**
Secondary: **Testing & Debugging**

The platform defaults to `APIs & Backend`; that was wrong for this skill and was changed.

## Tags

```
code-review, testing, embedded, can-bus, python, autosar, dbc, can-fd, automotive
```

## Pricing

**Free.** A paid listing requires connecting Stripe or Zoneless and completing KYC first,
and the open-source repo is already public — a free listing is consistent and needs no
payout setup. Revisit once there is a track record.

## Full description

Automotive DBC matrices break silently. Two signals overlap one bit and both ECUs keep running while the value is wrong. A frame keeps its name but moves to a new CAN id, and routing tables point at an address nothing sends. A checksum's data id changes inside a comment, and the receiver rejects every frame without raising an error.

This skill gives your agent 11 structural lint checks and 14 revision-diff codes to catch those before integration, using one standard-library Python script — no cantools, no pip install, nothing to version-pin.

## What it does

- **Bit-field overlap** — two signals occupying the same bits inside one frame, which compiles cleanly and corrupts values at runtime
- **Payload overrun** — a signal that extends past the frame's DLC
- **Encoding** — a GBK matrix that Vector opens fine but that breaks Python and CI
- **Left/right asymmetry** — one side of the vehicle has a signal the other lacks (L/R, A/B, FL/FR, LH/RH, MFL/MFR)
- **Spelling drift** — the same signal spelled differently on each side (`AFSFctSt` vs `AFSFctst`), so code written against one side silently gets nothing from the other
- **Version diff** — frames added, removed, renamed, resized, retimed; transmitters, cycle times, scaling, ranges, units and value tables changed
- **Frame decoding** — raw hex payload interpreted against the matrix, with scaled values and enum labels
- **Inventory export** — full signal list to CSV for suppliers or documentation

## Two things a naive diff cannot express

- A frame that **keeps its name but moves to a different CAN id** is reported as a single id-change, not as one removal plus one addition. The naive reading buries the actual cause under dozens of unrelated lines.
- A **checksum data id lives in free text** inside a signal comment (`CRC16 checksum (DataID: 0x61D2)`), so a structural diff only sees "comment changed". It is extracted and promoted to an error, because a receiver whose checksum fails drops the whole frame — the symptom is silence, not a fault.

## How it is used

1. `info` — probe message count, signal count, bus load, so a large matrix is never dumped unfiltered
2. `lint` — structural audit; exits 1 on errors, so it drops straight into CI
3. `fix-encoding` then `lint` again — a GBK original must be transcoded first, or every comment-dependent check degrades silently
4. `diff` — compare a baseline against a new release, with the baseline first
5. `decode` / `export` — inspect one frame, or hand the supplier a complete inventory

## Verification

61 unit tests. Two synthetic fixtures ship inside the skill so your agent can confirm the tool works before touching a real matrix: one clean matrix, and the same matrix with ten defect classes planted. Both are generated with computed bit placement, so the clean one cannot overlap by construction.

Zero dependencies, MIT licensed, no network calls, no telemetry, no file writes outside the paths you pass in. Source and issue tracker: https://github.com/autosar-skills/autosar-agent-skills

## Why not just prompt it

A general model reading a DBC will estimate bit positions and lose track of overlaps once a frame has twenty signals. This skill does the arithmetic in deterministic code and leaves the judgement to the agent, so the findings are computed rather than plausible.

## Known limitations

Read-only except the explicit `fix-encoding` and `export` commands. DBC only — does not parse ARXML, LDF or KCD. Multiplexed signals are not modelled, so matrices using mux can produce false positives on the overlap check. Symmetry checks are naming heuristics and need frame names of the form `X_L_Y` / `X_R_Y`. CRC and rolling-counter algorithms are not verified, only whether they are declared.

## Demo — the request

```
Audit this supplier matrix before we flash it: demo_broken.dbc

Check the encoding first, then lint it. After that decode frame 0x201 with payload 0102030405060708 — I want to see what the two signals in that frame actually read.
```

## Demo — the result

## Matrix audit — demo_broken.dbc

**Conclusion: do not flash this yet.** 4 errors, 4 warnings. The file is **GBK encoded**, so it was transcoded to UTF-8 before the comment-dependent checks ran — a clean result on the transcoded copy would not have meant the original was fine.

```
encoding        gbk  [not UTF-8]
nodes           ACM_A, ACM_B, RCM, RCM_SPARE
messages        20
signals         166
CAN FD frames   12 / 20
```

### Errors (4)

| Code | Frame | What is wrong | Symptom |
|---|---|---|---|
| `BIT-001` | `0x201 ACM_B_Status` | `ACM_B_Supply_Voltage` and `ACM_B_Temperature` share 8 bits | Both sides run fine and one value is silently wrong |
| `DLC-001` | `0x500 Log_Snapshot` | DLC 13 is not a legal CAN FD size | Vector may accept it; other tools reject the frame |
| `ENC-001` | whole file | Not valid UTF-8 (GBK) | Python and CI break; Vector tolerates it and hides the problem |
| `RNG-001` | `0x500 Log_Snapshot` | `Log_Word_4` reaches byte 15 in a 13-byte frame | Receiver reads past the payload |

```
[E] BIT-001  ACM_B_Supply_Voltage and ACM_B_Temperature occupy overlapping bits   (0x201 ACM_B_Status)
      8 shared bit(s): [(5, 0), (5, 1), (5, 2), (5, 3), (5, 4), (6, 5), (6, 6), (6, 7)]

[E] DLC-001  illegal DLC 13   (0x500 Log_Snapshot)
      valid CAN FD payload sizes are 0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64
```

### Warnings (4)

`DUP-001` a signal name reused across frames · `ENU-001` enum attribute written as a numeric index · `SYM-001` `ACM_A_Status` has two signals `ACM_B_Status` lacks · `TYP-001` `ACM_X_Projection_State` vs `ACM_X_Projection_statE`

```
[W] SYM-001  ACM_A_Status / ACM_B_Status are not symmetric   (0x200 vs 0x201)
      ACM_A_Status only: 2 (ACM_X_Projection_Fault, ACM_X_Projection_statE) | ACM_B_Status only: 1
      (ACM_X_Projection_State)

[W] TYP-001  same signal spelled differently (beyond the side token)
      ACM_X_Projection_State vs ACM_X_Projection_statE
```

### Decoding 0x201 with `0102030405060708`

```
0x201 ACM_B_Status  DLC=32  payload=01 02 03 04 05 06 07 08
  ACM_B_Checksum                     = 258
  ACM_B_Counter                      = 3
  ACM_B_High_Beam_State              = 2 (On)
  ACM_B_Adaptive_Light_State         = 2 (On)
  ACM_B_Supply_Voltage               = 4.8 V
  ACM_B_Temperature                  = -16 degC
```

**This is the overlap made visible.** 4.8 V supply with the module at −16 °C is not a plausible pair — the two signals are reading the same bits, so each one's value is contaminated by the other's. Nothing in the file says this. Only the bit geometry does.

### Next steps

1. Give `ACM_B_Supply_Voltage` and `ACM_B_Temperature` disjoint bits, then re-run `lint` — expect the `BIT-001` to clear and the decoded pair to become physically sensible.
2. Fix the `DLC 13` on `0x500` to a legal size (12 or 16), then re-check `Log_Word_4` against the corrected length.
3. Ship the transcoded UTF-8 file to CI, and keep the GBK original archived — the encoding itself is a defect, not a cosmetic issue.
4. Confirm `RCM_SPARE` is intentional; an undeclared-but-present node usually means a leftover from a previous variant.

## Compatibility note

```
Works with any agent that reads SKILL.md — Claude Code, Codex CLI, Cursor, GitHub Copilot, Gemini CLI. Requires Python 3.8+ on the machine running the agent; no packages to install, no network access, no API keys.
```

## Required tools & software

```
Python 3.8+ (standard library only, nothing to install)
```

## Permissions (auto-detected from the ZIP, verified)

| Tool | Detected | Correct |
|---|---|---|
| Terminal / Shell | on | yes — runs a Python script |
| Read Files | on | yes — reads the DBC you point it at |
| Write Files | on | yes — only via explicit `fix-encoding` / `export` |
| Browser | off | yes |
| Network Access | off | yes — no calls at all |
| Environment Variables | off | yes |

File scopes: `**/*.dbc`, `*.csv`

## Documentation URL

```
https://github.com/autosar-skills/autosar-agent-skills
```

---

## Notes on what was changed from the platform's autofill

**The generated demo was fabricated.** It invented `WheelSpeed_FL`, `Engine_RPM` and
`chassis_v2.dbc`, none of which exist in this skill. A buyer running the bundled
examples would get output that does not match the listing. Replaced with a real
`info` / `lint` / `decode` run against `examples/demo_broken.dbc`.

The real output is also the better demo: `4.8 V` supply at `−16 °C` is exactly the
contaminated pair produced by the `BIT-001` overlap, so the consequence of the check is
visible rather than described.

**The generated FAQ overclaimed.** It said the tool ensures "100% reliability in signal
mapping". Rewritten to state the actual boundaries — symmetry and spelling checks are
naming heuristics, multiplexed frames are not modelled, CRC algorithms are not verified.
An absolute claim is the first thing a reviewer or buyer will test.
