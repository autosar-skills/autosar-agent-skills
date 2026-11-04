#!/usr/bin/env python3
# tools/gen_demo_dbc.py
"""Generate the example databases shipped with dbc-matrix-audit.

Two files are produced:

  skills/dbc-matrix-audit/examples/demo.dbc          a clean, synthetic CAN FD matrix for a fictional
                             auxiliary control node pair. Passes lint with no
                             errors and no warnings.
  skills/dbc-matrix-audit/examples/demo_broken.dbc   the same matrix with nine deliberate defects, one
                             per check family, so the linter has something to
                             find.

Everything here is invented. No real vehicle programme, supplier, person or
signal naming convention is reproduced.

Bit placement is computed rather than hand-written: a Motorola cursor walks
MSB-first (7,6,...,0,15,14,...) and each signal simply takes the next N bits.
That makes overlap structurally impossible in the clean file.

Usage:
    python tools/gen_demo_dbc.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

OUT_DIR = (Path(__file__).resolve().parent.parent
           / "skills" / "dbc-matrix-audit" / "examples")

NODES = ["ACM_A", "ACM_B", "RCM"]

# --------------------------------------------------------------------------
# signal / message description
# --------------------------------------------------------------------------


@dataclass
class Sig:
    name: str
    length: int
    factor: float = 1
    offset: float = 0
    unit: str = ""
    minimum: float | None = None
    maximum: float | None = None
    values: dict[int, str] | None = None
    comment: str = ""
    start: int = -1  # filled in by the packer


@dataclass
class Msg:
    frame_id: int
    name: str
    dlc: int
    transmitter: str
    cycle: int | None = None
    send_type: str = "Cyclic"
    signals: list[Sig] = field(default_factory=list)
    comment: str = ""
    start_value: dict[str, int] = field(default_factory=dict)


def motorola_cursor_first(start: int, length: int) -> list[int]:
    """Bit coordinates occupied by a Motorola signal, MSB first."""
    out, pos = [], start
    for _ in range(length):
        out.append(pos)
        pos = pos + 15 if pos % 8 == 0 else pos - 1
    return out


def pack(msg: Msg) -> None:
    """Assign non-overlapping Motorola start bits to every signal."""
    cursor = 7
    for sig in msg.signals:
        if sig.start >= 0:
            # respect a hand-placed position, then continue after it
            occupied = motorola_cursor_first(sig.start, sig.length)
            cursor = occupied[-1]
            continue
        sig.start = cursor
        for _ in range(sig.length):
            cursor = cursor + 15 if cursor % 8 == 0 else cursor - 1


# --------------------------------------------------------------------------
# the fictional matrix
# --------------------------------------------------------------------------

COMMON_HEAD = dict(factor=1, offset=0)


def build_messages() -> list[Msg]:
    msgs: list[Msg] = []

    msgs.append(Msg(
        0x100, "Node_Status", 8, "Vector__XXX", cycle=20, comment="primary node status heartbeat",
        signals=[
            Sig("Node_Status_Checksum", 16, comment="CRC16 over bytes 2..7, data id 0x9A11"),
            Sig("Node_Status_Counter", 8, comment="rolling counter 0..255"),
            Sig("Work_Mode", 4,
                values={0: "Init", 1: "Idle", 2: "Active", 3: "Degraded", 15: "Invalid"},
                comment="node work mode"),
            Sig("Power_Mode", 2,
                values={0: "Off", 1: "On", 2: "Reserved", 3: "Invalid"},
                comment="supply mode as seen by the node"),
            Sig("Power_Mode_Fault", 2,
                values={0: "False", 1: "True", 2: "Reserved", 3: "Invalid"}),
            Sig("Bus_Off_Count", 8, maximum=255, comment="cumulative bus-off events since power-on"),
        ],
    ))
    msgs[0].start_value = {"Work_Mode": 0, "Power_Mode": 0}

    msgs.append(Msg(
        0x110, "Vehicle_Motion", 32, "Vector__XXX", cycle=50, comment="motion inputs from the chassis domain",
        signals=[
            Sig("Motion_Checksum", 16),
            Sig("Motion_Counter", 8),
            Sig("Vehicle_Speed", 13, factor=0.05625, unit="km/h", minimum=0, maximum=460.74),
            Sig("Vehicle_Speed_Valid", 1, values={0: "Invalid", 1: "Valid"}),
            Sig("Steering_Angle", 14, factor=0.1, offset=-780, unit="deg",
                minimum=-780, maximum=858.3, comment="steering wheel angle, left positive"),
            Sig("Steering_Rate", 15, factor=0.1, offset=-1024, unit="deg/s", minimum=-1024, maximum=2253),
            Sig("Yaw_Rate", 15, factor=0.01, offset=-163.84, unit="deg/s",
                minimum=-163.84, maximum=163.83),
            Sig("Lateral_Accel", 10, factor=0.01, offset=-5.12, unit="m/s2",
                minimum=-5.12, maximum=5.11),
        ],
    ))

    msgs.append(Msg(
        0x120, "Ambient_Input", 8, "Vector__XXX", cycle=100, comment="ambient light and rain sensing",
        signals=[
            Sig("Forward_Light_Level", 10, factor=10, unit="lx", maximum=10230,
                comment="brightness ahead of the vehicle"),
            Sig("Ambient_Light_Level", 10, factor=10, unit="lx", maximum=10230),
            Sig("Rain_Intensity", 4, values={0: "None", 1: "Light", 2: "Medium", 3: "Heavy", 15: "Invalid"}),
            Sig("Ambient_Valid", 1, values={0: "Invalid", 1: "Valid"}),
        ],
    ))

    msgs.append(Msg(
        0x130, "Control_Cmd", 32, "Vector__XXX", cycle=100,
        send_type="CyclicAndEvent", comment="actuator commands toward both lamp modules",
        signals=[
            Sig("Cmd_Checksum", 16),
            Sig("Cmd_Counter", 8),
            Sig("Position_Lamp_On", 2, values={0: "Init", 1: "Off", 2: "On", 3: "Invalid"}),
            Sig("Position_Lamp_Brightness", 3, values={0: "Initial", 1: "Night", 2: "Day1", 3: "Day2", 7: "Invalid"}),
            Sig("Turn_Lamp_On", 2, values={0: "Init", 1: "Off", 2: "On", 3: "Invalid"}),
            Sig("Turn_Lamp_Brightness", 7, unit="%", maximum=100),
            Sig("Low_Beam_On", 2, values={0: "Init", 1: "Off", 2: "On", 3: "Invalid"}),
            Sig("High_Beam_On", 2, values={0: "Init", 1: "Off", 2: "On", 3: "Invalid"}),
            Sig("Adaptive_Light_Enable", 2, values={0: "Init", 1: "Disabled", 2: "Enabled", 3: "Invalid"}),
            Sig("Projection_Scene", 4, values={0: "None", 1: "Welcome", 2: "Goodbye", 3: "Charging", 15: "Invalid"}),
            Sig("Projection_Intensity", 8, unit="%", maximum=100),
            Sig("Aux_Lamp_On", 2, values={0: "Init", 1: "Off", 2: "On", 3: "Invalid"}),
        ],
    ))

    msgs.append(Msg(
        0x140, "Time_Sync", 8, "Vector__XXX", cycle=1000, comment="wall clock broadcast",
        signals=[
            Sig("Time_Year", 8, offset=2000, unit="year", minimum=2000, maximum=2255),
            Sig("Time_Month", 4, unit="month", minimum=1, maximum=12),
            Sig("Time_Day", 5, unit="day", minimum=1, maximum=31),
            Sig("Time_Hour", 5, unit="h", maximum=23),
            Sig("Time_Minute", 6, unit="min", maximum=59),
            Sig("Time_Second", 6, unit="s", maximum=59),
            Sig("Time_Valid", 2, values={0: "Invalid", 1: "Valid", 2: "Reserved", 3: "Invalid"}),
        ],
    ))

    msgs.append(Msg(
        0x150, "Scene_Sync", 8, "Vector__XXX", cycle=50, comment="bitmap of projection scenes available on this vehicle",
        signals=[Sig(f"Scene_Available_{i}", 1, values={0: "NotAvailable", 1: "Available"})
                 for i in range(16)],
    ))

    msgs.append(Msg(
        0x160, "Sensor_Fusion", 32, "Vector__XXX", cycle=50,
        signals=[
            Sig("Fusion_Checksum", 16),
            Sig("Fusion_Counter", 8),
            Sig("Object_Count", 6, maximum=63),
            Sig("Nearest_Object_Distance", 12, factor=0.05, unit="m", maximum=204.75),
            Sig("Nearest_Object_Speed", 12, factor=0.05, offset=-102.4, unit="m/s",
                minimum=-102.4, maximum=102.35),
            Sig("Fusion_Valid", 1, values={0: "Invalid", 1: "Valid"}),
        ],
    ))

    def status_msg(fid: int, node: str, extra_projection: bool) -> Msg:
        sigs = [
            Sig(f"{node}_Checksum", 16),
            Sig(f"{node}_Counter", 8),
            Sig(f"{node}_Position_Lamp_State", 2, values={0: "Init", 1: "Off", 2: "On", 3: "Invalid"}),
            Sig(f"{node}_Position_Lamp_Brightness", 3, unit="%", maximum=100),
            Sig(f"{node}_Position_Lamp_Fault", 2, values={0: "NoFault", 1: "Fault", 2: "Reserved", 3: "Invalid"}),
            Sig(f"{node}_Turn_Lamp_State", 2, values={0: "Init", 1: "Off", 2: "On", 3: "Invalid"}),
            Sig(f"{node}_Turn_Lamp_Fault", 2, values={0: "NoFault", 1: "Fault", 2: "Reserved", 3: "Invalid"}),
            Sig(f"{node}_Low_Beam_State", 2, values={0: "Init", 1: "Off", 2: "On", 3: "Invalid"}),
            Sig(f"{node}_High_Beam_State", 2, values={0: "Init", 1: "Off", 2: "On", 3: "Invalid"}),
            Sig(f"{node}_Adaptive_Light_State", 2, values={0: "Init", 1: "Off", 2: "On", 3: "Invalid"}),
            Sig(f"{node}_Adaptive_Light_Fault", 2, values={0: "NoFault", 1: "Fault", 2: "Reserved", 3: "Invalid"}),
            Sig(f"{node}_Supply_Voltage", 8, factor=0.1, unit="V", maximum=25.5),
            Sig(f"{node}_Temperature", 8, factor=0.5, offset=-40, unit="degC",
                minimum=-40, maximum=87.5),
        ]
        if extra_projection:
            sigs += [
                Sig(f"{node}_Projection_State", 4,
                    values={0: "Off", 1: "Standby", 2: "Projecting", 3: "Fault", 15: "Invalid"}),
                Sig(f"{node}_Projection_Intensity", 8, unit="%", maximum=100),
                Sig(f"{node}_Projection_Fault", 2, values={0: "NoFault", 1: "Fault", 2: "Reserved", 3: "Invalid"}),
            ]
        return Msg(fid, f"{node}_Status", 32, node, cycle=100, signals=sigs,
                   comment=f"state feedback from {node}")

    # both nodes carry the same feature set in the clean file; the broken
    # variant drops one signal from B to demonstrate asymmetry detection
    a = status_msg(0x200, "ACM_A", True)
    b = status_msg(0x201, "ACM_B", True)
    msgs += [a, b]

    def diag_msg(fid: int, node: str) -> Msg:
        sigs = [
            Sig(f"{node}_Total_Fault_Count", 8, maximum=255),
            Sig(f"{node}_Frame_Index", 5, maximum=31),
            Sig(f"{node}_Supplier_Code", 3, maximum=7,
                values={0: "Unspecified", 1: "SupplierA", 2: "SupplierB", 7: "Invalid"}),
        ]
        sigs += [Sig(f"{node}_Fault_Code_{i}", 12, maximum=4095) for i in range(1, 6)]
        return Msg(fid, f"{node}_Diagnostics", 32, node, cycle=500, signals=sigs,
                   comment=f"condensed fault snapshot from {node}")

    msgs += [diag_msg(0x300, "ACM_A"), diag_msg(0x301, "ACM_B")]

    msgs.append(Msg(
        0x400, "Calibration_Block", 64, "RCM", send_type="Event",
        comment="calibration payload, transferred on request only",
        signals=[Sig(f"Calibration_Byte_{i}", 8, maximum=255) for i in range(1, 33)],
    ))

    msgs.append(Msg(
        0x500, "Log_Snapshot", 64, "ACM_A", send_type="Event",
        comment="diagnostic log words, little structure by design",
        signals=[Sig(f"Log_Word_{i}", 32, maximum=4294967295) for i in range(1, 5)],
    ))

    def nm_msg(fid: int, node: str) -> Msg:
        return Msg(fid, f"NM_{node}", 8, node, send_type="Event",
                   comment="AUTOSAR network management frame",
                   signals=[
                       Sig(f"{node}_Source_Node_Id", 8, maximum=255),
                       Sig(f"{node}_Repeat_Message_Request", 1, values={0: "No", 1: "Yes"}),
                       Sig(f"{node}_Active_Wakeup", 1, values={0: "No", 1: "Yes"}),
                       Sig(f"{node}_Repeat_Status", 1, values={0: "No", 1: "Yes"}),
                       Sig(f"{node}_Wakeup_Reason", 6, maximum=63,
                           values={0: "Undefined", 1: "PowerOn", 2: "Can", 3: "Local", 63: "Invalid"}),
                   ])

    msgs += [nm_msg(0x600, "ACM_A"), nm_msg(0x601, "ACM_B")]

    msgs.append(Msg(
        0x210, "Thermal_Status", 8, "ACM_A", cycle=500,
        signals=[
            Sig("Board_Temperature", 8, factor=0.5, offset=-40, unit="degC",
                minimum=-40, maximum=87.5),
            Sig("Led_Temperature", 8, factor=0.5, offset=-40, unit="degC",
                minimum=-40, maximum=87.5),
            Sig("Thermal_Derating", 2, values={0: "None", 1: "Level1", 2: "Level2", 3: "Invalid"}),
            Sig("Fan_Duty", 7, unit="%", maximum=100),
            Sig("Thermal_Fault", 2, values={0: "NoFault", 1: "Fault", 2: "Reserved", 3: "Invalid"}),
            Sig("Thermal_Valid", 1, values={0: "Invalid", 1: "Valid"}),
        ],
    ))

    msgs.append(Msg(
        0x220, "Voltage_Rail", 8, "ACM_B", cycle=500,
        signals=[
            Sig("Rail_12V", 10, factor=0.01, unit="V", maximum=10.23),
            Sig("Rail_5V", 10, factor=0.005, unit="V", maximum=5.115),
            Sig("Rail_3V3", 10, factor=0.005, unit="V", maximum=5.115),
            Sig("Rail_Status", 2, values={0: "Ok", 1: "UnderVoltage", 2: "OverVoltage", 3: "Invalid"}),
            Sig("Rail_Valid", 1, values={0: "Invalid", 1: "Valid"}),
        ],
    ))

    msgs.append(Msg(
        0x7DF, "Diag_Functional", 64, "Vector__XXX", send_type="Event",
        comment="functional diagnostic request; payload length varies with the service",
        signals=[Sig("Diag_Functional_Data", 64, maximum=18446744073709551615)],
    ))

    msgs.append(Msg(
        0x700, "Diag_Phys_ACM_A", 64, "Vector__XXX", send_type="Event",
        signals=[Sig("Diag_Phys_A_Data", 64, maximum=18446744073709551615)],
    ))
    msgs.append(Msg(
        0x708, "Diag_Resp_ACM_A", 64, "ACM_A", send_type="Event",
        signals=[Sig("Diag_Resp_A_Data", 64, maximum=18446744073709551615)],
    ))

    for m in msgs:
        pack(m)
    return msgs


# --------------------------------------------------------------------------
# emitter
# --------------------------------------------------------------------------

def esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def fmt_num(v: float) -> str:
    if isinstance(v, int) or float(v).is_integer():
        return str(int(v))
    return f"{v:g}"


def emit(msgs: list[Msg], *, broken: bool) -> str:
    L: list[str] = []
    L.append('VERSION "1.0"')
    L.append("")
    L.append("")
    L.append("NS_ :")
    for item in ("NS_DESC_", "CM_", "BA_DEF_", "BA_", "VAL_", "CAT_DEF_", "CAT_",
                 "FILTER", "BA_DEF_DEF_", "EV_DATA_", "ENVVAR_DATA_", "SGTYPE_",
                 "SGTYPE_VAL_", "BA_DEF_SGTYPE_", "BA_SGTYPE_", "SIG_TYPE_REF_",
                 "VAL_TABLE_", "SIG_GROUP_", "SIG_VALTYPE_", "SIGTYPE_VALTYPE_",
                 "BO_TX_BU_", "BA_DEF_REL_", "BA_REL_", "BA_DEF_DEF_REL_",
                 "BU_SG_REL_", "BU_EV_REL_", "BU_BO_REL_", "SG_MUL_VAL_"):
        L.append(f"        {item}")
    L.append("")
    L.append("BS_:")
    L.append("")
    nodes = list(NODES)
    if broken:
        nodes.append("RCM_SPARE")  # declared but unused, keeps BU_ valid
    L.append("BU_: " + " ".join(nodes))
    L.append("")

    # ---- attribute definitions -----------------------------------------
    L.append('BA_DEF_ BO_ "GenMsgCycleTime" INT 0 10000;')
    L.append('BA_DEF_ BO_ "GenMsgSendType" ENUM "Cyclic","Event","CyclicAndEvent","IfActive","NoMsgSendType";')
    L.append('BA_DEF_ BO_ "GenMsgILSupport" ENUM "No","Yes";')
    L.append('BA_DEF_ BO_ "CANFD_BRS" ENUM "0","1";')
    L.append('BA_DEF_ BO_ "VFrameFormat" ENUM "StandardCAN","ExtendedCAN","reserved",'
             '"reserved","reserved","reserved","reserved","reserved","reserved","reserved",'
             '"reserved","reserved","reserved","reserved","StandardCAN_FD","ExtendedCAN_FD";')
    L.append('BA_DEF_ SG_ "GenSigStartValue" INT 0 4294967295;')
    L.append('BA_DEF_ SG_ "GenSigInactiveValue" INT 0 4294967295;')
    L.append('BA_DEF_ BU_ "NodeLayerModules" STRING ;')
    L.append('BA_DEF_  "DBName" STRING ;')
    L.append('BA_DEF_  "BusType" STRING ;')
    L.append('BA_DEF_DEF_ "GenMsgCycleTime" 0;')
    L.append('BA_DEF_DEF_ "GenMsgSendType" "Cyclic";')
    L.append('BA_DEF_DEF_ "GenMsgILSupport" "No";')
    L.append('BA_DEF_DEF_ "CANFD_BRS" "1";')
    L.append('BA_DEF_DEF_ "VFrameFormat" "StandardCAN_FD";')
    L.append('BA_DEF_DEF_ "GenSigStartValue" 0;')
    L.append('BA_DEF_DEF_ "GenSigInactiveValue" 0;')
    L.append('BA_DEF_DEF_ "DBName" "demo";')
    L.append('BA_DEF_DEF_ "BusType" "CAN FD";')
    L.append('')

    L.append(f'CM_ "Synthetic matrix generated by tools/gen_demo_dbc.py. '
             f'All entities are fictional.";')
    L.append("")

    for m in msgs:
        L.append(f"BO_ {m.frame_id} {m.name}: {m.dlc} {m.transmitter}")
        for s in m.signals:
            recv = "Vector__XXX"
            L.append(
                f' SG_ {s.name} : {s.start}|{s.length}@0+ '
                f'({fmt_num(s.factor)},{fmt_num(s.offset)}) '
                f'[{"" if s.minimum is None else fmt_num(s.minimum)}|'
                f'{"" if s.maximum is None else fmt_num(s.maximum)}] '
                f'"{s.unit}"  {recv}'
            )
        L.append("")

    # ---- value tables --------------------------------------------------
    L.append("")
    for m in msgs:
        for s in m.signals:
            if s.values:
                pairs = " ".join(f'{k} "{esc(v)}"' for k, v in sorted(s.values.items()))
                L.append(f"VAL_ {m.frame_id} {s.name} {pairs} ;")
    L.append("")

    # ---- comments ------------------------------------------------------
    for m in msgs:
        if m.comment:
            L.append(f'CM_ BO_ {m.frame_id} "{esc(m.comment)}";')
    for m in msgs:
        for s in m.signals:
            if s.comment:
                L.append(f'CM_ SG_ {m.frame_id} {s.name} "{esc(s.comment)}";')
    L.append("")

    # ---- attributes ----------------------------------------------------
    for m in msgs:
        if m.cycle:
            L.append(f'BA_ "GenMsgCycleTime" BO_ {m.frame_id} {m.cycle};')
        st = m.send_type
        if broken and m.frame_id == 0x100:
            L.append(f'BA_ "GenMsgSendType" BO_ {m.frame_id} 0;')  # numeric, not "Cyclic"
        else:
            L.append(f'BA_ "GenMsgSendType" BO_ {m.frame_id} "{st}";')
        L.append(f'BA_ "GenMsgILSupport" BO_ {m.frame_id} "Yes";')
        L.append(f'BA_ "VFrameFormat" BO_ {m.frame_id} '
                 f'"{("StandardCAN_FD" if m.dlc > 8 else "StandardCAN")}";')
    if not broken:
        for m in msgs:
            for sig_name, val in m.start_value.items():
                L.append(f'BA_ "GenSigStartValue" SG_ {m.frame_id} {sig_name} {val};')
    L.append("")
    L.append('BA_ "DBName" "demo";')
    L.append('BA_ "BusType" "CAN FD";')
    L.append("")
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------
# deliberate defects
# --------------------------------------------------------------------------

def corrupt(msgs: list[Msg]) -> list[Msg]:
    """Apply one defect per check family. Mutates and returns ``msgs``."""
    by_id = {m.frame_id: m for m in msgs}

    # BIT-001: force one signal to start where another already sits
    m = by_id[0x201]
    target = next(s for s in m.signals if s.name == "ACM_B_Temperature")
    victim = next(s for s in m.signals if s.name == "ACM_B_Supply_Voltage")
    target.start = victim.start

    # RNG-001: push one signal past the end of an 8 byte frame
    m = by_id[0x120]
    next(s for s in m.signals if s.name == "Ambient_Valid").start = 63

    # SYM-001 + TYP-001: drop one signal from B, and misspell the A-side one
    # in a case-only way (the real-world `FctSt` / `Fctst` pattern)
    m = by_id[0x201]
    m.signals = [s for s in m.signals if s.name != "ACM_B_Projection_Fault"]
    a = by_id[0x200]
    for s in a.signals:
        if s.name == "ACM_A_Projection_State":
            s.name = "ACM_A_Projection_statE"

    # DUP-001: reuse a signal name that already exists in another frame
    m = by_id[0x210]
    m.signals[0].name = "Node_Status_Counter"

    # DLC-001: an illegal payload size
    by_id[0x500].dlc = 13

    # NOD-001: transmit from a node that was never declared
    by_id[0x400].transmitter = "GATEWAY_X"

    return msgs


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    clean = emit(build_messages(), broken=False)
    clean_path = OUT_DIR / "demo.dbc"
    clean_path.write_text(clean, encoding="utf-8", newline="\n")
    print(f"wrote {clean_path}")

    broken = emit(corrupt(build_messages()), broken=True)
    # the broken file is also encoded as GBK so that ENC-001 fires; this
    # mirrors the most common real-world problem with vendor-supplied files
    broken_path = OUT_DIR / "demo_broken.dbc"
    broken_with_cjk = broken.replace(
        "Synthetic matrix generated by tools/gen_demo_dbc.py. All entities are fictional.",
        "合成通信矩阵，由 tools/gen_demo_dbc.py 生成。所有实体均为虚构。",
    )
    broken_path.write_bytes(broken_with_cjk.encode("gbk"))
    print(f"wrote {broken_path}  (GBK encoded on purpose)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
