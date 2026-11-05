#!/usr/bin/env python3
"""Build the PyPI distribution from the two single-file skill implementations.

Why a staging step: the repo keeps each tool inside its skill directory
(`skills/<name>/scripts/*.py`) because that is what an agent loads from. PyPI
wants a flat module layout. Rather than duplicating the sources or flattening
the repo, this script stages a throwaway tree and builds there, so the published
files are byte-identical to the ones the tests run against.

Usage:
    python3 tools/build_pypi.py            # → dist/*.whl, dist/*.tar.gz
    python3 tools/build_pypi.py --check    # build only, verify, no output
    python3 tools/build_pypi.py --clean    # remove dist/ then build

Requires: python3 -m pip install build twine
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")

# module name → source file inside the repo
MODULES = {
    "dbc_analyze.py": "skills/dbc-matrix-audit/scripts/dbc_analyze.py",
    "arxml_dbc_check.py": "skills/arxml-dbc-consistency/scripts/arxml_dbc_check.py",
}
EXTRA = ["pyproject.toml", "README.en.md", "LICENSE", "CHANGELOG.md"]


def stage(target):
    for name, src in MODULES.items():
        shutil.copy2(os.path.join(ROOT, src), os.path.join(target, name))
    for name in EXTRA:
        src = os.path.join(ROOT, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(target, name))
        else:
            raise SystemExit("missing required file: " + name)

    # The repo keeps each module under skills/<name>/scripts/, and pyproject
    # points package-dir there so `pip install -e .` works from a clone. The
    # staged tree is flat, so rewrite that one line for the build. Keeping the
    # rewrite here (rather than splitting into two pyproject files) means there
    # is still exactly one source of truth for version, classifiers and URLs.
    pp = os.path.join(target, "pyproject.toml")
    text = open(pp, encoding="utf-8").read()
    replaced = text.replace('"" = "skills/dbc-matrix-audit/scripts"', '"" = "."')
    if replaced == text:
        raise SystemExit("pyproject.toml: expected package-dir line not found — "
                         "the build would silently package nothing")
    open(pp, "w", encoding="utf-8").write(replaced)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="build and verify, discard output")
    ap.add_argument("--clean", action="store_true", help="remove dist/ first")
    args = ap.parse_args()

    if args.clean and os.path.isdir(DIST):
        shutil.rmtree(DIST)

    tmp = tempfile.mkdtemp(prefix="pypi-stage-")
    try:
        stage(tmp)
        print("staged in", tmp)
        for name in sorted(os.listdir(tmp)):
            print("   ", name)

        out = os.path.join(tmp, "dist") if args.check else DIST
        cmd = [sys.executable, "-m", "build", "--outdir", out, tmp]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout[-3000:])
            print(r.stderr[-3000:])
            raise SystemExit("build failed")

        files = sorted(f for f in os.listdir(out) if f.endswith((".whl", ".tar.gz")))
        print("\nbuilt:")
        for f in files:
            print("   %-52s %8d B" % (f, os.path.getsize(os.path.join(out, f))))

        chk = subprocess.run([sys.executable, "-m", "twine", "check", "--strict"]
                             + [os.path.join(out, f) for f in files],
                             capture_output=True, text=True)
        print("\ntwine check --strict:")
        print(chk.stdout.strip() or chk.stderr.strip())
        if chk.returncode != 0:
            raise SystemExit("twine check failed — PyPI would reject this")

        if args.check:
            print("\n--check: output discarded (build + verify only)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
