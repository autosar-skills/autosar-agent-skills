#!/usr/bin/env python3
# skills/cdd-arxml-consistency/scripts/demo_fixtures.py
"""Build a synthetic CDD / ARXML pair with known planted defects.

Synthetic on purpose: no real vehicle, supplier, DID, DTC or CAN id from any
customer project appears here. What *is* modelled faithfully is the containers'
shapes — a fixture whose structure differs from reality validates a code path
that does not exist, and the self-test then passes while the tool is broken on
real files.

Planted defects, one per check code:

    CDX-001  DID in the CDD, missing from Dcm
    CDX-002  DID in Dcm, missing from the CDD
    CDX-003  DID on both sides, DcmDspDidUsed = false
    CDX-004  DTC in the CDD, missing from Dem
    CDX-005  DTC in Dem, missing from the CDD
    CDX-006  routine in the CDD, missing from Dcm
    CDX-010  physical request CAN id disagrees (filter sides with the CDD)
    CDX-020  P2Server disagrees per session
    CDX-030  session defined in the CDD only
    CDX-032  seed and key length differ
    CDX-043  CDD fault-memory pool differs from its instance records
"""

from __future__ import annotations

import pathlib
import tempfile

# Locked to what compare() must produce on this fixture. Both the per-severity
# totals and the code set are asserted: asserting only the code set let a
# fixture drift from 3 findings to 7 in another skill without failing.
#
# These numbers were not derived by hand — they were read off a real run and
# then checked line by line against the planted defects. An expectation
# written from the fixture's source drifts the moment the checker changes
# behaviour, and then the self-test either goes red for no reason or, worse,
# gets "fixed" by editing the number.
EXPECTED_COUNTS = {"error": 6, "warn": 4, "info": 3}

EXPECTED_CODES = [
    "CDX-001", "CDX-002", "CDX-003", "CDX-004", "CDX-005",
    "CDX-006", "CDX-010", "CDX-020", "CDX-030", "CDX-032",
    "CDX-042", "CDX-043", "CDX-044",
]

# Second fixture: the same CDD with every <ECU> attribute removed. This is the
# shape a CANdelaStudio template has after "save as" and before anyone fills in
# the CAN tab — DID/DTC/routines are all real, addressing and timing are not.
# It must produce CDX-013 + CDX-025 and must NOT produce CDX-010/011/012/020/021
# (there is nothing to disagree with); the whole point is that "no finding" must
# never be mistaken for "no problem".
UNCONFIGURED_CODES = ["CDX-013", "CDX-025"]
UNCONFIGURED_MUST_NOT = [
    "CDX-010", "CDX-011", "CDX-012", "CDX-020", "CDX-021", "CDX-022",
]

# CAN ids chosen from the 0x6xx range so they cannot collide with any real
# matrix in this repo. Names are deliberately neutral.
REQ_ID_CDD = 0x6A0
REQ_ID_ARXML = 0x6A1     # the disagreement CDX-010 reports
RESP_ID = 0x6A8
FUNC_ID = 0x6AF
FILTER_MASK = 0x7FF


def _tuv(tag: str, text: str) -> str:
    return f"<{tag}><TUV xml:lang='en-US'>{text}</TUV></{tag}>"


CDD_TEMPLATE = """<?xml version='1.0' encoding='utf-8' standalone='no'?>
<!DOCTYPE CANDELA SYSTEM 'candela.dtd'>
<CANDELA dtdvers='11.0.100'>
<ECUDOC oid='DEMO0000000000000000000000000001' doctype='inst' manufacturer='Vector'>
{desc}
<PROTOCOLSTANDARD>UDS</PROTOCOLSTANDARD>
{attrdefs}
{ecu}
{dcltmpls}
{dids}
{negres}
{pool}
{services}
{insts}
</ECUDOC>
</CANDELA>
"""


def build(unconfigured: bool = False) -> tuple[str, str]:
    """Write the pair into a temp dir; return (cdd_path, arxml_path).

    With ``unconfigured=True`` the <ECU> node keeps only its QUAL and loses
    every CAN.* override, while the DEFATTS definitions stay. That is exactly
    what a CANdelaStudio template looks like before anyone fills in the CAN
    tab: real DIDs, real DTCs, no addressing. The ARXML side is unchanged, so
    the only difference in output must be the two "not configured" findings.
    """
    out = pathlib.Path(tempfile.mkdtemp(
        prefix="cdxselftest-nocfg-" if unconfigured else "cdxselftest-"))

    # ---- attribute definitions -----------------------------------------
    # ECU-level values are numeric ids in <UNS attrref=...>; this table is how
    # they get names. Real CANdela exports index ~180 of them.
    attrs = [
        ("_ATTR_REQ", "CAN.ReqCanId"),
        ("_ATTR_RESP", "CAN.ResCanId"),
        ("_ATTR_FUNC", "CAN.ReqCanIdFunc"),
        ("_ATTR_P2", "CAN.P2Server"),
        ("_ATTR_P2S", "CAN.P2ExServer"),
        ("_ATTR_S3C", "CAN.S3Client"),
        ("_ATTR_S3S", "CAN.S3Server"),
        ("_ATTR_STMIN", "CAN.StMin"),
        ("_ATTR_BS", "CAN.Blocksize"),
    ]
    attrdefs = ["<DEFATTS><DATAOBJATTS>"]
    for ident, name in attrs:
        attrdefs.append(
            f"<UNSDEF id='{ident}' attrcatref='_CAT' v='0' df='dec'>"
            + _tuv("QUAL", name) + "</UNSDEF>"
        )
    attrdefs.append("</DATAOBJATTS></DEFATTS>")
    attrdefs.append("<ATTRCATS><ATTRCAT id='_CAT' usage='sys'><QUAL>COM.CAN</QUAL></ATTRCAT></ATTRCATS>")

    # ---- ECU node -------------------------------------------------------
    # P2 = 50 ms both sides agree; P2* disagrees (5000 vs 4500) -> CDX-021?
    # No: CDX-021 is warn on P2*. Keep P2* equal and make P2 disagree in a
    # session row instead (that is CDX-020, driven by the ARXML session row).
    if unconfigured:
        ecu = "<ECU id='_ECU'><QUAL>Demo_ECU</QUAL></ECU>"
    else:
        ecu = (
            "<ECU id='_ECU'><QUAL>Demo_ECU</QUAL>"
            f"<UNS attrref='_ATTR_REQ' v='{REQ_ID_CDD}'/>"
            f"<UNS attrref='_ATTR_RESP' v='{RESP_ID}'/>"
            f"<UNS attrref='_ATTR_FUNC' v='{FUNC_ID}'/>"
            "<UNS attrref='_ATTR_P2' v='50'/>"
            "<UNS attrref='_ATTR_P2S' v='5000'/>"
            "<UNS attrref='_ATTR_S3C' v='4000'/>"
            "<UNS attrref='_ATTR_S3S' v='5000'/>"
            "<UNS attrref='_ATTR_STMIN' v='10'/>"
            "<UNS attrref='_ATTR_BS' v='0'/>"
            "</ECU>"
        )

    # ---- templates ------------------------------------------------------
    # cls drives classification. 'idn' = data identifier, 'ses' = session,
    # 'sec' = security, 'rtn' = routine.
    dcltmpls = (
        "<DCLTMPLS>"
        "<DCLTMPL id='_T_CLS_IDN' cls='idn'/>"
        "<DCLTMPL id='_T_CLS_SES' cls='ses'/>"
        "<DCLTMPL id='_T_CLS_SEC' cls='sec'/>"
        "<DCLTMPL id='_T_CLS_RTN' cls='rtn'/>"
        "</DCLTMPLS>"
    )

    # ---- DIDs -----------------------------------------------------------
    # 0xF190, 0xF18C match ARXML; 0x4800 is CDD-only (CDX-001);
    # 0xF187 is ARXML-only (CDX-002); 0xF18A is on both but unused (CDX-003).
    dids = (
        "<DIDS>"
        f"<DID n='{0xF190}'><NAME><TUV xml:lang='en-US'>VIN</TUV></NAME>"
        "<QUAL><TUV xml:lang='en-US'>Vehicle_Identification_Number</TUV></QUAL></DID>"
        f"<DID n='{0xF18C}'><NAME><TUV xml:lang='en-US'>ECU Serial</TUV></NAME>"
        "<QUAL><TUV xml:lang='en-US'>ECU_Serial_Number</TUV></QUAL></DID>"
        f"<DID n='{0xF18A}'><NAME><Tuv/></NAME>"
        "<QUAL><TUV xml:lang='en-US'>System_Supplier_Id</TUV></QUAL></DID>"
        f"<DID n='{0x4800}'><NAME><TUV xml:lang='en-US'>Traceability Code</TUV></NAME>"
        "<QUAL><TUV xml:lang='en-US'>Traceability_Code</TUV></QUAL></DID>"
        "</DIDS>"
    )

    # ---- negative response codes ---------------------------------------
    negres = (
        "<NEGRESCODES>"
        "<NEGRESCODE v='17'><QUAL><TUV xml:lang='en-US'>Service_not_supported</TUV></QUAL></NEGRESCODE>"
        "<NEGRESCODE v='49'><QUAL><TUV xml:lang='en-US'>Request_out_of_range</TUV></QUAL></NEGRESCODE>"
        "</NEGRESCODES>"
    )

    # ---- DTC pool -------------------------------------------------------
    # The pool carries one DTC that the diagnostic-instance records below do
    # not reference -> CDX-043 (info): the CDD disagrees with itself, and the
    # tool must say which population it actually compared.
    pool = (
        "<RECORDDTPOOL>"
        "<RECORDDT rtSpec='faultMemory'><NAME><TUV xml:lang='en-US'>Primary</TUV></NAME>"
        "<RECORD v='%d'/><RECORD v='%d'/><RECORD v='%d'/>"
        "</RECORDDT>"
        "<RECORDDT rtSpec='obdFaultMemory'><NAME><TUV xml:lang='en-US'>OBD</TUV></NAME>"
        "</RECORDDT>"
        "</RECORDDTPOOL>"
    ) % (0x100001, 0x100002, 0x1000FF)

    # ---- protocol services ---------------------------------------------
    # Names carry the SID. `WDBI` in the real file resolves via the abbreviation
    # table; here both spellings are exercised.
    services = (
        "<PROTOCOLSERVICES>"
        "<PROTOCOLSERVICE func='1' phys='1'><QUAL><TUV xml:lang='en-US'>_10_DiagnosticSessionControl</TUV></QUAL></PROTOCOLSERVICE>"
        "<PROTOCOLSERVICE func='0' phys='1'><QUAL><TUV xml:lang='en-US'>RDBI</TUV></QUAL></PROTOCOLSERVICE>"
        "<PROTOCOLSERVICE func='0' phys='1'><QUAL><TUV xml:lang='en-US'>SA_SK</TUV></QUAL></PROTOCOLSERVICE>"
        "<PROTOCOLSERVICE func='1' phys='1'><QUAL><TUV xml:lang='en-US'>TP</TUV></QUAL></PROTOCOLSERVICE>"
        "</PROTOCOLSERVICES>"
    )

    # ---- diagnostic instances -------------------------------------------
    # DTCs referenced by the instances: 0x100001, 0x100002 (both in Dem) and
    # 0x100003 (CDD-only -> CDX-004). 0x1000FF stays pool-only.
    insts = []
    # sessions: Default(1), Programming(2) match; Extended(3) is CDD-only.
    for qual, level in (("DefaultSession", 1), ("ProgrammingSession", 2),
                        ("ExtendedSession", 3)):
        insts.append(
            f"<DIAGINST tmplref='_T_CLS_SES'><QUAL><TUV xml:lang='en-US'>{qual}</TUV></QUAL>"
            f"<STATICVALUE v='{level}'/></DIAGINST>"
        )
    # security: level 1 present on both sides; the STATICVALUE here is the
    # sub-function (1 = requestSeed), which must NOT be read as the level.
    insts.append(
        "<DIAGINST tmplref='_T_CLS_SEC'><QUAL><TUV xml:lang='en-US'>SeedLevel1</TUV></QUAL>"
        "<STATICVALUE v='1'/></DIAGINST>"
    )
    insts.append(
        "<DIAGINST tmplref='_T_CLS_SEC'><QUAL><TUV xml:lang='en-US'>KeyLevel1</TUV></QUAL>"
        "<STATICVALUE v='2'/></DIAGINST>"
    )
    # routines: 0x0203 matches; 0x0303 is CDD-only (CDX-006).
    for qual, rid in (("Routine_0x0203", 0x0203), ("Routine_0x0303", 0x0303)):
        insts.append(
            f"<DIAGINST tmplref='_T_CLS_RTN'><QUAL><TUV xml:lang='en-US'>{qual}</TUV></QUAL>"
            f"<STATICVALUE v='{rid}'/></DIAGINST>"
        )
    # DTC population: nested RECORDDATAOBJ records inside an identifier
    # instance — this is where the real CANdela export keeps them.
    for did in (0xF190, 0xF18C, 0xF18A, 0x4800):
        recs = "".join(f"<RECORD v='{d}'/>" for d in (0x100001, 0x100002, 0x100003))
        insts.append(
            f"<DIAGINST tmplref='_T_CLS_IDN'><QUAL><TUV xml:lang='en-US'>did_{did:04X}</TUV></QUAL>"
            f"<RECORDDATAOBJ>{recs}</RECORDDATAOBJ></DIAGINST>"
        )

    cdd_text = CDD_TEMPLATE.format(
        desc="<DESC><TUV xml:lang='en-US'>Synthetic fixture. No customer data.</TUV></DESC>",
        attrdefs="".join(attrdefs),
        ecu=ecu,
        dcltmpls=dcltmpls,
        dids=dids,
        negres=negres,
        pool=pool,
        services=services,
        insts="".join(insts),
    )
    cdd_path = out / "demo.cdd"
    cdd_path.write_text(cdd_text, encoding="utf-8")

    # =====================================================================
    # ARXML
    # =====================================================================
    def module(name: str, short: str, body: str) -> str:
        return (
            "<ECUC-MODULE-CONFIGURATION-VALUES>"
            f"<SHORT-NAME>{short}</SHORT-NAME>"
            f"<DEFINITION-REF DEST='ECUC-MODULE-DEF'>/AUTOSAR/{name}</DEFINITION-REF>"
            f"<CONTAINERS>{body}</CONTAINERS>"
            "</ECUC-MODULE-CONFIGURATION-VALUES>"
        )

    def ctr(short: str, defname: str, params: dict, subs: str = "") -> str:
        body = "".join(
            "<ECUC-NUMERICAL-PARAM-VALUE>"
            f"<DEFINITION-REF DEST='ECUC-INTEGER-PARAM-DEF'>/AUTOSAR/{defname}/{k}</DEFINITION-REF>"
            f"<VALUE>{v}</VALUE></ECUC-NUMERICAL-PARAM-VALUE>"
            for k, v in params.items()
        )
        return (
            "<ECUC-CONTAINER-VALUE>"
            f"<SHORT-NAME>{short}</SHORT-NAME>"
            f"<DEFINITION-REF DEST='ECUC-PARAM-CONF-CONTAINER-DEF'>/AUTOSAR/{defname}</DEFINITION-REF>"
            f"<PARAMETER-VALUES>{body}</PARAMETER-VALUES>"
            f"{('<SUB-CONTAINERS>' + subs + '</SUB-CONTAINERS>') if subs else ''}"
            "</ECUC-CONTAINER-VALUE>"
        )

    # ---- Dcm ------------------------------------------------------------
    # DIDs: 0xF190, 0xF18C (both), 0xF18A (both, used=false -> CDX-003),
    #       0xF187 (ARXML only -> CDX-002)
    dcm_body = "".join([
        ctr("Did_0xF190", "Dcm/DcmConfigSet/DcmDsp/DcmDspDid",
            {"DcmDspDidIdentifier": 0xF190, "DcmDspDidUsed": "true"}),
        ctr("Did_0xF18C", "Dcm/DcmConfigSet/DcmDsp/DcmDspDid",
            {"DcmDspDidIdentifier": 0xF18C, "DcmDspDidUsed": "true"}),
        ctr("Did_0xF18A", "Dcm/DcmConfigSet/DcmDsp/DcmDspDid",
            {"DcmDspDidIdentifier": 0xF18A, "DcmDspDidUsed": "false"}),
        ctr("Did_0xF187", "Dcm/DcmConfigSet/DcmDsp/DcmDspDid",
            {"DcmDspDidIdentifier": 0xF187, "DcmDspDidUsed": "true"}),
        # sessions: Default + Programming agree. P2 on Programming is 60 ms
        # against the CDD's 50 -> CDX-020.
        ctr("Default", "Dcm/DcmConfigSet/DcmDsp/DcmDspSessionRow",
            {"DcmDspSessionLevel": 1, "DcmDspSessionP2ServerMax": "0.05",
             "DcmDspSessionP2StarServerMax": "5.0"}),
        ctr("Programming", "Dcm/DcmConfigSet/DcmDsp/DcmDspSessionRow",
            {"DcmDspSessionLevel": 2, "DcmDspSessionP2ServerMax": "0.06",
             "DcmDspSessionP2StarServerMax": "5.0"}),
        # security level 1: seed 16 / key 8 -> CDX-032
        ctr("Level_1", "Dcm/DcmConfigSet/DcmDsp/DcmDspSecurity/DcmDspSecurityRow",
            {"DcmDspSecurityLevel": 1, "DcmDspSecuritySeedSize": 16,
             "DcmDspSecurityKeySize": 8, "DcmDspSecurityDelayTime": "10.0",
             "DcmDspSecurityNumAttDelay": 3}),
        # routines: only 0x0203 -> 0x0303 is CDD-only (CDX-006)
        ctr("Routine_0x0203", "Dcm/DcmConfigSet/DcmDsp/DcmDspRoutine",
            {"DcmDspRoutineIdentifier": 0x0203}),
        # services: request byte lives in the SHORT-NAME
        ctr("Service_0x10_DiagnosticSessionControl", "Dcm/DcmConfigSet/DcmDsd/DcmDsdService", {}),
        ctr("Service_0x22_ReadDataByIdentifier", "Dcm/DcmConfigSet/DcmDsd/DcmDsdService", {}),
        ctr("Service_0x27_SecurityAccess", "Dcm/DcmConfigSet/DcmDsd/DcmDsdService", {}),
        ctr("Service_0x3E_TesterPresent", "Dcm/DcmConfigSet/DcmDsd/DcmDsdService", {}),
    ])

    # ---- Dem ------------------------------------------------------------
    # 0x100001, 0x100002 match; 0x100004 is ARXML-only -> CDX-005.
    dem_body = "".join(
        ctr(f"DTC_0x{v:06X}", "Dem/DemConfigSet/DemDTC", {"DemDtcValue": v})
        for v in (0x100001, 0x100002, 0x100004)
    )

    # ---- CanIf ----------------------------------------------------------
    def pdu(short: str, defname: str, can_id: int) -> str:
        return ctr(short, defname,
                   {"CanIfRxPduCanId" if "Rx" in defname else "CanIfTxPduCanId": can_id})

    canif_body = "".join([
        pdu("CanIfRxPduCfg_Phys_Req", "CanIf/CanIfInitCfg/CanIfRxPduCfg", REQ_ID_ARXML),
        pdu("CanIfRxPduCfg_Func_Req", "CanIf/CanIfInitCfg/CanIfRxPduCfg", FUNC_ID),
        pdu("CanIfTxPduCfg_Resp", "CanIf/CanIfInitCfg/CanIfTxPduCfg", RESP_ID),
    ])

    # ---- Can (hardware filters) -----------------------------------------
    # The filter admits the CDD's request id and NOT the CanIf one. That is the
    # evidence CDX-010 uses to say "CanIf is wrong", so the fixture has to
    # carry it or the check cannot be proven to work.
    filters = "".join(
        ctr(f"CanHwFilter_{i}", "Can/CanConfigSet/CanHwFilter",
            {"CanHwFilterCode": code, "CanHwFilterMask": FILTER_MASK})
        for i, code in enumerate((REQ_ID_CDD, FUNC_ID, RESP_ID))
    )

    # ---- CanTp ----------------------------------------------------------
    cantp_body = ctr("CanTpRxNSdu_Phys", "CanTp/CanTpConfig/CanTpRxNSdu",
                     {"CanTpBs": 0, "CanTpSTmin": "0.01", "CanTpNSa": 56, "CanTpNTa": 56})

    arxml_text = (
        "<?xml version='1.0' encoding='UTF-8'?>\n"
        "<AUTOSAR xmlns='http://autosar.org/schema/r4.0'>\n"
        "<AR-PACKAGES><AR-PACKAGE><SHORT-NAME>Demo</SHORT-NAME><ELEMENTS>\n"
        + module("Dcm", "Dcm", dcm_body)
        + module("Dem", "Dem", dem_body)
        + module("CanIf", "CanIf", canif_body)
        + module("Can", "Can", filters)
        + module("CanTp", "CanTp", cantp_body)
        + "\n</ELEMENTS></AR-PACKAGE></AR-PACKAGES>\n</AUTOSAR>\n"
    )
    arxml_path = out / "demo_ecuconfig.xml"
    arxml_path.write_text(arxml_text, encoding="utf-8")

    return str(cdd_path), str(arxml_path)


if __name__ == "__main__":
    c, a = build()
    print(c)
    print(a)
