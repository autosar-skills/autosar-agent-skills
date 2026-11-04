# Agensi listing — copy to paste into the form

## Name
DBC Matrix Audit

## Short description (one line, appears on the card)
Lint, diff and decode CAN / CAN FD communication matrices with zero dependencies — 11 structural checks, 14 revision-diff codes, CI-ready.

## Full description

Automotive DBC matrices break silently. Two signals overlap one bit and both ECUs keep
running while the value is wrong. A frame keeps its name but moves to a new CAN id, and
routing tables point at an address nothing sends. A checksum's data id changes inside a
comment, and the receiver rejects every frame without raising an error.

This skill gives your agent the checks to catch those before integration, using one
standard-library Python script — no cantools, no pip install, nothing to pin.

**What it checks (11 codes)**

- Encoding: a GBK matrix breaks Python and CI even when Vector opens it fine
- Bit-field overlap inside a frame
- Signals that extend past the payload length
- Illegal DLC values for CAN FD
- Enum attributes written as numeric indices
- Left/right signal set asymmetry (L/R, A/B, FL/FR, LH/RH, MFL/MFR)
- Case-only spelling drift between sides (`AFSFctSt` vs `AFSFctst`)
- Duplicate signal names across frames
- Missing start values on signals where 0 is meaningful
- Transmitters not declared in the node list
- Short signals with no value table

**Revision comparison (14 codes)**

Frames added, removed, renamed, resized, retimed; transmitters and send types changed;
signal geometry, scaling, range, unit and value tables changed. Two design points worth
calling out:

- A frame that keeps its name but moves to a different CAN id is reported as a single
  id-change, not as one removal plus one addition. The naive reading buries the actual
  cause under dozens of unrelated lines.
- A checksum data id lives in free text inside a signal comment
  (`CRC16 checksum (DataID: 0x61D2)`), so a structural diff only sees "comment changed".
  It is extracted and promoted to an error, because a receiver whose checksum fails drops
  the whole frame — the symptom is silence, not a fault.

**Also included**

- Raw frame decoding against the matrix
- Signal inventory export to CSV
- GBK → UTF-8 transcoding
- Bus-load estimate from cycle times and payload sizes

**Tested**

61 unit tests. Two synthetic fixtures ship inside the skill so your agent can verify the
tool is working before touching a real matrix: one clean matrix, one with ten defect
classes planted. Both are generated with computed bit placement, so the clean one cannot
overlap by construction.

Zero dependencies, MIT licensed, no network calls, no telemetry, no file writes outside
the paths you pass in.

Source: https://github.com/autosar-skills/autosar-agent-skills

## Category
Developer Tools / Embedded / Code Quality

## Tags
autosar, can, canfd, dbc, communication-matrix, lint, embedded, automotive, code-review, c

## Price
Free to start (matches the open-source repo, and avoids the payout/KYC step before the
listing can go live). Add a paid bundle later if it gets traction.

## Notes / caveats to state in the listing
- Read-only except the explicit `fix-encoding` and `export` commands
- DBC only; does not parse ARXML, LDF or KCD
- Multiplexed signals are not modelled, so matrices using mux can produce false positives
  on the bit-overlap check
- Symmetry checks are naming heuristics and need frame names of the form `X_L_Y` / `X_R_Y`
