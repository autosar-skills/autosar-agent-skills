# DBC Matrix Audit

A zero-dependency linter, comparator and decoder for CAN / CAN FD communication matrices
in DBC format. Standard library only — nothing to install, nothing to pin.

## What it does

| Command | Purpose |
|---|---|
| `info` | Message, signal, node counts; DLC histogram; cycle times; bus load |
| `messages` | Frame list with id, DLC, cycle, transmitter |
| `signals --frame` | Signals in one frame, with value tables, ranges and comments |
| `lint` | 11 structural checks, severity-classified, CI-ready exit code |
| `diff` | Compare two revisions: 14 difference codes |
| `decode` | Decode a raw hex payload against the matrix |
| `export --csv` | Full signal inventory, opens in Excel |
| `fix-encoding` | Transcode a GBK matrix to UTF-8 |

## Why not an existing DBC library

Mainstream parsers are built for decoding and discard exactly what an audit needs: cycle
times (`GenMsgCycleTime`), value tables (`VAL_`), comments (`CM_`) and attributes (`BA_`).
They also tend to tolerate GBK-encoded bytes silently, so a Chinese-comment file parses
"successfully" with every comment lost. Both are disqualifying for audit work.

## Install

Copy this folder into your agent's skills directory. The script needs Python 3.8+ and
nothing else.

```bash
python3 scripts/dbc_analyze.py info your_matrix.dbc
```

## Verify it works

Two fixtures ship with the skill, so you can confirm the tool is functioning before
pointing it at a real matrix:

```bash
python3 scripts/dbc_analyze.py lint examples/demo.dbc          # expect 0 error, 0 warn
python3 scripts/dbc_analyze.py lint examples/demo_broken.dbc   # expect 10 defect codes
```

`demo.dbc` is clean by construction: bit assignments are computed by a generator, not
typed by hand, so overlapping signals are structurally impossible. `demo_broken.dbc` is
the same matrix with deliberately planted defects and a GBK encoding.

## Typical use

```bash
# 1. Look before you lint
python3 scripts/dbc_analyze.py info matrix.dbc

# 2. A GBK file must be transcoded first, or every comment-dependent
#    check silently degrades
python3 scripts/dbc_analyze.py fix-encoding matrix.dbc matrix_utf8.dbc
python3 scripts/dbc_analyze.py lint matrix_utf8.dbc

# 3. Comparing revisions: the first argument is the baseline
python3 scripts/dbc_analyze.py diff old.dbc new.dbc
```

## Exit codes

`0` no errors ｜ `1` errors present ｜ `2` bad arguments or file problem

Suitable for CI as-is. `--no-fail` forces exit 0.

## Contents

```
dbc-matrix-audit/
├── SKILL.md
├── scripts/dbc_analyze.py      single file, standard library
├── references/
│   ├── checks.md               detection rules and false-positive notes
│   ├── dbc-syntax-notes.md     format notes and parsing traps
│   └── encoding.md             GBK/UTF-8 handling
└── examples/
    ├── demo.dbc                synthetic clean matrix
    ├── demo_broken.dbc         same matrix, 10 defect classes
    └── README.md
```

## Licence

MIT. The bundled matrices are synthetic and contain no real vehicle, supplier or
personal data.
