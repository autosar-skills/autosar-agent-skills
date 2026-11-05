# autosar-agent-skills

![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)
![dependencies: none](https://img.shields.io/badge/dependencies-none-brightgreen)
![license: MIT](https://img.shields.io/badge/license-MIT-green)
![checks: 11 + 26](https://img.shields.io/badge/checks-11%20%2B%2026-orange)
![tests: 65](https://img.shields.io/badge/tests-65-blueviolet)

[English](README.en.md) | [中文](README.md)

Agent skills for AUTOSAR Classic Platform engineering. Zero third-party
dependencies — every script is standard-library Python, so it runs inside an
air-gapped build server, a CI container, or an agent sandbox without a network
round-trip or a `pip install`.

Every skill here is self-contained: drop the directory into an agent's skill
path and the agent loads it, or run the script directly as a CLI tool.

They all target one class of engineering problem: **bugs that compile cleanly
and only surface during ECU integration testing** — a signal decoded three bits
off, a frame length that changed without anyone updating the config, a receiver
that silently drops every frame because a CRC seed moved.

## Skills

| Skill | What it does | Deps |
|---|---|---|
| [dbc-matrix-audit](https://github.com/autosar-skills/autosar-agent-skills/tree/main/skills/dbc-matrix-audit) | DBC communication matrix audit: bit-field overlap, out-of-range signals, left/right asymmetry, naming drift, GBK encoding | **none** |
| [arxml-dbc-consistency](https://github.com/autosar-skills/autosar-agent-skills/tree/main/skills/arxml-dbc-consistency) | ARXML comm-stack × DBC cross-validation: binding, DLC, bit geometry, byte order, init values, PduR routing, TX/RX direction | **none** |

Also listed on the Agensi marketplace: **[DBC Matrix Audit](https://www.agensi.io/skills/dbc-matrix-audit)** (free).
The English packages uploaded there are generated from this repo by
`tools/pack_marketplace.py`; the same input produces byte-identical output.

> Note: `LISTING.md` records the sha256 of the zip **as submitted**. Editing a
> skill's text afterwards (e.g. `8b27f44` fixed an example README) changes the
> rebuild hash — that is content changing, not broken reproducibility. To verify,
> build on the corresponding commit first, then compare.

## dbc-matrix-audit

Static auditor for DBC communication matrices: 11 structural checks, **two-revision
diff**, live frame decoding, and CSV export — standard library only.

```bash
python skills/dbc-matrix-audit/scripts/dbc_analyze.py info     matrix.dbc
python skills/dbc-matrix-audit/scripts/dbc_analyze.py messages matrix.dbc
python skills/dbc-matrix-audit/scripts/dbc_analyze.py lint     matrix.dbc
python skills/dbc-matrix-audit/scripts/dbc_analyze.py decode   matrix.dbc 0x1D2 1234052a00000000
python skills/dbc-matrix-audit/scripts/dbc_analyze.py export   matrix.dbc --csv inventory.csv
python skills/dbc-matrix-audit/scripts/dbc_analyze.py diff     old.dbc new.dbc
```

### Checks

| Code | Severity | Meaning |
|---|---|---|
| `ENC-001` | error | File is not UTF-8 (typically GBK comments) |
| `BIT-001` | error | Two signals in one frame occupy the same bit |
| `RNG-001` | error | Signal extends past the frame length |
| `DLC-001` | error | Illegal DLC |
| `ENU-001` | warn | ENUM attribute assigned a numeric index |
| `SYM-001` | warn | Left/right signal sets (L/R, A/B, FL/FR…) are asymmetric |
| `TYP-001` | warn | Same signal spelled differently once the side token is removed |
| `DUP-001` | warn | Signal name reused across frames |
| `STA-001` | info | Many signals have no `GenSigStartValue` |
| `NOD-001` | info | Transmitting node not declared in `BU_` |
| `VAL-001` | info | Short signal (≤4 bit) has no value table |

### Revision diff

| Code | Severity | Meaning |
|---|---|---|
| `DIF-GEO` | error | Signal bit definition changed |
| `DIF-DLC` | error | Frame length changed |
| `DIF-REN` | error | Frame / signal / node renamed |
| `DIF-ID` | error | Frame with the same name moved to a different CAN ID |
| `DIF-CRC` | error | DataID inside the checksum comment changed |
| `DIF-DEL` | warn | Frame or signal deleted |
| `DIF-SCL` | warn | Factor / offset changed |
| `DIF-RNG` | warn | Min / max / unit changed |
| `DIF-VAL` | warn | Value table changed |
| `DIF-CYC` | warn | Cycle time changed |
| `DIF-TX` | warn | Transmitting node changed |
| `DIF-TYP` | warn | Send type changed |
| `DIF-ADD` | info | Frame or signal added |
| `DIF-CMT` | info | Comment-only change |

Two miss patterns handled deliberately:

- **Same name, new ID.** Comparing by ID alone degrades into "one deleted + one
  added", burying the actual cause. The tool pairs by name first and suppresses
  the misleading add/delete pair.
- **CRC DataID change.** It hides inside a `CM_` comment
  (`CRC16 checksum (DataID: 0x61D2)`), so a plain comment diff reports `info`.
  The tool regex-extracts it and escalates to `error` — every receiver will
  reject the whole frame.

Renames are matched by **bit definition** (the name is precisely what changed),
so `Bus_Off_Count` → `Bus_Off_Cnt` is one `DIF-REN`, not a delete plus an add.

```bash
# Real case: NM frame moved to a new ID + CRC DataID changed — either one breaks the link
$ python skills/dbc-matrix-audit/scripts/dbc_analyze.py diff old.dbc new.dbc
[E] DIF-CRC  Node_Info_Checksum: checksum data id changed   (0x1D2)
      0x61D2 -> 0x41D2. Every receiver that validates this CRC will reject
      the frame until it is rebuilt with the new id.
[E] DIF-ID   NM_Autosar_ECU_R: CAN id changed   (0x457 -> 0x46B)
      Same name, different address: routing tables and filters still point
      at the old id.
```

Rule details and **false-positive scenarios**: [references/checks.md](https://github.com/autosar-skills/autosar-agent-skills/blob/main/skills/dbc-matrix-audit/references/checks.md).

### Why not cantools

cantools is a good library, but parsing throws away exactly what an audit needs:

| Data | cantools | This tool |
|---|---|---|
| Cycle time `GenMsgCycleTime` | ✗ | ✓ |
| Value tables `VAL_` | partial | ✓ |
| Comments `CM_` | ✗ | ✓ |
| Frame/signal attributes `BA_` | ✗ | ✓ |

cantools also **silently tolerates** GBK byte sequences — parsing appears to
succeed while every comment is lost. This tool reports `ENC-001` instead.

### Example

```bash
$ python skills/dbc-matrix-audit/scripts/dbc_analyze.py lint skills/dbc-matrix-audit/examples/demo.dbc
[I] STA-001  165/167 signals have no GenSigStartValue
      ...
summary: 0 error, 0 warn, 1 info

$ python skills/dbc-matrix-audit/scripts/dbc_analyze.py lint skills/dbc-matrix-audit/examples/demo_broken.dbc
[E] BIT-001  ACM_B_Supply_Voltage and ACM_B_Temperature occupy overlapping bits   (0x201 ACM_B_Status)
[E] DLC-001  illegal DLC 13   (0x500 Log_Snapshot)
[E] ENC-001  file is not valid UTF-8 (detected: gbk)
[E] RNG-001  Log_Word_4 extends past the frame length   (0x500 Log_Snapshot)
[W] DUP-001  signal name Node_Status_Counter appears in 2 frames
[W] ENU-001  1 ENUM attribute assignments use numeric indices
[W] SYM-001  ACM_A_Status / ACM_B_Status are not symmetric   (0x200 vs 0x201)
[W] TYP-001  same signal spelled differently (beyond the side token)
              ACM_X_Projection_State vs ACM_X_Projection_statE
summary: 4 error, 4 warn, 2 info
```

`examples/demo.dbc` is a clean synthetic matrix; `demo_broken.dbc` plants 10
classes of defect for demonstration. Both are generated by `tools/gen_demo_dbc.py`,
which computes bit allocation programmatically — they cannot structurally overlap.

## arxml-dbc-consistency

Cross-validates AUTOSAR Classic ECU configuration (Com / PduR / CanIf / CanDrv
ECUC containers) against a DBC communication matrix. 26 check codes, **standard
library only**.

```bash
python skills/arxml-dbc-consistency/scripts/arxml_dbc_check.py probe      ecuconfig.xml
python skills/arxml-dbc-consistency/scripts/arxml_dbc_check.py check      ecuconfig.xml matrix.dbc
python skills/arxml-dbc-consistency/scripts/arxml_dbc_check.py matrix     ecuconfig.xml matrix.dbc --csv inventory.csv
python skills/arxml-dbc-consistency/scripts/arxml_dbc_check.py selftest
```

`probe` inspects structure first (vendor container names, parameter names, and
where signals are mounted vary enormously); `check` then compares. `check` exits
1 on error, so it drops straight into CI.

### Why name matching cannot work

In a real configuration Com and CanIf are **not directly connected**; the only
sound binding key is the CAN ID:

```
DBC frame ──CanId──> CanIf PDU ──CanIfXxxPduRef──> EcuC Pdu(X)
                        ──PduR routing──> EcuC Pdu(COM_X)
                        ──ComPduIdRef──> Com IPdu
```

`IPDU_COM_TP_Param` has nothing name-wise in common with the DBC frame
`Diag_CalData`, yet they are the same link
(`COM_TP_Param → CanTp_TP_Param → 0x9B`). Joining by name is guaranteed wrong.

### There is exactly one correct bit-geometry formula

AUTOSAR's `ComBitPosition` always stores the signal **LSB** (flat numbering,
bit0 = LSB of byte0), **regardless of byte order**. DBC numbers Motorola signals
in sawtooth form and stores the **MSB**, so first walk back `len-1` steps:

```python
def motorola_msb_from_lsb(lsb, length):
    pos = lsb
    for _ in range(length - 1):
        pos = pos - 15 if pos % 8 == 7 else pos + 1
    return pos
```

Measured on a production project: **215/215** signals matched. An earlier version
assumed "MSB and LSB schools coexist", tried both, and accepted either — that
design is wrong: a genuine error gets whitewashed by a coincidental match, and
the measured hit rate was only 153/215.

### A whole-network matrix is not one ECU's view

A DBC may describe only this ECU (a dozen frames), or the entire network
(hundreds of frames, with many other nodes under `BU_:`). In the latter, most
frames belong to other parties and **this ECU should have no configuration for
them at all**. The script decides frame by frame — "sender is this ECU, or some
signal's receiver includes this ECU" — and only raises `error` on relevant frames.

On an 11-node, 91-frame matrix, the old "every frame must be configured"
assumption produced **99 false errors** and buried all 6 real defects.

### Bus coverage

An ARXML often drives several CAN buses at once. The script walks back through
`CanIfBufferCfg → CanIfHthCfg → CanIfHthCanCtrlIdRef` to identify the bus and
computes each bus's hit rate against the DBC: ≥20% is compared normally, <20% is
skipped wholesale with an info. The `check` header prints it, and reports must
quote it verbatim:

```
bus     CANIF_CTR_BCAN 16/21 compared | CANIF_CTR_PCAN 0/32 skipped
```

### Reference docs

- Chinese: `skills/arxml-dbc-consistency/references/checks.md`
- English: `skills/arxml-dbc-consistency/references/checks.en.md`
- English SKILL.md (for marketplace packages): `packaging/agensi/arxml-dbc-consistency/SKILL.md`

## Documentation site

Rendered docs with full schema markup: https://autosar-skills.github.io/autosar-agent-skills/

## Install

```bash
git clone https://github.com/autosar-skills/autosar-agent-skills.git
cd autosar-agent-skills
python -m unittest discover -s tests      # 65 tests, standard library only
```

No `pip install` required — the scripts run from the clone as-is. If you want
the short commands on your PATH:

```bash
pip install dbc-matrix-audit
dbc-analyze lint matrix.dbc        # DBC auditor
arxml-dbc-check check cfg.arxml matrix.dbc   # ARXML x DBC cross-check
```

> Note: `dbc-analyze` output and help are English. `arxml-dbc-check` currently
> emits Chinese messages — the audit vocabulary (bit geometry, PduR routing,
> FD flags) is identical, but the prose is not translated yet.

## Using as an agent skill

`skills/<name>/SKILL.md` follows the general AgentSkill format. Put the whole
`skills/<name>/` directory on the agent's skill path; scripts are invoked by the
relative path `scripts/dbc_analyze.py`.

SKILL.md is a **runbook for the agent** (mode detection → execution order →
output interpretation), not human documentation. This README is the human-facing
half. The split:

| Location | Reader | Contents |
|---|---|---|
| `README.md` / `README.en.md` | humans | Why it is designed this way, what rules mean, sample output |
| `SKILL.md` | agent | Step 0–4 workflow, commands, reporting format |
| `references/checks.md` | loaded on demand | Per-rule decision detail and false-positive scenarios |

OpenClaw users:

```bash
openclaw skills install skills/dbc-matrix-audit          # first install
openclaw skills install --force skills/dbc-matrix-audit  # re-sync after repo changes
openclaw skills info dbc-matrix-audit                    # confirm Ready
```

Installation **copies** the directory into `~/.openclaw/workspace/skills/`, so a
repo update requires re-running with `--force`.

## Repository layout

```
skills/dbc-matrix-audit/
├── SKILL.md                  agent runbook (Chinese: mode / flow / reporting)
├── scripts/dbc_analyze.py    implementation (single file, standard library)
├── examples/                 synthetic fixtures (clean / seeded), shipped with the skill
└── references/               rule detail, encoding notes, DBC syntax
skills/arxml-dbc-consistency/
├── SKILL.md                  bilingual runbook (mode / flow / reporting)
├── README.md                 English description (repo and marketplace)
├── scripts/arxml_dbc_check.py implementation (single file, standard library)
├── scripts/demo_fixtures.py  program-generated fixtures (topology must match production)
├── scripts/test_contract.py  bidirectional assertion: documented codes ↔ emitted codes
└── references/               checks.md (zh) / checks.en.md (en)
tools/gen_demo_dbc.py         fixture generator
tools/pack_marketplace.py     marketplace packager (reproducible, structure-checked)
tests/                        65 unit tests (including diff-specific)
packaging/agensi/             listing material: English SKILL.md / README overlays, copy archive, logo
CHANGELOG.md                  version history
dist/                         build output (gitignored, regenerate with the scripts above)
```

### Marketplace packaging

```bash
python3 tools/pack_marketplace.py                              # → dist/agensi/dbc-matrix-audit.zip
python3 tools/pack_marketplace.py --skill arxml-dbc-consistency  # → dist/agensi/arxml-dbc-consistency.zip
python3 tools/pack_marketplace.py --check                        # validate without writing
```

`SKILL.md` / `README.md` under `packaging/<market>/<skill>/` override the Chinese
originals; every other file comes from `skills/<name>/`. The flat layout
`packaging/<market>/` is still supported for older skills — only its top-level
files are read, so a sibling skill's overlay cannot leak in. The packager strips
`__pycache__`, binaries, dotfiles and symlinks, and validates "single top-level
folder + SKILL.md at its root + README present", failing otherwise. Entries are
sorted with fixed timestamps, so repeated builds are byte-identical.

## License

MIT. All sample DBC files are fictional and contain no real vehicle model,
supplier, or personnel information.

## Background

Design rationale and the debugging story behind these tools:
[How I designed an engineering-grade skill for AI agents](https://me.tech-harry.top/blog/dbc-matrix-audit-skill.html) ·
[105 errors, 99 of them fake](https://me.tech-harry.top/blog/arxml-dbc-consistency.html)
