#!/usr/bin/env python3
# skills/cdd-arxml-consistency/scripts/cdd_arxml_check.py
"""Cross-check a CANdelaStudio CDD against an AUTOSAR ECU configuration ARXML.

The CDD is what the diagnostic tester is built from; the ARXML is what the ECU
actually runs. When they disagree, every diagnostic request still compiles, the
tester still connects, and the ECU answers 0x31 (requestOutOfRange) — or the
session opens and the DID reads back the wrong length.

Zero dependencies, standard library only, read-only.

Subcommands:
    probe   <cdd> <arxml>   what each side actually contains
    check   <cdd> <arxml>   full comparison
    matrix  <cdd> <arxml>   per-item CSV inventory
    selftest                built-in fixture with planted defects

Exit codes: 0 no errors, 1 errors present, 2 bad arguments or unreadable file
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Iterable, Optional

__version__ = "1.0.0"

AUTOSAR_NS = "http://autosar.org/schema/r4.0"

# Tolerances. Timings are compared in integer milliseconds: CDD states them in
# ms, AUTOSAR in seconds, and binary float cannot represent 0.05 exactly, so a
# strict equality test would flag every P2 value in the file.
TIMING_TOL_MS = 1


# --------------------------------------------------------------------------
# findings
# --------------------------------------------------------------------------

@dataclass
class Finding:
    code: str
    severity: str          # error | warn | info
    title: str
    detail: str = ""
    where: str = ""

    def line(self) -> str:
        head = f"[{self.severity[0].upper()}] {self.code}  {self.title}"
        if self.where:
            head += f"  [{self.where}]"
        if self.detail:
            head += f"\n      {self.detail}"
        return head


SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}


# --------------------------------------------------------------------------
# decoding / parsing helpers
# --------------------------------------------------------------------------

def _die(message: str) -> "NoReturn":
    """Print a sentence to stderr and exit 2.

    `_die("text")` prints the text and exits **1**, which collides
    with "errors were found". A caller in CI cannot then tell "your config has
    4 errors" from "you passed the wrong file" — both look like a failed check.
    The documented contract is 2 for bad input, so say it explicitly.
    """
    print(message, file=sys.stderr)
    sys.exit(2)


def decode_bytes(raw: bytes) -> tuple[str, str]:
    """Decode as UTF-8 (with or without BOM), else GB18030, else latin-1.

    GB18030 matters here: Chinese suppliers routinely save the CDD export and
    the ARXML with ANSI encoding, and a UTF-8-only reader turns every comment
    into mojibake without ever raising — the DIDs still parse, so nothing looks
    broken until you read a description.
    """
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="strict"), "utf-8-sig"
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16"), "utf-16"
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace"), "latin-1"


# A DOCTYPE with an external subset makes ElementTree try to resolve it. The
# CANdela export always carries `<!DOCTYPE CANDELA SYSTEM 'candela.dtd'>` and
# the DTD is not shipped, so strip the declaration before parsing.
_DOCTYPE_RE = re.compile(r"<!DOCTYPE[^>\[]*(\[[^\]]*\])?\s*>", re.IGNORECASE | re.DOTALL)


def load_xml(path: str) -> tuple[ET.Element, str]:
    with open(path, "rb") as fh:
        raw = fh.read()
    text, enc = decode_bytes(raw)
    text = _DOCTYPE_RE.sub("", text, count=1)
    try:
        root = ET.parse(io.StringIO(text)).getroot()
    except ET.ParseError as exc:
        _die(f"error: 无法解析 {path}: {exc}")
    return root, enc


def _tuv(el: Optional[ET.Element]) -> Optional[str]:
    """CDD text lives in a <TUV> child one level below NAME / DESC / QUAL.

    The direct `.text` of those elements is always empty in a CANdela export,
    so reading `.text` yields None for every name. That failure mode is silent:
    the element exists, so nothing looks missing.
    """
    if el is None:
        return None
    inner = el.find("TUV")
    if inner is not None:
        val = (inner.text or "").strip()
        if val:
            return val
    val = (el.text or "").strip()
    return val or None


def _hex(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(str(value).strip(), 0)
    except (TypeError, ValueError):
        return None


def _num(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _ms(seconds: Optional[float]) -> Optional[int]:
    return None if seconds is None else int(round(seconds * 1000.0))


# --------------------------------------------------------------------------
# CDD model  (CANdelaStudio 11.x)
# --------------------------------------------------------------------------

@dataclass
class CddDid:
    did: int
    qual: Optional[str]
    name: Optional[str]
    used: bool = True


@dataclass
class CddService:
    qual: str
    sid: Optional[int]


@dataclass
class CddModel:
    path: str
    encoding: str
    dtd_version: Optional[str]
    ecu_name: Optional[str]
    protocol: Optional[str]
    attrs: dict = field(default_factory=dict)          # 'CAN.ReqCanId' -> int
    # Values that exist only on the DEFATTS definition elements. They are the
    # CANdelaStudio *template* defaults, not this ECU's configuration. Kept
    # apart from `attrs` on purpose: mixing them in silently turns an
    # unconfigured CDD into a plausible-looking one, and every downstream
    # comparison then produces a confident verdict about the wrong number.
    attrs_template: dict = field(default_factory=dict)  # 'CAN.ReqCanId' -> int
    dids: dict = field(default_factory=dict)           # did -> CddDid
    dtcs: set = field(default_factory=set)             # from diagnostic instances
    dtcs_pool: set = field(default_factory=set)        # from RECORDDTPOOL
    routines: dict = field(default_factory=dict)       # id -> name
    sessions: dict = field(default_factory=dict)       # level -> name
    security: dict = field(default_factory=dict)       # level -> name
    services: list = field(default_factory=list)       # [CddService]
    negres: dict = field(default_factory=dict)         # code -> name
    notes: list = field(default_factory=list)


# CANdelaStudio templates are typed by a `cls` attribute. This is the mapping
# that turns "which template does this instance use" into "what kind of object
# is it". Anything not in here is reported as unmapped rather than guessed.
CDD_CLASS_SESSION = "ses"
CDD_CLASS_SECURITY = "sec"
CDD_CLASS_ROUTINE = "rtn"
CDD_CLASS_IDENT = "idn"

# UDS service identifiers, keyed by the abbreviation CANdelaStudio uses in
# front of each protocol service's QUAL. Names that are prefixed with the raw
# hex (`_22_ReadDataByIdentifier`) are parsed instead of looked up.
SERVICE_ABBREV = {
    "DSC": 0x10, "ER": 0x11, "CDI": 0x14, "RDTCI": 0x19, "RDBI": 0x22,
    "SA": 0x27, "CC": 0x28, "IOCBI": 0x2F, "RC": 0x31, "RD": 0x34,
    "RU": 0x35, "RTE": 0x37, "TP": 0x3E, "CDTCS": 0x85,
    "DDDI": 0x2C, "RDBPI": 0x2A, "RMBA": 0x2E, "WMBA": 0x2E,
    "RSDBI": 0x22, "RDTCI_R": 0x19,
}

_SID_PREFIX = re.compile(r"^_([0-9A-Fa-f]{2})_")

# `SeedLevel1` / `KeyLevel1`: the trailing number is the security *level*, not
# the sub-function. The sub-function is the STATICVALUE (1 = requestSeed,
# 2 = sendKey) and is what actually distinguishes the two instances. Reading
# the level off STATICVALUE turns one level into two phantom levels.
_SEC_LEVEL = re.compile(r"(?:Seed|Key)?_?Level_?(\d+)", re.IGNORECASE)


def security_level_from_name(name: Optional[str], subfunction: Optional[int]) -> Optional[int]:
    """Derive the security level of a CDD `sec` instance.

    Preference order:
      1. an explicit `Level<N>` in the name  (`SeedLevel1`)
      2. a bare numeric name                (`Level_1`)
      3. the sub-function itself            (only when nothing else exists)
    """
    if name:
        m = _SEC_LEVEL.search(name)
        if m:
            return int(m.group(1))
        m = re.fullmatch(r"\D*?(\d+)", name.strip())
        if m:
            return int(m.group(1))
    return subfunction


def service_id_from_name(name: str) -> Optional[int]:
    """Map a CDD protocol-service QUAL to a UDS service id, or None."""
    if not name:
        return None
    m = _SID_PREFIX.match(name)
    if m:
        return int(m.group(1), 16)
    head = name.split("_")[0].upper()
    return SERVICE_ABBREV.get(head)


def parse_cdd(path: str) -> CddModel:
    root, enc = load_xml(path)
    if root.tag != "CANDELA":
        _die(
            f"error: {path} 的根节点是 <{root.tag}>，不是 <CANDELA>。"
            "这两个参数是不是传反了？第一个参数应该是 CDD，第二个是 ARXML。"
        )

    ecudoc = root.find("ECUDOC")
    if ecudoc is None:
        _die(f"error: {path} 里没有 <ECUDOC>，不是 CANdela 导出文件")

    model = CddModel(
        path=path,
        encoding=enc,
        dtd_version=root.get("dtdvers"),
        ecu_name=None,
        protocol=None,
    )
    ps = ecudoc.find("PROTOCOLSTANDARD")
    if ps is not None and ps.text:
        model.protocol = ps.text.strip()

    # ---- attribute name index -------------------------------------------
    # ECU-level values are written as <UNS attrref='_000001FB...' v='1848'/>.
    # The numeric id means nothing on its own; the name lives in the DEFATTS
    # tree. Without this index every diagnostic address reads as a bare number
    # and cannot be matched against anything.
    attr_name: dict = {}

    def walk_defs(node: ET.Element) -> None:
        for child in node:
            ident = child.get("id")
            qual = _tuv(child.find("QUAL"))
            if ident and qual:
                attr_name[ident] = qual
                raw = child.get("v")
                if raw is not None:
                    val = _hex(raw)
                    model.attrs_template[qual] = (
                        val if val is not None else raw
                    )
            walk_defs(child)

    defs = ecudoc.find("DEFATTS")
    if defs is not None:
        walk_defs(defs)
    if not attr_name:
        model.notes.append("DEFATTS 为空，ECU 级属性无法解析成名字")

    # ---- ECU node --------------------------------------------------------
    ecu = ecudoc.find("ECU")
    if ecu is not None:
        model.ecu_name = _tuv(ecu.find("QUAL"))
        for child in ecu:
            name = attr_name.get(child.get("attrref") or "")
            if not name:
                continue  # NAME / DESC / QUAL / VAR carry no attrref
            raw = child.get("v")
            val = _hex(raw)
            model.attrs[name] = val if val is not None else raw
    if model.ecu_name is None:
        model.notes.append("ECU 节点没有 QUAL，无法确定 ECU 名")

    # A CDD that never overrides a CAN attribute is still a valid XML document
    # and still yields a full DID/DTC list — so nothing downstream notices that
    # the diagnostic addressing was never filled in. Say it out loud here, once,
    # instead of letting four comparison blocks each skip in silence.
    if not any(k.startswith("CAN.") for k in model.attrs):
        model.notes.append(
            "CDD 的 <ECU> 节点没有覆盖任何 CAN.* 属性（诊断地址与时序全部缺失），"
            "读到的同名单值只存在于 DEFATTS 模板定义里，不是本 ECU 的配置"
        )

    # ---- template class index -------------------------------------------
    tmpl_class: dict = {}
    tmpls = ecudoc.find("DCLTMPLS")
    if tmpls is not None:
        for t in tmpls:
            tid = t.get("id")
            if tid:
                tmpl_class[tid] = t.get("cls")
    if not tmpl_class:
        model.notes.append("DCLTMPLS 为空，诊断实例无法分类")

    # ---- DIDs ------------------------------------------------------------
    dids_node = ecudoc.find("DIDS")
    if dids_node is not None:
        for el in dids_node:
            if el.tag != "DID":
                continue
            raw = el.get("n")
            did = _hex(raw)
            if did is None:
                continue
            if did in model.dids:
                model.notes.append(f"DID 0x{did:04X} 在 CDD 中重复定义")
            model.dids[did] = CddDid(
                did=did,
                qual=_tuv(el.find("QUAL")),
                name=_tuv(el.find("NAME")),
            )

    # ---- diagnostic instances -------------------------------------------
    for inst in ecudoc.iter("DIAGINST"):
        cls = tmpl_class.get(inst.get("tmplref") or "")
        qual = _tuv(inst.find("QUAL"))
        static = [
            _hex(c.get("v"))
            for c in inst
            if c.tag == "STATICVALUE" and c.get("v") is not None
        ]
        level = static[0] if static else None

        if cls == CDD_CLASS_SESSION and level is not None:
            model.sessions[level] = qual or f"level_{level}"
        elif cls == CDD_CLASS_SECURITY:
            sec_level = security_level_from_name(qual, level)
            if sec_level is not None:
                model.security.setdefault(sec_level, qual or f"level_{sec_level}")
        elif cls == CDD_CLASS_ROUTINE and level is not None:
            model.routines[level] = qual or f"routine_0x{level:04X}"

    # ---- DTCs ------------------------------------------------------------
    # Two populations, deliberately kept apart:
    #   * records nested inside a diagnostic instance = DTCs the tester knows
    #   * ECUDOC/RECORDDTPOOL                          = the fault-memory pool
    # They are not the same list, and treating the pool as "the DTC list"
    # produces an empty intersection with Dem even when 45 DTCs match.
    for recdata in root.iter("RECORDDATAOBJ"):
        for rec in recdata.iter("RECORD"):
            val = _hex(rec.get("v"))
            if val is not None:
                model.dtcs.add(val)

    pool = ecudoc.find("RECORDDTPOOL")
    if pool is not None:
        for dt in pool:
            for rec in dt.iter("RECORD"):
                val = _hex(rec.get("v"))
                if val is not None:
                    model.dtcs_pool.add(val)

    # ---- protocol services ----------------------------------------------
    svcs = ecudoc.find("PROTOCOLSERVICES")
    if svcs is not None:
        for el in svcs:
            qual = _tuv(el.find("QUAL"))
            if not qual:
                continue
            model.services.append(CddService(qual=qual, sid=service_id_from_name(qual)))

    # ---- negative response codes ----------------------------------------
    negres = ecudoc.find("NEGRESCODES")
    if negres is not None:
        for el in negres:
            code = _hex(el.get("v"))
            if code is not None:
                model.negres[code] = _tuv(el.find("QUAL")) or ""

    return model


# --------------------------------------------------------------------------
# ARXML model  (AUTOSAR 4.x ECUC)
# --------------------------------------------------------------------------

@dataclass
class ArxmlModel:
    path: str
    encoding: str
    schema_ns: Optional[str]
    modules: list = field(default_factory=list)
    dids: dict = field(default_factory=dict)        # did -> {name, used}
    dtcs: dict = field(default_factory=dict)        # dtc -> {name}
    routines: dict = field(default_factory=dict)    # id -> name
    sessions: dict = field(default_factory=dict)    # level -> {name, p2, p2star}
    security: dict = field(default_factory=dict)    # level -> {seed, key, delay}
    services: dict = field(default_factory=dict)    # sid -> name
    canif_ids: dict = field(default_factory=dict)   # role -> (id, type)
    cantp: dict = field(default_factory=dict)
    dcm_rx: list = field(default_factory=list)
    hw_filters: list = field(default_factory=list)  # [(code, mask)]
    notes: list = field(default_factory=list)


def _ns(root: ET.Element) -> str:
    tag = root.tag
    if tag.startswith("{"):
        return tag[1:].split("}", 1)[0]
    return ""


class _Arx:
    """Namespace-tolerant accessor for an ECUC tree."""

    def __init__(self, root: ET.Element):
        self.root = root
        ns = _ns(root)
        self.ns = ns
        self.p = f"{{{ns}}}" if ns else ""

    def tag(self, name: str) -> str:
        return self.p + name

    def module(self, name: str) -> Optional[ET.Element]:
        for mc in self.root.iter(self.tag("ECUC-MODULE-CONFIGURATION-VALUES")):
            sn = mc.find(self.tag("SHORT-NAME"))
            if sn is not None and (sn.text or "").strip() == name:
                return mc
        return None

    def containers(self, node: ET.Element, defname: str) -> list:
        out = []
        if node is None:
            return out
        for cv in node.iter(self.tag("ECUC-CONTAINER-VALUE")):
            dref = cv.find(self.tag("DEFINITION-REF"))
            if dref is None:
                continue
            if (dref.text or "").rsplit("/", 1)[-1] == defname:
                out.append(cv)
        return out

    def params(self, cv: ET.Element) -> dict:
        """Parameter name (last path segment) -> raw text value.

        Values live in ECUC-NUMERICAL-PARAM-VALUE / ECUC-TEXTUAL-PARAM-VALUE;
        the same name can appear twice, last one wins.
        """
        out = {}
        for pv in cv.iter():
            if pv.tag not in (self.tag("ECUC-NUMERICAL-PARAM-VALUE"),
                              self.tag("ECUC-TEXTUAL-PARAM-VALUE")):
                continue
            dref = pv.find(self.tag("DEFINITION-REF"))
            val = pv.find(self.tag("VALUE"))
            if dref is None or val is None:
                continue
            out[(dref.text or "").rsplit("/", 1)[-1]] = (val.text or "").strip()
        return out

    def refs(self, cv: ET.Element) -> list:
        out = []
        for rv in cv.iter(self.tag("ECUC-REFERENCE-VALUE")):
            dref = rv.find(self.tag("DEFINITION-REF"))
            vref = rv.find(self.tag("VALUE-REF"))
            if dref is None or vref is None:
                continue
            out.append(((dref.text or "").rsplit("/", 1)[-1], (vref.text or "").strip()))
        return out


_SERVICE_NAME = re.compile(r"^Service_0x([0-9A-Fa-f]{2})")


def parse_arxml(path: str) -> ArxmlModel:
    root, enc = load_xml(path)
    ns = _ns(root)
    if not ns.startswith("http://autosar.org/schema/r"):
        _die(
            f"error: {path} 的根节点是 <{root.tag}>，命名空间 {ns or '(无)'}，"
            "不像 AUTOSAR ECUC 配置。这两个参数是不是传反了？"
            "第一个参数应该是 CDD，第二个是 ARXML。"
        )
    a = _Arx(root)
    model = ArxmlModel(path=path, encoding=enc, schema_ns=ns)

    for mc in root.iter(a.tag("ECUC-MODULE-CONFIGURATION-VALUES")):
        sn = mc.find(a.tag("SHORT-NAME"))
        if sn is not None:
            model.modules.append((sn.text or "").strip())

    # ---- Dcm -------------------------------------------------------------
    dcm = a.module("Dcm")
    if dcm is None:
        model.notes.append("ARXML 里没有 Dcm 模块，诊断部分无法比对")
    else:
        for cv in a.containers(dcm, "DcmDspDid"):
            p = a.params(cv)
            did = _hex(p.get("DcmDspDidIdentifier"))
            if did is None:
                continue
            sn = cv.find(a.tag("SHORT-NAME"))
            if did in model.dids:
                model.notes.append(f"DID 0x{did:04X} 在 Dcm 中重复定义")
            model.dids[did] = {
                "name": (sn.text or "") if sn is not None else "",
                "used": (p.get("DcmDspDidUsed") or "true").lower() == "true",
            }

        for cv in a.containers(dcm, "DcmDspSessionRow"):
            p = a.params(cv)
            level = _hex(p.get("DcmDspSessionLevel"))
            if level is None:
                continue
            sn = cv.find(a.tag("SHORT-NAME"))
            model.sessions[level] = {
                "name": (sn.text or "") if sn is not None else "",
                "p2": _ms(_num(p.get("DcmDspSessionP2ServerMax"))),
                "p2star": _ms(_num(p.get("DcmDspSessionP2StarServerMax"))),
            }

        for cv in a.containers(dcm, "DcmDspSecurityRow"):
            p = a.params(cv)
            level = _hex(p.get("DcmDspSecurityLevel"))
            if level is None:
                continue
            model.security[level] = {
                "seed": _hex(p.get("DcmDspSecuritySeedSize")),
                "key": _hex(p.get("DcmDspSecurityKeySize")),
                "delay": _num(p.get("DcmDspSecurityDelayTime")),
                "att": _hex(p.get("DcmDspSecurityNumAttDelay")),
            }

        for cv in a.containers(dcm, "DcmDspRoutine"):
            p = a.params(cv)
            rid = _hex(p.get("DcmDspRoutineIdentifier"))
            if rid is None:
                continue
            sn = cv.find(a.tag("SHORT-NAME"))
            model.routines[rid] = (sn.text or "") if sn is not None else ""

        # DcmDsdService: the request byte is normally encoded in the
        # SHORT-NAME ("Service_0x22_ReadDataByIdentifier"), not in a parameter.
        # Some vendors do configure DcmDsdServiceRequest; accept either.
        for cv in a.containers(dcm, "DcmDsdService"):
            p = a.params(cv)
            sid = _hex(p.get("DcmDsdServiceRequest"))
            sn = cv.find(a.tag("SHORT-NAME"))
            name = (sn.text or "") if sn is not None else ""
            if sid is None:
                m = _SERVICE_NAME.match(name)
                if m:
                    sid = int(m.group(1), 16)
            if sid is not None:
                model.services[sid] = name

        for cv in a.containers(dcm, "DcmDslProtocolRx"):
            p = a.params(cv)
            sn = cv.find(a.tag("SHORT-NAME"))
            model.dcm_rx.append({
                "name": (sn.text or "") if sn is not None else "",
                "addr_type": p.get("DcmDslProtocolRxAddrType") or "",
                "pdu": p.get("DcmDslProtocolRxPduId") or "",
            })

    # ---- Dem -------------------------------------------------------------
    dem = a.module("Dem")
    if dem is None:
        model.notes.append("ARXML 里没有 Dem 模块，DTC 部分无法比对")
    else:
        for cv in a.containers(dem, "DemDTC"):
            p = a.params(cv)
            dtc = _hex(p.get("DemDtcValue"))
            if dtc is None:
                continue
            sn = cv.find(a.tag("SHORT-NAME"))
            model.dtcs[dtc] = {"name": (sn.text or "") if sn is not None else ""}

    # ---- CanIf diagnostic PDUs ------------------------------------------
    # Identify the three diagnostic links by PDU name, then read the CAN id
    # from that PDU. Roles, not names, decide which is which — every supplier
    # spells these differently.
    canif = a.module("CanIf")
    if canif is None:
        model.notes.append("ARXML 里没有 CanIf 模块，诊断 CAN ID 无法比对")
    else:
        for cv in canif.iter(a.tag("ECUC-CONTAINER-VALUE")):
            dref = cv.find(a.tag("DEFINITION-REF"))
            if dref is None:
                continue
            kind = (dref.text or "").rsplit("/", 1)[-1]
            if "PduCfg" not in kind:
                continue
            sn = cv.find(a.tag("SHORT-NAME"))
            name = ((sn.text or "") if sn is not None else "")
            p = a.params(cv)
            cid = _hex(p.get("CanIfRxPduCanId") or p.get("CanIfTxPduCanId"))
            if cid is None:
                continue
            ctype = (p.get("CanIfRxPduCanIdType") or p.get("CanIfTxPduCanIdType") or "")
            low = name.lower()
            if "func" in low:
                role = "func_req"
            # `phys`, `physical` and the abbreviation `Phy` are all in use.
            # Matching only `phys` silently drops `RX_PDU_UDS_DiagPhyReq_LDLP`,
            # which then makes CDX-010 report "CanIf has no physical PDU" —
            # a false alarm that sends the reader hunting for a missing PDU
            # that is right there under a slightly shorter name.
            elif "physic" in low or "phys" in low or "phy" in low:
                role = "phys_req"
            elif "resp" in low:
                role = "resp"
            else:
                continue
            model.canif_ids[role] = (cid, ctype, name)

    # ---- CanTp -----------------------------------------------------------
    cantp = a.module("CanTp")
    if cantp is not None:
        for cv in a.containers(cantp, "CanTpRxNSdu"):
            p = a.params(cv)
            model.cantp.setdefault("bs", _hex(p.get("CanTpBs")))
            stmin = _num(p.get("CanTpSTmin"))
            if stmin is not None:
                model.cantp["stmin_ms"] = _ms(stmin)
            model.cantp.setdefault("n_sa", _hex(p.get("CanTpNSa")))
            model.cantp.setdefault("n_ta", _hex(p.get("CanTpNTa")))
            break
        for cv in a.containers(cantp, "CanTpTxNSdu"):
            p = a.params(cv)
            model.cantp.setdefault("tx_bs", _hex(p.get("CanTpBs")))
            model.cantp.setdefault("tx_n_sa", _hex(p.get("CanTpNSa")))
            model.cantp.setdefault("tx_n_ta", _hex(p.get("CanTpNTa")))
            break

    # ---- Can hardware acceptance filters --------------------------------
    # The only place that states, in hardware, which CAN ids the ECU will even
    # look at. When a diagnostic id disagrees between the CDD and CanIf, the
    # filter says which side is wrong — see the CDX-010 message.
    can_mod = a.module("Can")
    if can_mod is not None:
        for cv in can_mod.iter(a.tag("ECUC-CONTAINER-VALUE")):
            dref = cv.find(a.tag("DEFINITION-REF"))
            if dref is None or not (dref.text or "").endswith("/CanHwFilter"):
                continue
            p = a.params(cv)
            code = _hex(p.get("CanHwFilterCode"))
            mask = _hex(p.get("CanHwFilterMask"))
            if code is not None:
                model.hw_filters.append((code, mask))

    return model


def filter_accepts(filters: list, can_id: int) -> bool:
    """True when some hardware filter would let `can_id` through.

    A filter matches when (frame_id & mask) == (code & mask); bits that are
    clear in the mask are "don't care".
    """
    for code, mask in filters:
        if mask is None:
            if code == can_id:
                return True
            continue
        if (can_id & mask) == (code & mask):
            return True
    return False


# --------------------------------------------------------------------------
# comparison
# --------------------------------------------------------------------------

def _fmt_id(val: int, width: int = 3) -> str:
    return f"0x{val:0{width}X}"


def describe_diff(only_cdd: Iterable, only_arx: Iterable, limit: int = 12) -> str:
    """One-line evidence string, capped so a 100-item gap does not flood."""
    a = sorted(only_cdd)
    b = sorted(only_arx)
    parts = []
    if a:
        shown = ", ".join(a[:limit])
        more = f" …共 {len(a)} 个" if len(a) > limit else ""
        parts.append(f"仅 CDD 有: {shown}{more}")
    if b:
        shown = ", ".join(b[:limit])
        more = f" …共 {len(b)} 个" if len(b) > limit else ""
        parts.append(f"仅 ARXML 有: {shown}{more}")
    return "；".join(parts)


def compare(cdd: CddModel, arx: ArxmlModel) -> list:
    findings: list = []
    add = findings.append

    # -- 0. did we actually compare anything? -----------------------------
    compared = 0
    if cdd.dids and arx.dids:
        compared += 1
    if cdd.dtcs or arx.dtcs:
        compared += 1
    if cdd.attrs.get("CAN.ReqCanId") and arx.canif_ids:
        compared += 1
    if cdd.sessions and arx.sessions:
        compared += 1
    if compared == 0:
        add(Finding(
            "CDX-040", "error",
            "没有任何一项可以比对",
            "两侧都没有解析出 DID / DTC / 诊断 CAN ID / 会话中的任意一类。"
            "这通常意味着文件拿错了，或者解析路径与本项目的结构不符 —— "
            "不是「检查通过」。先跑 probe 看两侧到底读到了什么。",
        ))
        return findings

    # -- 1. DID -----------------------------------------------------------
    cdd_only = set(cdd.dids) - set(arx.dids)
    arx_only = set(arx.dids) - set(cdd.dids)
    if cdd_only:
        names = [f"{_fmt_id(d, 4)} {cdd.dids[d].qual or ''}".strip() for d in sorted(cdd_only)]
        add(Finding(
            "CDX-001", "error",
            f"{len(cdd_only)} 个 DID 在 CDD 中有、Dcm 里没配",
            "诊断仪会照着手册去读，ECU 只能回 0x31 requestOutOfRange。"
            "证据：" + describe_diff(names, []),
            where="DID",
        ))
    if arx_only:
        names = [f"{_fmt_id(d, 4)} {arx.dids[d]['name']}".strip() for d in sorted(arx_only)]
        add(Finding(
            "CDX-002", "warn",
            f"{len(arx_only)} 个 DID 在 Dcm 中已配、CDD 里没有",
            "ECU 支持但诊断规范没写，测试仪不会去读，属于规范滞后。"
            "证据：" + describe_diff([], names),
            where="DID",
        ))
    unused = [d for d in sorted(set(cdd.dids) & set(arx.dids))
              if not arx.dids[d]["used"]]
    if unused:
        add(Finding(
            "CDX-003", "warn",
            f"{len(unused)} 个 DID 两侧都有，但 Dcm 里 DcmDspDidUsed=false",
            "配了容器却没启用，读请求仍会回 0x31。"
            "证据：" + ", ".join(_fmt_id(d, 4) for d in unused[:12]),
            where="DID",
        ))

    # -- 2. DTC -----------------------------------------------------------
    # Only compare when the CDD actually carries a DTC population; a CDD with
    # none is a template, not an ECU description.
    if cdd.dtcs:
        cdd_only = set(cdd.dtcs) - set(arx.dtcs)
        arx_only = set(arx.dtcs) - set(cdd.dtcs)
        if cdd_only:
            add(Finding(
                "CDX-004", "error",
                f"{len(cdd_only)} 个 DTC 在 CDD 中有、Dem 里没配",
                "诊断仪能读到这个 DTC 的参数，ECU 却永远不会置位它 —— "
                "故障发生时读不到，现场只能靠猜。证据："
                + describe_diff([_fmt_id(d, 6) for d in sorted(cdd_only)], []),
                where="DTC",
            ))
        if arx_only:
            add(Finding(
                "CDX-005", "warn",
                f"{len(arx_only)} 个 DTC 在 Dem 中已配、CDD 里没有",
                "ECU 会置位，但诊断规范没定义，测试仪读不出含义。证据："
                + describe_diff([], [_fmt_id(d, 6) for d in sorted(arx_only)]),
                where="DTC",
            ))
        if cdd.dtcs_pool:
            pool_only = cdd.dtcs_pool - cdd.dtcs
            inst_only = cdd.dtcs - cdd.dtcs_pool
            common = cdd.dtcs_pool & cdd.dtcs
            if (pool_only or inst_only) and common:
                # The two populations are not in a subset relation in real
                # files: a DTC can be referenced by a diagnostic instance and
                # absent from the pool, and vice versa. State both directions
                # and the common count, otherwise "3 vs 3, diff 1" reads as
                # arithmetic that does not add up.
                parts = [
                    f"故障内存池 {len(cdd.dtcs_pool)} 个"
                    f"（RECORDDTPOOL）、诊断实例引用 {len(cdd.dtcs)} 个，"
                    f"其中 {len(common)} 个重合"
                ]
                if pool_only:
                    parts.append(
                        f"{len(pool_only)} 个只在池里、未被任何诊断实例引用"
                    )
                if inst_only:
                    parts.append(
                        f"{len(inst_only)} 个被实例引用、池里没有"
                    )
                add(Finding(
                    "CDX-043", "info",
                    f"CDD 内部 DTC 清单自相矛盾：{parts[0]}",
                    "；".join(parts[1:]) + "。"
                    "本工具以「诊断实例引用的」为准比对 Dem —— "
                    "RECORDDTPOOL 是模板／规划池，不等于本 ECU 实际使用的 DTC 清单。"
                    "要么池漏加了 DTC，要么有 DTC 忘了挂进诊断实例，两者都需要人工确认。",
                    where="DTC",
                ))
            elif not common:
                # Zero overlap is not a subset violation — it means the two
                # lists describe different things. Calling this a
                # "contradiction" would send someone hunting for dozens of
                # DTCs that were never meant to be in this ECU.
                add(Finding(
                    "CDX-043", "info",
                    f"CDD 两处 DTC 清单完全不相交：池 {len(cdd.dtcs_pool)} 个 / "
                    f"诊断实例 {len(cdd.dtcs)} 个，交集 0",
                    "这说明 RECORDDTPOOL 与诊断实例里的记录不是同一类清单"
                    "（前者通常是模板或规划池，后者才是本 ECU 实际引用的）。"
                    "本工具只用后者比对 Dem，前者不参与 —— 报此条是为了让读者知道"
                    "为什么两边数量对不上，不是让你去补 DTC。",
                    where="DTC",
                ))

    # -- 3. routines ------------------------------------------------------
    cdd_only = set(cdd.routines) - set(arx.routines)
    arx_only = set(arx.routines) - set(cdd.routines)
    if cdd_only:
        add(Finding(
            "CDX-006", "error",
            f"{len(cdd_only)} 个例程在 CDD 中有、RoutineControl 配置里没有",
            "诊断序列调用该例程会直接失败。证据："
            + describe_diff(
                [f"{_fmt_id(r, 4)} {cdd.routines[r]}" for r in sorted(cdd_only)], []),
            where="Routine",
        ))
    if arx_only:
        add(Finding(
            "CDX-007", "warn",
            f"{len(arx_only)} 个例程在 Dcm 中已配、CDD 里没有",
            "证据：" + describe_diff(
                [], [f"{_fmt_id(r, 4)} {arx.routines[r]}" for r in sorted(arx_only)]),
            where="Routine",
        ))

    # -- 4. diagnostic CAN addressing -------------------------------------
    id_map = (
        ("CDX-010", "error", "CAN.ReqCanId", "phys_req", "物理请求"),
        ("CDX-011", "warn", "CAN.ReqCanIdFunc", "func_req", "功能请求"),
        ("CDX-012", "error", "CAN.ResCanId", "resp", "响应"),
    )
    missing_ids = []
    for code, sev, attr, role, label in id_map:
        cdd_val = cdd.attrs.get(attr)
        if not isinstance(cdd_val, int):
            missing_ids.append((attr, label))
            continue
        arx_val = arx.canif_ids.get(role)
        if arx_val is None:
            add(Finding(
                code, sev,
                f"CDD 定义了{label} CAN ID {_fmt_id(cdd_val)}，CanIf 里找不到对应的诊断 PDU",
                f"CDD 属性 {attr}={cdd_val}。CanIf 中没有名字含 "
                f"{'phys' if role == 'phys_req' else 'func' if role == 'func_req' else 'resp'} 的 PDU。",
                where="CAN ID",
            ))
            continue
        arx_id, arx_type, arx_name = arx_val
        if arx_id != cdd_val:
            # Do not assert which side is wrong. The hardware acceptance
            # filter is the tie-breaker: if it lets the CDD id through but not
            # the CanIf id, the PDU config is what is wrong, and vice versa.
            # Without this the reader is sent to change whichever file they
            # happen to own — and half the time that is the wrong one.
            cdd_ok = filter_accepts(arx.hw_filters, cdd_val)
            arx_ok = filter_accepts(arx.hw_filters, arx_id)
            if cdd_ok and not arx_ok:
                verdict = (
                    f"硬件验收滤波器里有 {_fmt_id(cdd_val)}，没有 {_fmt_id(arx_id)} —— "
                    f"即芯片只会把 {_fmt_id(cdd_val)} 的帧交给上层。"
                    f"所以错的是 CanIf 的 {arx_name}（应为 {_fmt_id(cdd_val)}），不是 CDD。"
                )
            elif arx_ok and not cdd_ok:
                verdict = (
                    f"硬件验收滤波器里有 {_fmt_id(arx_id)}，没有 {_fmt_id(cdd_val)} —— "
                    f"即芯片只接收 {_fmt_id(arx_id)}。"
                    f"所以错的是 CDD 的 {attr}（应为 {_fmt_id(arx_id)}），CanIf 是对的。"
                )
            elif not arx.hw_filters:
                verdict = (
                    "ARXML 里没有配置 CanHwFilter，无法据此判断哪边错 —— "
                    "需要人工确认以哪份为准。"
                )
            elif cdd_ok and arx_ok:
                verdict = (
                    f"两个 ID 都能通过硬件滤波器（mask 有 don't-care 位），"
                    f"无法据此判断哪边错，需要人工确认。"
                )
            else:
                verdict = (
                    f"硬件滤波器两个 ID 都不接受 —— 说明滤波器配置本身也是错的，"
                    f"三处需要一起核对。"
                )
            add(Finding(
                code, sev,
                f"{label} CAN ID 不一致：CDD {_fmt_id(cdd_val)} / CanIf {_fmt_id(arx_id)}",
                f"CanIf 的 {arx_name} 配的是 {_fmt_id(arx_id)}（{arx_id}），"
                f"CDD 的 {attr} 是 {_fmt_id(cdd_val)}（{cdd_val}）。"
                "两者相差 " + str(abs(arx_id - cdd_val)) + "。"
                "诊断仪按 CDD 发，ECU 按 CanIf 收 —— 请求根本进不了 Dcm。"
                + verdict,
                where="CAN ID",
            ))

    # Silence is the wrong answer here. `continue` on a missing attribute used
    # to mean three addressing checks and five timing checks simply did not
    # run, while the report still read like a complete review — and "the report
    # did not mention the CAN id" is indistinguishable from "the CAN id is
    # fine". Report the gap as a gap.
    if missing_ids:
        names = "、".join(attr for attr, _ in missing_ids)
        tmpl = [f"{attr}={_fmt_id(cdd.attrs_template[attr])}"
                for attr, _ in missing_ids if attr in cdd.attrs_template]
        body = (
            f"CDD 的 <ECU> 节点没有覆盖 {names}；"
            f"{'/'.join(label for _, label in missing_ids)} CAN ID 因此无法与 CanIf 比对"
            f"（CDX-010/011/012 未执行，不代表通过）。"
        )
        if tmpl:
            body += (
                "DEFATTS 里还留着模板默认值 " + "、".join(tmpl)
                + " —— 那是 CANdelaStudio 模板的占位值，不能当成本 ECU 的配置。"
            )
        body += (
            "拿这份 CDD 导出 ODX，诊断仪会按这些地址发请求，ECU 侧不一定收得到。"
        )
        add(Finding(
            "CDX-013", "error",
            f"CDD 缺少 {len(missing_ids)} 项诊断 CAN 地址，相关比对未执行",
            body,
            where="CAN ID",
        ))

    # -- 5. timing --------------------------------------------------------
    for level in sorted(set(cdd.sessions) & set(arx.sessions)):
        cdd_p2 = cdd.attrs.get("CAN.P2Server")
        cdd_p2s = cdd.attrs.get("CAN.P2ExServer")
        row = arx.sessions[level]
        if isinstance(cdd_p2, int) and row.get("p2") is not None:
            if abs(row["p2"] - cdd_p2) > TIMING_TOL_MS:
                add(Finding(
                    "CDX-020", "error",
                    f"会话 {level} 的 P2Server 不一致：CDD {cdd_p2}ms / Dcm {row['p2']}ms",
                    "ECU 响应慢于诊断仪的等待时间，测试仪会报无响应。"
                    f"Dcm 的 {row['name']} 配的是 {row['p2']}ms。",
                    where="Timing",
                ))
        if isinstance(cdd_p2s, int) and row.get("p2star") is not None:
            if abs(row["p2star"] - cdd_p2s) > TIMING_TOL_MS:
                add(Finding(
                    "CDX-021", "warn",
                    f"会话 {level} 的 P2*Server 不一致：CDD {cdd_p2s}ms / Dcm {row['p2star']}ms",
                    "0x78 之后的长耗时处理，超时点不同会让刷写中途断开。",
                    where="Timing",
                ))

    cdd_s3 = cdd.attrs.get("CAN.S3Client")
    if isinstance(cdd_s3, int) and isinstance(cdd.attrs.get("CAN.S3Server"), int):
        # CDD carries both sides of S3; the handshake only holds if the server
        # keeps the session at least as long as the client waits.
        if cdd.attrs["CAN.S3Server"] < cdd_s3:
            add(Finding(
                "CDX-022", "warn",
                f"CDD 内部 S3 不一致：Client {cdd_s3}ms < Server {cdd.attrs['CAN.S3Server']}ms",
                "服务端保活时间短于客户端发送 TesterPresent 的间隔，"
                "会话会周期性掉回 Default。",
                where="Timing",
            ))

    cdd_stmin = cdd.attrs.get("CAN.StMin")
    arx_stmin = arx.cantp.get("stmin_ms")
    if isinstance(cdd_stmin, int) and isinstance(arx_stmin, int):
        if cdd_stmin != arx_stmin:
            add(Finding(
                "CDX-023", "warn",
                f"STmin 不一致：CDD {cdd_stmin}ms / CanTp {arx_stmin}ms",
                "接收方等待帧间隔与发送方给出的值不符，多帧传输易丢帧。",
                where="Timing",
            ))

    cdd_bs = cdd.attrs.get("CAN.Blocksize")
    arx_bs = arx.cantp.get("bs")
    if isinstance(cdd_bs, int) and isinstance(arx_bs, int) and cdd_bs != arx_bs:
        add(Finding(
            "CDX-024", "warn",
            f"BlockSize 不一致：CDD {cdd_bs} / CanTp {arx_bs}",
            "连续帧分块数不同，流控帧节奏会错位。",
            where="Timing",
        ))

    # Same failure mode as the addressing block: five timing checks that never
    # ran must not look like five timing checks that passed. Kept at `warn`
    # because an unconfigured P2 does not by itself make the CDD unusable —
    # but the reader has to know the comparison did not happen.
    timing_keys = (
        ("CAN.P2Server", "CDX-020"),
        ("CAN.P2ExServer", "CDX-021"),
        ("CAN.S3Client", "CDX-022"),
        ("CAN.StMin", "CDX-023"),
        ("CAN.Blocksize", "CDX-024"),
    )
    missing_timing = [(k, c) for k, c in timing_keys
                      if not isinstance(cdd.attrs.get(k), int)]
    if missing_timing:
        skipped = "、".join(c for _, c in missing_timing)
        body = (
            "CDD 的 <ECU> 节点没有覆盖 "
            + "、".join(k for k, _ in missing_timing)
            + f"；{skipped} 因此未执行（不代表通过）。"
        )
        tmpl = [f"{k}={cdd.attrs_template[k]}"
                for k, _ in missing_timing if k in cdd.attrs_template]
        if tmpl:
            body += (
                "DEFATTS 模板默认值 " + "、".join(tmpl)
                + "；模板默认值随 CANdelaStudio 版本变化，不能作为 ECU 的行为依据。"
            )
        add(Finding(
            "CDX-025", "warn",
            f"CDD 缺少 {len(missing_timing)} 项诊断时序参数，相关比对未执行",
            body,
            where="Timing",
        ))

    # -- 6. sessions / security -------------------------------------------
    cdd_only = set(cdd.sessions) - set(arx.sessions)
    arx_only = set(arx.sessions) - set(cdd.sessions)
    if cdd_only:
        add(Finding(
            "CDX-030", "error",
            f"{len(cdd_only)} 个诊断会话只有 CDD 定义、Dcm 里没有",
            "诊断仪切换到该会话会收到 0x12 subFunctionNotSupported。证据："
            + describe_diff([f"{lv} {cdd.sessions[lv]}" for lv in sorted(cdd_only)], [])
            + (("；" + describe_diff([], [f"{lv} {arx.sessions[lv]['name']}"
                                         for lv in sorted(arx_only)])) if arx_only else ""),
            where="Session",
        ))

    cdd_only = set(cdd.security) - set(arx.security)
    if cdd_only:
        add(Finding(
            "CDX-031", "error",
            f"{len(cdd_only)} 个安全访问等级只有 CDD 定义、Dcm 里没有",
            "该等级下的受保护服务全部无法解锁。证据："
            + describe_diff([f"{lv} {cdd.security[lv]}" for lv in sorted(cdd_only)], []),
            where="Security",
        ))

    # A sample, not a rule: the CDD does not carry seed/key length at the ECU
    # level, so this only fires when a vendor does put it there.
    for level in sorted(set(cdd.security) & set(arx.security)):
        row = arx.security[level]
        if row.get("seed") and row.get("key") and row["seed"] != row["key"]:
            add(Finding(
                "CDX-032", "warn",
                f"安全等级 {level} 的 Seed({row['seed']}B) 与 Key({row['key']}B) 长度不同",
                "多数 UDS 实现要求两者等长；不等长属于实现特性，需与供应商确认。",
                where="Security",
            ))

    # -- 7. duplicate identifiers -----------------------------------------
    for note in list(cdd.notes) + list(arx.notes):
        if "重复定义" in note:
            add(Finding("CDX-041", "warn", note,
                        "同一侧出现重复标识符，后面的会覆盖前面的，行为取决于工具。",
                        where="Sanity"))

    # -- 8. informational -------------------------------------------------
    bits = []
    if cdd.protocol:
        bits.append(f"CDD 协议 {cdd.protocol}")
    if cdd.dtd_version:
        bits.append(f"CANdela DTD {cdd.dtd_version}")
    if cdd.encoding:
        bits.append(f"CDD 编码 {cdd.encoding}")
    if arx.encoding and arx.encoding != cdd.encoding:
        bits.append(f"ARXML 编码 {arx.encoding}")
    if arx.modules:
        bits.append(f"ARXML {len(arx.modules)} 个模块")
    if bits:
        add(Finding("CDX-042", "info", "文件概况", "；".join(bits), where="Info"))

    mapped = [s for s in cdd.services if s.sid is not None]
    unmapped = [s for s in cdd.services if s.sid is None]
    if cdd.services:
        detail = (f"CDD 定义了 {len(cdd.services)} 个协议服务，"
                  f"其中 {len(mapped)} 个能解析出服务号")
        if unmapped:
            names = ", ".join(s.qual for s in unmapped[:10])
            detail += f"；{len(unmapped)} 个无法映射（不 guessed）：{names}"
        if arx.services:
            detail += (f"。Dcm 中显式配置了 {len(arx.services)} 个服务："
                       + ", ".join(_fmt_id(s, 2) for s in sorted(arx.services)))
        add(Finding("CDX-044", "info", "服务覆盖", detail, where="Info"))

    return findings


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------

def emit_text(findings: list, cdd: CddModel, arx: ArxmlModel) -> int:
    order = sorted(findings, key=lambda f: (SEVERITY_ORDER[f.severity], f.code))
    if order:
        print()
        for f in order:
            print(f.line())
    counts = {"error": 0, "warn": 0, "info": 0}
    for f in findings:
        counts[f.severity] += 1
    print()
    print(f"DID     CDD {len(cdd.dids)} / Dcm {len(arx.dids)} 交集 "
          f"{len(set(cdd.dids) & set(arx.dids))}")
    print(f"DTC     CDD {len(cdd.dtcs)} / Dem {len(arx.dtcs)} 交集 "
          f"{len(set(cdd.dtcs) & set(arx.dtcs))}")
    print(f"例程    CDD {len(cdd.routines)} / Dcm {len(arx.routines)} 交集 "
          f"{len(set(cdd.routines) & set(arx.routines))}")
    if cdd.sessions or arx.sessions:
        print(f"会话    CDD {len(cdd.sessions)} / Dcm {len(arx.sessions)}")
    if cdd.security or arx.security:
        print(f"安全    CDD {len(cdd.security)} / Dcm {len(arx.security)}")
    print()
    print(f"summary: {counts['error']} error, {counts['warn']} warn, {counts['info']} info")
    return 1 if counts["error"] else 0


def emit_json(findings: list, cdd: CddModel, arx: ArxmlModel) -> int:
    counts = {"error": 0, "warn": 0, "info": 0}
    for f in findings:
        counts[f.severity] += 1
    payload = {
        "summary": counts,
        "findings": [
            {"code": f.code, "severity": f.severity, "title": f.title,
             "detail": f.detail, "where": f.where}
            for f in sorted(findings, key=lambda x: (SEVERITY_ORDER[x.severity], x.code))
        ],
        "counts": {
            "did": {"cdd": len(cdd.dids), "arxml": len(arx.dids),
                    "common": len(set(cdd.dids) & set(arx.dids))},
            "dtc": {"cdd": len(cdd.dtcs), "arxml": len(arx.dtcs),
                    "common": len(set(cdd.dtcs) & set(arx.dtcs))},
            "routine": {"cdd": len(cdd.routines), "arxml": len(arx.routines),
                        "common": len(set(cdd.routines) & set(arx.routines))},
        },
        "cdd": {"ecu": cdd.ecu_name, "protocol": cdd.protocol,
                "encoding": cdd.encoding, "attrs": cdd.attrs},
        "arxml": {"modules": arx.modules, "encoding": arx.encoding,
                  "canif_ids": {k: {"id": v[0], "type": v[1], "pdu": v[2]}
                                for k, v in arx.canif_ids.items()},
                  "cantp": arx.cantp},
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if counts["error"] else 0


def cmd_probe(args) -> int:
    cdd = parse_cdd(args.cdd)
    arx = parse_arxml(args.arxml)

    print("=" * 72)
    print(f"CDD    {cdd.path}")
    print(f"       编码 {cdd.encoding}｜DTD {cdd.dtd_version}｜协议 {cdd.protocol}")
    print(f"       ECU  {cdd.ecu_name}")
    print(f"       DID {len(cdd.dids)}｜DTC {len(cdd.dtcs)}"
          f"（池 {len(cdd.dtcs_pool)}）｜例程 {len(cdd.routines)}"
          f"｜会话 {len(cdd.sessions)}｜安全 {len(cdd.security)}"
          f"｜服务 {len(cdd.services)}｜NRC {len(cdd.negres)}")
    if cdd.attrs:
        keys = ("CAN.ReqCanId", "CAN.ResCanId", "CAN.ReqCanIdFunc",
                "CAN.P2Server", "CAN.P2ExServer", "CAN.S3Client",
                "CAN.StMin", "CAN.Blocksize")
        shown = [f"{k}={cdd.attrs[k]}" for k in keys if k in cdd.attrs]
        if shown:
            print("       诊断参数 " + "  ".join(shown))
    if not any(k.startswith("CAN.") for k in cdd.attrs):
        # An absent line here is indistinguishable from a parser that read
        # nothing. Print the gap with its reason so the next reader does not
        # have to diff two probes to notice.
        print("       诊断参数 —（CDD 未覆盖任何 CAN.* 属性，"
              "CAN ID 与时序检查都会跳过）")

    print("-" * 72)
    print(f"ARXML  {arx.path}")
    print(f"       编码 {arx.encoding}｜命名空间 {arx.schema_ns}")
    print(f"       模块 {len(arx.modules)}: {' '.join(sorted(arx.modules))}")
    print(f"       DID {len(arx.dids)}｜DTC {len(arx.dtcs)}｜例程 {len(arx.routines)}"
          f"｜会话 {len(arx.sessions)}｜安全 {len(arx.security)}"
          f"｜服务 {len(arx.services)}")
    for role, (cid, ctype, name) in sorted(arx.canif_ids.items()):
        print(f"       诊断 PDU {role:9} {_fmt_id(cid)}  {ctype:16} {name}")
    if arx.cantp:
        print(f"       CanTp {arx.cantp}")

    notes = list(cdd.notes) + list(arx.notes)
    if notes:
        print("-" * 72)
        for n in notes:
            print(f"  ! {n}")
    print("=" * 72)
    print("下一步：check 做完整比对，matrix 导出逐项台账")
    return 0


def cmd_check(args) -> int:
    cdd = parse_cdd(args.cdd)
    arx = parse_arxml(args.arxml)
    findings = compare(cdd, arx)
    if args.min_severity != "info":
        floor = SEVERITY_ORDER[args.min_severity]
        findings = [f for f in findings if SEVERITY_ORDER[f.severity] <= floor]
    if args.json:
        return emit_json(findings, cdd, arx)
    return emit_text(findings, cdd, arx)


def cmd_matrix(args) -> int:
    cdd = parse_cdd(args.cdd)
    arx = parse_arxml(args.arxml)
    rows = []

    for did in sorted(set(cdd.dids) | set(arx.dids)):
        c = cdd.dids.get(did)
        a = arx.dids.get(did)
        if c and a:
            state = "both" if a["used"] else "arxml_unused"
        elif c:
            state = "cdd_only"
        else:
            state = "arxml_only"
        rows.append({
            "kind": "DID",
            "id": _fmt_id(did, 4),
            "cdd_name": (c.qual or "") if c else "",
            "arxml_name": a["name"] if a else "",
            "state": state,
        })

    for dtc in sorted(set(cdd.dtcs) | set(arx.dtcs)):
        c = dtc in cdd.dtcs
        a = dtc in arx.dtcs
        state = "both" if (c and a) else ("cdd_only" if c else "arxml_only")
        rows.append({
            "kind": "DTC",
            "id": _fmt_id(dtc, 6),
            "cdd_name": "in_cdd" if c else "",
            "arxml_name": arx.dtcs[dtc]["name"] if a else "",
            "state": state,
        })

    for rid in sorted(set(cdd.routines) | set(arx.routines)):
        c = rid in cdd.routines
        a = rid in arx.routines
        state = "both" if (c and a) else ("cdd_only" if c else "arxml_only")
        rows.append({
            "kind": "ROUTINE",
            "id": _fmt_id(rid, 4),
            "cdd_name": cdd.routines.get(rid, ""),
            "arxml_name": arx.routines.get(rid, ""),
            "state": state,
        })

    out = sys.stdout if args.output in (None, "-") else open(args.output, "w", newline="", encoding="utf-8-sig")
    try:
        w = csv.DictWriter(out, fieldnames=["kind", "id", "cdd_name", "arxml_name", "state"])
        w.writeheader()
        w.writerows(rows)
    finally:
        if out is not sys.stdout:
            out.close()

    if args.output in (None, "-"):
        return 0
    both = sum(1 for r in rows if r["state"] == "both")
    print(f"wrote {args.output}  ({len(rows)} rows, {both} matched)")
    return 0


def cmd_selftest(args) -> int:
    here = __file__.rsplit("/", 1)[0]
    if here not in sys.path:
        sys.path.insert(0, here)
    import demo_fixtures as fx

    problems = []

    # ---- fixture 1: fully configured, planted defects --------------------
    cdd_path, arx_path = fx.build()
    cdd = parse_cdd(cdd_path)
    arx = parse_arxml(arx_path)
    findings = compare(cdd, arx)
    emit_text(findings, cdd, arx)

    got = {}
    for f in findings:
        got[f.code] = got.get(f.code, 0) + 1
    counts = {"error": 0, "warn": 0, "info": 0}
    for f in findings:
        counts[f.severity] += 1

    if counts != fx.EXPECTED_COUNTS:
        problems.append(f"条数不符：期望 {fx.EXPECTED_COUNTS}，实际 {counts}")
    missing = set(fx.EXPECTED_CODES) - set(got)
    if missing:
        problems.append(f"这些检查码没有触发：{sorted(missing)}")
    extra = set(got) - set(fx.EXPECTED_CODES)
    if extra:
        problems.append(f"这些检查码不在预期内：{sorted(extra)}")

    # ---- fixture 2: CDD with no CAN.* configured -------------------------
    # The failure this guards against is not a crash. It is a clean-looking
    # report: every addressing and timing check skips itself, the totals stay
    # small, and nothing in the output says eight checks never ran.
    print()
    print("-" * 72)
    print("fixture 2: CDD 未覆盖任何 CAN.* 属性（模板另存、CAN 页未填）")
    print("-" * 72)
    nocfg_cdd, nocfg_arx = fx.build(unconfigured=True)
    cdd2 = parse_cdd(nocfg_cdd)
    arx2 = parse_arxml(nocfg_arx)
    got2 = {}
    for f in compare(cdd2, arx2):
        got2[f.code] = got2.get(f.code, 0) + 1

    for code in fx.UNCONFIGURED_CODES:
        if code not in got2:
            problems.append(f"fixture 2 没有触发 {code}（缺口被静默吞掉）")
    for code in fx.UNCONFIGURED_MUST_NOT:
        if code in got2:
            problems.append(
                f"fixture 2 不应触发 {code}（没有可比对的属性时不该报不一致）")
    if cdd2.attrs:
        problems.append(
            f"fixture 2 的 attrs 不该有键，实际 {sorted(cdd2.attrs)}")
    if "CAN.ReqCanId" not in cdd2.attrs_template:
        problems.append("fixture 2 的模板默认值没有单独收进 attrs_template")
    print(f"  触发：{sorted(got2)}")

    print()
    if problems:
        for p in problems:
            print(f"自检失败：{p}")
        return 1
    print("自检通过（2 组 fixture）")
    return 0


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def _preflight(path: str, label: str) -> None:
    """Fail with a sentence, not a traceback."""
    import os
    if not os.path.exists(path):
        _die(f"error: {label} 文件不存在：{path}")
    if os.path.isdir(path):
        _die(f"error: {label} 是一个目录，不是文件：{path}")
    if os.path.getsize(path) == 0:
        _die(f"error: {label} 文件是空的：{path}")
    try:
        with open(path, "rb") as fh:
            head = fh.read(4096)
    except OSError as exc:
        _die(f"error: 读不了 {label} 文件 {path}：{exc}")
    if b"<" not in head:
        _die(
            f"error: {label} 文件 {path} 开头不是 XML。"
            "这两个参数是不是传反了？第一个应该是 CDD，第二个是 ARXML。"
        )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="cdd_arxml_check",
        description="CANdelaStudio CDD × AUTOSAR ECU 配置交叉校验",
    )
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="command", required=True)

    for name, helptext in (
        ("probe", "看两侧各自读到了什么（比对之前先跑这个）"),
        ("check", "完整比对"),
        ("matrix", "导出逐项台账 CSV"),
    ):
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("cdd", help="CDD 文件（.cdd / .xml, CANdelaStudio 导出）")
        sp.add_argument("arxml", help="AUTOSAR ECU 配置 ARXML")
        if name == "check":
            sp.add_argument("--json", action="store_true", help="输出 JSON")
            sp.add_argument("--min-severity", default="info",
                            choices=["error", "warn", "info"],
                            help="只显示该级别及以上")
        if name == "matrix":
            sp.add_argument("--output", "-o", default="-",
                            help="输出 CSV 路径，默认标准输出")

    st = sub.add_parser("selftest", help="内置样例自检（含植入缺陷）")
    st.set_defaults(func=cmd_selftest)

    args = ap.parse_args(argv)

    if args.command == "selftest":
        return cmd_selftest(args)

    _preflight(args.cdd, "CDD")
    _preflight(args.arxml, "ARXML")

    # A swapped pair passes _preflight (both are XML) and then fails deep
    # inside the parser with a confusing message. Detect it by root element.
    if args.command in ("probe", "check", "matrix"):
        try:
            with open(args.cdd, "rb") as fh:
                head = fh.read(8192).decode("utf-8", "replace")
        except OSError:
            head = ""
        if "AUTOSAR" in head[:2048] and "CANDELA" not in head[:2048]:
            _die(
                "error: 第一个参数看起来是 ARXML（含 AUTOSAR 命名空间），不是 CDD。"
                "用法是：cdd_arxml_check check <CDD> <ARXML>"
            )

    if args.command == "probe":
        return cmd_probe(args)
    if args.command == "check":
        return cmd_check(args)
    return cmd_matrix(args)


if __name__ == "__main__":
    sys.exit(main())
