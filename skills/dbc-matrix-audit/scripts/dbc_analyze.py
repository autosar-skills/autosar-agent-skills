#!/usr/bin/env python3
# skills/dbc-matrix-audit/scripts/dbc_analyze.py
"""dbc_analyze.py — DBC communication-matrix auditor.

Pure stdlib. No cantools, no third-party dependencies.

Subcommands
-----------
  info            overview: message/signal counts, DLC mix, encoding, cycle times
  messages        message table
  signals         signal detail (with value tables and comments)
  lint            run all structural checks; non-zero exit on error
  decode          decode one hex frame
  export          export the full signal inventory as CSV
  fix-encoding    transcode a DBC (e.g. GBK -> UTF-8)

Design note: the parser is hand-written because most DBC libraries drop the
things that actually matter for a matrix audit -- value tables (VAL_),
comments (CM_), and message/signal attributes (BA_). See
references/checks.md for every rule and its false-positive caveats.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

__version__ = "0.2.0"

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------

CAN_CLASSIC_DLC = set(range(0, 9))
CAN_FD_DLC = {0, 1, 2, 3, 4, 5, 6, 7, 8, 12, 16, 20, 24, 32, 48, 64}

SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}

RE_BO = re.compile(r"^BO_\s+(\d+)\s+(\w+)\s*:\s*(\d+)\s+(\S+)\s*$")
RE_SG = re.compile(
    r'^SG_\s+(?P<name>[A-Za-z_][\w]*)\s*(?P<mux>M|m\d+M?)?\s*:\s*'
    r'(?P<start>\d+)\|(?P<len>\d+)@(?P<order>[01])(?P<sign>[+-])\s*'
    r'\(\s*(?P<factor>[^,]+?)\s*,\s*(?P<offset>[^)]+?)\s*\)\s*'
    r'\[\s*(?P<min>[^|\]]*?)\s*\|\s*(?P<max>[^\]]*?)\s*\]\s*'
    r'"(?P<unit>(?:[^"\\]|\\.)*)"\s*'
    r'(?P<recv>.*)$'
)
RE_VAL = re.compile(r"^VAL_\s+(\d+)\s+(\w+)\s+(.*)$", re.S)
RE_VAL_PAIR = re.compile(r'(-?\d+)\s+"((?:[^"\\]|\\.)*)"')
RE_CM_BO = re.compile(r'^CM_\s+BO_\s+(\d+)\s+"((?:[^"\\]|\\.)*)"$', re.S)
RE_CM_SG = re.compile(r'^CM_\s+SG_\s+(\d+)\s+(\w+)\s+"((?:[^"\\]|\\.)*)"$', re.S)
RE_CM_NET = re.compile(r'^CM_\s+"((?:[^"\\]|\\.)*)"$', re.S)
RE_BA_DEF = re.compile(
    r'^BA_DEF_\s+(?:(BO_|SG_|BU_|EV_)\s+)?\s*"([^"]+)"\s+(\w+)\s*(.*)$', re.S
)
RE_BA = re.compile(r'^BA_\s+"([^"]+)"\s+(.*)$', re.S)
RE_BA_DEF_DEF = re.compile(r'^BA_DEF_DEF_\s+"([^"]+)"\s+(.*)$', re.S)


# --------------------------------------------------------------------------
# encoding
# --------------------------------------------------------------------------

def sniff_encoding(raw: bytes) -> tuple[str, bool]:
    """Return (encoding, is_utf8_clean)."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig", True
    try:
        raw.decode("utf-8")
        return "utf-8", True
    except UnicodeDecodeError:
        pass
    try:
        raw.decode("gbk")
        return "gbk", False
    except UnicodeDecodeError:
        pass
    try:
        raw.decode("gb18030")
    except UnicodeDecodeError:
        return "latin-1", False
    return "gb18030", False


def read_dbc_text(path: Path) -> tuple[str, str, bool]:
    raw = path.read_bytes()
    enc, clean = sniff_encoding(raw)
    return raw.decode(enc, errors="replace"), enc, clean


# --------------------------------------------------------------------------
# model
# --------------------------------------------------------------------------

@dataclass
class Signal:
    name: str
    start: int
    length: int
    byte_order: str  # "motorola" | "intel"
    is_signed: bool
    factor: float
    offset: float
    minimum: float | None
    maximum: float | None
    unit: str
    receivers: list[str] = field(default_factory=list)
    multiplexer: str | None = None
    comment: str = ""
    value_table: dict[int, str] = field(default_factory=dict)
    attributes: dict[str, object] = field(default_factory=dict)

    # -- geometry ---------------------------------------------------------
    def bit_positions(self) -> list[tuple[int, int]]:
        """Bit coordinates as (byte_index, bit_index).

        For Motorola the list is MSB-first (that is how the value is
        assembled); for Intel it is LSB-first. Order is irrelevant for
        overlap detection, only the set matters.
        """
        out: list[tuple[int, int]] = []
        pos = self.start
        if self.byte_order == "motorola":
            for _ in range(self.length):
                out.append((pos // 8, pos % 8))
                pos = pos + 15 if pos % 8 == 0 else pos - 1
        else:
            for _ in range(self.length):
                out.append((pos // 8, pos % 8))
                pos += 1
        return out

    def max_bit_index(self) -> int:
        pos = self.bit_positions()
        return max(pos, key=lambda t: t[0])[0] if pos else -1

    # -- decode -----------------------------------------------------------
    def decode(self, data: bytes) -> float:
        raw = 0
        if self.byte_order == "motorola":
            pos = self.start
            for _ in range(self.length):
                byte_i, bit_i = pos // 8, pos % 8
                bit = (data[byte_i] >> bit_i) & 1 if byte_i < len(data) else 0
                raw = (raw << 1) | bit
                pos = pos + 15 if pos % 8 == 0 else pos - 1
        else:
            for i in range(self.length):
                pos = self.start + i
                byte_i, bit_i = pos // 8, pos % 8
                if byte_i < len(data):
                    raw |= ((data[byte_i] >> bit_i) & 1) << i
        if self.is_signed and self.length and (raw >> (self.length - 1)) & 1:
            raw -= 1 << self.length
        return raw * self.factor + self.offset

    # -- presentation -----------------------------------------------------
    def display(self, physical: float) -> str:
        if self.value_table:
            key = round(physical)
            if key in self.value_table:
                return f"{physical:g} ({self.value_table[key].strip()})"
        unit = f" {self.unit}" if self.unit else ""
        return f"{physical:g}{unit}"

    def fmt_range(self) -> str:
        lo = "-" if self.minimum is None else f"{self.minimum:g}"
        hi = "-" if self.maximum is None else f"{self.maximum:g}"
        return f"[{lo},{hi}]"


@dataclass
class Message:
    frame_id: int
    raw_id: int
    name: str
    dlc: int
    transmitter: str
    is_extended: bool = False
    signals: list[Signal] = field(default_factory=list)
    comment: str = ""
    attributes: dict[str, object] = field(default_factory=dict)

    @property
    def cycle_time(self) -> int | None:
        v = self.attributes.get("GenMsgCycleTime")
        try:
            return int(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def send_type(self) -> str | None:
        v = self.attributes.get("GenMsgSendType")
        return str(v) if v is not None else None

    @property
    def is_fd(self) -> bool:
        return self.dlc > 8

    @property
    def is_orphan_container(self) -> bool:
        """True for Vector's parking slot for unassigned signals.

        ``VECTOR__INDEPENDENT_SIG_MSG`` is id 0 with DLC 0. Vector uses it to
        keep signals that exist in the database but are not wired into any
        frame. Payload-geometry checks are meaningless inside it, and flagging
        it produces noise that buries real problems.
        """
        return self.name == "VECTOR__INDEPENDENT_SIG_MSG" or self.dlc == 0


@dataclass
class Database:
    path: Path
    encoding: str = "utf-8"
    utf8_clean: bool = True
    version: str = ""
    nodes: list[str] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)
    attr_defs: dict[str, dict] = field(default_factory=dict)
    attr_defaults: dict[str, object] = field(default_factory=dict)
    network_comment: str = ""

    # -- lookups ----------------------------------------------------------
    def by_id(self, frame_id: int) -> Message | None:
        for m in self.messages:
            if m.frame_id == frame_id:
                return m
        return None

    def all_signal_names(self) -> list[str]:
        return [s.name for m in self.messages for s in m.signals]

    def total_signals(self) -> int:
        return sum(len(m.signals) for m in self.messages)


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------

def _extract_complete(s: str) -> tuple[list[str], str]:
    """Pull every semicolon-terminated statement out of ``s``.

    Semicolons inside double-quoted strings do not terminate: a CM_ comment
    may legitimately contain one.
    """
    out: list[str] = []
    start = 0
    in_str = False
    esc = False
    for idx, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == ";":
            seg = s[start:idx].strip()
            if seg:
                out.append(seg)
            start = idx + 1
    return out, s[start:]


def _split_statements(text: str) -> list[str]:
    """Split a DBC body into statements.

    BO_/SG_ blocks and header lines (VERSION, BS_, BU_) are newline-terminated
    and carry no semicolon, so they are emitted on their own. Everything else
    accumulates until a semicolon that is not inside a quoted string.
    """
    out: list[str] = []
    buf: list[str] = []
    for line in text.splitlines():
        st = line.strip()
        if not st:
            continue
        if re.match(r"^(BO_|SG_)\s", st) or st.startswith(("BU_", "VERSION", "BS_")):
            if buf:
                pending = "\n".join(buf).strip()
                if pending:
                    out.append(pending)
                buf = []
            out.append(st)
            continue
        buf.append(line)
        complete, rest = _extract_complete("\n".join(buf))
        if complete:
            out.extend(complete)
            buf = [rest] if rest.strip() else []
    if buf:
        tail = "\n".join(buf).strip()
        if tail:
            out.append(tail)
    return out


def _unescape(s: str) -> str:
    return s.replace('\\"', '"').replace("\\\\", "\\").replace("\\n", "\n")


def _num(tok: str) -> float:
    tok = tok.strip()
    if not tok:
        return 0.0
    try:
        return float(tok)
    except ValueError:
        return 0.0


def parse_dbc(path: Path) -> Database:
    text, enc, clean = read_dbc_text(path)
    db = Database(path=path, encoding=enc, utf8_clean=clean)

    statements = _split_statements(text)

    # --- pass 1: attribute definitions (needed for ENUM detection) -------
    for st in statements:
        m = RE_BA_DEF.match(st)
        if m:
            obj, name, atype, rest = m.groups()
            enum_values: list[str] = []
            if atype == "ENUM":
                enum_values = re.findall(r'"([^"]*)"', rest)
            db.attr_defs[name] = {
                "object": obj or "network",
                "type": atype,
                "enum": enum_values,
            }
            continue
        m = RE_BA_DEF_DEF.match(st)
        if m:
            db.attr_defaults[m.group(1)] = _attr_value(m.group(2), db.attr_defs)

    # --- pass 2: structural content --------------------------------------
    current: Message | None = None
    pending_attrs: list[str] = []

    for st in statements:
        m = RE_BO.match(st)
        if m:
            raw_id = int(m.group(1))
            extended = bool(raw_id & 0x80000000)
            msg = Message(
                frame_id=raw_id & 0x1FFFFFFF,
                raw_id=raw_id,
                name=m.group(2),
                dlc=int(m.group(3)),
                transmitter=m.group(4),
                is_extended=extended,
            )
            db.messages.append(msg)
            current = msg
            pending_attrs = []
            continue

        m = RE_SG.match(st)
        if m and current is not None:
            gd = m.groupdict()
            recv_raw = gd["recv"].strip()
            receivers = [r for r in re.split(r"[,\s]+", recv_raw) if r and r != "Vector__XXX"]
            sig = Signal(
                name=gd["name"],
                start=int(gd["start"]),
                length=int(gd["len"]),
                byte_order="motorola" if gd["order"] == "0" else "intel",
                is_signed=gd["sign"] == "-",
                factor=_num(gd["factor"]),
                offset=_num(gd["offset"]),
                minimum=None if not gd["min"] else _num(gd["min"]),
                maximum=None if not gd["max"] else _num(gd["max"]),
                unit=_unescape(gd["unit"]),
                receivers=receivers,
                multiplexer=gd["mux"],
            )
            current.signals.append(sig)
            continue

        # BU_ node declaration (may be several lines; usually one)
        if st.startswith("BU_"):
            body = st[3:].lstrip(":").strip().rstrip(";")
            db.nodes = [n for n in re.split(r"[,\s]+", body) if n and n != "Vector__XXX"]
            continue

        if st.startswith("VERSION"):
            quoted = re.search(r'"([^"]*)"', st)
            db.version = quoted.group(1) if quoted else ""
            continue

        m = RE_CM_BO.match(st)
        if m:
            msg = db.by_id(int(m.group(1)))
            if msg:
                msg.comment = _unescape(m.group(2))
            continue

        m = RE_CM_SG.match(st)
        if m:
            msg = db.by_id(int(m.group(1)))
            if msg:
                for s in msg.signals:
                    if s.name == m.group(2):
                        s.comment = _unescape(m.group(3))
                        break
            continue

        m = RE_CM_NET.match(st)
        if m:
            db.network_comment = _unescape(m.group(1))
            continue

        m = RE_VAL.match(st)
        if m:
            msg = db.by_id(int(m.group(1)))
            if msg:
                pairs = RE_VAL_PAIR.findall(m.group(3))
                table = {int(k): _unescape(v).strip() for k, v in pairs}
                for s in msg.signals:
                    if s.name == m.group(2):
                        s.value_table = table
                        break
            continue

        m = RE_BA.match(st)
        if m and not st.startswith("BA_DEF"):
            _apply_attribute(db, m.group(1), m.group(2))
            continue

    return db


def _attr_value(raw: str, defs: dict) -> object:
    raw = raw.strip().rstrip(";").strip()
    if raw.startswith('"') and raw.endswith('"'):
        return _unescape(raw[1:-1])
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def _apply_attribute(db: Database, name: str, rest: str) -> None:
    rest = rest.rstrip(";").strip()
    m = re.match(r"BO_\s+(\d+)\s+(.*)$", rest, re.S)
    if m:
        msg = db.by_id(int(m.group(1)))
        if msg:
            msg.attributes[name] = _attr_value(m.group(2), db.attr_defs)
        return
    m = re.match(r"SG_\s+(\d+)\s+(\w+)\s+(.*)$", rest, re.S)
    if m:
        msg = db.by_id(int(m.group(1)))
        if msg:
            for s in msg.signals:
                if s.name == m.group(2):
                    s.attributes[name] = _attr_value(m.group(3), db.attr_defs)
                    break
        return
    m = re.match(r"BU_\s+(\w+)\s+(.*)$", rest, re.S)
    if m:
        return
    # network-level attribute
    db.network_comment = db.network_comment  # no-op, kept for clarity


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------

@dataclass
class Finding:
    code: str
    severity: str
    title: str
    detail: str = ""
    location: str = ""
    fix: str = ""

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "location": self.location,
            "fix": self.fix,
        }


def check_encoding(db: Database) -> list[Finding]:
    if db.utf8_clean:
        return []
    return [Finding(
        code="ENC-001",
        severity="error",
        title=f"file is not valid UTF-8 (detected: {db.encoding})",
        detail=(
            "Non-ASCII bytes (typically GBK-encoded Chinese comments) break strict "
            "parsers and most log/diff tooling. Tools such as cantools may silently "
            "tolerate it, which hides the problem until something else reads the file."
        ),
        fix=f"python dbc_analyze.py fix-encoding {db.path.name} {db.path.stem}_utf8.dbc",
    )]


def check_bit_overlap(db: Database) -> list[Finding]:
    out: list[Finding] = []
    for msg in db.messages:
        if msg.is_orphan_container:
            continue
        owner: dict[tuple[int, int], str] = {}
        clashes: dict[tuple[str, str], set[tuple[int, int]]] = {}
        for sig in msg.signals:
            for pos in sig.bit_positions():
                prev = owner.get(pos)
                if prev is None:
                    owner[pos] = sig.name
                elif prev != sig.name:
                    key = tuple(sorted((prev, sig.name)))
                    clashes.setdefault(key, set()).add(pos)
        for (a, b), positions in clashes.items():
            out.append(Finding(
                code="BIT-001",
                severity="error",
                title=f"{a} and {b} occupy overlapping bits",
                detail=f"{len(positions)} shared bit(s): {sorted(positions)[:12]}",
                location=f"0x{msg.frame_id:03X} {msg.name}",
            ))
    return out


def check_out_of_range(db: Database) -> list[Finding]:
    out: list[Finding] = []
    for msg in db.messages:
        if msg.is_orphan_container:
            continue
        limit = msg.dlc * 8
        for sig in msg.signals:
            last_byte = sig.max_bit_index()
            if last_byte * 8 >= limit:
                out.append(Finding(
                    code="RNG-001",
                    severity="error",
                    title=f"{sig.name} extends past the frame length",
                    detail=f"highest byte index {last_byte}, frame allows 0..{msg.dlc - 1}",
                    location=f"0x{msg.frame_id:03X} {msg.name}",
                ))
    return out


def check_enum_as_number(db: Database, statements_source: str) -> list[Finding]:
    """ENUM-typed attributes assigned bare numbers instead of the quoted label."""
    enum_names = {k for k, v in db.attr_defs.items() if v.get("type") == "ENUM"}
    if not enum_names:
        return []
    offenders: dict[str, int] = {}
    for m in re.finditer(r'^BA_\s+"([^"]+)"\s+[^\n]*?(-?\d+)\s*;', statements_source, re.M):
        name = m.group(1)
        if name in enum_names:
            offenders[name] = offenders.get(name, 0) + 1
    if not offenders:
        return []
    total = sum(offenders.values())
    detail = ", ".join(f"{k}={v}" for k, v in sorted(offenders.items(), key=lambda kv: -kv[1])[:6])
    return [Finding(
        code="ENU-001",
        severity="warn",
        title=f"{total} ENUM attribute assignments use numeric indices",
        detail=(
            f"{detail}. Vector CANoe tolerates the numeric form; strict DBC readers "
            "reject it or fall back to the default value."
        ),
    )]


def _sym_tokens() -> list[tuple[str, str]]:
    """Token pairs that conventionally denote the two sides of a vehicle.

    Deliberately excludes loose pairs such as IN/OUT, which are far more
    often used for unrelated semantics and would cause false positives.
    """
    return [
        ("LEFT", "RIGHT"),
        ("MFL", "MFR"),
        ("FL", "FR"),
        ("LH", "RH"),
        ("L", "R"),
        ("A", "B"),
    ]


def _left_tokens() -> set[str]:
    return {a for a, _ in _sym_tokens()}


def _right_tokens() -> set[str]:
    return {b for _, b in _sym_tokens()}


def _swap_sym(name: str) -> str | None:
    """Return ``name`` with its side token flipped, or None if it has none."""
    parts = name.split("_")
    for i, part in enumerate(parts):
        for a, b in _sym_tokens():
            if part == a:
                parts[i] = b
                return "_".join(parts)
            if part == b:
                parts[i] = a
                return "_".join(parts)
    return None


def _normalize_sym(name: str) -> str:
    """Canonicalise a signal name so the two sides compare equal.

    Two levels are needed:

    1. **Whole token** — ``FLM_L_FLTurnLampOnSt`` against
       ``FLM_R_FRTurnLampOnSt``. The ``L``/``R`` part is its own token, easy.
    2. **Token prefix** — ``FLADSLampFlt`` against ``FRADSLampBri``. Here the
       side is baked into the front of a compound token, so the token as a
       whole is not a side token. Stripping a leading side prefix is what
       makes these pair up.

    Folding only level 1 leaves ``FLM_X_FLTurn`` versus ``FLM_X_FRTurn`` and
    produces a spurious asymmetry on every matrix written this way.
    """
    parts: list[str] = []
    for idx, token in enumerate(name.split("_")):
        if token in _left_tokens() or token in _right_tokens():
            parts.append("X")
            continue
        # The first token is normally the object name (ACM, FLM, VIU, RTE...).
        # Prefix-stripping there would turn ACM into XCM and pollute grouping.
        if idx == 0:
            parts.append(token)
            continue
        replaced = token
        for side in _left_tokens() | _right_tokens():
            # Single-letter tokens are too ambiguous as a prefix: "AFS"
            # (Adaptive Front-lighting System) would become "XFS". Only
            # multi-character side tokens are safe to strip from a word.
            if len(side) < 2:
                continue
            # the remainder must start with an uppercase letter or a digit, so
            # ordinary words such as ``Flt`` / ``FlowSt`` are left alone
            if token.startswith(side) and len(token) > len(side) + 1:
                rest = token[len(side):]
                if rest[0].isupper() or rest[0].isdigit():
                    replaced = "X" + rest
                    break
        parts.append(replaced)
    return "_".join(parts)


def _pair_messages(db: Database) -> list[tuple[Message, Message]]:
    """Pair messages whose names differ only by a side token (L/R, A/B, ...)."""
    pairs: list[tuple[Message, Message]] = []
    used: set[str] = set()
    index = {m.name: m for m in db.messages}
    for msg in db.messages:
        if msg.name in used:
            continue
        swapped = _swap_sym(msg.name)
        if not swapped or swapped not in index:
            continue
        pairs.append((msg, index[swapped]))
        used.add(msg.name)
        used.add(swapped)
    return pairs


def check_lr_asymmetry(db: Database) -> list[Finding]:
    out: list[Finding] = []
    for first, second in _pair_messages(db):
        # pick the one that sorts first under the token order as the "left"
        left, right = (first, second) if _swap_sym(first.name) == second.name else (second, first)
        lset = {_normalize_sym(s.name) for s in left.signals}
        rset = {_normalize_sym(s.name) for s in right.signals}
        only_l = lset - rset
        only_r = rset - lset
        if only_l or only_r:
            parts = []
            if only_l:
                parts.append(f"{left.name} only: {len(only_l)} "
                             f"({', '.join(sorted(only_l)[:4])})")
            if only_r:
                parts.append(f"{right.name} only: {len(only_r)} "
                             f"({', '.join(sorted(only_r)[:4])})")
            out.append(Finding(
                code="SYM-001",
                severity="warn",
                title=f"{left.name} / {right.name} are not symmetric",
                detail=" | ".join(parts),
                location=f"0x{left.frame_id:03X} vs 0x{right.frame_id:03X}",
            ))
    return out


def check_case_variants(db: Database) -> list[Finding]:
    """Same logical signal spelled differently once the side token is removed.

    The side token itself is expected to differ; only the remaining spelling
    matters. Comparing normalised strings (not originals) keeps ordinary
    L/R and A/B pairs silent.
    """
    out: list[Finding] = []
    groups: dict[str, set[str]] = {}
    for msg in db.messages:
        for sig in msg.signals:
            normalized = _normalize_sym(sig.name)
            groups.setdefault(normalized.lower(), set()).add(normalized)
    for variants in groups.values():
        if len(variants) > 1:
            out.append(Finding(
                code="TYP-001",
                severity="warn",
                title="same signal spelled differently (beyond the side token)",
                detail=" vs ".join(sorted(variants)),
            ))
    return out


def check_duplicate_names(db: Database) -> list[Finding]:
    counts: dict[str, list[str]] = {}
    for msg in db.messages:
        # Signals parked in Vector's orphan container are by definition copies
        # of signals that live in a real frame; reporting those as duplicates
        # is noise, not a finding.
        if msg.is_orphan_container:
            continue
        for sig in msg.signals:
            counts.setdefault(sig.name, []).append(msg.name)
    out = []
    for name, msgs in counts.items():
        if len(msgs) > 1:
            out.append(Finding(
                code="DUP-001",
                severity="warn",
                title=f"signal name {name} appears in {len(msgs)} frames",
                detail=", ".join(sorted(set(msgs))),
            ))
    return out


def check_start_values(db: Database) -> list[Finding]:
    total = db.total_signals()
    with_start = sum(1 for m in db.messages for s in m.signals
                     if "GenSigStartValue" in s.attributes)
    if total == 0 or with_start == total:
        return []
    return [Finding(
        code="STA-001",
        severity="info",
        title=f"{total - with_start}/{total} signals have no GenSigStartValue",
        detail=(
            "Signals default to 0 on startup. For enum-style signals where 0 means "
            "'Initial' and 1 means 'Off', an unset start value can look like a "
            "different state than intended."
        ),
    )]


def check_transmitters(db: Database) -> list[Finding]:
    if not db.nodes:
        return []
    out = []
    for msg in db.messages:
        if msg.transmitter not in db.nodes and msg.transmitter != "Vector__XXX":
            out.append(Finding(
                code="NOD-001",
                severity="info",
                title=f"transmitter '{msg.transmitter}' is not declared in BU_",
                detail="rest-bus simulation needs the node to exist in the database",
                location=f"0x{msg.frame_id:03X} {msg.name}",
            ))
    return out


def check_dlc(db: Database) -> list[Finding]:
    out = []
    for msg in db.messages:
        if msg.is_orphan_container:
            continue
        if msg.dlc not in CAN_FD_DLC:
            out.append(Finding(
                code="DLC-001",
                severity="error",
                title=f"illegal DLC {msg.dlc}",
                detail="valid CAN FD payload sizes are "
                       + ", ".join(str(d) for d in sorted(CAN_FD_DLC)),
                location=f"0x{msg.frame_id:03X} {msg.name}",
            ))
    return out


def check_missing_value_table(db: Database) -> list[Finding]:
    """Short signals that almost certainly encode an enum but have no VAL_."""
    suspects = [
        f"{msg.name}.{sig.name}"
        for msg in db.messages
        for sig in msg.signals
        if sig.length <= 4 and not sig.value_table and not sig.unit
    ]
    if len(suspects) < 3:
        return []
    return [Finding(
        code="VAL-001",
        severity="info",
        title=f"{len(suspects)} short signals have no value table",
        detail=(
            "Signals of 4 bits or less with no unit usually encode an enum; "
            "without VAL_ their numeric values carry no documented meaning. "
            "Example: " + ", ".join(suspects[:5])
        ),
    )]


def run_checks(db: Database, source_text: str) -> list[Finding]:
    findings: list[Finding] = []
    findings += check_encoding(db)
    findings += check_dlc(db)
    findings += check_bit_overlap(db)
    findings += check_out_of_range(db)
    findings += check_enum_as_number(db, source_text)
    findings += check_lr_asymmetry(db)
    findings += check_case_variants(db)
    findings += check_duplicate_names(db)
    findings += check_start_values(db)
    findings += check_transmitters(db)
    findings += check_missing_value_table(db)
    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], f.code))
    return findings


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

MARK = {"error": "[E]", "warn": "[W]", "info": "[I]"}


def render_findings(findings: list[Finding], min_sev: str = "info") -> str:
    floor = SEVERITY_ORDER[min_sev]
    shown = [f for f in findings if SEVERITY_ORDER[f.severity] <= floor]
    if not shown:
        return "no findings"
    lines = []
    for f in shown:
        head = f"{MARK[f.severity]} {f.code}  {f.title}"
        if f.location:
            head += f"   ({f.location})"
        lines.append(head)
        if f.detail:
            for chunk in _wrap(f.detail, 96):
                lines.append(f"      {chunk}")
        if f.fix:
            lines.append(f"      fix: {f.fix}")
        lines.append("")
    counts = {s: sum(1 for f in findings if f.severity == s)
              for s in ("error", "warn", "info")}
    lines.append(f"summary: {counts['error']} error, {counts['warn']} warn, {counts['info']} info")
    return "\n".join(lines)


def _wrap(text: str, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines or [""]


# --------------------------------------------------------------------------
# subcommands
# --------------------------------------------------------------------------

def cmd_info(db: Database, args) -> int:
    fd = [m for m in db.messages if m.is_fd]
    cyc = [(m.name, m.cycle_time) for m in db.messages if m.cycle_time]
    print(f"file            {db.path}")
    print(f"version         {db.version or '(none)'}")
    print(f"encoding        {db.encoding}{'' if db.utf8_clean else '  [not UTF-8]'}")
    print(f"nodes           {', '.join(db.nodes) if db.nodes else '(none declared)'}")
    print(f"messages        {len(db.messages)}")
    print(f"signals         {db.total_signals()}")
    print(f"CAN FD frames   {len(fd)} / {len(db.messages)}")
    if db.messages:
        dlc_hist: dict[int, int] = {}
        for m in db.messages:
            dlc_hist[m.dlc] = dlc_hist.get(m.dlc, 0) + 1
        print("DLC histogram   " + ", ".join(f"{k}B x{v}" for k, v in sorted(dlc_hist.items())))
    if cyc:
        fastest = min(cyc, key=lambda t: t[1])
        slowest = max(cyc, key=lambda t: t[1])
        print(f"cycle times     {len(cyc)} cyclic, fastest {fastest[0]} {fastest[1]}ms, "
              f"slowest {slowest[0]} {slowest[1]}ms")
    bus_load = sum(1 for m in db.messages
                   for s in m.signals if s.value_table)
    print(f"value tables    {bus_load} signals carry VAL_ definitions")
    commented = sum(1 for m in db.messages for s in m.signals if s.comment)
    print(f"comments        {commented} signals, "
          f"{sum(1 for m in db.messages if m.comment)} messages")
    return 0


def cmd_messages(db: Database, args) -> int:
    print(f"{'ID':<8}{'name':<30}{'DLC':>4}{'sig':>5}  {'cycle':>7}  {'tx':<14}")
    print("-" * 74)
    for m in sorted(db.messages, key=lambda x: x.frame_id):
        cyc = f"{m.cycle_time}ms" if m.cycle_time else "-"
        print(f"0x{m.frame_id:03X}  {m.name:<30}{m.dlc:>4}{len(m.signals):>5}  {cyc:>7}  {m.transmitter:<14}")
    return 0


def cmd_signals(db: Database, args) -> int:
    msgs = db.messages
    if args.frame:
        target = args.frame.lower()
        msgs = [m for m in db.messages
                if f"0x{m.frame_id:x}" == target or m.name == args.frame]
        if not msgs:
            print(f"frame not found: {args.frame}", file=sys.stderr)
            return 2
    for m in msgs:
        cyc = f"  cycle {m.cycle_time}ms" if m.cycle_time else ""
        print(f"\n== 0x{m.frame_id:03X}  {m.name}  DLC={m.dlc}{cyc}")
        if m.comment:
            print(f"   {m.comment}")
        if not m.signals:
            print("   (no signals)")
            continue
        print(f"   {'signal':<34}{'bits':>10}  {'order':<9}{'k':>8}{'off':>8}  {'range':<18}{'unit':<6}")
        for s in m.signals:
            bits = f"{s.start}|{s.length}"
            print(f"   {s.name:<34}{bits:>10}  {s.byte_order:<9}"
                  f"{s.factor:>8g}{s.offset:>8g}  {s.fmt_range():<18}{s.unit:<6}")
            if s.value_table:
                pairs = ", ".join(f"{k}={v}" for k, v in sorted(s.value_table.items())[:6])
                more = "" if len(s.value_table) <= 6 else f" (+{len(s.value_table) - 6})"
                print(f"       values: {pairs}{more}")
            if s.comment:
                print(f"       note  : {s.comment}")
    return 0


def cmd_lint(db: Database, args) -> int:
    text, _, _ = read_dbc_text(db.path)
    findings = run_checks(db, text)
    if args.json:
        print(json.dumps({
            "file": str(db.path),
            "version": db.version,
            "encoding": db.encoding,
            "messages": len(db.messages),
            "signals": db.total_signals(),
            "findings": [f.as_dict() for f in findings],
            "counts": {s: sum(1 for f in findings if f.severity == s)
                       for s in ("error", "warn", "info")},
        }, ensure_ascii=False, indent=2))
    else:
        print(render_findings(findings, args.min_severity))
    errors = sum(1 for f in findings if f.severity == "error")
    if errors and not args.no_fail:
        return 1
    return 0


def cmd_decode(db: Database, args) -> int:
    target = args.frame.lower()
    msg = None
    for m in db.messages:
        if f"0x{m.frame_id:x}" == target or m.name == args.frame:
            msg = m
            break
    if msg is None:
        print(f"frame not found: {args.frame}", file=sys.stderr)
        return 2
    hexs = re.sub(r"[^0-9a-fA-F]", "", args.data)
    if len(hexs) % 2:
        print("payload must be an even number of hex digits", file=sys.stderr)
        return 2
    data = bytes.fromhex(hexs)
    print(f"0x{msg.frame_id:03X} {msg.name}  DLC={msg.dlc}  payload={data.hex(' ')}")
    if len(data) < msg.dlc:
        print(f"  warning: payload is {len(data)} bytes, frame expects {msg.dlc}", file=sys.stderr)
    for s in msg.signals:
        value = s.decode(data)
        print(f"  {s.name:<34} = {s.display(value)}")
    return 0


def cmd_export(db: Database, args) -> int:
    out_path = Path(args.csv)
    with out_path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow([
            "frame_id", "frame_name", "dlc", "cycle_ms", "transmitter",
            "signal_name", "start_bit", "length", "byte_order", "signed",
            "factor", "offset", "min", "max", "unit",
            "value_table", "receivers", "comment",
        ])
        for m in sorted(db.messages, key=lambda x: x.frame_id):
            for s in m.signals:
                w.writerow([
                    f"0x{m.frame_id:03X}", m.name, m.dlc, m.cycle_time or "",
                    m.transmitter, s.name, s.start, s.length, s.byte_order,
                    "signed" if s.is_signed else "unsigned",
                    s.factor, s.offset,
                    "" if s.minimum is None else s.minimum,
                    "" if s.maximum is None else s.maximum,
                    s.unit,
                    "; ".join(f"{k}={v}" for k, v in sorted(s.value_table.items())),
                    ",".join(s.receivers), s.comment,
                ])
    print(f"wrote {out_path}  ({db.total_signals()} signals)")
    return 0


def cmd_fix_encoding(db: Database, args) -> int:
    src, _, clean = read_dbc_text(db.path)
    if clean and not args.force:
        print(f"{db.path} is already valid UTF-8; nothing to do (use --force to re-save)")
        return 0
    out = Path(args.out)
    out.write_text(src, encoding="utf-8", newline="\n")
    print(f"wrote {out}  (from {db.encoding} -> utf-8)")
    return 0


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dbc_analyze",
        description="Audit and inspect DBC communication matrices (stdlib only).",
    )
    p.add_argument("--version", action="version", version=f"dbc_analyze {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("info", help="overview of the database")
    s.add_argument("dbc")
    s.set_defaults(func=cmd_info)

    s = sub.add_parser("messages", help="list messages")
    s.add_argument("dbc")
    s.set_defaults(func=cmd_messages)

    s = sub.add_parser("signals", help="list signals, optionally for one frame")
    s.add_argument("dbc")
    s.add_argument("--frame", help="frame id (0x1D2) or name")
    s.set_defaults(func=cmd_signals)

    s = sub.add_parser("lint", help="run structural checks")
    s.add_argument("dbc")
    s.add_argument("--json", action="store_true", help="machine-readable output")
    s.add_argument("--min-severity", choices=["error", "warn", "info"], default="info")
    s.add_argument("--no-fail", action="store_true",
                   help="always exit 0 even when errors are found")
    s.set_defaults(func=cmd_lint)

    s = sub.add_parser("decode", help="decode a hex payload")
    s.add_argument("dbc")
    s.add_argument("frame", help="frame id (0x1D2) or name")
    s.add_argument("data", help="hex payload, e.g. 1234052a00000000")
    s.set_defaults(func=cmd_decode)

    s = sub.add_parser("export", help="export signal inventory as CSV")
    s.add_argument("dbc")
    s.add_argument("--csv", default="signal_inventory.csv")
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("fix-encoding", help="transcode a DBC to UTF-8")
    s.add_argument("dbc")
    s.add_argument("out")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_fix_encoding)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = Path(args.dbc)
    if not path.is_file():
        print(f"file not found: {path}", file=sys.stderr)
        return 2
    db = parse_dbc(path)
    return args.func(db, args)


if __name__ == "__main__":
    sys.exit(main())
