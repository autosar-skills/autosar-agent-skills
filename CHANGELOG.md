# Changelog

所有值得注意的变更都记录在此文件。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [cdd-arxml-consistency 1.1.0] — 2026-11-06 · 不再静默跳过没配的检查

### 修复

**`CDX-010/011/012` 与 `CDX-020~024` 在 CDD 未配置 CAN 属性时全部静默跳过。**

CDD 里的诊断地址有两处来源：`<ECU>` 节点下的属性**实例**（本 ECU 的配置），
和 `DEFATTS/ECUATTS` 下的属性**定义**（CANdelaStudio 模板默认值）。
模板另存后没填 CAN 页时，只有后者存在。解析器读不到实例 →
八个检查各自 `continue` → **报告里完全没有 CAN ID 相关内容**。

这和「CAN ID 检查通过」在输出上完全一样。一份 DID/DTC/例程全中的报告
会让人以为诊断规范是完整的，实际诊断地址压根没填。

修法不是「读模板默认值凑数」——那样会得到一个自信的错误结论。
而是把缺口本身报出来：

| 码 | 级别 | 判据 |
|---|---|---|
| `CDX-013` | error | `CAN.ReqCanId` / `CAN.ReqCanIdFunc` / `CAN.ResCanId` 有任何一项没配 |
| `CDX-025` | warn | `CAN.P2Server` / `P2ExServer` / `S3Client` / `StMin` / `Blocksize` 有任何一项没配 |

两条都明确写出「`CDX-0xx` 未执行（不代表通过）」，并把 DEFATTS 里的值
标注为**模板默认值**而不是配置值 —— 拿 `0x700` 导出 ODX，诊断仪就按 `0x700` 发请求。

模板默认值另外存进 `CddModel.attrs_template`，与 `attrs` 分开：
混在一起会让一个未配置的 CDD 看起来像配置好的，之后每一次比对都在
针对错误的数字给出自信的结论。

**CanIf PDU 角色识别漏掉 `Phy` 缩写。**

`RX_PDU_UDS_DiagPhyReq_LDLP` 里是 `Phy` 不是 `phys`，`"phys" in name.lower()`
匹配不上，于是 `CDX-010` 报「CanIf 里找不到物理请求 PDU」—— 而那个 PDU
就在文件里，只是名字短了一截。误报方向最坏：让人去补一个不缺的 PDU。
现按 `phys` / `physical` / `phy` 三种拼法识别。

### 新增

**自检扩到 2 组 fixture。** 第二组是「模板另存、CAN 页未填」的 CDD，
断言必须触发 `CDX-013`/`CDX-025`，且**不许**触发 `CDX-010/011/012/020/021/022`
（没有可比对的属性时不该报「不一致」）。同时断言 `attrs` 为空、
`attrs_template` 有值 —— 防止修复退化成「把模板值读进 attrs」。

**`probe` 不再整行消失。** 没读到 CAN 属性时打印
`诊断参数 —（CDD 未覆盖任何 CAN.* 属性，CAN ID 与时序检查都会跳过）`。
「这一行不见了」和「这一行是空的」在屏幕上没有区别，必须写出来。

### 验证

两组真实工程文件复测，行为符合预期：

| 文件 | 修复前 | 修复后 |
|---|---|---|
| EHV_LCU（CAN 属性基本齐全，缺 Blocksize） | 1 error / 1 warn | 1 error / **2 warn**（多出 `CDX-025`，如实说 `CDX-024` 没跑） |
| X11（模板另存，CAN 页全空） | 2 error / 2 warn | **3 error / 3 warn**（多出 `CDX-013` + `CDX-025`） |

反向验证：给 X11 的 CDD 注入正确的 8 个属性 → `CDX-013`/`CDX-025` 消失、
回到 2 error；把物理请求注入成 `0x700` → `CDX-010` 出现，且裁决为
「错的是 CDD，应为 0x712」（依据硬件滤波器只接受 0x712）。

检查码总数 23 → 25（10 error / 12 warn / 3 info）。

---

## [1.3.2] — 2026-11-05 · 首个 PyPI 版本（修两处打包缺陷）

### 修复

**`arxml-dbc-check selftest` 在安装后的包里直接崩溃。**

`cmd_selftest` 在调用时才 `import demo_fixtures`，而 `demo_fixtures.py` 没有被
打进 wheel —— 构建成功、`twine check` 通过、单元测试全绿，用户装完一跑就是
`ModuleNotFoundError`。所有测试都在仓库里跑，而仓库里那个模块是可导入的，
所以没有任何一条断言能发现它。

`tools/build_pypi.py` 现在把 `demo_fixtures.py` 一起打包，并在 `py-modules`
里声明（这一行在暂存构建时改写，不影响仓库内的 editable 安装）。

**`dbc-analyze --version` 报 `0.2.0`。**

`dbc_analyze.py` 里的 `__version__` 从 0.2.0 之后就没再更新过，与
`pyproject.toml` 的版本号脱节。现已对齐到 1.3.2。

### 新增

**`tools/build_pypi.py` 的安装冒烟测试。** 构建后自动建一个临时 venv、装上刚打出的
wheel、实际执行 `dbc-analyze --version` 和 `arxml-dbc-check selftest`。
`twine check` 只看元数据，看不出「懒加载的模块没进包」这类问题 —— 正是上面那个 bug 的形态。

### 首次发布

PyPI: https://pypi.org/project/dbc-matrix-audit/

```
pip install dbc-matrix-audit
dbc-analyze lint matrix.dbc
arxml-dbc-check check cfg.arxml matrix.dbc
```

## [1.1.2] — 2026-11-05 · 文档与仓库结构

### 变更

**`packaging/agensi/` 改为每个 skill 一个子目录。**

原来 `dbc-matrix-audit` 的 overlay 文件散在 `packaging/agensi/` 根目录（`SKILL.md`、
`README.md`、`LISTING.md`、`logo512.png`），而 `arxml-dbc-consistency` 用的是
`packaging/agensi/arxml-dbc-consistency/`。两种布局并存，靠 `_overlay_for()` 的
`is_dir()` 判断临场决定走哪条路。

后果是**: 根目录那套是共享的**。任何一个新 skill 只要不建自己的子目录，就会静默继承
`dbc-matrix-audit` 的 SKILL.md，而且构建不会报错——包能打出来，只是打错了内容。

现在两个 skill 都在各自的子目录里：

```
packaging/agensi/dbc-matrix-audit/{SKILL.md,README.md,LISTING.md,logo512.png}
packaging/agensi/arxml-dbc-consistency/{SKILL.md,LISTING.md,logo512.png}
```

**产物不变**：`dbc-matrix-audit.zip` 搬家前后都是 `3d29d2ac…`，`cmp` 字节一致。
打包逻辑读的是 overlay 目录里的文件名和内容，与目录层级无关。

flat 布局仍然被接受（旧的 checkout 不会打不出包），但会往 stderr 打一行警告，
说明「本市场下所有 skill 会拿到同一个 SKILL.md」。宁可吵一句，也不要静默打错包。

### 新增

两个 skill 的 SKILL.md 都加了 `homepage:`（各自对应的博客文章）和 `## Links` 小节。
`homepage` 是 SKILL.md frontmatter 的合法键，不触发 `quick_validate.py` 报错。

---

## [1.1.1] — 2026-11-05

### 修复

**`arxml-dbc-consistency`：AXD-016 的提示语把责任硬指向 ARXML。**

`0x1AC–0x1AF` 四帧在 DBC 里标成 CAN FD，CanIf 却配成经典帧。原提示语写「**未配** FD 帧格式」，
主语落在 ARXML 上，读者会直接去补一个 FD 标记——但如果那几帧本就不该出现在本 ECU 的矩阵里，
补标记什么也没修好。现在改成现场从 Com IPdu 的信号实际 bit 占用算出 span，再按证据说话：

- `span > 8` → 「经典 CAN 单帧上限 8 字节，而这帧的信号实际占满 N 字节，所以它只能是 FD——
  标记错了。若这帧本就不该在本 ECU 的矩阵里，那是 DBC 内容的问题，不是补一个 FD 标记能解决的」
- 否则 → 「配成经典帧却要求 N 字节，`CanIdType` 或 `DLC` 必有一个写错」

同一个检查码在不同证据下给不同指向，而不是固定甩锅。严重度不变（仍为 error）。

### 说明

这份包此前有一个**文档与代码不一致**的问题：`checks.md` / `checks.en.md` 已经描述了上述新行为，
但脚本里跑的还是旧文案。文档承诺了代码没做的事，比代码写错更隐蔽——用户照着文档读输出，
会得到一个自信但错误的结论。现在两边一致，`test_contract.py` 也覆盖了双语文档与实现的对应关系。

### 其他

- 英文版 `SKILL.md` 的触发词里残留了一个供应商名，已替换为文件名触发词。

---

## [未发布]

### 新增

**`arxml-dbc-consistency`：AUTOSAR 通信栈 ARXML × DBC 交叉校验。**

编译期不报错、联调才发现的那一类问题：帧在矩阵里有、通信栈里没有；信号解到了邻居的位；
起始位差三位，值全错但没有任何异常。26 个检查码，绑定主键是 CAN ID 加真实 PduR 路由链
（`DBC 帧 → CanIf PDU → EcuC Pdu → PduR 路由 → EcuC Pdu(COM) → Com IPdu`），不是名字。

- 位几何只有**一个**正确公式：AUTOSAR 的 `ComBitPosition` 存的是 LSB（平坦编号，与字节序无关），
  DBC 大端用锯齿编号且起始位是 MSB，先回退 `len-1` 步。真实工程实测 215/215 信号命中。
  早期「两种约定都试、任一命中即通过」的设计被否掉——它会把真错误洗白，实测也只有 153/215。
- 整网矩阵与单 ECU 视角分开判定：前者只对本 ECU 该发/该收的帧判 error。11 节点 91 帧的矩阵上，
  原来「每帧都必须配」的假设造出 99 条假 error，把真缺陷全埋了。
- 总线覆盖率：ARXML 管多条 CAN 时，命中率 <20% 的总线整体跳过并说明，避免「只查了一条总线
  却被读成全都对上了」。
- 中英双语文档：`SKILL.md` 中英并列，`references/checks.md` / `checks.en.md` 各 26 码，
  `test_contract.py` 同时断言两种语言与代码一致。

三份不相关的厂商工程（某厂商标 A、厂商标 B/某 Cortex-M 控制器、整网矩阵）暴露了 6 个解析缺陷 + 伪帧处理 +
多配置选择规则——每个只在某一家成立的解析假设，换一家就崩。

### 修复

**`pack_marketplace.py` 支持按 skill 覆盖。** 原先覆盖层是扁平的一层
`packaging/<market>/`，只能服务一个 skill；改成 `packaging/<market>/<skill>/` 优先、
扁平布局兜底，`dbc-matrix-audit` 的产物字节不变。

### 新增

**市场打包（`tools/pack_marketplace.py`）。** 上架 Agensi 需要「单一顶层文件夹 + `SKILL.md`
在其根 + 纯文本 + 带 README」。手工打包不可复现：`dist/` 是 gitignored，换个环境就
拼不出同一个包，也就无法证明买家下载到的就是仓库里的代码。

- `packaging/<market>/` 放市场专用物料：英文 `SKILL.md` / `README.md` 覆盖仓库中文版，
  `LISTING.md` 存档已提交的文案，`logo512.png` 是上架用图标
- 打包器剔除 `__pycache__` / 二进制 / 隐藏文件 / 软链，并校验结构，不满足直接失败
- 条目排序 + 固定时间戳 `(1980,1,1)` + 固定权限 → 重复构建字节一致
  （实测 sha256 `54454647…`，与上架附件一致）

### 说明

`dbc-matrix-audit` 已上架 Agensi 市场，免费，审核中。仓库代码未变，只新增打包链路。

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
  `ECU_L_FLTurnLampOnSt` / `ECU_R_FRTurnLampOnSt` 时，归一化只替换了第一个侧别
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
