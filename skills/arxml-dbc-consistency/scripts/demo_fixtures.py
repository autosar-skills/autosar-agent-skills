"""内置示例：程序化生成 DBC + ARXML，避免仓库里放两份大文件。

**拓扑必须与真实厂商文件一致**，否则 selftest 测不到真实代码路径：
    DBC 帧 --CanId--> CanIf PDU --CanIfXxxPduRef--> EcuC Pdu(X)
         --PduR 路由--> EcuC Pdu(COM_X) --ComPduIdRef--> Com IPdu

踩过的坑（都因为早期 demo 用了「按名字直连」的假拓扑而没被发现）：
  * 参数标签写成了 ECUC-NUMERICAL-PARAMETER-VALUE，真实是 -PARAM-VALUE
  * ComSignal 名带 `<PDU名>` 后缀，需剥回
  * ComBitPosition 存的是 LSB（平坦编号），不是 MSB

缺陷是故意埋的，`selftest` 断言这些码必须被触发。
"""

from __future__ import annotations

DEMO_DBC = """VERSION ""

BU_: LDM DMD


BO_ 256 ProjProjectionCfg: 8 LDM
 SG_ ProjBrtnsAdjstReq : 7|14@0+ (1,0) [0|16383] ""  DMD
 SG_ ProjectionAngleAdjstReq : 18|3@0+ (1,0) [0|7] ""  DMD
 SG_ ProjDistortionSwitch : 20|2@0+ (1,0) [0|3] ""  DMD

BO_ 272 ProjProjectionCfgFb: 8 DMD
 SG_ ProjBrtnsAdjstFb : 7|14@0+ (1,0) [0|16383] ""  LDM
 SG_ ProjCeremonyModeFb : 34|3@0+ (1,0) [0|7] ""  LDM

BO_ 512 TestFrame: 8 LDM
 SG_ SigA : 0|8@1+ (1,0) [0|255] ""  DMD
 SG_ SigB : 8|8@1+ (1,0) [0|255] ""  DMD

BO_ 768 MissingFrame: 8 DMD
 SG_ GhostSig : 7|8@0+ (1,0) [0|255] ""  LDM


BA_DEF_ BO_  "GenMsgCycleTime" INT 0 65535;
BA_DEF_ BO_  "VFrameFormat" ENUM  "StandardCAN","ExtendedCAN","reserved","reserved","reserved","reserved","reserved","reserved","reserved","reserved","reserved","reserved","reserved","reserved","StandardCAN_FD","ExtendedCAN_FD";
BA_DEF_ SG_  "GenSigStartValue" INT 0 0;
BA_DEF_DEF_  "GenMsgCycleTime" 0;
BA_DEF_DEF_  "VFrameFormat" 0;
BA_DEF_DEF_  "GenSigStartValue" 0;

BA_ "GenMsgCycleTime" BO_ 256 100;
BA_ "GenMsgCycleTime" BO_ 272 500;
BA_ "GenMsgCycleTime" BO_ 512 20;
BA_ "GenMsgCycleTime" BO_ 768 1000;
BA_ "VFrameFormat" BO_ 256 0;
BA_ "GenSigStartValue" SG_ 512 SigA 5;
"""

_DEF = "/DEMO"


def _esc(v: object) -> str:
    return str(v)


def _c(
    name: str,
    defpath: str,
    params=(),
    refs=(),
    subs=(),
) -> str:
    """生成一个 ECUC-CONTAINER-VALUE。

    params: (kind, name, value)，kind ∈ num|text
    refs:   (name, target)
    subs:   子容器（字符串或 _c 的元组参数）
    """
    out = [
        "<ECUC-CONTAINER-VALUE>",
        f"<SHORT-NAME>{name}</SHORT-NAME>",
        f'<DEFINITION-REF DEST="ECUC-PARAM-CONF-CONTAINER-DEF">{defpath}'
        "</DEFINITION-REF>",
    ]
    if params:
        out.append("<PARAMETER-VALUES>")
        for kind, pname, val in params:
            # 真实标签名是 -PARAM-VALUE，不是 -PARAMETER-VALUE
            tag = (
                "ECUC-NUMERICAL-PARAM-VALUE"
                if kind == "num"
                else "ECUC-TEXTUAL-PARAM-VALUE"
            )
            out += [
                f"<{tag}>",
                f"<DEFINITION-REF>{defpath}/{pname}</DEFINITION-REF>",
                f"<VALUE>{_esc(val)}</VALUE>",
                f"</{tag}>",
            ]
        out.append("</PARAMETER-VALUES>")
    if refs:
        out.append("<REFERENCE-VALUES>")
        for rname, target in refs:
            out += [
                "<ECUC-REFERENCE-VALUE>",
                f"<DEFINITION-REF>{defpath}/{rname}</DEFINITION-REF>",
                f'<VALUE-REF DEST="ECUC-CONTAINER-VALUE">{target}</VALUE-REF>',
                "</ECUC-REFERENCE-VALUE>",
            ]
        out.append("</REFERENCE-VALUES>")
    if subs:
        out.append("<SUB-CONTAINERS>")
        for sub in subs:
            out.append(sub if isinstance(sub, str) else _c(*sub))
        out.append("</SUB-CONTAINERS>")
    out.append("</ECUC-CONTAINER-VALUE>")
    return "".join(out)


def _mod(name: str, subs) -> str:
    return (
        "<ECUC-MODULE-CONFIGURATION-VALUES>"
        f"<SHORT-NAME>{name}</SHORT-NAME>"
        f'<DEFINITION-REF DEST="ECUC-MODULE-DEF">{_DEF}/{name}</DEFINITION-REF>'
        "<CONTAINERS>"
        + "".join(s if isinstance(s, str) else _c(*s) for s in subs)
        + "</CONTAINERS>"
        "</ECUC-MODULE-CONFIGURATION-VALUES>"
    )


# -- 各模块 ---------------------------------------------------------------

ECUC_PDU = f"{_DEF}/EcuC/EcucPduCollection/Pdu"
CANIF_RX = f"{_DEF}/CanIf/CanIfInitCfg/CanIfRxPduCfg"
CANIF_TX = f"{_DEF}/CanIf/CanIfInitCfg/CanIfTxPduCfg"
PDUR_PATH = f"{_DEF}/PduR/PduRRoutingTables/PduRRoutingPath"
COM_IPDU = f"{_DEF}/Com/ComConfig/ComIPdu"
COM_SIG = f"{_DEF}/Com/ComConfig/ComSignal"


def _ecuc_pdu(name: str, length: int) -> str:
    return _c(name, ECUC_PDU, [("num", "PduLength", length)])


def _canif_rx(name: str, canid: int, dlc: int, pdu: str, id_type="STANDARD_CAN") -> str:
    return _c(
        name,
        CANIF_RX,
        [
            ("num", "CanIfRxPduCanId", canid),
            ("text", "CanIfRxPduCanIdType", id_type),
            ("num", "CanIfRxPduDlc", dlc),
        ],
        [("CanIfRxPduRef", f"{_DEF}/EcuC/EcucPduCollection/{pdu}")],
    )


def _canif_tx(name: str, canid: int, dlc: int, pdu: str, id_type="STANDARD_CAN") -> str:
    return _c(
        name,
        CANIF_TX,
        [
            ("num", "CanIfTxPduCanId", canid),
            ("text", "CanIfTxPduCanIdType", id_type),
            ("num", "CanIfTxPduDlc", dlc),
        ],
        [("CanIfTxPduRef", f"{_DEF}/EcuC/EcucPduCollection/{pdu}")],
    )


def _route(name: str, src: str, dest: str, rtype="IF") -> str:
    return _c(
        name,
        PDUR_PATH,
        [("text", "PduRRouteType", rtype)],
        (),
        [
            (
                "Src",
                f"{PDUR_PATH}/PduRSrcPdu",
                (),
                [("PduRSrcPduRef", f"{_DEF}/EcuC/EcucPduCollection/{src}")],
            ),
            (
                "Dest",
                f"{PDUR_PATH}/PduRDestPdu",
                (),
                [("PduRDestPduRef", f"{_DEF}/EcuC/EcucPduCollection/{dest}")],
            ),
        ],
    )


def _com_sig(name: str, pdu_name: str, pos: int, length: int, order="BIG_ENDIAN") -> str:
    return _c(
        f"{name}_{pdu_name}",  # 真实厂商会带 PDU 后缀
        COM_SIG,
        [
            ("num", "ComBitPosition", pos),
            ("num", "ComBitSize", length),
            ("text", "ComSignalEndianness", order),
            ("text", "ComSignalType", "UINT8"),
        ],
    )


def _com_ipdu(name: str, direction: str, length: int, sigs) -> str:
    return _c(
        f"IPDU_COM_{name}",
        COM_IPDU,
        [
            ("text", "ComIPduDirection", direction),
            ("text", "ComIPduType", "NORMAL"),
        ],
        [("ComPduIdRef", f"{_DEF}/EcuC/EcucPduCollection/COM_{name}")],
        sigs,
    )


def build_demo_arxml() -> str:
    can = _mod(
        "Can",
        [
            (
                "CanConfigSet",
                f"{_DEF}/Can/CanConfigSet",
                (),
                (),
                [
                    (
                        "CanController_0",
                        f"{_DEF}/Can/CanConfigSet/CanController",
                        [("num", "CanControllerBaudRate", 500000)],
                    ),
                    (
                        "CanHardwareObject_0",
                        f"{_DEF}/Can/CanConfigSet/CanHardwareObject",
                        [
                            ("text", "CanHandleType", "FULL"),
                            ("text", "CanIdType", "STANDARD"),
                        ],
                    ),
                ],
            )
        ],
    )

    canif = _mod(
        "CanIf",
        [
            (
                "CanIfInitCfg",
                f"{_DEF}/CanIf/CanIfInitCfg",
                (),
                (),
                [
                    # 缺陷：DLC 写 7（DBC 是 8）→ AXD-003
                    _canif_tx("CanIfTxPduCfg_100", 256, 7, "ProjProjectionCfg"),
                    _canif_rx("CanIfRxPduCfg_110", 272, 8, "ProjProjectionCfgFb"),
                    _canif_tx("CanIfTxPduCfg_200", 512, 8, "TestFrame"),
                    # 缺陷：DBC 里没有 0x7FF → AXD-002
                    _canif_rx("CanIfRxPduCfg_7FF", 2047, 8, "GhostPdu"),
                ],
            )
        ],
    )

    pdur = _mod(
        "PduR",
        [
            (
                "PduRRoutingTables",
                f"{_DEF}/PduR/PduRRoutingTables",
                (),
                (),
                [
                    _route("Routing_T_100", "COM_ProjProjectionCfg", "ProjProjectionCfg"),
                    _route("Routing_R_110", "ProjProjectionCfgFb", "COM_ProjProjectionCfgFb"),
                    # 缺陷：TestFrame 没有路由 → AXD-015
                ],
            )
        ],
    )

    com_pdus = [
        _com_ipdu(
            "ProjProjectionCfg",
            "SEND",
            8,
            [
                # DBC: 7|14 → LSB = 7+14-1 = 20
                _com_sig("ProjBrtnsAdjstReq", "IPDU_COM_ProjProjectionCfg", 20, 14),
                # 缺陷：DBC 里叫 ProjectionAngleAdjstReq，大小写不同 → AXD-019
                _com_sig(
                    "projectionangleadjstreq", "IPDU_COM_ProjProjectionCfg", 20, 3
                ),
                # 缺陷：DBC 有 ProjDistortionSwitch，这里没配 → AXD-006
            ],
        ),
        _com_ipdu(
            "ProjProjectionCfgFb",
            "RECEIVE",
            8,
            [
                # DBC: 7|14 → LSB = 20；这里故意写 19 → AXD-008
                _com_sig("ProjBrtnsAdjstFb", "IPDU_COM_ProjProjectionCfgFb", 19, 14),
                # DBC: 34|3 → LSB = 34+3-1 = 36
                _com_sig("ProjCeremonyModeFb", "IPDU_COM_ProjProjectionCfgFb", 36, 3),
                # 缺陷：DBC 没这个信号，且与上一信号位重叠 → AXD-007 + AXD-018
                _com_sig("OverlapSig", "IPDU_COM_ProjProjectionCfgFb", 36, 4),
            ],
        ),
        _com_ipdu(
            "TestFrame",
            "SEND",
            8,
            [
                # 缺陷：DBC 是小端，这里写成大端 → AXD-009
                _com_sig("SigA", "IPDU_COM_TestFrame", 0, 8, order="BIG_ENDIAN"),
                _com_sig("SigB", "IPDU_COM_TestFrame", 8, 8, order="MOST-SIGNIFICANT-BYTE-LAST"),
                # 缺陷：整个 IPdu 没有 PduR 路由 → AXD-015
            ],
        ),
    ]

    com = _mod(
        "Com",
        [
            (
                "ComConfig",
                f"{_DEF}/Com/ComConfig",
                (),
                (),
                com_pdus,
            )
        ],
    )

    ecuc = _mod(
        "EcuC",
        [
            (
                "EcucConfigSet",
                f"{_DEF}/EcuC/EcucConfigSet",
                (),
                (),
                [
                    ("EcucPduCollection", f"{_DEF}/EcuC/EcucConfigSet/EcucPduCollection", (), (), [
                        _ecuc_pdu("ProjProjectionCfg", 8),
                        _ecuc_pdu("COM_ProjProjectionCfg", 8),
                        _ecuc_pdu("ProjProjectionCfgFb", 8),
                        _ecuc_pdu("COM_ProjProjectionCfgFb", 8),
                        _ecuc_pdu("TestFrame", 8),
                        _ecuc_pdu("COM_TestFrame", 8),
                        _ecuc_pdu("GhostPdu", 8),
                    ]),
                ],
            )
        ],
    )

    isig_xml = "".join(
        f"<I-SIGNAL><SHORT-NAME>{n}</SHORT-NAME><LENGTH>{ln}</LENGTH></I-SIGNAL>"
        for n, ln in [
            ("ProjBrtnsAdjstReq", 14),
            ("projectionangleadjstreq", 3),
            ("ProjBrtnsAdjstFb", 14),
            ("ProjCeremonyModeFb", 3),
            ("OverlapSig", 4),
            ("SigA", 8),
            ("SigB", 8),
        ]
    )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<AUTOSAR xmlns="http://autosar.org/schema/r4.0"><AR-PACKAGES>'
        "<AR-PACKAGE><SHORT-NAME>Ecuc</SHORT-NAME><ELEMENTS>"
        + ecuc + can + canif + pdur + com
        + "</ELEMENTS></AR-PACKAGE>"
        "<AR-PACKAGE><SHORT-NAME>ISig</SHORT-NAME><ELEMENTS>"
        + isig_xml
        + "</ELEMENTS></AR-PACKAGE>"
        "</AR-PACKAGES></AUTOSAR>"
    )


#: selftest 断言这些码必须被触发
EXPECTED_CODES = {
    "AXD-001", "AXD-002", "AXD-003", "AXD-006",
    "AXD-007", "AXD-008", "AXD-009", "AXD-015",
    "AXD-018", "AXD-019",
}

#: selftest 同时断言条数 —— 只断码不断条数的话，示例漂了也照样"通过"。
#: 改动 demo 后必须同步这两个数字，否则自检会红（这是刻意的）。
EXPECTED_COUNTS = {"error": 13, "warn": 2, "info": 1}
