# autosar-agent-skills

![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)
![dependencies: none](https://img.shields.io/badge/dependencies-none-brightgreen)
![license: MIT](https://img.shields.io/badge/license-MIT-green)
![checks: 11 + 26](https://img.shields.io/badge/checks-11%20%2B%2026-orange)
![tests: 65](https://img.shields.io/badge/tests-65-blueviolet)
[![PyPI](https://img.shields.io/pypi/v/dbc-matrix-audit.svg)](https://pypi.org/project/dbc-matrix-audit/)

[English](README.en.md) | 中文

AUTOSAR 相关 Agent Skill 合集。每个 skill 自包含、可直接被 AI Agent 加载，也可以当独立命令行工具用。

面向真实工程问题：这些工具解决的问题都是「编译期不报错、联调时才发现」的那一类。

```
DBC 文件 ──► 解析（纯标准库）──► 11 类结构检查 ──► 报告
                                    │
                                    ├─ ENC/BIT/RNG/DLC   error（必崩）
                                    ├─ ENU/SYM/TYP/DUP   warn（会漂）
                                    └─ STA/NOD/VAL       info（该看一眼）

ARXML 配置 ──┐
             ├──► 按 CAN ID 绑定 ──► 26 个交叉校验码 ──► 报告
DBC 文件 ────┘        │
                      └─ 位几何（LSB↔MSB 换算）· DLC · 字节序
                         初始值 · PduR 路由 · 收发方向
```

> 设计取舍与踩坑记录：
> [如何为 AI Agent 设计一个工程级 Skill](https://me.tech-harry.top/blog/dbc-matrix-audit-skill.html) ·
> [105 个错误，99 个是假的](https://me.tech-harry.top/blog/arxml-dbc-consistency.html)

## Skills

| Skill | 说明 | 依赖 |
|---|---|---|
| [dbc-matrix-audit](skills/dbc-matrix-audit/) | DBC 通信矩阵审计：位域重叠、越界、左右不对称、命名漂移、GBK 编码 | **无** |
| [arxml-dbc-consistency](skills/arxml-dbc-consistency/) | ARXML 通信栈 × DBC 交叉校验：绑定、DLC、位几何、字节序、初始值、PduR 路由、收发方向 | **无** |
| [cdd-arxml-consistency](skills/cdd-arxml-consistency/) | CDD 诊断规范 × ARXML 诊断配置交叉校验：DID、DTC、例程、诊断 CAN 地址、会话、安全访问、P2/S3/STmin | **无** |

已上架 Agensi 市场：**[DBC Matrix Audit](https://www.agensi.io/skills/dbc-matrix-audit)**（免费，已上线）。
上架用的英文包由 `tools/pack_marketplace.py` 从本仓库生成；同样的输入重复构建字节一致。

> 注意：`LISTING.md` 记录的是**提交当时**那个 zip 的 sha256。之后若改动了该 skill 的正文
> （例如 `8b27f44` 修了示例 README），重新构建的 sha 会不同 —— 这是内容变了，不是打包不可复现。
> 需要核对时，先在对应 commit 上构建再比 sha。

## dbc-matrix-audit

DBC 通信矩阵的静态审计器。11 类结构检查 + **两版差异对比** + 实帧解码 + CSV 导出，**纯标准库**。

```bash
python skills/dbc-matrix-audit/scripts/dbc_analyze.py info     matrix.dbc
python skills/dbc-matrix-audit/scripts/dbc_analyze.py messages matrix.dbc
python skills/dbc-matrix-audit/scripts/dbc_analyze.py lint     matrix.dbc
python skills/dbc-matrix-audit/scripts/dbc_analyze.py decode   matrix.dbc 0x1D2 1234052a00000000
python skills/dbc-matrix-audit/scripts/dbc_analyze.py export   matrix.dbc --csv inventory.csv
python skills/dbc-matrix-audit/scripts/dbc_analyze.py diff     old.dbc new.dbc
```

### 检查项

| 代码 | 严重度 | 说明 |
|---|---|---|
| `ENC-001` | error | 文件不是 UTF-8（典型是 GBK 中文注释） |
| `BIT-001` | error | 同帧内两个信号占用同一位 |
| `RNG-001` | error | 信号超出报文长度 |
| `DLC-001` | error | 非法 DLC |
| `ENU-001` | warn | ENUM 属性被赋值为数字索引 |
| `SYM-001` | warn | 左右（L/R、A/B、FL/FR…）信号集不对称 |
| `TYP-001` | warn | 去掉侧别标识后，同一信号拼写不一致 |
| `DUP-001` | warn | 信号名跨报文重复 |
| `STA-001` | info | 大量信号未设 `GenSigStartValue` |
| `NOD-001` | info | 发送节点未在 `BU_` 中声明 |
| `VAL-001` | info | 短信号（≤4 bit）没有值表 |

### 版本对比（diff）

| 代码 | 严重度 | 说明 |
|---|---|---|
| `DIF-GEO` | error | 信号位定义变了 |
| `DIF-DLC` | error | 报文长度变了 |
| `DIF-REN` | error | 报文 / 信号 / 节点重命名 |
| `DIF-ID` | error | 同名报文换了 CAN ID |
| `DIF-CRC` | error | 校验和注释里的 DataID 变了 |
| `DIF-DEL` | warn | 报文或信号被删除 |
| `DIF-SCL` | warn | 系数 / 偏移变了 |
| `DIF-RNG` | warn | 最小值 / 最大值 / 单位变了 |
| `DIF-VAL` | warn | 值表变更 |
| `DIF-CYC` | warn | 周期变了 |
| `DIF-TX` | warn | 发送节点变了 |
| `DIF-TYP` | warn | 发送类型变了 |
| `DIF-ADD` | info | 新增报文或信号 |
| `DIF-CMT` | info | 仅注释变更 |

两个专门处理过的漏判场景：

- **同名报文换 ID**：只按 ID 比对会退化成「删一条 + 加一条」，真正原因被埋掉。工具先按名字配对并抑制那条误导性增删。
- **CRC DataID 变更**：藏在 `CM_` 注释里（`CRC16 checksum (DataID: 0x61D2)`），普通注释比对只当 `info`。工具正则提取，一变就报 `error` —— 接收方会拒收整帧。

信号重命名按**位定义**配对（名字正是变了的东西），所以 `Bus_Off_Count` → `Bus_Off_Cnt` 是 `DIF-REN` 而不是一删一加。

```bash
# 真实案例：NM 报文换 ID + CRC DataID 变更，两者都会导致整条链路失效
$ python skills/dbc-matrix-audit/scripts/dbc_analyze.py diff old.dbc new.dbc
[E] DIF-CRC  Node_Info_Checksum: checksum data id changed   (0x1D2)
      0x61D2 -> 0x41D2. Every receiver that validates this CRC will reject
      the frame until it is rebuilt with the new id.
[E] DIF-ID   NM_Autosar_ECU_R: CAN id changed   (0x457 -> 0x46B)
      Same name, different address: routing tables and filters still point
      at the old id.
```

规则判定细节与**误报场景**见 [references/checks.md](skills/dbc-matrix-audit/references/checks.md)。

### 为什么不用 cantools

cantools 是好库，但它解析时丢掉了审计最需要的东西：

| 数据 | cantools | 本工具 |
|---|---|---|
| 报文周期 `GenMsgCycleTime` | ✗ | ✓ |
| 值表 `VAL_` | 部分 | ✓ |
| 注释 `CM_` | ✗ | ✓ |
| 报文/信号属性 `BA_` | ✗ | ✓ |

而且 cantools 对 GBK 坏字节**静默容忍** —— 看起来解析成功，注释全丢。本工具会明确报 `ENC-001`。

### 示例

```bash
$ python skills/dbc-matrix-audit/scripts/dbc_analyze.py lint skills/dbc-matrix-audit/examples/demo.dbc
[I] STA-001  165/167 signals have no GenSigStartValue
      ...
summary: 0 error, 0 warn, 1 info

$ python skills/dbc-matrix-audit/scripts/dbc_analyze.py lint skills/dbc-matrix-audit/examples/demo_broken.dbc
[E] BIT-001  ACM_B_Supply_Voltage and ACM_B_Temperature occupy overlapping bits   (0x201 ACM_B_Status)
[E] DLC-001  illegal DLC 13   (0x500 Log_Snapshot)
[E] ENC-001  file is not valid UTF-8 (detected: gbk)
[E] RNG-001  Log_Word_4 extends past the frame length   (0x500 Log_Snapshot)
[W] DUP-001  signal name Node_Status_Counter appears in 2 frames
[W] ENU-001  1 ENUM attribute assignments use numeric indices
[W] SYM-001  ACM_A_Status / ACM_B_Status are not symmetric   (0x200 vs 0x201)
[W] TYP-001  same signal spelled differently (beyond the side token)
              ACM_X_Projection_State vs ACM_X_Projection_statE
summary: 4 error, 4 warn, 2 info
```

`skills/dbc-matrix-audit/examples/demo.dbc` 是干净的合成矩阵，`demo_broken.dbc` 埋了 10 类缺陷用于演示。两者都由 `tools/gen_demo_dbc.py` 生成，位分配由程序计算，结构上不可能重叠。

## arxml-dbc-consistency

AUTOSAR Classic ECU 配置（Com / PduR / CanIf / CanDrv 的 ECUC 容器）与 DBC 通信矩阵的交叉校验。
26 个检查码，**纯标准库**。

```bash
python skills/arxml-dbc-consistency/scripts/arxml_dbc_check.py probe      ecuconfig.xml
python skills/arxml-dbc-consistency/scripts/arxml_dbc_check.py check      ecuconfig.xml matrix.dbc
python skills/arxml-dbc-consistency/scripts/arxml_dbc_check.py matrix     ecuconfig.xml matrix.dbc --csv inventory.csv
python skills/arxml-dbc-consistency/scripts/arxml_dbc_check.py selftest
```

`probe` 先看结构（厂商的容器名、参数名、信号挂载位置差异极大），`check` 再比对。
`check` 有 error 时退出码 1，可直接接 CI。

### 为什么不能按名字匹配

真实配置里 Com 与 CanIf **不直连**，绑定主键只能是 CAN ID：

```
DBC 帧 ──CanId──> CanIf PDU ──CanIfXxxPduRef──> EcuC Pdu(X)
                        ──PduR 路由──> EcuC Pdu(COM_X)
                        ──ComPduIdRef──> Com IPdu
```

`IPDU_COM_TP_Param` 与 DBC 帧 `Diag_CalData` 名字毫无关系，
却是同一条链路（`COM_TP_Param → CanTp_TP_Param → 0x9B`）。按名字连必然全错。

### 位几何只有一个正确公式

AUTOSAR 的 `ComBitPosition` 存的始终是信号 **LSB**（平坦编号，bit0 = byte0 的 LSB），
**与字节序无关**。DBC 对大端用锯齿编号且起始位写 **MSB**，所以先回退 `len-1` 步：

```python
def motorola_msb_from_lsb(lsb, length):
    pos = lsb
    for _ in range(length - 1):
        pos = pos - 15 if pos % 8 == 7 else pos + 1
    return pos
```

真实工程实测 **215/215** 信号命中。早期版本假设「MSB / LSB 两派并存」，做成两种都试、
任一命中即通过 —— 这个设计是错的：真错误会被巧合命中洗白，且实测只有 153/215。

### 整网矩阵 ≠ 单 ECU 视角

一份 DBC 可能只描述本 ECU（十几帧），也可能是整张网络（几十上百帧、`BU_:` 一堆别的节点）。
后者里绝大多数帧是别人发给第三方的，**本 ECU 不该有配置**。脚本按「发送方是本 ECU、
或某信号的接收方含本 ECU」逐帧判定，只对相关帧判 error。

一个 11 节点 91 帧的矩阵上，原来「每帧都必须配」的假设造出 **99 条假 error**，
把 6 条真缺陷全埋了。

### 总线覆盖率

ARXML 常同时管多条 CAN。脚本按 `CanIfBufferCfg → CanIfHthCfg → CanIfHthCanCtrlIdRef`
回溯总线，算每条总线在 DBC 里的命中率：≥20% 正常比对，<20% 整体跳过并出 info。
`check` 头部直接打出来，汇报时必须原样转述：

```
总线    CANIF_CTR_BCAN 16/21 比对 | CANIF_CTR_PCAN 0/32 跳过
```

### 文档

- 中文：`skills/arxml-dbc-consistency/references/checks.md`
- English: `skills/arxml-dbc-consistency/references/checks.en.md`
- 英文 SKILL.md（市场包用）：`packaging/agensi/arxml-dbc-consistency/SKILL.md`

## cdd-arxml-consistency

诊断链路的交叉校验：**CANdelaStudio 的 CDD（诊断仪照着实现的规范）** 对
**ARXML 里的 Dcm / Dem / CanIf / CanTp（ECU 实际运行的配置）**。
25 个检查码，纯标准库，只读。

```bash
python skills/cdd-arxml-consistency/scripts/cdd_arxml_check.py probe  ecu.cdd ecuconfig.xml
python skills/cdd-arxml-consistency/scripts/cdd_arxml_check.py check  ecu.cdd ecuconfig.xml
python skills/cdd-arxml-consistency/scripts/cdd_arxml_check.py check  ecu.cdd ecuconfig.xml --json
python skills/cdd-arxml-consistency/scripts/cdd_arxml_check.py matrix ecu.cdd ecuconfig.xml -o inv.csv
python skills/cdd-arxml-consistency/scripts/cdd_arxml_check.py selftest
```

退出码 `0` 无 error / `1` 有 error / `2` 参数或文件错误，可直接进 CI。

### 和普通 diff 的区别：它会指方向

发现 CAN ID 不一致时**不猜哪边错**，而是查 `Can/CanConfigSet/CanHwFilter` 的
`Code` + `Mask` 做位运算裁决：

```
匹配条件：(frame_id & mask) == (code & mask)
```

实测一例：CDD 写 `0x738`、CanIf 写 `0x72F`，51 个滤波器里只有 `0x738`（mask `0x7FE`）
能过 —— 芯片不会把 `0x72F` 的帧交给上层，所以**错的是 CanIf**，改哪一边是确定的。
同时 CanTp 的 `N_SA/N_TA = 56 (0x38)` 正好是 `0x738` 的低字节，是第二条独立证据。

### 没配 ≠ 没问题

CDD 里的诊断地址有两处来源：`<ECU>` 下的属性**实例**（本 ECU 配置），
和 `DEFATTS/ECUATTS` 下的属性**定义**（CANdelaStudio 模板默认值）。
模板另存后没填 CAN 页时只有后者，此时读不到任何地址。

早期版本会让 8 个检查各自 `continue` —— 报告里完全不提 CAN ID，
和「CAN ID 检查通过」在输出上一模一样。现在 `CDX-013` / `CDX-025`
把缺口本身报出来，并把 DEFATTS 的值明确标注为**模板值**而非配置值。
拿 `0x700` 导 ODX，诊断仪就按 `0x700` 发请求。

### 查不出来的（工具自己会说）

DID 的数据长度与结构、服务-会话-安全的依赖矩阵、NRC 的使用范围、
安全算法、快照记录字段、N_SA/N_TA 与 CDD 地址方案的逐项核对 —— 都不覆盖。
`SKILL.md` 的 Step 4 要求每次报告都把这些写出来，否则「25 项通过」
会被当成「诊断全对」。

### 文档

- 中文：`skills/cdd-arxml-consistency/references/checks.md`
- English: `skills/cdd-arxml-consistency/references/checks.en.md`
- 英文 SKILL.md（市场包用）：`packaging/agensi/cdd-arxml-consistency/SKILL.md`

## 文档站

带完整结构化标记的文档页：https://autosar-skills.github.io/autosar-agent-skills/

## 安装

```bash
git clone https://github.com/autosar-skills/autosar-agent-skills.git
cd autosar-agent-skills
python -m unittest discover -s tests      # 65 个测试，纯标准库
```

不需要 `pip install`，克隆下来就能跑。想把短命令装进 PATH：

```bash
pip install dbc-matrix-audit          # https://pypi.org/project/dbc-matrix-audit/
dbc-analyze lint matrix.dbc                  # DBC 审计
arxml-dbc-check check cfg.arxml matrix.dbc   # ARXML × DBC 交叉校验
```

> 说明：`dbc-analyze` 的输出与帮助为英文；`arxml-dbc-check` 目前输出中文，
> 检查语义一致，但尚未提供英文文案。

## 作为 Agent Skill 使用

`skills/<name>/SKILL.md` 遵循通用 AgentSkill 格式。把整个 `skills/<name>/` 目录放到 agent 的 skill 路径下即可，脚本通过相对路径 `scripts/dbc_analyze.py` 调用。

SKILL.md 是**给 agent 执行的运行手册**（模式判定 → 执行顺序 → 输出解读），不是给人读的说明文档；
本 README 才是给人看的。两者分工：

| 位置 | 读者 | 内容 |
|---|---|---|
| `README.md` | 人 | 为什么这么设计、规则含义、示例输出 |
| `SKILL.md` | agent | Step 0–4 执行流程、命令、汇报格式 |
| `references/checks.md` | 按需加载 | 每条规则的判定细节与误报场景 |

OpenClaw 用户：

```bash
openclaw skills install skills/dbc-matrix-audit          # 首次安装
openclaw skills install --force skills/dbc-matrix-audit  # 仓库更新后重新同步
openclaw skills info dbc-matrix-audit                    # 确认 Ready
```

安装会复制一份到 `~/.openclaw/workspace/skills/`，因此**仓库更新后需要重新执行一次 `--force`**
才会同步过去。

## 目录结构

```
skills/dbc-matrix-audit/
├── SKILL.md                  agent 执行手册（中文，模式判定 / 流程 / 汇报格式）
├── scripts/dbc_analyze.py    核心实现（单文件，标准库）
├── examples/                 合成示例（干净 / 埋坑），随 skill 一起分发
└── references/               规则细节、编码问题、DBC 语法笔记
skills/arxml-dbc-consistency/
├── SKILL.md                  中英双语执行手册（模式判定 / 流程 / 汇报格式）
├── README.md                 英文说明（仓库与市场共用）
├── scripts/arxml_dbc_check.py 核心实现（单文件，标准库）
├── scripts/demo_fixtures.py  程序生成的示例（拓扑必须与真实工程一致）
├── scripts/test_contract.py  文档码 ↔ 代码实现 双向断言（中英双语都算）
└── references/               checks.md（中）/ checks.en.md（英）
skills/cdd-arxml-consistency/
├── SKILL.md                  执行手册（Step 0 模式判定 / 执行 / 汇报 / 查不出来的）
├── README.md                 英文说明（仓库与市场共用）
├── scripts/cdd_arxml_check.py 核心实现（单文件，标准库）
├── scripts/demo_fixtures.py  2 组 fixture（配好的 / CAN 页未填的）
├── scripts/test_contract.py  文档码 ↔ 代码实现 双向断言
└── references/               checks.md（中）/ checks.en.md（英）
tools/gen_demo_dbc.py         示例生成器
tools/pack_marketplace.py     市场打包器（可复现，带结构校验）
tests/                        65 个单元测试（含 diff 专项）
packaging/agensi/             上架物料：英文 SKILL.md / README 覆盖层、文案存档、logo
CHANGELOG.md                  版本变更记录
dist/                         构建产物（gitignored，用上面两个脚本重新生成）
```

### 市场打包

```bash
python3 tools/pack_marketplace.py                              # → dist/agensi/dbc-matrix-audit.zip
python3 tools/pack_marketplace.py --skill arxml-dbc-consistency  # → dist/agensi/arxml-dbc-consistency.zip
python3 tools/pack_marketplace.py --skill cdd-arxml-consistency   # → dist/agensi/cdd-arxml-consistency.zip
python3 tools/pack_marketplace.py --check                        # 只校验不落盘
```

`packaging/<market>/<skill>/` 里的 `SKILL.md` / `README.md` 会覆盖仓库中的中文版，其余文件从
`skills/<name>/` 取。扁平布局 `packaging/<market>/` 仍支持（老 skill 用），
此时只读它的顶层文件，避免把同层的别的 skill 覆盖层打进包。打包器剔除 `__pycache__`、二进制、隐藏文件和软链，并校验
「单一顶层文件夹 + SKILL.md 在其根 + 必须有 README」，不满足直接失败。
条目排序 + 固定时间戳，重复构建字节一致。

## 许可

MIT。示例 DBC 均为虚构，不含任何真实车型、供应商或人员信息。
