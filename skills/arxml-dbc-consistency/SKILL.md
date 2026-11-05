---
name: arxml-dbc-consistency
description: |
  校验 AUTOSAR 通信栈 ARXML 与 DBC 是否对得上。触发：arxml 校验、arxml 和 dbc 对不上、通信栈配置检查、Com/PduR/CanIf/CanDrv 配置核对、这个 arxml 配得对不对、ECU 配置和矩阵一致性、信号收不到、报文发不出去、联调对不上、导入 dbc 后没信号、某厂商标 A arxml 检查、vector arxml 检查。
  Cross-check AUTOSAR Classic ECU configuration ARXML (Com, PduR, CanIf, CanDrv ECUC containers) against a DBC communication matrix: CAN ID binding, DLC, bit geometry, byte order, signedness, init value, cycle time, PduR routing, and PDU direction.
homepage: https://me.tech-harry.top/blog/arxml-dbc-consistency.html
license: MIT
metadata:
  version: 1.1.2
  author: autosar-agent-skills
  tags: [autosar, can, dbc, arxml, ecuc, com, pdur, canif, consistency]
---

# ARXML ↔ DBC 一致性校验

零依赖，纯标准库。全部子命令走同一个脚本：

```bash
python3 <skill>/scripts/arxml_dbc_check.py <subcommand> ...
```

`<skill>` 是本文件所在目录。

## Step 0 — 判定模式

按用户原话直接选，**不要反问**。

| 用户提到 | 跑 |
|---|---|
| 这个 arxml 里有什么、结构怎样、能解析吗、第一次见这个文件 | `probe` |
| 校验、检查、对不上、一致吗、配得对不对、给个报告 | `check` |
| 台账、对照表、导出、发给供应商、Excel | `matrix` |
| 已经报了 `AXD-000`、或抽不出 Com IPdu | 回 `probe`，按 Step 2 处理 |

**拿到一份全新的 ARXML，永远先跑 `probe`**，不要直接 `check`。厂商的容器名、参数名、信号挂载位置差异极大，没 probe 就 check 拿到的「0 帧 0 信号」是解析失败，不是配置为空。

## Step 1 — 确认输入

需要两个文件：ARXML（ECUC 配置，不是系统描述）+ DBC。

```bash
file <arxml> <dbc>
```

- ARXML 里应能搜到 `ECUC-MODULE-CONFIGURATION-VALUES`。搜不到说明给的是**系统描述 ARXML**（只有 `CAN-CLUSTER` / `FRAME`），这类文件不含 Com/PduR/CanIf 配置，直接告诉用户「这份不是 ECU 配置」再要一份。
- DBC 是 GBK 时不用转码，脚本内部按多编码读。

## Step 2 — probe

```bash
python3 <skill>/scripts/arxml_dbc_check.py probe <arxml>
```

看三样东西：

1. **modules** —— 应包含 `Com` `PduR` `CanIf` `Can`。缺哪个就说明这份 ARXML 不完整，后面那层的检查会自动跳过并写进 notes。
2. **各层抽取结果** —— `Com IPdu 0` 或 `信号 0` 就是没抽出来。
3. **notes** —— 脚本已经写明猜不到的地方。**`notes` 为空是正常且理想的结果**（说明每一层都干净抽出来了），不是输出被吞了。

抽不出来时按这个顺序查，不要瞎改脚本：

```bash
# 看实际用了哪些容器类型
python3 <skill>/scripts/arxml_dbc_check.py probe <arxml> --json | python3 -m json.tool | head -60
# 看厂商给参数起的名字
grep -o '<DEFINITION-REF[^>]*>[^<]*</DEFINITION-REF>' <arxml> | sed 's/.*\///;s/<.*//' | sort -u | head -40
```

常见差异：
- 信号挂在 `ISignalToIPduMapping`（AUTOSAR 4.x 标准）还是 `ComSignal`（较老 / EB 风格）。两种都支持。
- 几何参数叫 `START-POSITION` 还是 `ComBitPosition`。两种都支持。
- 长度叫 `ComIPduSize` / `ComIPduLength` / 从 `CanIfTxPduDlc` 推。都支持。

三种都不中时，把 `grep` 输出贴给用户确认，不要自己猜字段名。

## Step 3 — check

```bash
# 先不指定节点，脚本会自动推断本配置覆盖哪些 DBC 节点
python3 <skill>/scripts/arxml_dbc_check.py check <arxml> <dbc>

# 明确指定（需要强制单节点时才用）
python3 <skill>/scripts/arxml_dbc_check.py check <arxml> <dbc> --node <节点名>
```

节点名从 DBC 的 `BU_:` 行取。**先不带 `--node` 跑一遍**：一个 MCU 可能同时管左右两路
（如 `ECU_L` + `ECU_R`），脚本会自动识别成多节点模式；强指定单节点会把对侧帧误判成方向错。

### 先分清：整网矩阵 还是 单 ECU 视角

两种 DBC 的判据完全不同，脚本自动区分：

| DBC 形态 | 特征 | 判定 |
|---|---|---|
| 单 ECU 视角 | 帧数少（约十几~几十），`BU_:` 里的节点基本就是本 ECU | DBC 每帧都该在本 ECU 有配置，缺了就报 `AXD-001`/`AXD-006` |
| 整网矩阵 | 帧数多（几十~几百），`BU_:` 有一堆别的节点 | **只对本 ECU 该发/该收的帧判 error**，其余直接跳过 |

「本 ECU 是否参与」的判据：帧的 `tx_node` 是本 ECU，或该帧任一信号的接收方列表含本 ECU
（DBC 里接收方写在 `SG_` 行末尾，逗号分隔）。

**不要因为整网矩阵报了上百条 error 就认为是配置烂** —— 先看脚本有没有识别出本 ECU 节点。
识别不出来（`ECU 节点 (未识别)`）时会退化成「每帧都查」，那才会满屏假 error，
此时用 `--node` 指定。

### 多总线：先看总线覆盖率

一份 ARXML 常同时管多条 CAN（如 `PCAN` 私有 + `BCAN` 车身）。脚本按
`CanIfBufferCfg → CanIfHthCfg → CanIfHthCanCtrlIdRef` 回溯每个 PDU 的总线归属，
算每条总线在 DBC 里的命中率：

- 命中率 **≥ 20%**：这条总线在 DBC 覆盖内，正常比对
- 命中率 **< 20%**：判定本 DBC 不含这条网络，该总线整体跳过，只出 `AXD-026` info

`check` 的头部会直接打出这行，汇报时**原样转述**：

```
总线    CANIF_CTR_BCAN 16/21 比对 | CANIF_CTR_PCAN 0/32 跳过
```

`--json` 里的 `bus_coverage` 是 `{总线: {hit, total, in_scope}}`。

**必须说明哪条总线被跳过了**，并提示用户补对应 DBC。否则用户会以为检查覆盖了全部总线。

有 error 时退出码 1，可直接接 CI。`--no-fail` 强制 0，`--json` 出结构化结果。

## Step 4 — 汇报

**固定三段**：

1. **结论** —— 几个 error、能不能上电联调。已识别的 ECU 节点要说出来；没识别到要明说「方向校验已跳过」。
2. **证据** —— 按 error → warn → info 顺序贴原文。同一检查码下超过 5 条的合并成一句（「38 条信号缺失，集中在 DLP 投影功能」），不要逐条念。
3. **待确认** —— 工具查不出、必须人工看的（见 Step 5）。

**error 必须翻译成现象**，不要只报代码：

| 码 | 说成人话 |
|---|---|
| `AXD-001` | 这帧配了矩阵但通信栈里没有，收发双方都不认 |
| `AXD-005` | 长度对不上，整帧会被拒 |
| `AXD-008` | 值解到了错的位，数值全错但不报错 |
| `AXD-009` | 大端小端搞反，数值错乱 |
| `AXD-015` | Com 和下层断路，数据不流转 |
| `AXD-018` | 两个信号抢同一位，值永远错 |
| `AXD-011` | 上电到第一次收发之间，双方看到的值不一样（以 DBC 为准） |
| `AXD-022` | 收发方向配反，报文进不了正确缓冲 |

判定口径：**凡是会导致联调时现象异常、但编译期不报错的，都按 error 报。**

## Step 5 — 工具查不出来的（必须人工核对）

- **SignalGroup / 复合信号** —— DBC 的 `SIG_GROUP_` 与 Com 的 `ComSignalGroup` 不做交叉校验
- **多路复用（multiplexed）** —— 含 mux 的矩阵可能误报 `AXD-018`，需人工确认位重叠是否只在同一 mux 分支内
- **CRC / rolling counter** —— 只检查信号存在性，不校验算法与 DataID
- **Com 的 UpdateBit / Timeout 配置** —— 不与 DBC 对照
- **SecOC / E2E** —— 完全未覆盖
- **跨 PDU 的信号打包（TP 分段）** —— 只按单帧 DLC 比，TP 帧需人工看

## Step 6 — 导出

```bash
python3 <skill>/scripts/arxml_dbc_check.py matrix <arxml> <dbc> --node <node> --csv inventory.csv
```

用户说「发给供应商」「做个对照表」时用这个。

`status` 列取值：

| 值 | 含义 |
|---|---|
| `OK` | 名称与位几何全对上 |
| `名字漂移` | 忽略大小写/下划线后一致，已归一比对 |
| `几何不同` | 起始位或占用位集合不一致 |
| `位宽不同` | 信号长度不一致 |
| `字节序不同` | 大端/小端不一致 |
| `只有DBC` | DBC 有、Com 没配 —— 真缺失 |
| `只有ARXML` | Com 有、DBC 没定义 —— 真多余 |
| `E2E信号未配` | Checksum / RollingCounter，由 E2E 库写入，不算差异 |
| `整帧字节数组` | Com 用 1 个 OPAQUE 信号覆盖全帧，与 DBC 拆分建模等价 |
| `不比对` | NM / 诊断 / TP 链路，或不在此 DBC 覆盖的总线上 |

只有前七种需要人工处理，后三种属正常建模差异。

## 自检

改过脚本、或怀疑环境有问题时：

```bash
python3 <skill>/scripts/arxml_dbc_check.py selftest      # 内置示例，期望 13 error / 2 warn / 1 info
# 自检同时断言「码集合」和「条数」；改过 demo 后这两个数字都要同步更新，否则自检会红（刻意如此）
python3 <skill>/scripts/test_contract.py                  # 文档检查码 ↔ 代码实现 一致性
```

## 检查码

**error**：`AXD-001` `AXD-003` `AXD-004` `AXD-005` `AXD-006` `AXD-008` `AXD-009` `AXD-010` `AXD-011` `AXD-014` `AXD-015` `AXD-016` `AXD-017` `AXD-018` `AXD-022` `AXD-023` `AXD-025`

**warn**：`AXD-000` `AXD-002` `AXD-007` `AXD-012` `AXD-019` `AXD-020`

**info**：`AXD-021` `AXD-024` `AXD-026`

位几何换算、匹配策略、总线覆盖率、已知局限 → `references/checks.md`（中文）/ `references/checks.en.md`（English）

## 退出码

`0` 无 error ｜ `1` 存在 error ｜ `2` 参数或文件问题

## 局限

- 只读，不改任何文件
- 只处理 AUTOSAR 4.x ECUC；3.x 部分兼容
- 不解 `.xdm` / `.ldf` / `.kcd`
- DBC 侧静态缺陷不查 —— 那是 `dbc-matrix-audit` 的活，两者可串联使用

---

# English

Everything below is the same tool and the same check codes; only the language differs.
Full rules in English: `references/checks.en.md`.

## Step 0 — Pick the subcommand

Do **not** ask which one; decide from what the user said.

| User says | Run |
|---|---|
| what is in this arxml / can it be parsed / first time seeing this file | `probe` |
| check / validate / does it match / is this configured right / give me a report | `check` |
| inventory / cross-reference table / send to supplier / Excel | `matrix` |
| already got `AXD-000`, or zero Com IPdus extracted | go back to `probe` |

**Always `probe` a new ARXML before `check`.** Vendors differ wildly in container names,
parameter names, and where signals hang. "0 frames / 0 signals" from a blind `check`
means parsing failed, not that the config is empty.

## Step 1 — probe

```bash
python3 <skill>/scripts/arxml_dbc_check.py probe <arxml>
```

Check three things: `modules` should contain `Com` `PduR` `CanIf` `Can`; the per-layer
counts must be non-zero; `notes` lists anything the script had to guess.
Empty `notes` is the good outcome, not swallowed output.

If nothing is extracted, inspect what the vendor actually used — do not guess field names:

```bash
python3 <skill>/scripts/arxml_dbc_check.py probe <arxml> --json | python3 -m json.tool | head -60
grep -o '<DEFINITION-REF[^>]*>[^<]*</DEFINITION-REF>' <arxml> | sed 's/.*\///;s/<.*//' | sort -u | head -40
```

## Step 2 — check

```bash
python3 <skill>/scripts/arxml_dbc_check.py check <arxml> <dbc>            # auto-detect ECU node(s)
python3 <skill>/scripts/arxml_dbc_check.py check <arxml> <dbc> --node X   # force a node
```

Run **without** `--node` first. One MCU often covers both sides (`ECU_L` + `ECU_R`);
forcing a single node makes the opposite side look like a direction error.

Two DBC shapes behave differently, and the script tells them apart automatically:

| DBC shape | Detection | Behaviour |
|---|---|---|
| Single-ECU view | few frames, `BU_:` lists mostly this ECU | every frame must be configured, else `AXD-001` / `AXD-006` |
| Whole-network matrix | many frames, `BU_:` lists many foreign nodes | only frames this ECU sends or receives are judged |

"This ECU is involved" = the frame's `tx_node` is this ECU, **or** any signal's receiver
list contains this ECU (receivers are the comma-separated tail of an `SG_` line).

So a whole-network matrix producing hundreds of errors is usually **not** a broken config —
check whether the ECU node was detected first. If you see `ECU 节点 (未识别)`, pass `--node`.

### Bus coverage

One ARXML often drives several CAN buses. For each bus the script reports how many of its
PDUs hit the DBC: `>= 20%` is compared normally, `< 20%` is skipped with `AXD-026` info only.
The header prints it verbatim — quote it in your report, and name the skipped bus:

```
总线    CANIF_CTR_BCAN 16/21 比对 | CANIF_CTR_PCAN 0/32 跳过
```

In `--json` this is `bus_coverage: {bus: {hit, total, in_scope}}`.

Exit codes: `0` no error, `1` errors found (CI-ready), `2` bad arguments or unreadable file.
`--no-fail` forces 0; `--json` emits structured output.

## Step 3 — Report

Fixed three parts: **verdict** (error count, ship-or-not, which ECU nodes were detected);
**evidence** (errors → warns → infos, collapse runs over 5 into one line);
**needs a human** (the Step 4 list).

Translate codes into symptoms — never report a bare code:

| Code | Say this |
|---|---|
| `AXD-001` | frame exists in the matrix but not in the stack — neither side will ever see it |
| `AXD-005` | length disagreement, the whole frame gets rejected |
| `AXD-008` | value is decoded from the wrong bits — wrong numbers, no error at runtime |
| `AXD-009` | endianness flipped, values scrambled |
| `AXD-011` | sender and receiver see different values until the first update (DBC wins) |
| `AXD-015` | Com is not connected to the layers below, nothing flows |
| `AXD-018` | two signals claim the same bits, one of them is always wrong |
| `AXD-022` | TX/RX swapped, the frame never reaches the right buffer |

Rule of thumb: **anything that breaks bench testing but passes compilation is an error.**

## Step 4 — What the tool cannot check

SignalGroups, multiplexed frames (may false-positive `AXD-018`), CRC/rolling-counter
algorithms and DataIDs, Com UpdateBit/Timeout, SecOC/E2E, TP segmentation.

## Step 5 — Inventory

```bash
python3 <skill>/scripts/arxml_dbc_check.py matrix <arxml> <dbc> --csv inventory.csv
```

`status` values: `OK`, `名字漂移` (name drift, already normalised), `几何不同`, `位宽不同`,
`字节序不同`, `只有DBC` (missing in Com), `只有ARXML` (extra in Com),
`E2E信号未配` (checksum/counter, written by the E2E library),
`整帧字节数组` (one OPAQUE signal covering the frame — equivalent modelling),
`不比对` (NM / diagnostic / TP, or a bus outside this DBC).

Only the first seven need action.

## Step 6 — Self-test

```bash
python3 <skill>/scripts/arxml_dbc_check.py selftest     # expect 13 error / 2 warn / 1 info
python3 <skill>/scripts/test_contract.py                # documented codes <-> implemented codes
```

`selftest` asserts both the code set **and** the counts; update both when you change the demo.

