#!/usr/bin/env python3
"""Build the marketplace package for a skill.

Agensi (and most SKILL.md marketplaces) require:
  - one single top-level folder named after the skill
  - SKILL.md at the root of that folder
  - no symlinks, no hidden files, no binaries

This assembles the package from the repo, overlaying the English
SKILL.md / README.md from packaging/<market>/ when present, and writes a
reproducible zip (sorted entries, fixed timestamps) so the artifact can
be rebuilt byte-for-byte from a clean checkout.

Usage:
    python3 tools/pack_marketplace.py                 # skill=dbc-matrix-audit, market=agensi
    python3 tools/pack_marketplace.py --skill X --market Y
    python3 tools/pack_marketplace.py --check         # build + verify, do not keep

Output: dist/<market>/<skill>.zip  (gitignored — build artefact)
"""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Never ship these: binaries trip the security scan, hidden files look evasive.
EXCLUDE_DIRS = {"__pycache__", ".git", ".openclaw", ".pytest_cache", "node_modules"}
EXCLUDE_SUFFIX = {".pyc", ".pyo", ".pyd", ".so", ".o", ".a", ".exe", ".dll", ".dylib"}
EXCLUDE_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}

# A marketplace package with no README gets a lower buyer-confidence score on Agensi.
REQUIRED = ["SKILL.md", "README.md"]

# Fixed timestamp so repeated builds are byte-identical (1980-01-01, the zip epoch).
FIXED_DATE = (1980, 1, 1, 0, 0, 0)
FIXED_MODE = 0o644


def _iter_files(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_dir():
            continue
        if any(part in EXCLUDE_DIRS for part in p.relative_to(root).parts):
            continue
        if p.suffix in EXCLUDE_SUFFIX or p.name in EXCLUDE_NAMES:
            continue
        if p.name.startswith("."):
            continue
        if p.is_symlink():
            raise SystemExit(f"refusing to package symlink: {p}")
        yield p


def _overlay_for(market: str, skill: str) -> tuple[Path, bool]:
    """Return (overlay dir, whether it is skill-specific).

    `packaging/<market>/<skill>/` is the layout to use: one folder per skill, so
    each package owns its English SKILL.md / README.md / LISTING.md and a new
    skill cannot silently inherit a sibling's overlay.

    The older flat `packaging/<market>/` layout is still accepted so a checkout
    from before the split keeps building, but it is a footgun: every skill in
    that market shares the same SKILL.md. Say so on stderr instead of letting it
    work by accident.
    """
    per_skill = REPO / "packaging" / market / skill
    if per_skill.is_dir():
        return per_skill, True

    flat = REPO / "packaging" / market
    if (flat / "SKILL.md").is_file():
        print(
            f"warning: {flat.relative_to(REPO)}/ has a top-level SKILL.md but no "
            f"{skill}/ subfolder — using the shared flat overlay. Any skill in "
            f"this market will get the same SKILL.md. Move these files to "
            f"{flat.relative_to(REPO)}/{skill}/.",
            file=sys.stderr,
        )
    return flat, False


def build(skill: str, market: str) -> Path:
    src = REPO / "skills" / skill
    if not src.is_dir():
        raise SystemExit(f"no such skill: {src}")

    overlay, per_skill = _overlay_for(market, skill)
    out_dir = REPO / "dist" / market
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{skill}.zip"
    if out.exists():
        out.unlink()

    written = []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in _iter_files(src):
            rel = p.relative_to(src)
            data = p.read_bytes()
            # Overlay: an English SKILL.md / README.md wins over the repo copy.
            override = overlay / rel.name if rel.parent == Path(".") else None
            if override and override.is_file():
                data = override.read_bytes()
            _add(z, f"{skill}/{rel.as_posix()}", data)
            written.append((rel.as_posix(), len(data)))

        # Files that exist only in the packaging overlay (e.g. README.md when
        # the skill folder has none).
        #
        # Flat layout (packaging/<market>/) is shared by every skill, so only its
        # top level belongs to this package — recursing there would pull a
        # sibling skill's overlay into this zip.
        extra = _iter_files(overlay) if per_skill else [
            p for p in sorted(overlay.iterdir()) if p.is_file() and not p.is_symlink()
        ]
        for p in extra:
            if p.suffix != ".md" or p.name == "LISTING.md":
                continue  # LISTING.md is operator copy, not part of the package
            arc = f"{skill}/{p.name}"
            if any(a == arc.split("/", 1)[1] for a, _ in written):
                continue
            data = p.read_bytes()
            _add(z, arc, data)
            written.append((p.name, len(data)))

    return out


def _add(z: zipfile.ZipFile, arcname: str, data: bytes) -> None:
    info = zipfile.ZipInfo(arcname, date_time=FIXED_DATE)
    info.external_attr = (0o100000 | FIXED_MODE) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    z.writestr(info, data)


def verify(path: Path, skill: str) -> list[str]:
    """Fail loudly on the structural mistakes marketplaces reject."""
    problems = []
    with zipfile.ZipFile(path) as z:
        bad = z.testzip()
        if bad:
            problems.append(f"corrupt entry: {bad}")
        names = z.namelist()
        tops = {n.split("/")[0] for n in names}
        if tops != {skill}:
            problems.append(f"expected single top-level folder {skill!r}, got {sorted(tops)}")
        if f"{skill}/SKILL.md" not in names:
            problems.append("SKILL.md is not at the root of the top-level folder")
        for req in REQUIRED:
            if f"{skill}/{req}" not in names:
                problems.append(f"missing {req} (marketplace requires it)")
        for n in names:
            if n.endswith("/"):
                continue
            if any(part in EXCLUDE_DIRS for part in n.split("/")):
                problems.append(f"excluded dir leaked in: {n}")
            if Path(n).suffix in EXCLUDE_SUFFIX:
                problems.append(f"binary leaked in: {n}")
            if Path(n).name.startswith("."):
                problems.append(f"hidden file leaked in: {n}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill", default="dbc-matrix-audit")
    ap.add_argument("--market", default="agensi")
    ap.add_argument("--check", action="store_true", help="verify only, then remove the zip")
    args = ap.parse_args()

    out = build(args.skill, args.market)
    problems = verify(out, args.skill)

    with zipfile.ZipFile(out) as z:
        print(f"{out.relative_to(REPO)}  {out.stat().st_size} bytes  {len(z.namelist())} files")
        for i in z.infolist():
            print(f"  {i.file_size:>7}  {i.filename}")

    if problems:
        print("\nFAILED:")
        for p in problems:
            print(f"  ✗ {p}")
        out.unlink(missing_ok=True)
        return 1

    print("\n✓ single top-level folder, SKILL.md at its root, text only, README present")
    if args.check:
        out.unlink(missing_ok=True)
        print("(removed: --check)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
