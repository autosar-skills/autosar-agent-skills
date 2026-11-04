# DBC 语法要点（审计视角）

只记录**做解析器时必须知道**的部分，不重复 DBC 规范全文。

## 哪些语句以分号结尾，哪些以换行结尾

这是写解析器第一个坑。

| 语句 | 终止方式 |
|---|---|
| `VERSION "..."` | 换行 |
| `NS_ :` 及其下条目 | 换行 |
| `BS_:` | 换行 |
| `BU_: NodeA NodeB` | 换行 |
| `BO_ <id> <name>: <dlc> <tx>` | 换行 |
| ` SG_ ...` | 换行 |
| **其他所有**（`CM_` `BA_` `VAL_` `VAL_TABLE_` `SIG_VALTYPE_` …） | **分号** |

`BO_` 后面紧跟的 `SG_` 行属于该报文，直到下一个 `BO_` 或非 `SG_` 语句出现。

## 分号可能出现在引号里

```dbc
CM_ SG_ 466 Sig "sent when `ready`;\r\nretry after 3s";
```

按行扫描找 `;` 会在此处误切。必须维护「是否在字符串内」的状态，并处理 `\"` 转义。

正确做法：逐字符扫描，遇到 `;` 且不在字符串内才切分。

## Motorola 位序

DBC 中 `@0` 是 Motorola（大端），`@1` 是 Intel（小端）。

**位编号约定**：bit 0 是 byte 0 的最低位（LSB）。但 **Motorola 信号的起始位是 MSB**。

字节内位序（从高到低）：

```
byte 0:  7  6  5  4  3  2  1  0
byte 1: 15 14 13 12 11 10  9  8
byte 2: 23 22 21 20 19 18 17 16
```

Motorola 信号从起始位开始，**按此顺序递减**，跨越字节边界时跳到下一个字节的最高位：

```
next(pos) = pos + 15  if pos % 8 == 0
          = pos - 1    otherwise
```

例：`start=7, length=16` → 7,6,5,4,3,2,1,0,15,14,13,12,11,10,9,8，即 byte0 整个字节 + byte1 整个字节，高位在前。

Intel 信号则从起始位开始**递增**（起始位是 LSB）。

⚠️ 一个常见误解：以为 Motorola 的起始位就是「最低位」。不是。起始位是 **MSB**，所以 `start=7|8` 表示 byte0 的全部 8 位，而不是从 bit 7 向上数的 8 位。

## 报文 ID 与扩展帧

DBC 用 **bit 31 标记扩展帧**：

```
raw = 0x18DAF110 | 0x80000000   扩展帧
raw = 0x1D2                     标准帧
```

解析时应做 `frame_id = raw & 0x1FFFFFFF`，`is_extended = bool(raw & 0x80000000)`。

## 属性系统

三层：

```dbc
BA_DEF_ BO_ "GenMsgCycleTime" INT 0 10000;     定义（对象类型 + 名称 + 类型 + 范围）
BA_DEF_DEF_ "GenMsgCycleTime" 0;               默认值
BA_ "GenMsgCycleTime" BO_ 466 20;              赋值
```

对象类型可以省略（表示网络级属性）：`BA_DEF_ "DBName" STRING ;`

**ENUM 赋值应当用带引号的标签**：

```dbc
BA_ "GenMsgSendType" BO_ 466 "Event";    正确
BA_ "GenMsgSendType" BO_ 466 1;          可被 Vector 容忍，严格解析器拒绝
```

## 值表

```dbc
VAL_ 466 Work_Mode 0 "Init" 1 "Idle" 2 "Active" 15 "Invalid" ;
```

键是**原始值（raw）**，不是物理值。若信号有 `factor`/`offset`，解码时要先取 raw 再查表 —— 不能用物理值查。

本工具在 `Signal.display()` 里对物理值 `round()` 后查表，适用于 `factor=1, offset=0` 的常见枚举；若枚举带缩放，查表应基于 raw。

## 复用信号（multiplexed）

```dbc
 SG_ MuxSwitch M : 0|8@1+ (1,0) [0|255] "" Vector__XXX
 SG_ SignalA m0 : 8|8@1+ (1,0) [0|255] "" Vector__XXX
 SG_ SignalB m1 : 8|8@1+ (1,0) [0|255] "" Vector__XXX
```

`M` 是复用器，`m<N>` 表示「当复用器值 = N 时有效」。这些信号**故意**共用同一批位，因此位重叠检查必须感知 mux，否则误报。

当前 `dbc_analyze.py` **未实现 mux 感知**，遇到复用信号会报 `BIT-001`。这是已知局限，`checks.md` 中有说明。

## 注释可以有多行

```dbc
CM_ BO_ 466 "first line
second line";
```

字符串内可含换行，切分器必须跨越行边界保持字符串状态。

## 常见厂商偏差

真实文件里经常见到：

- ENUM 属性全部写成数字（Vector 容忍）
- `GenSigASIL` 批量填同一个值，不是真实安全分析结果
- 左右两侧一侧多几个信号（功能差异或漏写）
- `AFSFctst` 与 `AFSFctSt` 这类大小写漂移
- 中文注释用 GBK
- `BU_` 只声明了本 ECU，上游节点全用 `Vector__XXX`

前五条分别对应 `ENU-001` / `SYM-001` / `TYP-001` / `ENC-001` / `NOD-001`。
