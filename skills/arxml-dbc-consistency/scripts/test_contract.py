#!/usr/bin/env python3
"""文档 ↔ 代码 一致性断言。

SKILL.md / references/checks*.md（中英文都算）里写的检查码，必须和脚本里真正 emit 的完全一致：
  文档写了没实现 → 红
  实现了没写文档 → 也红

用法：python3 scripts/test_contract.py
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
SRC = SCRIPTS / "arxml_dbc_check.py"
DOCS = [
    ROOT / "SKILL.md",
    ROOT / "references" / "checks.md",
    ROOT / "references" / "checks.en.md",
]

CODE_RE_SRC = re.compile(r'"(AXD-\d{3})"')
CODE_RE_DOC = re.compile(r"`(AXD-\d{3})`")


def main() -> int:
    if not SRC.exists():
        print(f"缺少脚本：{SRC}", file=sys.stderr)
        return 2

    sys.path.insert(0, str(SCRIPTS))
    import arxml_dbc_check as axd
    import demo_fixtures as fixtures

    implemented = set(CODE_RE_SRC.findall(SRC.read_text(encoding="utf-8")))

    doc_text = ""
    for d in DOCS:
        if d.exists():
            doc_text += "\n" + d.read_text(encoding="utf-8")
    documented = set(CODE_RE_DOC.findall(doc_text))

    failures: list[str] = []

    ahead = documented - implemented
    behind = implemented - documented
    if ahead:
        failures.append(f"文档超前（写了但代码没实现）：{', '.join(sorted(ahead))}")
    if behind:
        failures.append(f"文档滞后（代码实现了但没写）：{', '.join(sorted(behind))}")

    for code in sorted(implemented):
        n = int(code.split("-")[1])
        if not 0 <= n <= 99:
            failures.append(f"检查码超出 000-099：{code}")

    # 内置示例必须触发预期码集合
    with tempfile.TemporaryDirectory() as td:
        ax = Path(td) / "demo.arxml"
        dbc_path = Path(td) / "demo.dbc"
        ax.write_text(fixtures.build_demo_arxml(), encoding="utf-8")
        dbc_path.write_text(fixtures.DEMO_DBC, encoding="utf-8")
        model = axd.parse_arxml(ax)
        stack = axd.extract_stack(model)
        dbc = axd.parse_dbc(dbc_path)
        findings, _, _ = axd.run_checks(dbc, stack, None)

    fired = {f.code for f in findings}
    missing = set(fixtures.EXPECTED_CODES) - fired
    if missing:
        failures.append(f"内置示例未触发预期码：{', '.join(sorted(missing))}")
    if not fired <= implemented:
        failures.append(f"示例触发了未登记的码：{fired - implemented}")

    # --node 分支不应抛异常
    try:
        axd.run_checks(dbc, stack, "LDM")
    except Exception as exc:  # pragma: no cover
        failures.append(f"--node 分支抛异常：{exc}")

    print(f"实现 {len(implemented)} 个检查码：{' '.join(sorted(implemented))}")
    print(f"文档 {len(documented)} 个检查码")
    print(f"示例触发 {len(fired)} 个：{' '.join(sorted(fired))}")

    if failures:
        for f in failures:
            print("FAIL: " + f, file=sys.stderr)
        return 1
    print("contract OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
