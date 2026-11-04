# autosar-agent-skills

AUTOSAR 相关 Agent Skill 合集。每个 skill 自包含、可直接被 AI Agent 加载，也可以当独立命令行工具用。

面向真实工程问题：这些工具解决的问题都是「编译期不报错、联调时才发现」的那一类。

## Skills

| Skill | 说明 | 依赖 |
|---|---|---|
| [dbc-matrix-audit](skills/dbc-matrix-audit/) | DBC 通信矩阵审计：位域重叠、越界、左右不对称、命名漂移、GBK 编码 | **无** |

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
[E] DIF-CRC  VIU_Info_Checksum: checksum data id changed   (0x1D2)
      0x61D2 -> 0x41D2. Every receiver that validates this CRC will reject
      the frame until it is rebuilt with the new id.
[E] DIF-ID   NM_Autosar_FLM_R: CAN id changed   (0x457 -> 0x46B)
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

## 安装

```bash
git clone https://github.com/ZhaoBoxiong/autosar-agent-skills.git
cd autosar-agent-skills
python -m unittest discover -s tests      # 61 个测试，纯标准库
```

不需要 `pip install`。要用 `dbc-analyze` 这个短命令时：

```bash
pip install -e .
```

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
├── SKILL.md                  agent 执行手册（模式判定 / 流程 / 汇报格式）
├── scripts/dbc_analyze.py    核心实现（单文件，标准库）
├── examples/                 合成示例（干净 / 埋坑），随 skill 一起分发
└── references/               规则细节、编码问题、DBC 语法笔记
tools/gen_demo_dbc.py         示例生成器
tests/                        61 个单元测试（含 diff 专项）
CHANGELOG.md                  版本变更记录
```

## 许可

MIT。示例 DBC 均为虚构，不含任何真实车型、供应商或人员信息。
