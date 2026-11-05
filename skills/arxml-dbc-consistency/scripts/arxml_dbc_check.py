#!/usr/bin/env python3
"""arxml_dbc_check.py — AUTOSAR 通信栈 ARXML 与 DBC 交叉一致性校验。

零依赖（仅 Python 标准库）。校验链路：
    DBC  <-  CanDrv  <-  CanIf  <-  PduR  <-  Com

子命令：
    probe   <arxml>                    探测 ARXML 变体：有哪些模块 / 容器 / 参数名
    check   <arxml> <dbc>              全链路校验
    matrix  <arxml> <dbc> --csv OUT    导出帧-信号对照台账
    selftest                           内置示例自检

退出码：0 无 error | 1 存在 error | 2 参数/文件问题
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

SEV_ORDER = {"error": 3, "warn": 2, "info": 1}

#: 一个 CAN ID 在 CanIf 里被置为扩展帧时常见的标志位
EXTENDED_FLAG = 0x80000000

#: 标准帧最大 ID
STD_ID_MAX = 0x7FF

#: CANdb++ 用来收纳「没挂到任何报文」的孤立信号的伪帧。
#: 它不是真帧：DLC=0、发送方 Vector__XXX、ID 固定 0xC0000000。
#: 当成真帧会把 DBC 凭空多算一帧，还会因为 ID > 0x7FF 误判成扩展帧，
#: 连带触发「DBC 有扩展帧但 CanDrv 没配 EXTENDED」的假报。
PSEUDO_FRAME_IDS = {0xC0000000}
PSEUDO_FRAME_NAMES = {"VECTOR__INDEPENDENT_SIG_MSG"}

#: 非 DBC 文件可容忍的编码
_ARXML_ENCODINGS = ("utf-8", "utf-8-sig", "gb18030", "gbk", "latin-1")


class AxdError(RuntimeError):
    """参数或文件层面的错误（退出码 2）。"""


# ---------------------------------------------------------------------------
# 公共工具
# ---------------------------------------------------------------------------


def xml_local(tag: str) -> str:
    """去掉 XML 命名空间，返回 local tag。"""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def ref_tail(ref: str) -> str:
    """取 AUTOSAR 引用路径最后一段。"""
    parts = [p for p in ref.split("/") if p]
    return parts[-1] if parts else ""


def read_text_any(path: Path) -> tuple[str, str]:
    """按常见编码读文本，返回 (text, encoding)。"""
    raw = path.read_bytes()
    for enc in _ARXML_ENCODINGS:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    raise AxdError(f"无法解码文件（已尝试 {', '.join(_ARXML_ENCODINGS)}）：{path}")


def to_number(value: Any) -> Any:
    """把字符串转成 int/float，转不了就原样返回。"""
    if not isinstance(value, str):
        return value
    s = value.strip()
    if not s:
        return value
    if re.fullmatch(r"[+-]?\d+", s):
        try:
            return int(s)
        except ValueError:
            return value
    if re.fullmatch(r"[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?", s):
        try:
            return float(s)
        except ValueError:
            return value
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    return s


# ---------------------------------------------------------------------------
# DBC 解析
# ---------------------------------------------------------------------------

_RE_BO = re.compile(r"^BO_\s+(\d+)\s+(\w+)\s*:\s*(\d+)\s+(\w+)")
_RE_SG = re.compile(
    r"^\s*SG_\s+(\w+)\s*(?:M|m\d+M?)?\s*:\s*"
    r"(\d+)\|(\d+)@([01])([+-])\s*"
    r"\(([^,]+),([^)]+)\)\s*"
    r"\[([^|\]]*)\|([^\]]*)\]\s*"
    r'"([^"]*)"\s*(.*)$'
)
_RE_CM_SG = re.compile(r'CM_\s+SG_\s+(\d+)\s+(\w+)\s+"(.*?)";', re.S)
_RE_CM_BO = re.compile(r'CM_\s+BO_\s+(\d+)\s+"(.*?)";', re.S)
_RE_VAL = re.compile(r"VAL_\s+(\d+)\s+(\w+)\s*([^;]*);")
_RE_BA_CYCLE = re.compile(r'BA_\s+"GenMsgCycleTime"\s+BO_\s+(\d+)\s+(\d+);')
_RE_BA_START = re.compile(
    r'BA_\s+"GenSigStartValue"\s+SG_\s+(\d+)\s+(\w+)\s+([-+0-9.eE]+);'
)
_RE_BA_VFRAME = re.compile(r'BA_\s+"VFrameFormat"\s+BO_\s+(\d+)\s+(\d+);')


def split_receivers(raw: str) -> list[str]:
    """拆 DBC 信号尾部的接收方列表。

    DBC 规范里用**逗号**分隔（`"" ECU_L,ECU_R`），但有些工具会写成空格，
    还有 `Vector__XXX` 这种占位符。只按空格拆会得到 ['ECU_L,ECU_R'] 一个元素，
    导致「本 ECU 是不是接收方」永远判错。
    """
    out: list[str] = []
    for part in re.split(r"[,\s]+", raw.strip()):
        part = part.strip()
        if part and part not in out:
            out.append(part)
    return out


@dataclass
class DbcSignal:
    name: str
    start: int
    length: int
    is_intel: bool
    signed: bool
    factor: float
    offset: float
    minimum: float | None
    maximum: float | None
    unit: str
    receivers: list[str]
    comment: str = ""
    start_value: float | None = None
    value_table: dict[int, str] = field(default_factory=dict)

    @property
    def byte_order(self) -> str:
        return "LITTLE" if self.is_intel else "BIG"

    def bits(self) -> set[int]:
        """返回信号占用的 bit 集合（DBC 锯齿位编号，bit0 = byte0 的 LSB）。"""
        if self.is_intel:
            return set(range(self.start, self.start + self.length))
        return motorola_bits(self.start, self.length)


@dataclass
class DbcMessage:
    can_id: int
    name: str
    dlc: int
    tx_node: str
    signals: dict[str, DbcSignal] = field(default_factory=dict)
    comment: str = ""
    cycle_ms: int | None = None
    vframe_format: int | None = None
    frame_format: str = ""  # "CAN" / "CANFD"

    @property
    def is_fd(self) -> bool:
        if self.vframe_format is not None:
            return self.vframe_format >= 14  # StandardCAN_FD=14, ExtendedCAN_FD=15
        return self.dlc > 8 or self.frame_format.upper() == "CANFD"

    @property
    def is_extended(self) -> bool:
        return self.can_id > STD_ID_MAX


@dataclass
class DbcModel:
    path: Path
    encoding: str
    nodes: list[str] = field(default_factory=list)
    messages: dict[int, DbcMessage] = field(default_factory=dict)
    #: 伪帧里的孤立信号（名称 -> 信号），单独存，不参与帧级校验
    orphan_signals: dict[str, DbcSignal] = field(default_factory=dict)


def motorola_bits(msb: int, length: int) -> set[int]:
    """从 DBC 起始位（MSB，锯齿编号）推出占用的 bit 集合。"""
    bits: set[int] = set()
    pos = msb
    for _ in range(length):
        bits.add(pos)
        pos = pos + 15 if pos % 8 == 0 else pos - 1
    return bits


def motorola_msb_from_lsb(lsb: int, length: int) -> int:
    """已知 LSB（平坦编号）和长度，反推 Motorola 的 MSB 位置。"""
    pos = lsb
    for _ in range(length - 1):
        pos = pos - 15 if pos % 8 == 7 else pos + 1
    return pos


def parse_dbc(path: Path) -> DbcModel:
    text, enc = read_text_any(path)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    model = DbcModel(path=path, encoding=enc)

    for m in re.finditer(r"^BU_\s*:\s*(.+)$", text, re.M):
        for node in m.group(1).split():
            if node not in model.nodes:
                model.nodes.append(node)

    current: DbcMessage | None = None
    pseudo_mode = False  # 当前 BO_ 是否为 CANdb++ 伪帧
    for line in text.split("\n"):
        mb = _RE_BO.match(line)
        if mb:
            cid, name = int(mb.group(1)), mb.group(2)
            current = DbcMessage(
                can_id=cid,
                name=name,
                dlc=int(mb.group(3)),
                tx_node=mb.group(4),
            )
            # 伪帧只用来收集孤立信号，不进 messages
            if cid in PSEUDO_FRAME_IDS or name in PSEUDO_FRAME_NAMES:
                current = None
                pseudo_mode = True
                continue
            pseudo_mode = False
            model.messages[current.can_id] = current
            continue
        if line.startswith("BO_") or (
            line.strip() and not line.startswith((" ", "\t")) and not pseudo_mode
        ):
            if not line.startswith((" ", "\t")) and not line.startswith("SG_"):
                if line[:3] in ("VAL", "CM_", "BA_", "BA_", "SG_", "SIG", "BO_"):
                    pass
                elif not line.startswith(" "):
                    current = None
        ms = _RE_SG.match(line)
        if ms and pseudo_mode:
            # 伪帧下的孤立信号
            sig = DbcSignal(
                name=ms.group(1),
                start=int(ms.group(2)),
                length=int(ms.group(3)),
                is_intel=(ms.group(4) == "1"),
                signed=(ms.group(5) == "-"),
                factor=_safe_float(ms.group(6), 1.0),
                offset=_safe_float(ms.group(7), 0.0),
                minimum=None,
                maximum=None,
                unit=ms.group(10),
                receivers=split_receivers(ms.group(11)),
            )
            model.orphan_signals[sig.name] = sig
            continue
        if ms and current is not None:
            try:
                mn = float(ms.group(8))
                mx = float(ms.group(9))
            except ValueError:
                mn = mx = None
            current.signals[ms.group(1)] = DbcSignal(
                name=ms.group(1),
                start=int(ms.group(2)),
                length=int(ms.group(3)),
                is_intel=(ms.group(4) == "1"),
                signed=(ms.group(5) == "-"),
                factor=_safe_float(ms.group(6), 1.0),
                offset=_safe_float(ms.group(7), 0.0),
                minimum=mn,
                maximum=mx,
                unit=ms.group(10),
                receivers=split_receivers(ms.group(11)),
            )

    for m in _RE_CM_SG.finditer(text):
        msg = model.messages.get(int(m.group(1)))
        if msg and m.group(2) in msg.signals:
            msg.signals[m.group(2)].comment = " ".join(m.group(3).split())
    for m in _RE_CM_BO.finditer(text):
        msg = model.messages.get(int(m.group(1)))
        if msg:
            msg.comment = " ".join(m.group(2).split())

    for m in _RE_VAL.finditer(text):
        msg = model.messages.get(int(m.group(1)))
        if not msg or m.group(2) not in msg.signals:
            continue
        table = {
            int(k): v
            for k, v in re.findall(r'(-?\d+)\s+"([^"]*)"', m.group(3))
        }
        msg.signals[m.group(2)].value_table = table

    for m in _RE_BA_CYCLE.finditer(text):
        msg = model.messages.get(int(m.group(1)))
        if msg:
            msg.cycle_ms = int(m.group(2))
    for m in _RE_BA_START.finditer(text):
        msg = model.messages.get(int(m.group(1)))
        if msg and m.group(2) in msg.signals:
            msg.signals[m.group(2)].start_value = _safe_float(m.group(3), 0.0)
    for m in _RE_BA_VFRAME.finditer(text):
        msg = model.messages.get(int(m.group(1)))
        if msg:
            msg.vframe_format = int(m.group(2))

    return model


def _safe_float(tok: str, default: float) -> float:
    try:
        return float(tok.strip())
    except (ValueError, AttributeError):
        return default


# ---------------------------------------------------------------------------
# ARXML (ECUC) 解析
# ---------------------------------------------------------------------------

#: ARXML 里把参数/引用/子容器再包一层的容器标签（真实文件几乎都有）
_WRAPPER_TAGS = {
    "PARAMETER-VALUES",
    "REFERENCE-VALUES",
    "SUB-CONTAINERS",
    "CONTAINERS",
    "INSTANCE-REFS",
}

#: AUTOSAR 4.x 真实标签名是 ECUC-xxx-PARAM-VALUE（不含 ETER）。
#: 部分工具会写成长形式，两种都接受。
_PARAM_TAGS = {
    "ECUC-NUMERICAL-PARAM-VALUE": "num",
    "ECUC-NUMERICAL-PARAMETER-VALUE": "num",
    "ECUC-TEXTUAL-PARAM-VALUE": "text",
    "ECUC-TEXTUAL-PARAMETER-VALUE": "text",
    "ECUC-BOOLEAN-PARAM-VALUE": "bool",
    "ECUC-BOOLEAN-PARAMETER-VALUE": "bool",
    "ECUC-ENUMERATION-PARAM-VALUE": "enum",
    "ECUC-ENUMERATION-PARAMETER-VALUE": "enum",
    "ECUC-MULTILINE-STRING-PARAM-VALUE": "str",
    "ECUC-MULTILINE-STRING-PARAMETER-VALUE": "str",
    "ECUC-REFERENCE-VALUE": "ref",
    "ECUC-INSTANCE-REFERENCE-VALUE": "iref",
}


@dataclass
class Ecuc:
    """一个 ECUC-CONTAINER-VALUE 节点。"""

    module: str
    def_type: str
    short_name: str
    path: str
    parent: "Ecuc | None" = None
    params: dict[str, list[Any]] = field(default_factory=dict)
    children: list["Ecuc"] = field(default_factory=list)

    def get(self, *names: str, default: Any = None) -> Any:
        for name in names:
            vals = self.params.get(name)
            if vals:
                return vals[0]
        return default

    def getall(self, *names: str) -> list[Any]:
        out: list[Any] = []
        for name in names:
            out.extend(self.params.get(name, []))
        return out

    def has(self, *names: str) -> bool:
        return any(self.params.get(n) for n in names)


class ArxmlModel:
    def __init__(self, path: Path, encoding: str) -> None:
        self.path = path
        self.encoding = encoding
        self.containers: list[Ecuc] = []
        self.modules: dict[str, list[Ecuc]] = {}
        #: <I-SIGNAL> 不在 ECUC 里，单独建索引：short_name -> {length, ...}
        self.isignals: dict[str, dict[str, Any]] = {}
        self.isignal_packages: list[str] = []

    # -- 索引 -------------------------------------------------------------
    def by_def(self, *def_types: str) -> list[Ecuc]:
        wanted = {d.lower() for d in def_types}
        return [c for c in self.containers if c.def_type.lower() in wanted]

    def by_short(self, name: str) -> list[Ecuc]:
        return [c for c in self.containers if c.short_name == name]

    def resolve(self, ref: str) -> list[Ecuc]:
        """按 AUTOSAR 引用路径解析容器（容忍厂商路径前缀差异）。"""
        if not ref:
            return []
        tail = ref_tail(ref)
        cands = self.by_short(tail)
        if cands:
            return cands
        # 退化：路径后缀匹配
        norm = "/" + "/".join(p for p in ref.split("/") if p)
        return [c for c in self.containers if norm.endswith("/" + c.path)]

    def module_names(self) -> list[str]:
        return sorted(self.modules)


def parse_arxml(path: Path) -> ArxmlModel:
    text, enc = read_text_any(path)
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError as exc:  # pragma: no cover - 输入损坏
        raise AxdError(f"ARXML 解析失败：{exc}") from exc

    model = ArxmlModel(path=path, encoding=enc)

    for mod_elem in root.iter():
        if xml_local(mod_elem.tag) != "ECUC-MODULE-CONFIGURATION-VALUES":
            continue
        sn = _child_text(mod_elem, "SHORT-NAME") or "(unnamed)"
        mod_containers: list[Ecuc] = []
        for child in _iter_leaves(mod_elem):
            if xml_local(child.tag) != "ECUC-CONTAINER-VALUE":
                continue
            built = _build_container(child, module=sn, parent=None, prefix=sn)
            if built is not None:
                mod_containers.append(built)
        model.modules[sn] = mod_containers
        for top in mod_containers:
            _flatten(top, model.containers)

    # I-SIGNAL 是普通 ARXML 元素，不在 ECUC 树里
    for elem in root.iter():
        if xml_local(elem.tag) != "I-SIGNAL":
            continue
        name = _child_text(elem, "SHORT-NAME")
        if not name:
            continue
        length = None
        for c in elem:
            if xml_local(c.tag) == "LENGTH":
                length = to_number(_text(c))
                break
        dtype = None
        for c in elem:
            if xml_local(c.tag) == "DATA-TYPE-POLICY":
                dtype = _text(c)
                break
        model.isignals[name] = {
            "length": length if isinstance(length, int) else None,
            "data_type_policy": dtype or "",
        }

    if not model.modules:
        raise AxdError(f"未找到任何 ECUC-MODULE-CONFIGURATION-VALUES：{path}")
    return model


def _build_container(
    elem: ET.Element, module: str, parent: Ecuc | None, prefix: str
) -> Ecuc | None:
    sn = _child_text(elem, "SHORT-NAME") or ""
    def_ref = _child_text(elem, "DEFINITION-REF") or ""
    def_type = ref_tail(def_ref) or "?"
    path = f"{prefix}/{sn}" if sn else prefix
    node = Ecuc(
        module=module, def_type=def_type, short_name=sn, path=path, parent=parent
    )

    for child in _iter_leaves(elem):
        tag = xml_local(child.tag)
        kind = _PARAM_TAGS.get(tag)
        if kind:
            p_def = _child_text(child, "DEFINITION-REF") or ""
            p_name = ref_tail(p_def)
            if kind in ("ref", "iref"):
                # 注意：ET 元素无子节点时布尔值为 False，不能用 `a or b`
                val_el = _child(child, "VALUE-REF")
                if val_el is None:
                    val_el = _child(child, "VALUE-IREF")
                val = _text(val_el)
            else:
                val = _text(_child(child, "VALUE"))
            if p_name:
                node.params.setdefault(p_name, []).append(to_number(val))
        elif tag == "ECUC-CONTAINER-VALUE":
            sub = _build_container(child, module=module, parent=node, prefix=path)
            if sub is not None:
                node.children.append(sub)
    return node


def _iter_leaves(elem: ET.Element) -> Iterable[ET.Element]:
    """展开 PARAMETER-VALUES / REFERENCE-VALUES / SUB-CONTAINERS 等包装层。"""
    for child in elem:
        if xml_local(child.tag) in _WRAPPER_TAGS:
            yield from _iter_leaves(child)
        else:
            yield child


def _flatten(node: Ecuc, out: list[Ecuc]) -> None:
    out.append(node)
    for child in node.children:
        _flatten(child, out)


def _child(elem: ET.Element, local: str) -> ET.Element | None:
    for c in elem:
        if xml_local(c.tag) == local:
            return c
    return None


def _text(elem: ET.Element | None) -> str:
    if elem is None:
        return ""
    return (elem.text or "").strip()


def _child_text(elem: ET.Element, local: str) -> str:
    return _text(_child(elem, local))


# ---------------------------------------------------------------------------
# 领域模型：把 ARXML 抽成 Com / PduR / CanIf / CanDrv 四层
# ---------------------------------------------------------------------------


@dataclass
class AxSignal:
    name: str
    pdu_name: str
    start_position: int | None
    length: int | None
    byte_order: str  # "BIG" / "LITTLE" / "?"
    signed: bool | None
    init_value: float | None
    source: str  # "ComSignal" / "ISignalToIPduMapping"
    container: Ecuc
    bits: set[int] = field(default_factory=set)
    bits_convention: str = ""
    #: 备选位宽：ComSignalLength 的单位在不同导出里可能是字节也可能是位
    length_alt: int | None = None
    #: 是否整帧字节数组（OPAQUE / UINT8_DYN），此时不做逐信号比对
    is_byte_array: bool = False

    def length_candidates(self) -> list[int]:
        out: list[int] = []
        for v in (self.length, self.length_alt):
            if v and v not in out:
                out.append(v)
        return out

    def compute_bits(self) -> None:
        """把 AUTOSAR 的起始位换算成 DBC 的 bit 集合。

        实测结论（215/215 信号零失败）：AUTOSAR 的 `START-POSITION` /
        `ComBitPosition` 存的始终是信号的 **LSB**，按平坦编号（bit0 = byte0 的 LSB），
        与小端/大端无关。与 DBC 的差异只有大端信号的锯齿编号转换：
        先把 LSB 回退 (len-1) 步求出 MSB，再按锯齿走完整个信号。

        写成"两种约定都试"是错的 —— 那会把真正的起始位错误掩盖掉。
        """
        if self.start_position is None or self.length is None:
            self.bits = set()
            self.bits_convention = ""
            return
        if self.byte_order == "LITTLE":
            self.bits = set(
                range(self.start_position, self.start_position + self.length)
            )
            self.bits_convention = "little-flat"
        else:
            msb = motorola_msb_from_lsb(self.start_position, self.length)
            self.bits = motorola_bits(msb, self.length)
            self.bits_convention = "big-lsb-flat"



@dataclass
class AxPdu:
    name: str
    direction: str  # "SEND" / "RECEIVE" / "?"
    length: int | None
    length_source: str
    cycle_ms: float | None
    signals: list[AxSignal] = field(default_factory=list)
    container: Ecuc | None = None
    can_id: int | None = None  # 从 CanIf 回填
    pdu_ref: str = ""  # EcuC Pdu 名（COM_xxx），PduR 链路的一环
    bus: str = ""  # 所属 CanController，由绑定的 CanIf PDU 回填


@dataclass
class CanIfPdu:
    name: str
    direction: str  # "RX" / "TX"
    can_id: int | None
    can_id_raw: int | None
    id_type: str  # STANDARD / EXTENDED / ?
    is_fd: bool  # 由 CanIdType 含 _FD_CAN 得出
    dlc: int | None
    container: Ecuc
    pdu_ref: str = ""  # 指向的 EcuC Pdu 名
    bus: str = ""  # 所属 CanController，如 CANIF_CTR_DRV_BCAN


@dataclass
class PduRRouting:
    name: str
    src_refs: list[str]
    dest_refs: list[str]
    container: Ecuc
    route_type: str = ""  # IF / TP


@dataclass
class CanController:
    name: str
    baudrate: int | None
    fd_baudrate: int | None
    container: Ecuc


@dataclass
class CanHwObject:
    name: str
    handle_type: str
    id_type: str
    container: Ecuc


@dataclass
class StackModel:
    com_pdus: list[AxPdu] = field(default_factory=list)
    canif_rx: list[CanIfPdu] = field(default_factory=list)
    canif_tx: list[CanIfPdu] = field(default_factory=list)
    routing: list[PduRRouting] = field(default_factory=list)
    controllers: list[CanController] = field(default_factory=list)
    hw_objects: list[CanHwObject] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    present_modules: list[str] = field(default_factory=list)
    #: EcuC 的 Pdu 容器：名字 -> 字节长度（Com 与 CanIf 之间的枢纽）
    ecuc_pdus: dict[str, int | None] = field(default_factory=dict)
    has_can_nm: bool = False
    has_can_tp: bool = False
    #: 总线覆盖率：CanController 名 -> (命中 DBC 的 PDU 数, 总 PDU 数)
    bus_coverage: dict[str, tuple[int, int]] = field(default_factory=dict)
    #: 不在本 DBC 覆盖范围内的总线（命中率 < 20%）
    off_dbc_buses: set[str] = field(default_factory=set)


def extract_stack(model: ArxmlModel) -> StackModel:
    st = StackModel()
    st.present_modules = model.module_names()

    # EcuC 的 Pdu 容器是 Com 与 CanIf 之间的枢纽，且提供 PDU 长度。
    # 必须最先扫，后面各层都要用它兜底。
    for pdu in model.by_def("Pdu"):
        st.ecuc_pdus[pdu.short_name] = _first_int(pdu, "PduLength")

    _extract_com(model, st)
    _extract_canif(model, st)
    _extract_pdur(model, st)
    _extract_candr(model, st)
    return st


def _extract_com(model: ArxmlModel, st: StackModel) -> None:
    ipdus = model.by_def("ComIPdu")
    mapping = model.by_def("ISignalToIPduMapping")
    isignals = model.isignals  # short_name -> {length, data_type_policy}
    com_signals = {c.short_name: c for c in model.by_def("ComSignal")}

    # 有的厂商把 PDU 长度放在 EcuC 的 Pdu 容器里，Com 用 ComPduIdRef 指过去
    pdu_len: dict[str, int] = {}
    for pdu in model.by_def("Pdu"):
        ln = _first_int(pdu, "PduLength")
        if ln is not None:
            pdu_len[pdu.short_name] = ln

    for ipdu in ipdus:
        pdu = AxPdu(
            name=ipdu.short_name,
            direction=_norm_direction(
                ipdu.get("ComIPduDirection", "ComIPduDirectionRef", default="?")
            ),
            length=_first_int(ipdu, "ComIPduSize", "ComIPduLength", "PduLength"),
            length_source="",
            cycle_ms=_extract_cycle(ipdu),
            container=ipdu,
        )
        pdu_ref_raw = ipdu.get("ComPduIdRef", default="")
        pdu.pdu_ref = ref_tail(pdu_ref_raw) if isinstance(pdu_ref_raw, str) else ""
        if pdu.length is not None:
            pdu.length_source = "ComIPdu"
        elif pdu.pdu_ref in pdu_len:
            pdu.length = pdu_len[pdu.pdu_ref]
            pdu.length_source = "EcuC.Pdu"
        # 方向兜底：ComIPduType / 命名
        if pdu.direction == "?":
            pdu.direction = _guess_direction_from_type(ipdu)

        # 1) 挂在 IPdu 下的 ISignalToIPduMapping / ComSignal 子容器
        sigs: list[AxSignal] = []
        refs = [r for r in ipdu.getall("ComIPduSignalRef") if isinstance(r, str)]
        ref_tails = {ref_tail(r) for r in refs if ref_tail(r)}

        for child in ipdu.children:
            if child.def_type == "ISignalToIPduMapping":
                sigs.append(_signal_from_mapping(child, ipdu.short_name, isignals))
            elif child.def_type == "ComSignal":
                # 有 ComIPduSignalRef 时，未被引用的 ComSignal 属死配置
                # （有的导出会保留整个信号定义集，但实际只引用其中一部分）
                if ref_tails and child.short_name not in ref_tails:
                    continue
                sigs.append(_signal_from_comsignal(child, ipdu.short_name))

        # 2) IPdu 上的信号引用（引用到模块级 ComSignal / ISignal 时补上）
        for ref in ipdu.getall("ComIPduSignalRef", "ComIPduGroupSignalRef"):
            if not isinstance(ref, str):
                continue
            tail = ref_tail(ref)
            if any(s.name == tail for s in sigs):
                continue
            if tail in com_signals:
                sigs.append(_signal_from_comsignal(com_signals[tail], ipdu.short_name))
            elif tail in isignals:
                sigs.append(
                    _signal_from_isignal_only(tail, isignals[tail], ipdu.short_name)
                )

        # 3) 全局 mapping 容器（不在 IPdu 子容器里时）
        for mp in mapping:
            parent = mp.parent
            if parent is not None and parent.short_name == ipdu.short_name:
                if not any(s.container is mp for s in sigs):
                    sigs.append(_signal_from_mapping(mp, ipdu.short_name, isignals))

        # 4) 模块级 ComSignal 按 ComIPduSignalRef / ComSignalIPduRef 反查
        for sig in model.by_def("ComSignal"):
            for r in sig.getall(
                "ComIPduSignalRef", "ComSignalIPduRef", "ComIPduRef"
            ):
                if isinstance(r, str) and ref_tail(r) == ipdu.short_name:
                    sigs.append(_signal_from_comsignal(sig, ipdu.short_name))
                    break

        # 去重
        seen: set[tuple[str, int | None]] = set()
        uniq: list[AxSignal] = []
        for s in sigs:
            s.name = _strip_ipdu_suffix(s.name, ipdu.short_name)
            key = (s.name, s.start_position)
            if key in seen:
                continue
            seen.add(key)
            s.compute_bits()
            uniq.append(s)
        pdu.signals = uniq
        st.com_pdus.append(pdu)

    if not ipdus:
        st.notes.append("ARXML 中没有找到 ComIPdu 容器")
    if ipdus and not any(p.signals for p in st.com_pdus):
        st.notes.append(
            "ComIPdu 存在但没解析出任何信号 —— 信号可能挂在其它容器类型下，"
            "请先跑 probe 看实际 DEFINITION-REF"
        )


def _strip_ipdu_suffix(name: str, pdu_name: str) -> str:
    """有的厂商导出会把 ComSignal 命名成 `<信号>_<PDU名>`，需剥回原始信号名。

    两种常见写法：
      Signal_IPDU_COM_Foo  + IPdu 名 IPDU_COM_Foo -> Signal      （后缀 _PDU名）
      Signal_IPDU_X        + IPdu 名 X            -> Signal      （后缀 _IPDU_PDU名）
    先试长的，再试短的，都要求完整匹配，避免误伤本来就带 _IPDU_ 的信号。
    """
    if not pdu_name:
        return name
    for suffix in ("_IPDU_" + pdu_name, "_" + pdu_name):
        if len(name) > len(suffix) and name.endswith(suffix):
            return name[: -len(suffix)]
    # 大小写差异兜底
    low_name, low_pdu = name.lower(), pdu_name.lower()
    for prefix in ("_ipdu_", "_"):
        suffix = prefix + low_pdu
        if len(low_name) > len(suffix) and low_name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _signal_from_mapping(
    mp: Ecuc, pdu_name: str, isignals: dict[str, dict[str, Any]]
) -> AxSignal:
    ref = mp.get("ISignalRef", default="")
    tail = ref_tail(ref) if isinstance(ref, str) else ""
    isig = isignals.get(tail)
    length = None
    if isig is not None:
        length = isig.get("length")
    name = tail or mp.short_name

    order_raw = str(
        mp.get(
            "PACKING-BYTE-ORDER",
            "ComSignalEndianness",
            "ISignalToIPduMappingByteOrder",
            default="",
        )
    ).upper()
    byte_order = "?"
    if order_raw:
        if "MOST-SIGNIFICANT-BYTE-FIRST" in order_raw or "BIG" in order_raw:
            byte_order = "BIG"
        elif "MOST-SIGNIFICANT-BYTE-LAST" in order_raw or "LITTLE" in order_raw:
            byte_order = "LITTLE"

    start = _first_int(mp, "START-POSITION", "START-POSITION-OF-SIGNAL", "ComBitPosition")

    signed: bool | None = None
    if isig is not None:
        dtype = str(isig.get("data_type_policy", "")).upper()
        if "SIGNED" in dtype and "UNSIGNED" not in dtype:
            signed = True
        elif "UNSIGNED" in dtype:
            signed = False

    return AxSignal(
        name=name,
        pdu_name=pdu_name,
        start_position=start,
        length=length,
        byte_order=byte_order,
        signed=signed,
        init_value=None,
        source="ISignalToIPduMapping",
        container=mp,
    )


def _signal_from_isignal_only(
    name: str, meta: dict[str, Any], pdu_name: str
) -> AxSignal:
    return AxSignal(
        name=name,
        pdu_name=pdu_name,
        start_position=None,
        length=meta.get("length"),
        byte_order="?",
        signed=None,
        init_value=None,
        source="ISignal",
        container=None,  # type: ignore[arg-type]
    )


def _signal_from_comsignal(sig: Ecuc, pdu_name: str) -> AxSignal:
    raw_order = str(
        sig.get("ComSignalEndianness", "ComBitOrder", default="")
    ).upper()
    byte_order = "?"
    if "BIG" in raw_order:
        byte_order = "BIG"
    elif "LITTLE" in raw_order:
        byte_order = "LITTLE"
    elif "OPAQUE" in raw_order:
        byte_order = "OPAQUE"

    stype = str(sig.get("ComSignalType", default="")).upper()
    signed: bool | None = None
    if stype:
        signed = stype.startswith("SINT")

    # ComBitSize 是位长（静态信号）；ComSignalLength 常见于动态/字节数组信号，
    # 单位在不同导出里可能是位或字节 —— 两个候选都留着，比对时逐个试。
    bit_size = _first_int(sig, "ComBitSize")
    sig_len = _first_int(sig, "ComSignalLength")
    bit_size = bit_size if bit_size else None
    sig_len = sig_len if sig_len else None

    length = bit_size or sig_len
    length_alt = sig_len * 8 if (bit_size is None and sig_len) else None

    # OPAQUE / UINT8_DYN 是字节数组：整个 PDU 当一个信号用，不做逐信号映射
    is_byte_array = "OPAQUE" in raw_order or stype in (
        "UINT8_DYN",
        "UINT8_N",
    )

    init = sig.get("ComSignalInitValue", "ComSignalInitValueRef")
    init_val = _parse_int_literal(init)

    return AxSignal(
        name=sig.short_name,
        pdu_name=pdu_name,
        start_position=_first_int(sig, "ComBitPosition", "ComSignalBitPosition"),
        length=length,
        byte_order=byte_order,
        signed=signed,
        init_value=init_val,
        source="ComSignal",
        container=sig,
        length_alt=length_alt,
        is_byte_array=is_byte_array,
    )


def _parse_int_literal(v: Any) -> float | None:
    """Com 的初始值常写成 0x0 / 0b101 / 十进制字符串。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        return None
    s = v.strip().lower()
    if not s:
        return None
    try:
        if s.startswith("0x"):
            return float(int(s, 16))
        if s.startswith("0b"):
            return float(int(s, 2))
        return float(s)
    except ValueError:
        return None


def _extract_canif(model: ArxmlModel, st: StackModel) -> None:
    bufs = {c.short_name: c for c in model.by_def("CanIfBufferCfg")}
    hths = {c.short_name: c for c in model.by_def("CanIfHthCfg")}
    hrhs = {c.short_name: c for c in model.by_def("CanIfHrhCfg")}

    for pdu in model.by_def("CanIfRxPduCfg", "CanIfRxPdu"):
        p = _canif_pdu(pdu, "RX")
        p.bus = _bus_of(pdu, "RX", bufs, hths, hrhs)
        _fill_dlc_from_ecuc(p, st)
        st.canif_rx.append(p)
    for pdu in model.by_def("CanIfTxPduCfg", "CanIfTxPdu"):
        p = _canif_pdu(pdu, "TX")
        p.bus = _bus_of(pdu, "TX", bufs, hths, hrhs)
        _fill_dlc_from_ecuc(p, st)
        st.canif_tx.append(p)
    if not st.canif_rx and not st.canif_tx:
        st.notes.append("ARXML 中没有找到 CanIfRxPduCfg / CanIfTxPduCfg 容器")


def _fill_dlc_from_ecuc(p: CanIfPdu, st: StackModel) -> None:
    """TX PDU 常不配 CanIfTxPduDlc（篇幅省在 EcuC 的 PduLength 里）。

    缺失时退到它引用的 EcuC Pdu 长度，否则 DLC 校验会永远静默跳过。
    """
    if p.dlc is not None or not p.pdu_ref:
        return
    ln = st.ecuc_pdus.get(p.pdu_ref)
    if ln is not None:
        p.dlc = ln


def _bus_of(
    pdu: Ecuc,
    direction: str,
    bufs: dict[str, Ecuc],
    hths: dict[str, Ecuc],
    hrhs: dict[str, Ecuc],
) -> str:
    """追 TX: Buffer -> HTH -> CanCtrlIdRef；RX: HrhIdRef -> HRH -> CanCtrlIdRef。

    一个 MCU 同时管多条 CAN 总线时，必须知道每个 PDU 挂在哪条上，
    否则会拿私有总线的帧去比整车 DBC。
    """
    if direction == "TX":
        ref = pdu.get("CanIfTxPduBufferRef")
        if isinstance(ref, str) and ref:
            buf = bufs.get(ref_tail(ref))
            if buf is not None:
                href = buf.get("CanIfBufferHthRef")
                if isinstance(href, str) and href:
                    h = hths.get(ref_tail(href))
                    if h is not None:
                        cref = h.get("CanIfHthCanCtrlIdRef")
                        if isinstance(cref, str) and cref:
                            return ref_tail(cref)
    else:
        ref = pdu.get("CanIfRxPduHrhIdRef")
        if isinstance(ref, str) and ref:
            h = hrhs.get(ref_tail(ref))
            if h is not None:
                cref = h.get("CanIfHrhCanCtrlIdRef")
                if isinstance(cref, str) and cref:
                    return ref_tail(cref)
    return ""


def _canif_pdu(c: Ecuc, direction: str) -> CanIfPdu:
    pfx = "CanIfRxPdu" if direction == "RX" else "CanIfTxPdu"
    canid_raw = _first_int(c, f"{pfx}CanId")
    id_type_raw = str(
        c.get(f"{pfx}CanIdType", f"{pfx}IdType", default="")
    ).upper()

    id_type = "?"
    if "EXTENDED" in id_type_raw:
        id_type = "EXTENDED"
    elif "STANDARD" in id_type_raw:
        id_type = "STANDARD"

    # STANDARD_FD_CAN / EXTENDED_FD_CAN 里的 FD 是帧格式，不是 ID 类型
    is_fd = "FD_CAN" in id_type_raw or id_type_raw.endswith("_FD")

    can_id = canid_raw
    if can_id is not None and can_id & EXTENDED_FLAG:
        can_id = can_id & ~EXTENDED_FLAG
        if id_type == "?":
            id_type = "EXTENDED"

    ref = c.get(f"{pfx}Ref", default="")

    return CanIfPdu(
        name=c.short_name,
        direction=direction,
        can_id=can_id,
        can_id_raw=canid_raw,
        id_type=id_type,
        is_fd=is_fd,
        dlc=_first_int(c, f"{pfx}Dlc", f"{pfx}DataLength"),
        container=c,
        pdu_ref=ref_tail(ref) if isinstance(ref, str) else "",
    )


def _extract_pdur(model: ArxmlModel, st: StackModel) -> None:
    for rp in model.by_def("PduRRoutingPath"):
        src: list[str] = []
        dest: list[str] = []
        for name, vals in rp.params.items():
            low = name.lower()
            for v in vals:
                if not isinstance(v, str) or not v:
                    continue
                if "src" in low and ("ref" in low or "pdu" in low):
                    src.append(v)
                elif "dest" in low and ("ref" in low or "pdu" in low):
                    dest.append(v)
        # 子容器形式：PduRSrcPdu / PduRDestPdu（最常见）
        for child in rp.children:
            if child.def_type == "PduRSrcPdu":
                for name, vals in child.params.items():
                    if "ref" in name.lower():
                        src.extend(v for v in vals if isinstance(v, str) and v)
            elif child.def_type.startswith("PduRDestPdu"):
                for name, vals in child.params.items():
                    if "ref" in name.lower():
                        dest.extend(v for v in vals if isinstance(v, str) and v)
        route_type = str(rp.get("PduRRouteType", default="")).upper()
        st.routing.append(
            PduRRouting(
                name=rp.short_name,
                src_refs=src,
                dest_refs=dest,
                container=rp,
                route_type=route_type,
            )
        )
    if not st.routing:
        st.notes.append("ARXML 中没有找到 PduRRoutingPath 容器")

    # EcuC 的 Pdu 容器：长度兜底
    for pdu in model.by_def("Pdu"):
        st.ecuc_pdus[pdu.short_name] = _first_int(pdu, "PduLength")

    for ap in st.com_pdus:
        if ap.length is None and ap.pdu_ref in st.ecuc_pdus:
            ap.length = st.ecuc_pdus[ap.pdu_ref]
            ap.length_source = "PduR"


def _extract_candr(model: ArxmlModel, st: StackModel) -> None:
    for ctrl in model.by_def("CanController"):
        st.controllers.append(
            CanController(
                name=ctrl.short_name,
                baudrate=_first_int(ctrl, "CanControllerBaudRate", "CanCpuClockRef"),
                fd_baudrate=_first_int(
                    ctrl, "CanControllerFdBaudRate", "CanControllerBaudRateFd"
                ),
                container=ctrl,
            )
        )
    for hoh in model.by_def("CanHardwareObject"):
        st.hw_objects.append(
            CanHwObject(
                name=hoh.short_name,
                handle_type=str(hoh.get("CanHandleType", default="?")).upper(),
                id_type=str(hoh.get("CanIdType", default="?")).upper(),
                container=hoh,
            )
        )
    if not st.controllers:
        st.notes.append("ARXML 中没有找到 CanController 容器")


def _first_int(c: Ecuc, *names: str) -> int | None:
    for name in names:
        for v in c.params.get(name, []):
            if isinstance(v, bool):
                continue
            if isinstance(v, int):
                return v
            if isinstance(v, float) and v.is_integer():
                return int(v)
            if isinstance(v, str):
                try:
                    return int(v, 0)
                except ValueError:
                    continue
    return None


def _norm_direction(raw: Any) -> str:
    s = str(raw).upper()
    if "SEND" in s or "TX" in s:
        return "SEND"
    if "RECEIVE" in s or "RX" in s:
        return "RECEIVE"
    return "?"


def _norm_name(raw: str) -> str:
    """名字归一：去掉 PDU 前缀、非字母数字、全部小写。

    用于「同一 CanId 有多份 CanIf 配置」时挑出与本帧同名的那一份。
    DBC 帧名 `ECU_L` 与 EcuC Pdu `ECU_L` 归一后相等；
    而改版残留的 `LegacyProjCfg` 归一后不同，会被排到后面。
    """
    s = re.sub(r"^(IPDU_|TX_PDU_|RX_PDU_|CANIF_(TX|RX)PDU_)", "", raw or "", flags=re.I)
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _guess_direction_from_type(ipdu: Ecuc) -> str:
    t = str(ipdu.get("ComIPduType", default="")).upper()
    if t == "NORMAL":
        d = str(ipdu.get("ComIPduDirection", default="")).upper()
        return _norm_direction(d)
    return "?"


def _extract_cycle(ipdu: Ecuc) -> float | None:
    for child in ipdu.children:
        if child.def_type in ("ComTxModeTrue", "ComTxModeFalse", "ComTxMode"):
            v = child.get("ComTxModeTimePeriod", "ComTxModeTimeOffset")
            if isinstance(v, (int, float)):
                return float(v)
    v = ipdu.get("ComIPduCycleTime", "ComTxModeTimePeriod")
    return float(v) if isinstance(v, (int, float)) else None


# ---------------------------------------------------------------------------
# 校验结果
# ---------------------------------------------------------------------------


#: DBC 里的 E2E 信号：由 E2E 库（E2E_P01/P02/...）在 Com 之外写入，
#: 所以 Com 里往往不配它们，不能当成「信号缺失」报。
_E2E_SIGNAL_RE = re.compile(
    r"(checksum|crc|counter|rollcnt|rollingcounter|alivecounter|aliveindication|msgcounter)",
    re.I,
)


def _is_e2e_signal(name: str) -> bool:
    return bool(_E2E_SIGNAL_RE.search(name))


def _is_whole_pdu_opaque(ax: AxPdu) -> bool:
    """Com 是否把整帧当一个字节数组建模（OPAQUE / UINT8_DYN）。

    这种建模下，Com 侧只有 1 个覆盖全帧的信号，而 DBC 可能把它拆成多个；
    两者语义等价，不能逐个信号比。
    """
    if len(ax.signals) != 1 or ax.length is None:
        return False
    s = ax.signals[0]
    if not s.is_byte_array:
        return False
    # 覆盖整帧（长度容差：字节/位两种单位）
    for cand in (s.length, s.length_alt):
        if cand and cand >= ax.length * 8:
            return True
    return False


@dataclass
class Finding:
    code: str
    severity: str
    title: str
    detail: str = ""
    where: str = ""

    def one_line(self) -> str:
        loc = f"  [{self.where}]" if self.where else ""
        return f"[{self.severity[0].upper()}] {self.code}  {self.title}{loc}"


# ---------------------------------------------------------------------------
# 匹配与校验
# ---------------------------------------------------------------------------


@dataclass
class FrameBinding:
    dbc: DbcMessage
    canif: CanIfPdu | None = None
    com: AxPdu | None = None
    direction: str = "?"  # 相对本 ECU：SEND / RECEIVE
    category: str = "COM"  # COM / TP / NM / DIAG / UNKNOWN
    pdu_ref: str = ""  # CanIf 指向的 EcuC Pdu
    note: str = ""
    #: 本 ECU 是否应该参与这帧（发或收）。
    #: 整网矩阵里有大量“与本 ECU 无关”的帧（别的节点的发给第三个节点的），
    #: 它们本来就该在 CanIf/Com 里找不到对应配置，不配报错。
    #: None = 无法判定（DBC 没有接收方信息、也没有节点信息）。
    involved: bool | None = None


def _build_route_index(
    st: StackModel,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """PduR 路由索引：dest->src、src->dest、dest->route_type。"""
    dest_to_src: dict[str, str] = {}
    src_to_dest: dict[str, str] = {}
    dest_to_type: dict[str, str] = {}
    for r in st.routing:
        srcs = [ref_tail(x) for x in r.src_refs if ref_tail(x)]
        dests = [ref_tail(x) for x in r.dest_refs if ref_tail(x)]
        for d in dests:
            dest_to_type[d] = r.route_type
            for s in srcs:
                dest_to_src[d] = s
                src_to_dest[s] = d
    return dest_to_src, src_to_dest, dest_to_type


def _classify(
    pdu_ref: str, dest_to_type: dict[str, str], st: StackModel, frame_name: str = "",
    can_id: int | None = None,
) -> str:
    """根据 CanIf 指向的 EcuC Pdu、PduR 路由类型、DBC 帧名与 CAN ID 判定链路种类。

    优先看 ARXML（更权威），ARXML 没线索时退到 DBC 命名与 ID 区间。
    """
    low = pdu_ref.lower()
    if dest_to_type.get(pdu_ref, "") == "TP" or "cantp" in low:
        return "TP"
    if low.startswith("dcm") or "_usdt" in low or "diag" in low:
        return "DIAG"
    if low.startswith("nm_") or "cannm" in low or low.startswith("nm"):
        return "NM"

    # ARXML 无明确指向时，按 DBC 帧名与 ID 区间补判
    fn = frame_name.upper()
    if fn.startswith("NM_") or fn.startswith("NM") or "_NM_" in fn:
        return "NM"
    if "CANTP" in fn:
        return "TP"
    if fn.startswith("DIAG") or "_DIAG" in fn:
        return "DIAG"
    # ISO 15765 标准诊断 ID 区间
    if can_id is not None:
        if 0x7E0 <= can_id <= 0x7EF or 0x7E8 <= can_id <= 0x7EF + 0x10:
            return "DIAG"
        if can_id == 0x7DF:
            return "DIAG"
    return "COM"


def build_bindings(
    dbc: DbcModel, st: StackModel, node: str | None
) -> tuple[list[FrameBinding], list[AxPdu], list[str]]:
    """按 CAN ID 把 DBC 帧、CanIf PDU、Com IPdu 绑在一起。

    真实拓扑不是按名字直连，而是：
        DBC 帧 --CanId--> CanIf PDU --CanIfXxxPduRef--> EcuC Pdu(X)
             --PduR 路由--> EcuC Pdu(COM_X) --ComPduIdRef--> Com IPdu

    返回 (绑定列表, 未匹配的 Com IPdu, 本配置覆盖的 DBC 节点列表)。
    """
    ecu_nodes = [node] if node else _infer_nodes(dbc, st)
    dest_to_src, src_to_dest, dest_to_type = _build_route_index(st)

    canif_by_id: dict[int, list[CanIfPdu]] = {}
    for p in st.canif_rx + st.canif_tx:
        if p.can_id is not None:
            canif_by_id.setdefault(p.can_id, []).append(p)

    com_by_pdu_ref: dict[str, AxPdu] = {}
    for p in st.com_pdus:
        if p.pdu_ref:
            com_by_pdu_ref[p.pdu_ref] = p

    used_com: set[int] = set()
    bindings: list[FrameBinding] = []

    for can_id, msg in sorted(dbc.messages.items()):
        b = FrameBinding(dbc=msg, direction="?")
        if ecu_nodes:
            # 多节点时：发送方在覆盖范围内就是 SEND，否则 RECEIVE
            b.direction = "SEND" if msg.tx_node in ecu_nodes else "RECEIVE"
        # 整网矩阵里判断这帧到底跟本 ECU 有没有关系
        b.involved = frame_involves_ecu(msg, ecu_nodes)

        # 1) CanIf：按 CAN ID，多个候选时按方向优先
        cand = canif_by_id.get(can_id, [])
        if len(cand) > 1:
            # 同一 ID 多份 CanIf 配置时，光看方向不够（同为 TX 的两份无法区分），
            # 必须再用名字相似度挑 —— 否则会绑到同名改版残留上，
            # 派生出一大串假的「信号缺失」，把真问题淹掉。
            want = ("TX" if b.direction == "SEND" else "RX") if b.direction != "?" else None
            fname = _norm_name(msg.name)

            def _rank(p: CanIfPdu) -> tuple[int, int]:
                dir_rank = 0 if (want and p.direction == want) else 1
                ref = _norm_name(p.pdu_ref or "")
                nm = _norm_name(p.name)
                name_rank = 0 if fname and (fname == ref or fname == nm) else (
                    1 if fname and (fname in ref or ref in fname or fname in nm) else 2
                )
                # 方向优先：DBC 说本 ECU 是发送方时，必须优先选 TX 那份。
                # 名字只用来在同方向的多份里挑「不是改版残留」的那份。
                return (dir_rank, name_rank)

            cand = sorted(cand, key=_rank)
        if cand:
            b.canif = cand[0]
            b.pdu_ref = cand[0].pdu_ref

        # 2) 分类：TP / DIAG / NM / COM
        b.category = _classify(
            b.pdu_ref, dest_to_type, st, frame_name=msg.name, can_id=can_id
        )

        # 3) Com：沿 PduR 路由找到 COM_ 前缀的 Pdu，再找 Com IPdu
        if b.pdu_ref:
            for com_ref in (
                dest_to_src.get(b.pdu_ref),  # dest=X -> src=COM_X
                src_to_dest.get(b.pdu_ref),  # dest=COM_X -> src=X
                b.pdu_ref,  # 直接同名
                "COM_" + b.pdu_ref,
            ):
                if not com_ref:
                    continue
                hit = com_by_pdu_ref.get(com_ref)
                if hit is not None:
                    b.com = hit
                    break

        if b.com is not None:
            used_com.add(id(b.com))
            if b.canif is not None and not b.com.bus:
                b.com.bus = b.canif.bus
        bindings.append(b)

    # 未匹配的 Com：排除 TP / 诊断等本身就不走 Com 链路的
    unused = [
        p
        for p in st.com_pdus
        if id(p) not in used_com
        and dest_to_type.get(p.pdu_ref, "") != "TP"
        and "cantp" not in p.pdu_ref.lower()
    ]

    # 未匹配的 Com IPdu 也补上总线归属：沿路由找到对端 EcuC Pdu，再找 CanIf PDU
    canif_by_pdu_ref: dict[str, CanIfPdu] = {
        p.pdu_ref: p for p in st.canif_rx + st.canif_tx if p.pdu_ref
    }
    for p in unused:
        if p.bus:
            continue
        for other in (dest_to_src.get(p.pdu_ref), src_to_dest.get(p.pdu_ref)):
            if not other:
                continue
            cand = canif_by_pdu_ref.get(other)
            if cand is not None:
                p.bus = cand.bus
                break

    # 总线覆盖率：判断哪条总线不在本 DBC 的覆盖范围内
    dbc_ids = set(dbc.messages)
    stats: dict[str, list[int]] = {}
    for p in st.canif_rx + st.canif_tx:
        if p.can_id is None:
            continue
        key = p.bus or "(未知总线)"
        bucket = stats.setdefault(key, [0, 0])
        bucket[1] += 1
        if p.can_id in dbc_ids:
            bucket[0] += 1
    st.bus_coverage = {k: (v[0], v[1]) for k, v in stats.items()}

    # 命中率 < 20% 的总线：本 DBC 不含这条网络，其帧不参与比对
    st.off_dbc_buses = {
        k for k, (hit, tot) in st.bus_coverage.items() if tot and hit / tot < 0.2
    }

    return bindings, unused, ecu_nodes


def _bus_in_dbc(pdu: CanIfPdu | None, st: StackModel) -> bool:
    """该 CanIf PDU 所在总线是否落在这份 DBC 的覆盖范围内。"""
    if pdu is None or not pdu.bus:
        return True
    return pdu.bus not in st.off_dbc_buses


def _match_com_by_prefix(name: str, pdus: list[AxPdu], used: set[int]) -> AxPdu | None:
    norm = re.sub(r"[^a-z0-9]", "", name.lower())
    for p in pdus:
        if id(p) in used:
            continue
        pn = re.sub(r"[^a-z0-9]", "", p.name.lower())
        if not pn:
            continue
        if pn == norm or pn.endswith(norm) or norm.endswith(pn):
            return p
    return None


def _infer_nodes(dbc: DbcModel, st: StackModel) -> list[str]:
    """找出本配置覆盖了 DBC 里的哪几个节点。

    一个 MCU 可能同时管左右两路（如 ECU_L + ECU_R），此时方向类检查不能按
    单节点推断，必须退化为“多节点”模式，否则会把对侧帧误判成方向错。
    """
    if not dbc.nodes:
        return []
    blob = " ".join(c.name for c in st.com_pdus)
    blob += " " + " ".join(p.name for p in st.canif_rx + st.canif_tx)
    return [
        node
        for node in dbc.nodes
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(node)}(?![A-Za-z0-9])", blob)
    ]


def frame_involves_ecu(msg: DbcMessage, ecu_nodes: list[str]) -> bool | None:
    """本 ECU 是否应该参与这帧（发或收）。

    整网矩阵（一个 DBC 含全部 11 个节点、91 帧）里，绝大多数帧与本 ECU 无关：
    是别的节点发给第三个节点的。这些帧本来就**不该**在本 ECU 的 CanIf/Com 里
    出现，缺配置是正确状态，不是缺陷。

    原先的逻辑假定「DBC 每一帧都必须在本 ECU 里有配置」——那只对**单 ECU 视角**
    的 DBC 成立。整网矩阵上这个假定会造出大量假 error（实测 91 帧里 99 条误报）。

    返回 None 表示无法判定（没有节点信息，或节点对不上 DBC 的节点表）。
    """
    if not ecu_nodes or not msg.signals:
        return None
    if msg.tx_node in ecu_nodes:
        return True  # 本 ECU 是发送方
    for sig in msg.signals.values():
        for rx in sig.receivers:
            if rx in ecu_nodes:
                return True  # 本 ECU 是某个信号的接收方
    # 有发送方信息、有接收方信息，且都不含本 ECU -> 与本 ECU 无关
    known_rx = any(sig.receivers for sig in msg.signals.values())
    if known_rx and msg.tx_node and msg.tx_node not in ("Vector__XXX", ""):
        return False
    return None


def _infer_node(dbc: DbcModel, st: StackModel) -> str | None:
    nodes = _infer_nodes(dbc, st)
    return nodes[0] if nodes else None


def run_checks(
    dbc: DbcModel, st: StackModel, node: str | None = None
) -> tuple[list[Finding], list[FrameBinding], list[str]]:
    findings: list[Finding] = []
    bindings, unused_com, ecu_nodes = build_bindings(dbc, st, node)
    ecu_node = ", ".join(ecu_nodes) if ecu_nodes else ""

    # ---------- L0 前置 ----------
    # 空 DBC / 给错 DBC 是最容易造成「假绿」的场景：所有 PDU 都会因总线
    # 命中率 0% 被判为「不在本 DBC 范围」而整体跳过，最终报 0 error 0 warn。
    # 那等于什么都没查。必须失败，而不是成功。
    if not dbc.messages:
        findings.append(
            Finding(
                "AXD-023", "error",
                "DBC 里没有任何帧（BO_ 为空）",
                "没有参照物就无法校验。请确认给的是通信矩阵，"
                "而不是空文件或只含 BU_/VAL_TABLE_ 的片段。",
                where=str(dbc.path),
            )
        )
        return findings, [], ecu_nodes

    if st.canif_rx or st.canif_tx:
        in_scope = [
            p
            for p in st.canif_rx + st.canif_tx
            if p.can_id is not None and _bus_in_dbc(p, st)
        ]
        if not in_scope:
            findings.append(
                Finding(
                    "AXD-023", "error",
                    "没有任何 CanIf PDU 落在本 DBC 的覆盖范围内",
                    "两种可能：一是这份 DBC 不是本 ECU 所属网络的（给错了文件）；"
                    "二是总线归属回溯失败。无论哪种，本次校验实际上什么都没比。",
                    where=", ".join(sorted(st.bus_coverage)) or "无总线信息",
                )
            )
            return findings, [], ecu_nodes

    if not st.com_pdus:
        findings.append(
            Finding("AXD-000", "warn", "ARXML 未解析出 Com IPdu",
                    "后续 Com 层校验全部跳过。请先用 probe 确认容器/参数命名。")
        )

    # ---------- CanIf 层 ----------
    unrelated = 0
    for b in bindings:
        msg = b.dbc
        if b.canif is None:
            # 整网矩阵里与本 ECU 无关的帧：不配 CanIf 是**正确**状态
            if b.involved is False and b.category == "COM":
                unrelated += 1
                continue
            # NM / 诊断帧经常不在 CanIf 里（走 CanNm / CanTp+Dcm 的专用通道），
            # 只在确认属于 COM 链路时才报 error
            if b.category == "COM":
                findings.append(
                    Finding(
                        "AXD-001", "error",
                        f"DBC 帧 {msg.name}(0x{msg.can_id:X}) 在 CanIf 中无对应 PDU",
                        "该帧不会被收发：接收方永远等不到，发送方不会发出去。",
                        where=f"0x{msg.can_id:X}",
                    )
                )
            else:
                findings.append(
                    Finding(
                        "AXD-024", "info",
                        f"{b.category} 帧 {msg.name}(0x{msg.can_id:X}) 未在 CanIf 中单独配置",
                        "NM / 诊断 / TP 通常由 CanNm / Dcm / CanTp 内部管理，"
                        "需要人工确认这几层是否存在对应配置。",
                        where=f"0x{msg.can_id:X}",
                    )
                )
            continue
        p = b.canif
        # CanIf 收发方向与 DBC 发送方的一致性
        if b.direction != "?":
            want_dir = "TX" if b.direction == "SEND" else "RX"
            if p.direction != want_dir:
                findings.append(
                    Finding(
                        "AXD-022", "error",
                        f"{p.name} 是 {p.direction} PDU，但本 ECU 对 "
                        f"0x{msg.can_id:X} 应为 {want_dir}",
                        "收发方向配反，报文不会进本 PDU 的缓冲。",
                        where=p.name,
                    )
                )
        # TP 帧的 CanIf DLC 由 CanTp 协商，诊断帧 DBC 常写最大长度
        # —— 这两类都不与 DBC 单帧 DLC 硬比
        if (
            b.category not in ("TP", "DIAG")
            and p.dlc is not None
            and p.dlc != msg.dlc
        ):
            findings.append(
                Finding(
                    "AXD-003", "error",
                    f"{p.name} DLC 与 DBC 不一致：CanIf={p.dlc}B / DBC={msg.dlc}B",
                    "长度不符会导致 PDU 被截断或读取越界。",
                    where=p.name,
                )
            )
        if p.id_type != "?":
            want = "EXTENDED" if msg.is_extended else "STANDARD"
            if p.id_type != want:
                findings.append(
                    Finding(
                        "AXD-004", "error",
                        f"{p.name} CanIdType={p.id_type}，但 0x{msg.can_id:X} 应为 {want}",
                        "标准/扩展帧不匹配时报文收不到。",
                        where=p.name,
                    )
                )
        # DBC 是 FD 但 CanIf 未配 FD 帧格式
        if msg.is_fd and p.id_type != "?" and not p.is_fd:
            findings.append(
                Finding(
                    "AXD-016", "error",
                    f"{p.name} 未配 FD 帧格式，但 DBC 中 0x{msg.can_id:X} 是 CAN FD",
                    "FD 帧按普通 CAN 处理，长数据会被丢。",
                    where=p.name,
                )
            )

    # 同一个 CanId 出现多份 CanIf 配置（典型：RX+TX 各一份，或改版本没删旧容器）。
    # 绑定只会取其中一份，另一份的错误会被静默吞掉——必须单独报出来。
    _by_can_id: dict[int, list[CanIfPdu]] = {}
    for p in st.canif_rx + st.canif_tx:
        if p.can_id is not None:
            _by_can_id.setdefault(p.can_id, []).append(p)
    for cid, plist in sorted(_by_can_id.items()):
        if len(plist) < 2:
            continue
        desc = " / ".join(
            f"{q.direction}:{q.name}({'FD' if q.is_fd else '经典'},DLC={q.dlc})"
            for q in plist
        )
        # 多份配置本身不一定是错：两套工程合并到同一 ARXML 时，
        # 两边的 PDU 可能恰好落在同一个 CAN ID 上，这是**有意设计**。
        # 真正不可接受的是其中某一份自己就自相矛盾（经典帧却配 >8 字节），
        # 那份一定跑不起来。所以只按「有无自相矛盾的副本」定严重度。
        self_contradictory = [
            q for q in plist if (not q.is_fd) and q.dlc is not None and q.dlc > 8
        ]
        if self_contradictory:
            detail = (
                "其中 "
                + "、".join(
                    f"{q.name} 是经典帧却配了 {q.dlc} 字节（经典帧上限 8 字节）"
                    for q in self_contradictory
                )
                + "，这份配置不可能正常收发。"
            )
        else:
            detail = (
                "多套工程合并到同一 ARXML 时，PDU 落在同一 CAN ID 上属正常设计，"
                "只要每份自身长度/FD 状态自洽即可忽略；否则需确认保留哪一份。"
            )
        findings.append(
            Finding(
                "AXD-025", "error" if self_contradictory else "warn",
                f"CanId 0x{cid:X} 有 {len(plist)} 份 CanIf 配置：{desc}",
                detail,
                where=f"0x{cid:X}",
            )
        )

    dbc_ids = set(dbc.messages)
    for p in st.canif_rx + st.canif_tx:
        if p.can_id is None:
            continue
        if p.can_id not in dbc_ids:
            cat = _classify(p.pdu_ref, {}, st, frame_name=p.name, can_id=p.can_id)
            in_scope = _bus_in_dbc(p, st)
            if not in_scope:
                # 该总线不在这份 DBC 的覆盖范围内，不报警
                findings.append(
                    Finding(
                        "AXD-026", "info",
                        f"{p.bus} 上的 {p.name} (0x{p.can_id:X}) 不在本 DBC 覆盖范围",
                        "该总线已整体跳过，详见头部「总线」行。",
                        where=p.name,
                    )
                )
                continue
            findings.append(
                Finding(
                    "AXD-002", "warn" if cat == "COM" else "info",
                    f"CanIf PDU {p.name} 的 CanId=0x{p.can_id:X} 在 DBC 中不存在",
                    "可能是多配、或 DBC 漏了这帧。"
                    if cat == "COM"
                    else f"该 PDU 属于 {cat} 链路，DBC 通常不收录。",
                    where=p.name,
                )
            )

    # ---------- Com 层 ----------
    for b in bindings:
        msg = b.dbc
        if b.com is None:
            if not st.com_pdus:
                continue
            # 与本 ECU 无关的帧，Com 里没有配置是正确状态
            if b.involved is False and b.category == "COM":
                continue
            if b.category == "COM":
                findings.append(
                    Finding(
                        "AXD-006", "error",
                        f"DBC 帧 {msg.name}(0x{msg.can_id:X}) 在 Com 中无对应 IPdu",
                        "Com 层不知道这帧，信号不会被打包/解包。",
                        where=f"0x{msg.can_id:X}",
                    )
                )
            else:
                findings.append(
                    Finding(
                        "AXD-024", "info",
                        f"{b.category} 帧 {msg.name}(0x{msg.can_id:X}) 不经过 Com",
                        "属正常拓扑：NM 走 CanNm，诊断走 Dcm/CanTp。",
                        where=f"0x{msg.can_id:X}",
                    )
                )
            continue
        ax = b.com
        # TP PDU 是分段传输的缓冲区，长度与单帧 DLC 无可比性
        if ax.length is not None and ax.length != msg.dlc and b.category != "TP":
            findings.append(
                Finding(
                    "AXD-005", "error",
                    f"{ax.name} Com IPdu 长度 {ax.length}B ≠ DBC DLC {msg.dlc}B",
                    "PDU 长度是上下层一致的硬约束。",
                    where=ax.name,
                )
            )

        # 方向一致性
        if b.direction != "?" and ax.direction != "?":
            if b.direction != ax.direction:
                findings.append(
                    Finding(
                        "AXD-020", "warn",
                        f"{ax.name} 方向 {ax.direction} 与 DBC 发送方矛盾",
                        f"本 ECU({ecu_node}) 在 DBC 里对 0x{msg.can_id:X} 是 {b.direction}。",
                        where=ax.name,
                    )
                )

        # 信号集合
        ax_sigs = {s.name: s for s in ax.signals}
        dbc_sigs = msg.signals

        # 整帧 OPAQUE 建模，或所在总线不在本 DBC 覆盖范围：不做逐信号比对
        if _is_whole_pdu_opaque(ax) or not _bus_in_dbc(b.canif, st):
            continue

        for sname, dsig in dbc_sigs.items():
            if sname not in ax_sigs:
                # E2E 信号（Checksum / RollingCounter）由 E2E 库写入，Com 不配属正常
                if _is_e2e_signal(sname):
                    continue
                alt = _find_name_drift(sname, ax_sigs)
                if alt:
                    findings.append(
                        Finding(
                            "AXD-019", "warn",
                            f"信号命名漂移：DBC '{sname}' ↔ ARXML '{alt}'",
                            "仅大小写/下划线差异，工具能认，但手写代码会取不到值。",
                            where=ax.name,
                        )
                    )
                    ax_sigs[alt].name = sname  # 归一后继续做几何比对
                    ax_sigs[sname] = ax_sigs.pop(alt)
                else:
                    findings.append(
                        Finding(
                            "AXD-006", "error",
                            f"{ax.name} 缺少 DBC 信号 '{sname}'",
                            f"位 {dsig.start}|{dsig.length}@{dsig.byte_order}",
                            where=ax.name,
                        )
                    )
        for sname in list(ax_sigs):
            if sname not in dbc_sigs:
                # Com 里的 E2E 信号，DBC 未定义时也不报
                if _is_e2e_signal(sname):
                    continue
                findings.append(
                    Finding(
                        "AXD-007", "warn",
                        f"{ax.name} 里多出 DBC 中不存在的信号 '{sname}'",
                        "Com 配了但 DBC 没定义，联调时该位无人解读。",
                        where=ax.name,
                    )
                )

        # 逐个信号比对
        for sname, dsig in dbc_sigs.items():
            asig = ax_sigs.get(sname)
            if asig is None:
                continue
            _check_signal(findings, ax, dsig, asig)

        # Com 内部重叠
        _check_internal_overlap(findings, ax)

    for ax in unused_com:
        if not dbc.messages:
            continue
        # 该 Com IPdu 所在总线不在本 DBC 覆盖范围 → 不报
        if ax.bus and ax.bus in st.off_dbc_buses:
            continue
        findings.append(
            Finding(
                "AXD-007", "warn",
                f"Com IPdu {ax.name} 在 DBC 中找不到对应帧",
                "可能已废弃、或 DBC 版本滞后。",
                where=ax.name,
            )
        )

    # ---------- PduR 层 ----------
    _check_pdur(findings, dbc, st, bindings)

    # ---------- CanDrv 层 ----------
    if st.hw_objects:
        has_ext = any(m.is_extended for m in dbc.messages.values())
        has_std = any(not m.is_extended for m in dbc.messages.values())
        types = {h.id_type for h in st.hw_objects}
        if has_ext and not any("EXTENDED" in t or "MIXED" in t for t in types):
            findings.append(
                Finding("AXD-004", "error",
                        "DBC 含扩展帧，但 CanHardwareObject 无 EXTENDED/MIXED",
                        f"现有: {', '.join(sorted(types))}", where="CanDrv")
            )
        if has_std and not any("STANDARD" in t or "MIXED" in t for t in types):
            findings.append(
                Finding("AXD-004", "error",
                        "DBC 含标准帧，但 CanHardwareObject 无 STANDARD/MIXED",
                        f"现有: {', '.join(sorted(types))}", where="CanDrv")
            )
    for ctrl in st.controllers:
        if ctrl.baudrate is not None and ctrl.baudrate < 10000:
            findings.append(
                Finding("AXD-021", "info",
                        f"{ctrl.name} 波特率异常小：{ctrl.baudrate}",
                        "可能单位是 kbps 而非 bps，仅供参考。", where=ctrl.name)
            )

    findings.sort(key=lambda f: (-SEV_ORDER[f.severity], f.code))
    return findings, bindings, ecu_nodes


def _find_name_drift(name: str, pool: dict[str, Any]) -> str | None:
    norm = re.sub(r"[^a-z0-9]", "", name.lower())
    for cand in pool:
        if re.sub(r"[^a-z0-9]", "", cand.lower()) == norm and cand != name:
            return cand
    return None


def _check_signal(
    findings: list[Finding], ax: AxPdu, dsig: DbcSignal, asig: AxSignal
) -> None:
    where = f"{ax.name}.{dsig.name}"

    # 字节序
    if asig.byte_order != "?" and asig.byte_order != dsig.byte_order:
        findings.append(
            Finding(
                "AXD-009", "error",
                f"{where} 字节序不一致：Com={asig.byte_order} / DBC={dsig.byte_order}",
                "大端小端搞反会让数值完全错乱。",
                where=where,
            )
        )

    if asig.length is not None and asig.length != dsig.length:
        findings.append(
            Finding(
                "AXD-010", "error",
                f"{where} 位宽不一致：Com={asig.length} / DBC={dsig.length}",
                "", where=where,
            )
        )

    if asig.signed is not None and asig.signed != dsig.signed:
        findings.append(
            Finding(
                "AXD-010", "error",
                f"{where} 符号性不一致：Com={'signed' if asig.signed else 'unsigned'} "
                f"/ DBC={'signed' if dsig.signed else 'unsigned'}",
                "有符号当无符号解析，负值会变成大正数。", where=where,
            )
        )

    # 位几何：只按 DBC 与 AUTOSAR 实测一致的 MSB 约定算。
    # 若厂商用了 LSB 约定，这里会报 AXD-008 —— 提交给人确认，不做静默回退，
    # 否则真正的起始位错误会被"约定回退"掩盖掉。
    if asig.start_position is not None and asig.length is not None:
        want = dsig.bits()
        got = asig.bits
        if got != want:
            findings.append(
                Finding(
                    "AXD-008", "error",
                    f"{where} 位几何不一致",
                    f"Com: start={asig.start_position} len={asig.length} "
                    f"[{asig.bits_convention}] 占用 bits={sorted(got)[:8]}…\n"
                    f"      DBC: start={dsig.start} len={dsig.length} "
                    f"占用 bits={sorted(want)[:8]}…",
                    where=where,
                )
            )

    # 越界
    if ax.length and asig.bits and max(asig.bits) >= ax.length * 8:
        findings.append(
            Finding(
                "AXD-017", "error",
                f"{where} 越过 IPdu 边界：最高 bit {max(asig.bits)} ≥ {ax.length*8}",
                "", where=where,
            )
        )

    # 初始值
    if asig.init_value is not None and dsig.start_value is not None:
        if abs(asig.init_value - dsig.start_value) > 1e-9:
            findings.append(
                Finding(
                    "AXD-011", "error",
                    f"{where} 初始值不一致：Com={asig.init_value} / DBC={dsig.start_value}",
                    "以 DBC 的 GenSigStartValue 为准。上电到第一次收发之间，"
                    "收发双方看到的就是初始值；不一致会导致这段时间的状态判断出错"
                    "（例：大灯高度初始角算错）。两边都没写、或只有一边写，不算问题。",
                    where=where,
                )
            )



def _check_cycle(findings: list[Finding], msg: DbcMessage, ax: AxPdu) -> None:
    if ax.cycle_ms is None or msg.cycle_ms is None:
        return
    raw = ax.cycle_ms
    candidates = {raw, raw * 1000.0, raw / 1000.0}
    if any(abs(c - msg.cycle_ms) <= 1.0 for c in candidates):
        return
    findings.append(
        Finding(
            "AXD-012", "warn",
            f"{ax.name} 周期不一致：Com={raw} / DBC={msg.cycle_ms}ms",
            "已尝试秒/毫秒两种换算仍不匹配。",
            where=ax.name,
        )
    )



def _check_internal_overlap(findings: list[Finding], ax: AxPdu) -> None:
    seen: dict[int, str] = {}
    for sig in ax.signals:
        if sig.is_byte_array:
            continue
        for bit in sorted(sig.bits):
            if bit in seen:
                findings.append(
                    Finding(
                        "AXD-018", "error",
                        f"{ax.name} 内信号位重叠：bit {bit} 被 "
                        f"'{seen[bit]}' 与 '{sig.name}' 同时占用",
                        "两个信号抢同一位，值永远错。",
                        where=ax.name,
                    )
                )
                break
            seen[bit] = sig.name


def _check_pdur(
    findings: list[Finding],
    dbc: DbcModel,
    st: StackModel,
    bindings: list[FrameBinding],
) -> None:
    if not st.routing:
        return

    # 已知的 EcuC Pdu 全集：EcuC 定义 + Com 引用 + CanIf 引用
    known: set[str] = set(st.ecuc_pdus)
    known |= {p.pdu_ref for p in st.com_pdus if p.pdu_ref}
    known |= {p.pdu_ref for p in st.canif_rx + st.canif_tx if p.pdu_ref}

    routed: set[str] = set()
    for r in st.routing:
        ends = [ref_tail(x) for x in r.src_refs + r.dest_refs]
        ends = [x for x in ends if x]
        routed.update(ends)
        # 悬空引用：引用的名字在 EcuC / Com / CanIf 里一个都不存在
        for tail in ends:
            if tail not in known:
                findings.append(
                    Finding(
                        "AXD-014", "error",
                        f"PduR 路由 {r.name} 引用了不存在的 PDU '{tail}'",
                        "悬空引用会导致该路由失效，链接期或运行时才暴露。",
                        where=r.name,
                    )
                )

    # Com IPdu 是否接上了 PduR（按它的 EcuC Pdu 引用判断）
    for b in bindings:
        if b.com is None or b.category == "TP":
            continue
        ref = b.com.pdu_ref
        if not ref:
            findings.append(
                Finding(
                    "AXD-015", "error",
                    f"Com IPdu {b.com.name} 没有 ComPduIdRef，无法接入 PduR",
                    "Com 与下层之间没有通路，数据不会流转。",
                    where=b.com.name,
                )
            )
        elif ref not in routed:
            findings.append(
                Finding(
                    "AXD-015", "error",
                    f"Com IPdu {b.com.name} 的 PDU '{ref}' 没有 PduR 路由",
                    "Com 与下层之间没有通路，数据不会流转。",
                    where=b.com.name,
                )
            )

    # CanIf PDU 是否也有路由（NM / 诊断例外）
    for b in bindings:
        if b.canif is None or b.category in ("NM", "DIAG", "TP"):
            continue
        ref = b.canif.pdu_ref
        if ref and ref not in routed:
            findings.append(
                Finding(
                    "AXD-015", "error",
                    f"CanIf PDU {b.canif.name} 的 PDU '{ref}' 没有 PduR 路由",
                    "报文能收到但上不去，或 Com 发出来但下不去。",
                    where=b.canif.name,
                )
            )


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------


def render(findings: list[Finding], min_sev: str = "info") -> str:
    threshold = SEV_ORDER[min_sev]
    shown = [f for f in findings if SEV_ORDER[f.severity] >= threshold]
    counts = {s: sum(1 for f in findings if f.severity == s) for s in SEV_ORDER}
    lines: list[str] = []
    last = None
    for f in shown:
        if f.code != last:
            lines.append("")
            last = f.code
        lines.append(f.one_line())
        if f.detail:
            for dl in f.detail.split("\n"):
                lines.append("      " + dl)
    lines.append("")
    lines.append(
        f"summary: {counts['error']} error, {counts['warn']} warn, {counts['info']} info"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------


def cmd_probe(args: argparse.Namespace) -> int:
    model = parse_arxml(Path(args.arxml))
    st = extract_stack(model)
    print(f"file      {model.path}")
    print(f"encoding  {model.encoding}")
    print(f"modules   {', '.join(model.module_names()) or '(none)'}")
    print()
    print("=== 容器类型统计 ===")
    counts: dict[str, int] = {}
    for c in model.containers:
        counts[c.def_type] = counts.get(c.def_type, 0) + 1
    for name, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        if n >= 1:
            print(f"  {name:<36} {n}")
    print()
    print("=== 各层抽取结果 ===")
    print(f"  Com IPdu        {len(st.com_pdus):>4}   信号 "
          f"{sum(len(p.signals) for p in st.com_pdus):>4}")
    print(f"  CanIf RX/TX     {len(st.canif_rx):>4} / {len(st.canif_tx)}")
    print(f"  PduR 路由       {len(st.routing):>4}")
    print(f"  CanController   {len(st.controllers):>4}")
    print(f"  CanHardwareObj  {len(st.hw_objects):>4}")
    if st.notes:
        print()
        print("=== 注意 ===")
        for n in st.notes:
            print("  ! " + n)

    if args.json:
        payload = {
            "modules": model.module_names(),
            "container_counts": counts,
            "com_pdus": [
                {
                    "name": p.name,
                    "direction": p.direction,
                    "length": p.length,
                    "cycle_ms": p.cycle_ms,
                    "signals": [
                        {
                            "name": s.name,
                            "start": s.start_position,
                            "len": s.length,
                            "order": s.byte_order,
                            "source": s.source,
                        }
                        for s in p.signals
                    ],
                }
                for p in st.com_pdus
            ],
            "canif": [
                {"name": p.name, "dir": p.direction, "canid": p.can_id,
                 "id_type": p.id_type, "dlc": p.dlc}
                for p in st.canif_rx + st.canif_tx
            ],
            "routing": [
                {"name": r.name, "src": r.src_refs, "dest": r.dest_refs}
                for r in st.routing
            ],
            "notes": st.notes,
        }
        print()
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    arxml_path = Path(args.arxml)
    dbc_path = Path(args.dbc)
    model = parse_arxml(arxml_path)
    st = extract_stack(model)
    dbc = parse_dbc(dbc_path)

    findings, bindings, ecu_nodes = run_checks(dbc, st, args.node)
    ecu_node = ", ".join(ecu_nodes) if ecu_nodes else ""

    # 帧级周期校验（信号循环里不做）
    for b in bindings:
        if b.com is not None:
            _check_cycle(findings, b.dbc, b.com)
    findings.sort(key=lambda f: (-SEV_ORDER[f.severity], f.code))

    if args.json:
        print(json.dumps(
            {
                "arxml": str(arxml_path),
                "dbc": str(dbc_path),
                "ecu_nodes": ecu_nodes,
                "dbc_encoding": dbc.encoding,
                "arxml_encoding": model.encoding,
                "frames": len(dbc.messages),
                "com_pdus": len(st.com_pdus),
                "canif_pdus": len(st.canif_rx) + len(st.canif_tx),
                "routing_paths": len(st.routing),
                "bus_coverage": {
                    k: {"hit": v[0], "total": v[1],
                        "in_scope": k not in st.off_dbc_buses}
                    for k, v in sorted(st.bus_coverage.items())
                },
                "findings": [
                    {"code": f.code, "severity": f.severity, "title": f.title,
                     "detail": f.detail, "where": f.where}
                    for f in findings
                ],
                "notes": st.notes,
            },
            ensure_ascii=False, indent=2,
        ))
    else:
        print(f"arxml   {arxml_path}   (编码 {model.encoding})")
        print(f"dbc     {dbc_path}   (编码 {dbc.encoding})")
        print(f"模块    {', '.join(st.present_modules)}")
        print(f"帧      DBC {len(dbc.messages)} / Com {len(st.com_pdus)} / "
              f"CanIf {len(st.canif_rx)+len(st.canif_tx)} / 路由 {len(st.routing)}")
        print(f"ECU 节点 {ecu_node or '(未识别，跳过方向校验，可用 --node 指定)'}")
        # 总线覆盖率必须打出来：命中率低的总线会被整体跳过，
        # 不说清楚就会把「只查了一条总线」误读成「全都对上了」
        if st.bus_coverage:
            parts = []
            for bus, (hit, tot) in sorted(st.bus_coverage.items()):
                tag = "跳过" if bus in st.off_dbc_buses else "比对"
                parts.append(f"{bus} {hit}/{tot} {tag}")
            print(f"总线    {' | '.join(parts)}")
        for n in st.notes:
            print(f"注意    {n}")
        print(render(findings, args.min_severity))

    has_error = any(f.severity == "error" for f in findings)
    if args.no_fail:
        return 0
    return 1 if has_error else 0


def cmd_matrix(args: argparse.Namespace) -> int:
    model = parse_arxml(Path(args.arxml))
    st = extract_stack(model)
    dbc = parse_dbc(Path(args.dbc))
    bindings, unused, ecu_nodes = build_bindings(dbc, st, args.node)
    ecu_node = ", ".join(ecu_nodes) if ecu_nodes else ""

    rows = []
    for b in bindings:
        m = b.dbc
        ax = b.com
        ax_sigs = {s.name: s for s in ax.signals} if ax else {}
        used_ax: set[str] = set()
        status_map: dict[str, str] = {}

        # 不走 Com 链路的帧（NM / 诊断 / TP）：整体一行标注，
        # 不逐信号报「只有DBC」，否则 64 个 TP 分片会肿成上百行假差异
        if ax is None or not _bus_in_dbc(b.canif, st):
            why = (
                f"不在本 DBC 覆盖的总线({b.canif.bus})"
                if ax is not None and not _bus_in_dbc(b.canif, st)
                else f"{b.category} 链路，不经过 Com"
            )
            rows.append({
                "canid": f"0x{m.can_id:X}",
                "frame": m.name,
                "dlc": m.dlc,
                "tx_node": m.tx_node,
                "ecu_dir": b.direction,
                "canif_pdu": b.canif.name if b.canif else "",
                "com_pdu": ax.name if ax else "",
                "dbc_signal": f"({len(m.signals)} 个信号)",
                "arxml_signal": "",
                "status": "不比对",
                "dbc_geom": why,
                "arxml_geom": "",
            })
            continue

        # 整帧 OPAQUE 建模：Com 侧只有 1 个字节数组信号，DBC 拆分建模，
        # 语义等价，导出时标注 whole-pdu 而不是逐行报「只有DBC」
        if ax is not None and _is_whole_pdu_opaque(ax):
            only = ax.signals[0]
            rows.append({
                "canid": f"0x{m.can_id:X}",
                "frame": m.name,
                "dlc": m.dlc,
                "tx_node": m.tx_node,
                "ecu_dir": b.direction,
                "canif_pdu": b.canif.name if b.canif else "",
                "com_pdu": ax.name,
                "dbc_signal": f"({len(m.signals)} 个信号)",
                "arxml_signal": only.name,
                "status": "整帧字节数组",
                "dbc_geom": "",
                "arxml_geom": f"{only.start_position}|{only.length}@{only.byte_order}",
            })
            continue

        # 先按同名配对，再按命名漂移配对，剩下的各自单列
        pairs: list[tuple[str, str]] = []
        for dn in m.signals:
            if dn in ax_sigs:
                pairs.append((dn, dn))
                used_ax.add(dn)
        for dn in m.signals:
            if any(dn == x for x, _ in pairs):
                continue
            drift = _find_name_drift(dn, ax_sigs)
            if drift is not None and drift not in used_ax:
                pairs.append((dn, drift))
                used_ax.add(drift)
                status_map[dn] = "名字漂移"
        for dn in m.signals:
            if not any(dn == x for x, _ in pairs):
                pairs.append((dn, ""))
                # E2E 信号由 E2E 库在 Com 之外写入，Com 未配置属正常
                status_map[dn] = "E2E信号未配" if _is_e2e_signal(dn) else "只有DBC"
        for an in ax_sigs:
            if an not in used_ax:
                pairs.append(("", an))
                # Com 里的 E2E 信号，DBC 未定义时也不当差异报
                status_map[an] = (
                    "E2E信号未配" if _is_e2e_signal(an) else "只有ARXML"
                )

        for dn, an in pairs:
            d = m.signals.get(dn)
            a = ax_sigs.get(an)
            status = status_map.get(dn) or status_map.get(an) or "OK"
            if status == "OK" and d and a:
                if d.bits() != a.bits:
                    status = "几何不同"
                elif d.length != a.length:
                    status = "位宽不同"
                elif a.byte_order != "?" and d.byte_order != a.byte_order:
                    status = "字节序不同"
            rows.append({
                "canid": f"0x{m.can_id:X}",
                "frame": m.name,
                "dlc": m.dlc,
                "tx_node": m.tx_node,
                "ecu_dir": b.direction,
                "canif_pdu": b.canif.name if b.canif else "",
                "com_pdu": ax.name if ax else "",
                "dbc_signal": dn,
                "arxml_signal": an,
                "status": status,
                "dbc_geom": f"{d.start}|{d.length}@{d.byte_order}" if d else "",
                "arxml_geom": (
                    f"{a.start_position}|{a.length}@{a.byte_order}" if a else ""
                ),
            })

    out = Path(args.csv)
    with out.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["canid"])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out}  ({len(rows)} 行, ECU 节点 {ecu_node or '未识别'}, "
          f"{len(unused)} 个 Com IPdu 未匹配)")
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    """用程序生成的内置示例跑一遍，断言预期检查码全部命中。"""
    import tempfile

    try:
        import demo_fixtures as fixtures
    except ImportError:  # pragma: no cover
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import demo_fixtures as fixtures

    with tempfile.TemporaryDirectory() as td:
        ax = Path(td) / "demo.arxml"
        dbc_path = Path(td) / "demo.dbc"
        ax.write_text(fixtures.build_demo_arxml(), encoding="utf-8")
        dbc_path.write_text(fixtures.DEMO_DBC, encoding="utf-8")

        model = parse_arxml(ax)
        st = extract_stack(model)
        dbc_model = parse_dbc(dbc_path)
        findings, bindings, node = run_checks(dbc_model, st, None)

    codes = sorted({f.code for f in findings})
    expected = set(fixtures.EXPECTED_CODES)
    missing = expected - set(codes)
    print(f"节点推断: {node or '(未识别)'}")
    print(f"帧 {len(dbc_model.messages)} / ComPdus {len(st.com_pdus)} / "
          f"CanIf {len(st.canif_rx)+len(st.canif_tx)} / 路由 {len(st.routing)}")
    print(f"命中代码: {', '.join(codes) or '(无)'}")
    print(render(findings, "info"))
    if missing:
        print(f"自检失败：以下预期代码未触发 -> {', '.join(sorted(missing))}",
              file=sys.stderr)
        return 1

    # 只断言码集合是不够的：示例数据漂到面目全非时码仍可能触发，
    # 「自检通过」会变成一句空话。条数也要卡住。
    got_counts = {
        lvl: sum(1 for f in findings if f.severity == lvl)
        for lvl in ("error", "warn", "info")
    }
    want_counts = getattr(fixtures, "EXPECTED_COUNTS", None)
    if want_counts:
        off = {k: (want_counts.get(k), got_counts[k])
               for k in got_counts if want_counts.get(k) != got_counts[k]}
        if off:
            detail = ", ".join(f"{k} 期望 {w} 实得 {g}" for k, (w, g) in off.items())
            print(f"自检失败：条数不符 -> {detail}", file=sys.stderr)
            return 1
    print("自检通过")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="arxml_dbc_check",
        description="AUTOSAR 通信栈 ARXML (Com/PduR/CanIf/CanDrv) 与 DBC 交叉校验",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("probe", help="探测 ARXML 变体")
    sp.add_argument("arxml")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_probe)

    sc = sub.add_parser("check", help="全链路校验")
    sc.add_argument("arxml")
    sc.add_argument("dbc")
    sc.add_argument("--node", help="本 ECU 在 DBC 中的节点名（用于方向校验）")
    sc.add_argument("--json", action="store_true")
    sc.add_argument("--min-severity", default="info",
                    choices=["error", "warn", "info"])
    sc.add_argument("--no-fail", action="store_true")
    sc.set_defaults(func=cmd_check)

    sm = sub.add_parser("matrix", help="导出帧-信号对照台账 CSV")
    sm.add_argument("arxml")
    sm.add_argument("dbc")
    sm.add_argument("--csv", required=True)
    sm.add_argument("--node")
    sm.set_defaults(func=cmd_matrix)

    ss = sub.add_parser("selftest", help="内置示例自检")
    ss.set_defaults(func=cmd_selftest)

    args = p.parse_args(argv)

    # 先把输入文件查一遍，避免在深层派系里抛裸 traceback
    for attr in ("arxml", "dbc"):
        val = getattr(args, attr, None)
        if not val:
            continue
        path = Path(val)
        if not path.exists():
            print(f"error: {attr} 文件不存在：{val}", file=sys.stderr)
            return 2
        if path.is_dir():
            print(f"error: {attr} 是目录，不是一个文件：{val}", file=sys.stderr)
            return 2
        if path.stat().st_size == 0:
            print(f"error: {attr} 是空文件：{val}", file=sys.stderr)
            return 2
        try:
            with path.open("rb") as fh:
                head = fh.read(512).lstrip()
        except OSError as exc:
            print(f"error: 读不了 {attr} {val}：{exc}", file=sys.stderr)
            return 2
        # 传反了是最常见的误操作，提前给出点名提示
        if attr == "arxml" and not head.startswith(b"<?xml") and not head.startswith(b"<"):
            print(
                f"error: {val} 看起来不是 XML/ARXML（开头不是 '<'）。"
                "是不是把 .dbc 和 .arxml 两个参数传反了？",
                file=sys.stderr,
            )
            return 2

    try:
        return int(args.func(args))
    except AxdError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
