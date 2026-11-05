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
import re
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
    # arxml_dbc_check's `selftest` subcommand imports this at call time, so
    # leaving it out builds fine and then fails on the user's machine with
    # ModuleNotFoundError. Caught by installing the wheel into a clean venv
    # and running `arxml-dbc-check selftest` — not by any unit test, because
    # the tests run from the repo where the module is importable.
    "demo_fixtures.py": "skills/arxml-dbc-consistency/scripts/demo_fixtures.py",
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

    # py-modules has to list every staged module. The repo's editable install
    # only needs the two entry-point modules, but the published wheel must also
    # carry demo_fixtures.py — arxml_dbc_check.selftest imports it at call time.
    want = 'py-modules = ["%s"]' % '", "'.join(sorted(m[:-3] for m in MODULES))
    new, n = re.subn(r'py-modules = \[[^\]]*\]', want, replaced)
    if n != 1:
        raise SystemExit("pyproject.toml: expected exactly one py-modules line, "
                         "found %d — refusing to guess" % n)
    open(pp, "w", encoding="utf-8").write(new)


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

        # Install the wheel into a throwaway venv and actually run both commands.
        # twine check only inspects metadata; it cannot tell you that a lazily
        # imported module is missing from the archive, which is exactly the bug
        # this step caught on 1.3.1.
        smoke = os.path.join(tmp, "smokevenv")
        subprocess.run([sys.executable, "-m", "venv", smoke], check=True,
                       capture_output=True)
        whl = [f for f in files if f.endswith(".whl")][0]
        subprocess.run([os.path.join(smoke, "bin", "pip"), "install", "-q",
                        "--no-index", "--no-deps",
                        os.path.join(out, whl)], check=True, capture_output=True)
        print("\ninstalled-wheel smoke test:")
        for cmd, check_sub in (("dbc-analyze", "--version"),
                               ("arxml-dbc-check", "selftest")):
            exe = os.path.join(smoke, "bin", cmd)
            r2 = subprocess.run([exe, check_sub], capture_output=True, text=True)
            ok = r2.returncode == 0
            tail = (r2.stdout or r2.stderr).strip().splitlines()
            print("   %-16s %-9s %s" % (cmd, check_sub,
                                        (tail[-1] if tail else "")[:70]))
            if not ok:
                print(r2.stdout[-1500:])
                print(r2.stderr[-1500:])
                raise SystemExit("%s %s failed in a clean install" % (cmd, check_sub))

        if args.check:
            print("\n--check: output discarded (build + verify only)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
