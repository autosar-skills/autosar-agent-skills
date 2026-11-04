# tests/test_diff.py
"""Tests for the `diff` subcommand.

Fixtures are produced at test time by rewriting examples/demo.dbc, so the
repository does not have to carry a second near-duplicate matrix.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "dbc-matrix-audit" / "scripts" / "dbc_analyze.py"
DEMO = ROOT / "skills" / "dbc-matrix-audit" / "examples" / "demo.dbc"

spec = importlib.util.spec_from_file_location("dbc_analyze_diff", SCRIPT)
assert spec and spec.loader
dbc = importlib.util.module_from_spec(spec)
sys.modules["dbc_analyze_diff"] = dbc
spec.loader.exec_module(dbc)


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = dbc.main(argv)
    return code, buf.getvalue()


class Fixture:
    """Write a variant of demo.dbc into a temp dir."""

    def __init__(self, td: str, name: str = "variant.dbc"):
        self.path = Path(td) / name
        self.base = DEMO.read_text(encoding="utf-8")

    def write(self, content: str) -> "Fixture":
        self.path.write_text(content, encoding="utf-8")
        return self

    def replace(self, old: str, new: str) -> "Fixture":
        if old not in self.base:
            raise AssertionError(f"fixture anchor not found in demo.dbc: {old!r}")
        return self.write(self.base.replace(old, new, 1))


class TestDiffIdentical(unittest.TestCase):
    def test_same_file_has_no_findings(self):
        findings = dbc.diff_databases(
            dbc.parse_dbc(DEMO), dbc.parse_dbc(DEMO)
        )
        self.assertEqual(findings, [])

    def test_exit_code_zero_when_identical(self):
        code, out = run(["diff", str(DEMO), str(DEMO)])
        self.assertEqual(code, 0)
        self.assertIn("no differences", out)


class TestDiffStructural(unittest.TestCase):
    def test_message_renamed_is_error(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td).replace("BO_ 256 Node_Status:", "BO_ 256 Node_Heartbeat:")
            findings = dbc.diff_databases(dbc.parse_dbc(DEMO), dbc.parse_dbc(f.path))
            codes = {x.code for x in findings}
            self.assertIn("DIF-REN", codes)
            rename = [x for x in findings if x.code == "DIF-REN"]
            self.assertTrue(any("Node_Status" in x.detail or "Node_Status" in x.title
                                for x in rename))
            self.assertTrue(all(x.severity == "error" for x in rename if x.location != "BU_"))

    def test_dlc_change_is_error(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td).replace("BO_ 256 Node_Status: 8 ", "BO_ 256 Node_Status: 12 ")
            findings = dbc.diff_databases(dbc.parse_dbc(DEMO), dbc.parse_dbc(f.path))
            dlc = [x for x in findings if x.code == "DIF-DLC"]
            self.assertEqual(len(dlc), 1)
            self.assertEqual(dlc[0].severity, "error")
            self.assertIn("8 -> 12", dlc[0].detail)

    def test_can_id_move_detected(self):
        """The same name at a different id must be one DIF-ID, not an add+remove."""
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td).replace("BO_ 256 Node_Status:", "BO_ 257 Node_Status:")
            findings = dbc.diff_databases(dbc.parse_dbc(DEMO), dbc.parse_dbc(f.path))
            moved = [x for x in findings if x.code == "DIF-ID"]
            self.assertEqual(len(moved), 1)
            self.assertIn("0x100", moved[0].detail)
            self.assertIn("0x101", moved[0].detail)
            # the add/remove pair must be suppressed, otherwise the cause is buried
            titles = [x.title for x in findings]
            self.assertFalse(any("message added" in t for t in titles))
            self.assertFalse(any("message removed" in t for t in titles))

    def test_message_added_and_removed(self):
        with tempfile.TemporaryDirectory() as td:
            body = Fixture(td).base
            # drop the whole Thermal_Status block (BO_ 528 plus its SG_ lines)
            lines = body.splitlines(keepends=True)
            keep, skipping = [], False
            for line in lines:
                if line.startswith("BO_ 528 "):
                    skipping = True
                    continue
                if skipping and line.startswith("BO_ "):
                    skipping = False
                if not skipping:
                    keep.append(line)
            f = Fixture(td).write("".join(keep))
            findings = dbc.diff_databases(dbc.parse_dbc(DEMO), dbc.parse_dbc(f.path))
            removed = [x for x in findings if x.code == "DIF-DEL"
                       and "message removed" in x.title]
            self.assertEqual(len(removed), 1)
            self.assertIn("Thermal_Status", removed[0].title)


class TestDiffSignals(unittest.TestCase):
    def test_geometry_change_is_error(self):
        with tempfile.TemporaryDirectory() as td:
            # Bus_Off_Count is at 39|8 in demo.dbc; move it one bit left
            f = Fixture(td).replace(
                "SG_ Bus_Off_Count : 39|8@0+",
                "SG_ Bus_Off_Count : 38|8@0+",
            )

            findings = dbc.diff_databases(dbc.parse_dbc(DEMO), dbc.parse_dbc(f.path))
            geo = [x for x in findings if x.code == "DIF-GEO"]
            self.assertEqual(len(geo), 1)
            self.assertEqual(geo[0].severity, "error")

    def test_scaling_change_is_warn(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td).replace(
                '(0.05625,0) [0|460.74] "km/h"',
                '(0.1,0) [0|819.1] "km/h"',
            )
            findings = dbc.diff_databases(dbc.parse_dbc(DEMO), dbc.parse_dbc(f.path))
            scl = [x for x in findings if x.code == "DIF-SCL"]
            self.assertTrue(scl)
            self.assertEqual(scl[0].severity, "warn")
            self.assertIn("0.05625", scl[0].detail)

    def test_signal_renamed_pairs_by_geometry(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td).replace("SG_ Bus_Off_Count ", "SG_ Bus_Off_Cnt ")
            findings = dbc.diff_databases(dbc.parse_dbc(DEMO), dbc.parse_dbc(f.path))
            ren = [x for x in findings if x.code == "DIF-REN"
                   and "signal renamed" in x.title]
            self.assertEqual(len(ren), 1)
            self.assertIn("Bus_Off_Count", ren[0].detail)
            self.assertIn("Bus_Off_Cnt", ren[0].detail)
            # must not degenerate into add + remove
            self.assertFalse(any(
                x.code in ("DIF-ADD", "DIF-DEL") and "Bus_Off" in x.title
                for x in findings))

    def test_value_table_change(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td).replace(
                'VAL_ 256 Work_Mode 0 "Init" 1 "Idle" 2 "Active" 3 "Degraded" 15 "Invalid" ;',
                'VAL_ 256 Work_Mode 0 "Init" 1 "Idle" 2 "Running" 3 "Degraded" 15 "Invalid" ;',
            )
            findings = dbc.diff_databases(dbc.parse_dbc(DEMO), dbc.parse_dbc(f.path))
            val = [x for x in findings if x.code == "DIF-VAL"]
            self.assertEqual(len(val), 1)
            self.assertIn("relabelled", val[0].detail)

    def test_cycle_time_change(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td).replace(
                'BA_ "GenMsgCycleTime" BO_ 256 20;',
                'BA_ "GenMsgCycleTime" BO_ 256 50;',
            )
            findings = dbc.diff_databases(dbc.parse_dbc(DEMO), dbc.parse_dbc(f.path))
            cyc = [x for x in findings if x.code == "DIF-CYC"]
            self.assertEqual(len(cyc), 1)
            self.assertIn("20 -> 50", cyc[0].detail)

    def test_transmitter_change(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td).replace(
                "BO_ 1024 Calibration_Block: 64 RCM",
                "BO_ 1024 Calibration_Block: 64 ACM_A",
            )
            findings = dbc.diff_databases(dbc.parse_dbc(DEMO), dbc.parse_dbc(f.path))
            tx = [x for x in findings if x.code == "DIF-TX"]
            self.assertEqual(len(tx), 1)
            self.assertIn("RCM -> ACM_A", tx[0].detail)


class TestDiffChecksum(unittest.TestCase):
    def test_dataid_change_is_error_not_info(self):
        """A moved CRC data id silently makes every receiver reject the frame."""
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td).replace(
                "CRC16 over bytes 2..7, data id 0x9A11",
                "CRC16 over bytes 2..7, data id 0x9A12",
            )
            findings = dbc.diff_databases(dbc.parse_dbc(DEMO), dbc.parse_dbc(f.path))
            crc = [x for x in findings if x.code == "DIF-CRC"]
            self.assertEqual(len(crc), 1)
            self.assertEqual(crc[0].severity, "error")
            self.assertIn("0x9A11", crc[0].detail)
            self.assertIn("0x9A12", crc[0].detail)
            # must not also show up as a plain comment change
            self.assertFalse(any(
                x.code == "DIF-CMT" and "Checksum" in x.title for x in findings))

    def test_plain_comment_change_stays_info(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td).replace(
                "cumulative bus-off events since power-on",
                "bus-off events counted since power-on",
            )
            findings = dbc.diff_databases(dbc.parse_dbc(DEMO), dbc.parse_dbc(f.path))
            cmt = [x for x in findings if x.code == "DIF-CMT"]
            self.assertEqual(len(cmt), 1)
            self.assertEqual(cmt[0].severity, "info")


class TestDiffCli(unittest.TestCase):
    def test_exit_one_on_error_level_difference(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td).replace("BO_ 256 Node_Status:", "BO_ 256 Renamed_Status:")
            code, _ = run(["diff", str(DEMO), str(f.path)])
            self.assertEqual(code, 1)

    def test_no_fail_flag_returns_zero(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td).replace("BO_ 256 Node_Status:", "BO_ 256 Renamed_Status:")
            code, _ = run(["diff", str(DEMO), str(f.path), "--no-fail"])
            self.assertEqual(code, 0)

    def test_warn_only_difference_exits_zero(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td).replace(
                "cumulative bus-off events since power-on",
                "bus-off events counted since power-on",
            )
            code, _ = run(["diff", str(DEMO), str(f.path)])
            self.assertEqual(code, 0)

    def test_json_output_shape(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td).replace("BO_ 256 Node_Status:", "BO_ 256 Renamed_Status:")
            buf = io.StringIO()
            with redirect_stdout(buf):
                dbc.main(["diff", str(DEMO), str(f.path), "--json", "--no-fail"])
            payload = json.loads(buf.getvalue())
            self.assertFalse(payload["identical"])
            self.assertGreater(payload["counts"]["error"], 0)
            self.assertEqual(payload["old_messages"], payload["new_messages"])
            self.assertTrue(all("code" in x and "severity" in x
                                for x in payload["findings"]))

    def test_min_severity_filter(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td).replace("BO_ 256 Node_Status:", "BO_ 256 Renamed_Status:")
            code, out = run(["diff", str(DEMO), str(f.path), "--min-severity", "error",
                             "--no-fail"])
            self.assertNotIn("[W]", out)
            self.assertNotIn("[I]", out)

    def test_missing_file_returns_two(self):
        code, _ = run(["diff", str(DEMO), "/nonexistent/nope.dbc"])
        self.assertEqual(code, 2)


class TestDiffSymmetry(unittest.TestCase):
    def test_reverse_diff_flags_same_kinds(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td).replace("BO_ 256 Node_Status:", "BO_ 256 Renamed_Status:")
            forward = dbc.diff_databases(dbc.parse_dbc(DEMO), dbc.parse_dbc(f.path))
            backward = dbc.diff_databases(dbc.parse_dbc(f.path), dbc.parse_dbc(DEMO))
            self.assertEqual({x.code for x in forward}, {x.code for x in backward})


if __name__ == "__main__":
    unittest.main()
