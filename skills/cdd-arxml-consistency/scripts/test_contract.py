#!/usr/bin/env python3
# skills/cdd-arxml-consistency/scripts/test_contract.py
"""Assert that the documentation and the code agree in both directions.

Three things break silently in a check-code tool:

  1. a code documented but never emitted  -> users wait for a finding that
     cannot happen, and a real defect class goes unreported
  2. a code emitted but never documented  -> the finding is unreadable; nobody
     knows whether it is an error or noise
  3. the severity in the docs differs from the severity in the code -> triage
     is wrong, which is worse than no triage

This file checks all three, across both language versions of the reference
doc. It is run standalone and from the repo's unittest suite.
"""

from __future__ import annotations

import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
SKILL = HERE.parent
CODE = HERE / "cdd_arxml_check.py"
DOCS = [
    SKILL / "references" / "checks.md",
    SKILL / "references" / "checks.en.md",
]

# A code is emitted either as a literal in `Finding(...)` or as a tuple in the
# CAN-id table (`id_map`), which is walked in a loop — so matching only
# `add(Finding("CDX-...` misses three codes. Match the (code, severity) pair
# itself; no other construct in this file pairs a code literal with a severity
# literal, so there is nothing else for it to latch onto.
EMIT_RE = re.compile(r'"CDX-(\d{3})",\s*"(error|warn|info)"')

# In the docs a code appears in a table cell as `CDX-001` followed by a
# severity column.
DOC_ROW_RE = re.compile(
    r"\|\s*`CDX-(\d{3})`\s*\|\s*(error|warn|info)\s*\|"
)


def implemented() -> dict:
    src = CODE.read_text(encoding="utf-8")
    out = {}
    for code, sev in EMIT_RE.findall(src):
        key = f"CDX-{code}"
        # CDX-043 is emitted twice (two different situations, same code).
        # Same severity both times; if that ever diverges, flag it.
        if key in out and out[key] != sev:
            raise AssertionError(
                f"{key} 在代码中以两个不同级别发出：{out[key]} 和 {sev}"
            )
        out[key] = sev
    return out


def documented(path: pathlib.Path) -> dict:
    text = path.read_text(encoding="utf-8")
    return {f"CDX-{c}": s for c, s in DOC_ROW_RE.findall(text)}


def main() -> int:
    impl = implemented()
    if not impl:
        print("失败：代码里没有找到任何 add(Finding(...)) 调用")
        return 1

    problems = []

    for doc in DOCS:
        if not doc.is_file():
            problems.append(f"文档缺失：{doc}")
            continue
        doc_map = documented(doc)
        rel = doc.relative_to(SKILL)

        missing_doc = sorted(set(impl) - set(doc_map))
        if missing_doc:
            problems.append(f"{rel}: 代码实现了但文档没写：{missing_doc}")

        missing_impl = sorted(set(doc_map) - set(impl))
        if missing_impl:
            problems.append(f"{rel}: 文档写了但代码从不 emit：{missing_impl}")

        for code in sorted(set(impl) & set(doc_map)):
            if impl[code] != doc_map[code]:
                problems.append(
                    f"{rel}: {code} 级别不一致：代码 {impl[code]} / 文档 {doc_map[code]}"
                )

    counts = {"error": 0, "warn": 0, "info": 0}
    for sev in impl.values():
        counts[sev] += 1

    # The docs state a total in prose; keep it honest.
    #
    # Parse the compact "9 error / 11 warn / 3 info" line as a unit rather than
    # scanning for "<n> error" anywhere in the file: the code list at the end
    # contains "CDX-041" followed by a newline and "info", which a loose scan
    # reads as "41 info".
    TRIPLE_RE = re.compile(
        r"(\d+)\s*error\s*/\s*(\d+)\s*warn\s*/\s*(\d+)\s*info"
    )
    TOTAL_RE = re.compile(r"共\s*\**(\d+)\**\s*个|\*\*(\d+)\*\*\s+check codes|"
                          r"(\d+)\s+check codes")
    for doc in DOCS:
        if not doc.is_file():
            continue
        text = doc.read_text(encoding="utf-8")
        rel = doc.relative_to(SKILL)

        m = TOTAL_RE.search(text)
        if m:
            claimed = int(next(g for g in m.groups() if g))
            if claimed != len(impl):
                problems.append(
                    f"{rel}: 声明的检查码总数 {claimed}，实际 {len(impl)}"
                )

        t = TRIPLE_RE.search(text)
        if t:
            claimed = {
                "error": int(t.group(1)),
                "warn": int(t.group(2)),
                "info": int(t.group(3)),
            }
            if claimed != counts:
                problems.append(
                    f"{rel}: 声明的分级 {claimed}，实际 {counts}"
                )

    print(f"实现 {len(impl)} 个检查码：" + " ".join(
        f"{c}" for c in sorted(impl)))
    print(f"分级：{counts['error']} error / {counts['warn']} warn / "
          f"{counts['info']} info")

    if problems:
        print()
        for p in problems:
            print(f"  ✗ {p}")
        return 1

    print("contract OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
