# Changelog

所有值得注意的变更都记录在此文件。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [1.3.0] — 2026-11-04

### 修复

**在隔离环境实测时发现的三个问题。** 此前只在本机 workspace 里装过，
而本机恰好有仓库在旁边，掩盖了下面第 1 条。

#### 1. `examples/` 没有随 skill 分发，SKILL.md 引用的是死路径

`examples/` 原本在仓库根目录，`openclaw skills install` 只复制 `skills/<name>/`，
所以安装后的 skill 里没有示例，而 SKILL.md 的「示例」段仍然写着 `examples/demo.dbc`。
agent 照抄会 `No such file`。

现已移入 `skills/dbc-matrix-audit/examples/`，skill 自包含。同步更新了
`tools/gen_demo_dbc.py` 的输出路径、CI 全部路径、测试里的 `EXAMPLES` / `DEMO` 常量。

顺带让 agent 能用它**自检环境**：

```bash
python3 <skill>/scripts/dbc_analyze.py lint <skill>/examples/demo.dbc         # 0 error 0 warn
python3 <skill>/scripts/dbc_analyze.py lint <skill>/examples/demo_broken.dbc # 10 类缺陷全报
```

#### 2. 转码后报「0 error」，把真实的 `ENC-001` 吞掉了

实测：agent 完全遵守 Step 2（先 `fix-encoding` 再 `lint`），但因为只 lint 了转码后的文件，
最终汇报「**0 error**」—— 而原始文件其实是 GBK，`lint` 原文件会明确报 `ENC-001` error。
用户看到「0 error」会以为文件本来干净。

已在 Step 2 和 Step 4 补上硬要求：**转码过的必须说明「原文件是 GBK」**，
并加了一句自检：「如果出现 0 error，回看一遍原文件编码」。

`diff` 场景同样要求**两边都先转码** —— 实测时 agent 自己这么做了，
但 SKILL.md 里原本没写，属于运气好。

#### 3. 文档说「9 类缺陷」，实际是 10 类

`demo_broken.dbc` 触发 10 个不同检查码（4 error / 4 warn / 2 info），
SKILL.md 和 README 都写着 9 类。这是又一次「文档数字没跟代码对上」。

已改正，并**新增 `TestExampleExpectations` 三条测试**锁住这些数字：

- `demo.dbc` 必须 0 error 0 warn
- `demo_broken.dbc` 必须刚好触发 10 个码，且集合等于预期
- 严重度分布必须刚好是 4 / 4 / 2

以后再改检查逻辑导致示例表现变化，CI 会直接红。

### 测试

58 → 61。

---

## [1.2.0] — 2026-11-04

### 变更

**`SKILL.md` 重写为执行手册，不再是说明文档。**

旧版是一份写给人的 README：讲「为什么自己写解析器」「为什么这些检查值得做」，
但 agent 真正需要的是「拿到文件之后按什么顺序做什么」。两者读者不同，混在一起两边都不好用。

新版是 Step 0–4 的运行手册：

| 步骤 | 内容 |
|---|---|
| Step 0 | 模式判定 —— 用户原话 → 子命令，不用反问 |
| Step 1 | 先跑 `info` 探规模，信号 > 500 时不裸跑 `signals` |
| Step 2 | `ENC-001` 时先转码再重跑，否则注释类判断全部失效 |
| Step 3 | 各子命令的调用方式与顺序陷阱（如 `diff` 参数顺序） |
| Step 4 | 输出解读：error 必须翻译成现象，汇报固定三段 |

新增两节旧版没有的内容：

- **「工具查不出来的」** —— 节点声明但零发送、同名报文 CAN ID 不一致、版本记录与文件不符、
  changelog 声称新增但文件里没有、属性被批量填同一个值。这些 `lint` 永远报不出来，
  必须靠 `diff` + `messages` 人工交叉核对。明确写进去，避免下次分析时以为「lint 绿了就没事」。
- **「error 翻译成人话」对照表** —— 用户不关心 `BIT-001` 这个编号，
  关心「为什么我的灯不亮」。

删掉的：cantools 对比表、四类事故的小故事、退出码重复说明（`--help` 已有）。
这些内容 README 里都有，留在 SKILL.md 只是让每次加载多花 token。

### 修复

**frontmatter 有 6 个无效字段。**

`slug` / `displayName` / `summary` / `version` / `tags` / `author` 全部不被 OpenClaw 读取
（`openclaw skills list --json` 只输出 `name` + `description`），
而且会让官方 `quick_validate.py` 直接报错：

```
Unexpected key(s) in SKILL.md frontmatter: author, displayName, slug, summary, tags, version.
Allowed properties are: allowed-tools, description, homepage, license, metadata, name, user-invocable
```

现在只保留 `name` / `description` / `license`，其余移入 `metadata:`（允许的扩展位置）。
校验通过：`Skill is valid!`

`description` 同时收紧了：原来把 11 条检查逐条列了一遍，那不是触发所需的信息，
而是 `references/checks.md` 的内容。现在只留触发词。

---

## [1.1.0] — 2026-11-04

### 新增

**`diff` 子命令 —— 两版 DBC 差异对比**

```bash
python dbc_analyze.py diff old.dbc new.dbc
python dbc_analyze.py diff old.dbc new.dbc --json
python dbc_analyze.py diff old.dbc new.dbc --min-severity warn
```

positional 的第一个参数是基线（旧版）。14 个差异代码：

| 代码 | 严重度 | 说明 |
|---|---|---|
| `DIF-GEO` | error | 信号位定义变了（起始位 / 长度 / 字节序 / 符号） |
| `DIF-DLC` | error | 报文长度变了 |
| `DIF-REN` | error | 报文 / 信号 / 节点重命名 |
| `DIF-ID` | error | 同名报文换了 CAN ID |
| `DIF-CRC` | error | 校验和注释里的 DataID 变了 |
| `DIF-DEL` | warn | 报文或信号被删除 |
| `DIF-SCL` | warn | 系数 / 偏移变了 |
| `DIF-RNG` | warn | 最小值 / 最大值 / 单位变了 |
| `DIF-VAL` | warn | 值表增删或改标签 |
| `DIF-CYC` | warn | 周期变了 |
| `DIF-TX` | warn | 发送节点变了 |
| `DIF-TYP` | warn | 发送类型变了 |
| `DIF-ADD` | info | 新增报文或信号 |
| `DIF-CMT` | info | 仅注释变更 |

有 `error` 级差异时退出码 1，`--no-fail` 强制返回 0。

**两个通用解析思路解决不了的场景，做了专门处理：**

- **同名报文换 CAN ID**。只按 frame id 逐条比对，会退化成「删一条 + 加一条」，
  真正的原因（地址变了）被埋在几十条增删中间。现在先按名字配对，报一条 `DIF-ID`，
  并抑制那条误导性的增删。
- **CRC DataID 变更**。这个信息不在结构化字段里，而是藏在信号的 `CM_` 注释文本中
  （`CRC16 checksum (DataID: 0x61D2)`）。普通注释比对只会归为 `info`。
  现在用正则提取 DataID 并单独提级为 `error` —— 因为接收方校验 CRC 失败会**拒收
  该帧的全部内容**，现象是「模块完全没反应」，比报错更难查。

信号重命名按**位定义**配对（名字正是变了的东西，只能靠位置锚定），因此
`Bus_Off_Count` → `Bus_Off_Cnt` 会报 `DIF-REN`，而不是一删一加。

### 修复

用真实整车矩阵验证时发现的两个误报：

- **`SYM-001` / `TYP-001` 在复合侧别命名上误报**。当两侧写成
  `FLM_L_FLTurnLampOnSt` / `FLM_R_FRTurnLampOnSt` 时，归一化只替换了第一个侧别
  标识，折叠 `L`/`R` 后仍剩 `FLTurn` 与 `FRTurn` 不同。现在会折叠全部侧别标识，
  并对复合 token 的侧别前缀（`FLADSLampFlt` / `FRADSLampFlt`）也做剥离。
  前缀剥离加了双重保护：单字符标识不剥离（否则 `AFS` 变 `XFS`），
  首个 token 不剥离（否则 `ACM` 变 `XCM`）。
- **`VECTOR__INDEPENDENT_SIG_MSG` 误报**。这是 Vector 存放「未分配给任何报文的
  信号」的约定容器（id 0 / DLC 0），其中的信号按定义就不属于任何帧。
  `BIT-001` / `RNG-001` / `DLC-001` / `DUP-001` 现在统一跳过它。
  对外暴露为 `Message.is_orphan_container`。

### 测试

- 33 → 58 个单元测试，新增 `tests/test_diff.py` 25 个用例
- 覆盖：增删改、ID 迁移、信号重命名（按位配对）、几何变更、缩放变更、值表变更、
  周期变更、发送节点变更、CRC DataID 变更、JSON 输出、退出码、`--min-severity`、
  正反向对称性
- 测试夹具在运行时从 `examples/demo.dbc` 现场改写生成，仓库不额外保存近似副本

---

## [1.0.0] — 2026-11-04

首个版本。`dbc-matrix-audit` 是一个零依赖的 DBC 通信矩阵审计器。

### 新增

**核心**

- `dbc_analyze.py` —— 手写的 DBC 解析器与审计器，仅用 Python 标准库
  - 解析 `BO_` / `SG_` / `VAL_` / `CM_` / `BA_DEF_` / `BA_` / `BA_DEF_DEF_` / `BU_`
  - 正确处理 Motorola（`@0`，起始位是 MSB）与 Intel（`@1`，起始位是 LSB）两种位序
  - 支持扩展帧标记（bit 31）、多行注释、注释内的分号与转义引号

**子命令**

- `info` —— 报文数、信号数、DLC 分布、编码、周期、值表覆盖
- `messages` —— 报文清单表
- `signals` —— 信号明细（起始位、长度、系数、偏移、范围、单位、值表、注释），可 `--frame` 过滤
- `lint` —— 全部结构检查，支持 `--json` / `--min-severity` / `--no-fail`
- `decode` —— 给定十六进制负载解出一帧的物理值
- `export` —— 导出信号总表 CSV（UTF-8 BOM，Excel 直接打开）
- `fix-encoding` —— GBK / 其他编码转 UTF-8，换行统一为 `\n`

**检查规则（11 个代码）**

| 代码 | 严重度 | 说明 |
|---|---|---|
| `ENC-001` | error | 文件不是 UTF-8（典型是 GBK 中文注释） |
| `BIT-001` | error | 同一帧内两个信号占用同一位 |
| `RNG-001` | error | 信号超出报文长度 |
| `DLC-001` | error | 非法 DLC（CAN FD 只允许 0-8/12/16/20/24/32/48/64） |
| `ENU-001` | warn | ENUM 类型属性被赋值为数字索引 |
| `SYM-001` | warn | 左右（L/R、A/B、FL/FR、LH/RH…）信号集不对称 |
| `TYP-001` | warn | 去掉侧别标识后同一信号拼写不一致 |
| `DUP-001` | warn | 信号名跨报文重复 |
| `STA-001` | info | 大量信号未设 `GenSigStartValue` |
| `NOD-001` | info | 发送节点未在 `BU_` 中声明 |
| `VAL-001` | info | 短信号（≤4 bit）没有值表 |

严重度为 `error` 时退出码为 1，可直接接入 CI。

**示例**

- `examples/demo.dbc` —— 合成的干净矩阵：20 报文 / 167 信号 / 12 个 CAN FD 帧，
  `lint` 输出 0 error 0 warn
- `examples/demo_broken.dbc` —— 同一矩阵注入 9 类缺陷（覆盖每个检查族），
  故意用 GBK 编码，`lint` 输出 4 error 4 warn
- `tools/gen_demo_dbc.py` —— 示例生成器。位分配由 Motorola 游标计算，
  因此干净文件中的「无重叠」是构造保证；CI 用 `diff` 断言示例可重现

**测试与 CI**

- 33 个单元测试，纯标准库 `unittest`
- GitHub Actions 覆盖 Python 3.10 / 3.11 / 3.12 / 3.13
- CI 额外断言：干净示例必须零 error 零 warn；缺陷示例必须被拒绝；示例必须可重现

**文档**

- `README.md` —— 安装、用法、检查项一览、与 cantools 的对比
- `skills/dbc-matrix-audit/SKILL.md` —— AgentSkill 格式，含触发词
- `references/checks.md` —— 每条规则的判定方式、误报场景、未实现项
- `references/encoding.md` —— GBK 问题、坏字节定位方法、转码后验证清单
- `references/dbc-syntax-notes.md` —— 写解析器必须知道的 DBC 语法要点

### 已知局限

- 位重叠检查**未感知复用信号**（`m<N>`），遇到 multiplexed 信号会误报 `BIT-001`
- 只处理 DBC，不解析 `.arxml` / `.ldf` / `.kcd`
- 对称性检查是启发式：报文名需形如 `X_L_Y` / `X_R_Y` 或 `X_A_Y` / `X_B_Y`
- 不校验 CRC / rolling counter 的算法，只检查它们是否存在
- 值表查表基于物理值 `round()`，适用于 `factor=1, offset=0` 的常见枚举；
  带缩放的枚举应基于原始值查表

### 说明

示例数据全部虚构，不含任何真实车型代号、供应商名称或人员姓名。
