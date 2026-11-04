# Bundled examples

| File | What it is |
|---|---|
| `demo.dbc` | A clean synthetic matrix: 20 messages / 167 signals / 12 CAN FD frames. `lint` reports 0 error 0 warn. |
| `demo_broken.dbc` | The same matrix with 10 defect classes planted: 166 signals, `lint` reports 4 error, 4 warn, 2 info. **Deliberately GBK encoded.** |

## Why `demo_broken.dbc` has one signal fewer

Planting three of the ten defects requires the signal list to change, so the two
files are not byte-identical apart from injected values:

| Change | Defect it plants |
|---|---|
| `ACM_A_Projection_State` respelled `ACM_A_Projection_statE` | `TYP-001` spelling drift |
| `ACM_B_Projection_Fault` removed from one side only | `SYM-001` left/right asymmetry |
| `Board_Temperature` replaced by `Node_Status_Counter` | `DUP-001` duplicate signal name |

Net −3 +2 = 166. This is the minimum edit that produces those three defects:
an asymmetric check cannot fire without a real asymmetry, and a duplicate name
cannot fire without a real duplicate.

## What is in the matrix

A fictional driver-assistance network: two lamp controllers `ACM_A` / `ACM_B` and a
rear control module `RCM`.

Covered: node heartbeat, vehicle motion input, ambient light and rain, lamp commands,
time synchronisation, scene bitmaps, sensor fusion, dual-node status feedback,
diagnostic snapshot, calibration block, log block, network management, thermal state,
voltage rails, diagnostic request/response.

**Every entity is fictional.** No real vehicle codename, supplier name or person appears.

## Verifying the tool works

Run these from inside this skill directory:

```bash
python3 scripts/dbc_analyze.py lint examples/demo.dbc           # 0 error, 0 warn, 1 info
python3 scripts/dbc_analyze.py lint examples/demo_broken.dbc    # 4 error, 4 warn, 2 info
python3 scripts/dbc_analyze.py decode examples/demo.dbc 0x100 0000002100000000
```

If the first two print those counts, the tool and the fixtures are both intact —
before you point it at a real matrix.

## How the fixtures were produced

`demo.dbc` is generated, not hand-written. Bit placement is computed (a Motorola cursor
advances from bit 7 as 7,6,…,0,15,14,…), so overlapping signals are structurally
impossible in the clean file. Its clean result is guaranteed by construction, not by
luck.

The defects in `demo_broken.dbc` are injected after generation, one per check code.
The generator lives in the source repository, not in this package:

https://github.com/autosar-skills/autosar-agent-skills/blob/main/tools/gen_demo_dbc.py

It is not bundled because the fixtures are already here — you only need the generator
if you want to add a defect class of your own.
