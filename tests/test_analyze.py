# tests/test_analyze.py
"""Tests for dbc_analyze. Run with:  python -m unittest discover -s tests"""

from __future__ import annotations

import importlib.util
import io
import json
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "dbc-matrix-audit" / "scripts" / "dbc_analyze.py"
EXAMPLES = ROOT / "skills" / "dbc-matrix-audit" / "examples"

spec = importlib.util.spec_from_file_location("dbc_analyze", SCRIPT)
assert spec and spec.loader
dbc = importlib.util.module_from_spec(spec)
sys.modules["dbc_analyze"] = dbc
spec.loader.exec_module(dbc)


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = dbc.main(argv)
    return code, buf.getvalue()


class TestParsing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = dbc.parse_dbc(EXAMPLES / "demo.dbc")

    def test_message_count(self):
        self.assertEqual(len(self.db.messages), 20)

    def test_signal_count(self):
        self.assertEqual(self.db.total_signals(), 167)

    def test_nodes(self):
        self.assertEqual(self.db.nodes, ["ACM_A", "ACM_B", "RCM"])

    def test_encoding_is_utf8(self):
        self.assertTrue(self.db.utf8_clean)
        self.assertEqual(self.db.encoding, "utf-8")

    def test_cycle_time_from_attribute(self):
        msg = self.db.by_id(0x100)
        self.assertEqual(msg.cycle_time, 20)

    def test_value_table_parsed(self):
        msg = self.db.by_id(0x100)
        mode = next(s for s in msg.signals if s.name == "Work_Mode")
        self.assertEqual(mode.value_table[2], "Active")
        self.assertEqual(mode.value_table[15], "Invalid")

    def test_signal_comment_parsed(self):
        msg = self.db.by_id(0x100)
        counter = next(s for s in msg.signals if s.name == "Node_Status_Counter")
        self.assertIn("rolling counter", counter.comment)

    def test_message_comment_parsed(self):
        self.assertIn("heartbeat", self.db.by_id(0x100).comment)

    def test_send_type_string_not_number(self):
        self.assertEqual(self.db.by_id(0x100).send_type, "Cyclic")

    def test_can_fd_frames(self):
        fd = [m for m in self.db.messages if m.is_fd]
        self.assertEqual(len(fd), 12)

    def test_no_bit_overlap_in_clean_file(self):
        self.assertEqual(dbc.check_bit_overlap(self.db), [])

    def test_no_out_of_range_in_clean_file(self):
        self.assertEqual(dbc.check_out_of_range(self.db), [])


class TestEncoding(unittest.TestCase):
    def test_utf8_sniff(self):
        enc, clean = dbc.sniff_encoding("hello".encode("utf-8"))
        self.assertEqual((enc, clean), ("utf-8", True))

    def test_gbk_sniff(self):
        enc, clean = dbc.sniff_encoding("中文注释".encode("gbk"))
        self.assertEqual(enc, "gbk")
        self.assertFalse(clean)

    def test_bom_detected(self):
        enc, clean = dbc.sniff_encoding("\ufeffVERSION".encode("utf-8-sig"))
        self.assertEqual(enc, "utf-8-sig")
        self.assertTrue(clean)

    def test_broken_file_reports_encoding_error(self):
        db = dbc.parse_dbc(EXAMPLES / "demo_broken.dbc")
        codes = [f.code for f in dbc.check_encoding(db)]
        self.assertIn("ENC-001", codes)

    def test_fix_encoding_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "fixed.dbc"
            db = dbc.parse_dbc(EXAMPLES / "demo_broken.dbc")
            rc = dbc.main(["fix-encoding", str(EXAMPLES / "demo_broken.dbc"), str(out)])
            self.assertEqual(rc, 0)
            self.assertTrue(out.exists())
            reencoded = dbc.parse_dbc(out)
            self.assertTrue(reencoded.utf8_clean)
            # structure must survive the transcode
            self.assertEqual(len(reencoded.messages), len(db.messages))


class TestLint(unittest.TestCase):
    def test_clean_file_has_no_errors_or_warnings(self):
        db = dbc.parse_dbc(EXAMPLES / "demo.dbc")
        findings = dbc.run_checks(db, "")
        errors = [f for f in findings if f.severity == "error"]
        warns = [f for f in findings if f.severity == "warn"]
        self.assertEqual(errors, [])
        self.assertEqual(warns, [])

    def test_broken_file_exit_code_nonzero(self):
        code, _ = run(["lint", str(EXAMPLES / "demo_broken.dbc")])
        self.assertEqual(code, 1)

    def test_broken_file_hits_every_family(self):
        db = dbc.parse_dbc(EXAMPLES / "demo_broken.dbc")
        text, _, _ = dbc.read_dbc_text(EXAMPLES / "demo_broken.dbc")
        codes = {f.code for f in dbc.run_checks(db, text)}
        expected = {
            "ENC-001",   # GBK encoding
            "BIT-001",   # overlapping bits
            "RNG-001",   # signal past the frame end
            "DLC-001",   # illegal payload size
            "ENU-001",   # enum attribute written as a number
            "SYM-001",   # A/B asymmetry
            "TYP-001",   # case-only spelling drift
            "DUP-001",   # duplicated signal name
            "NOD-001",   # undeclared transmitter
        }
        self.assertTrue(expected.issubset(codes), f"missing: {expected - codes}")

    def test_no_fail_flag_returns_zero(self):
        code, _ = run(["lint", str(EXAMPLES / "demo_broken.dbc"), "--no-fail"])
        self.assertEqual(code, 0)

    def test_json_output_is_valid(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            dbc.main(["lint", str(EXAMPLES / "demo_broken.dbc"), "--json", "--no-fail"])
        payload = json.loads(buf.getvalue())
        self.assertIn("findings", payload)
        self.assertGreater(payload["counts"]["error"], 0)

    def test_min_severity_filters(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            dbc.main(["lint", str(EXAMPLES / "demo_broken.dbc"),
                      "--min-severity", "error", "--no-fail"])
        out = buf.getvalue()
        self.assertNotIn("[W]", out)
        self.assertNotIn("[I]", out)


class TestDecode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = dbc.parse_dbc(EXAMPLES / "demo.dbc")

    def test_motorola_roundtrip(self):
        # Work_Mode and Power_Mode sit at known positions; build a payload and
        # check both the raw decode and the value-table rendering.
        msg = self.db.by_id(0x100)
        mode = next(s for s in msg.signals if s.name == "Work_Mode")
        power = next(s for s in msg.signals if s.name == "Power_Mode")
        data = bytearray(8)
        # place Work_Mode = 2 in the four MSBs of byte 3, Power_Mode = 1 in the next two bits
        data[3] = (2 << 4) | (1 << 2)
        self.assertEqual(mode.decode(bytes(data)), 2)
        self.assertEqual(power.decode(bytes(data)), 1)
        self.assertIn("Active", mode.display(2))

    def test_signed_scaling(self):
        sig = dbc.Signal(
            name="T", start=7, length=8, byte_order="motorola", is_signed=True,
            factor=0.5, offset=-10, minimum=None, maximum=None, unit="",
        )
        # 0xFE == -2 signed -> -2 * 0.5 - 10 = -11
        self.assertAlmostEqual(sig.decode(bytes([0xFE] + [0] * 7)), -11.0)

    def test_offset_scaling(self):
        msg = self.db.by_id(0x110)
        angle = next(s for s in msg.signals if s.name == "Steering_Angle")
        # raw 7800 * 0.1 - 780 == 0 degrees
        raw = 7800
        data = bytearray(32)
        pos = angle.start
        for i in range(angle.length):
            bit = (raw >> (angle.length - 1 - i)) & 1
            byte_i, bit_i = pos // 8, pos % 8
            if bit:
                data[byte_i] |= 1 << bit_i
            pos = pos + 15 if pos % 8 == 0 else pos - 1
        self.assertAlmostEqual(angle.decode(bytes(data)), 0.0, places=6)

    def test_decode_cli_output(self):
        code, out = run(["decode", str(EXAMPLES / "demo.dbc"), "0x100", "0000002100000000"])
        self.assertEqual(code, 0)
        self.assertIn("Work_Mode", out)
        self.assertIn("Active", out)

    def test_unknown_frame_returns_two(self):
        code, _ = run(["decode", str(EXAMPLES / "demo.dbc"), "0x999", "00"])
        self.assertEqual(code, 2)


class TestExport(unittest.TestCase):
    def test_csv_export(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "inv.csv"
            code, _ = run(["export", str(EXAMPLES / "demo.dbc"), "--csv", str(out)])
            self.assertEqual(code, 0)
            text = out.read_text(encoding="utf-8-sig")
            lines = [l for l in text.splitlines() if l.strip()]
            self.assertEqual(len(lines), 1 + 167)
            self.assertIn("frame_id", lines[0])
            self.assertIn("value_table", lines[0])


class TestCliSurface(unittest.TestCase):
    def test_info_runs(self):
        code, out = run(["info", str(EXAMPLES / "demo.dbc")])
        self.assertEqual(code, 0)
        self.assertIn("messages        20", out)

    def test_messages_runs(self):
        code, out = run(["messages", str(EXAMPLES / "demo.dbc")])
        self.assertEqual(code, 0)
        self.assertIn("Node_Status", out)

    def test_signals_single_frame(self):
        code, out = run(["signals", str(EXAMPLES / "demo.dbc"), "--frame", "0x100"])
        self.assertEqual(code, 0)
        self.assertIn("Work_Mode", out)
        self.assertNotIn("Steering_Angle", out)

    def test_missing_file_returns_two(self):
        code, _ = run(["info", "/nonexistent/nope.dbc"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()


class TestExampleExpectations(unittest.TestCase):
    """The numbers SKILL.md promises about the bundled examples.

    docs claiming "0 error" or "N defect classes" is exactly the kind of
    statement that silently rots when a check is added, so assert it here.
    """

    def _lint(self, path):
        code, out = run(["lint", str(path), "--json"])
        payload = json.loads(out)
        findings = payload["findings"] if isinstance(payload, dict) else payload
        return code, findings

    def test_demo_is_clean(self):
        code, findings = self._lint(EXAMPLES / "demo.dbc")
        errors = [f for f in findings if f["severity"] == "error"]
        warns = [f for f in findings if f["severity"] == "warn"]
        self.assertEqual(code, 0)
        self.assertEqual(errors, [], "demo.dbc must have no errors")
        self.assertEqual(warns, [], "demo.dbc must have no warnings")

    def test_broken_covers_ten_codes(self):
        """SKILL.md claims 10 defect classes; keep that claim honest."""
        _, findings = self._lint(EXAMPLES / "demo_broken.dbc")
        codes = {f["code"] for f in findings}
        self.assertEqual(len(codes), 10, f"expected 10 distinct codes, got {sorted(codes)}")
        expected = {"ENC-001", "BIT-001", "RNG-001", "DLC-001", "ENU-001",
                    "SYM-001", "TYP-001", "DUP-001", "STA-001", "NOD-001"}
        self.assertEqual(codes, expected)

    def test_broken_severity_split(self):
        """SKILL.md says 4 error / 4 warn / 2 info."""
        _, findings = self._lint(EXAMPLES / "demo_broken.dbc")
        import collections
        c = collections.Counter(f["severity"] for f in findings)
        self.assertEqual(dict(c), {"error": 4, "warn": 4, "info": 2})


class TestPackagedDocAccuracy(unittest.TestCase):
    """The docs that ship inside the package must be true, and self-contained.

    Two failures this catches, both found in the Agensi submission:

    1. `examples/README.md` claimed "9 defect classes ... 4 error 4 warn" while the
       fixtures produce 10 codes at 4/4/2. The code-side assertions above were correct;
       the shipped prose was not, so a buyer counting the findings got a mismatch.
    2. It also told the reader to run `python tools/gen_demo_dbc.py`, but `tools/` is
       not in the package. Every path a shipped doc names must resolve inside the
       package, or the doc is instructing the buyer to do something that fails.

    The package is `skills/<name>/` plus the `packaging/<market>/` overlay, so that is
    exactly what is checked.
    """

    SKILL_DIR = ROOT / "skills" / "dbc-matrix-audit"
    OVERLAY = ROOT / "packaging" / "agensi"

    # Any relative path, e.g. scripts/x.py, tools/y.py, docs/z.md.
    PATH_REF = re.compile(r"(?<![\w/.-])([A-Za-z_][\w.-]*/[\w.-]+\.[A-Za-z0-9]{1,5})(?![\w/.-])")

    # Fenced blocks whose content is meant to be executed or acted on.
    CODE_BLOCK = re.compile(r"```(?:bash|sh|console|shell)?\n(.*?)```", re.S)

    def _shipped_docs(self):
        """Docs that end up inside the zip: skill dir (minus dirs) + overlay .md."""
        docs = {p.relative_to(self.SKILL_DIR).as_posix(): p
                for p in self.SKILL_DIR.rglob("*.md")}
        for p in self.OVERLAY.glob("*.md"):
            if p.name != "LISTING.md":          # operator copy, not shipped
                docs[p.name] = p
        return docs

    def test_commands_in_shipped_docs_resolve_inside_the_package(self):
        """Anything a buyer is told to run must exist in the package.

        Prose may name a path that lives only in the repo — that is how the
        examples README explains where the generator is, with a URL next to it.
        A fenced block is different: it is an instruction. So only block contents
        are checked, which keeps `see tools/gen_demo_dbc.py in the repo` legal
        while rejecting `python tools/gen_demo_dbc.py` as a step to follow.
        """
        missing = []
        for name, path in self._shipped_docs().items():
            text = path.read_text(encoding="utf-8")
            for block in self.CODE_BLOCK.findall(text):
                block = re.sub(r"https?://\S+", "", block)
                # Docs write `<skill>/scripts/...`; the prefix is a variable, not a
                # path segment. Strip it or the leading slash defeats the word
                # boundary in PATH_REF and the whole check silently no-ops.
                block = block.replace("<skill>/", "")
                for ref in self.PATH_REF.findall(block):
                    candidates = [self.SKILL_DIR / ref, path.parent / ref]
                    if not any(c.exists() for c in candidates):
                        missing.append(f"{name} runs a command naming {ref}")
        self.assertEqual(missing, [],
                         "shipped docs instruct the buyer to use paths that are not in "
                         "the package:\n  " + "\n  ".join(missing))

    def test_the_path_check_actually_sees_the_skill_md_commands(self):
        """Guard the guard: if the path check silently matches nothing it is dead.

        SKILL.md addresses every path as `<skill>/scripts/...`. An earlier version of
        PATH_REF missed all of them because the `/` after `<skill>` failed the
        lookbehind, so the check passed no matter what the docs said.
        """
        text = (self.SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        seen = set()
        for block in self.CODE_BLOCK.findall(text):
            block = re.sub(r"https?://\S+", "", block).replace("<skill>/", "")
            seen.update(self.PATH_REF.findall(block))
        self.assertTrue(seen, "path check found no references in SKILL.md — it is dead")
        self.assertIn("scripts/dbc_analyze.py", seen)
        self.assertIn("examples/demo.dbc", seen)

    def test_example_readme_numbers_match_reality(self):
        text = (self.SKILL_DIR / "examples" / "README.md").read_text(encoding="utf-8")

        def info_signals(dbc_name):
            code, out = run(["info", str(EXAMPLES / dbc_name)])
            self.assertEqual(code, 0)
            m = re.search(r"^signals\s+(\d+)", out, re.M)
            self.assertIsNotNone(m, f"no signal count in info output:\n{out}")
            return int(m.group(1))

        self.assertEqual(info_signals("demo.dbc"), 167)
        self.assertEqual(info_signals("demo_broken.dbc"), 166)

        # the counts the README states must be the counts the tool produces
        self.assertIn("167 signals", text)
        self.assertIn("166 signals", text)
        self.assertIn("10 defect classes", text)
        self.assertIn("4 error, 4 warn, 2 info", text)

    def test_example_readme_does_not_claim_nine_defects(self):
        """Guard the exact regression: the old text said 9."""
        text = (self.SKILL_DIR / "examples" / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("9 类缺陷", text)
        self.assertNotIn("9 defect", text.lower())
        self.assertNotIn("9 defect", text.lower())


class TestDocConsistency(unittest.TestCase):
    """Documentation must not advertise codes the code cannot produce.

    Covers both families: `XXX-001` lint codes and `DIF-XXX` diff codes.
    """

    # docs wrap codes in backticks; source writes them as string literals
    DOC_LINT = re.compile(r"`([A-Z]{3}-\d{3})`")
    DOC_DIFF = re.compile(r"`(DIF-[A-Z]{3})`")
    SRC_LINT = re.compile(r'code="([A-Z]{3}-\d{3})"')
    SRC_DIFF = re.compile(r'"(DIF-[A-Z]{3})",\s*DIF_SEVERITY')

    def _pairs(self):
        skill_md = (ROOT / "skills" / "dbc-matrix-audit" / "SKILL.md").read_text(encoding="utf-8")
        source = SCRIPT.read_text(encoding="utf-8")
        return [
            ("lint", set(self.DOC_LINT.findall(skill_md)), set(self.SRC_LINT.findall(source))),
            ("diff", set(self.DOC_DIFF.findall(skill_md)), set(self.SRC_DIFF.findall(source))),
        ]

    def test_every_documented_code_is_implemented(self):
        for label, documented, implemented in self._pairs():
            self.assertTrue(documented, f"no {label} codes found in SKILL.md")
            missing = documented - implemented
            self.assertEqual(missing, set(),
                             f"{label}: documented but never emitted: {missing}")

    def test_every_implemented_code_is_documented(self):
        for label, documented, implemented in self._pairs():
            undocumented = implemented - documented
            self.assertEqual(undocumented, set(),
                             f"{label}: emitted but undocumented: {undocumented}")


class TestDeterminism(unittest.TestCase):
    """Two parses of the same file must agree, and lint must be stable."""

    def test_parse_is_deterministic(self):
        a = dbc.parse_dbc(EXAMPLES / "demo.dbc")
        b = dbc.parse_dbc(EXAMPLES / "demo.dbc")
        self.assertEqual(
            [(m.frame_id, m.name, len(m.signals)) for m in a.messages],
            [(m.frame_id, m.name, len(m.signals)) for m in b.messages],
        )

    def test_lint_order_is_stable(self):
        db = dbc.parse_dbc(EXAMPLES / "demo_broken.dbc")
        text, _, _ = dbc.read_dbc_text(EXAMPLES / "demo_broken.dbc")
        first = [f.code for f in dbc.run_checks(db, text)]
        second = [f.code for f in dbc.run_checks(db, text)]
        self.assertEqual(first, second)
