---
name: cdd-arxml-consistency
description: |
  交叉校验 CANdelaStudio CDD 诊断数据库与 AUTOSAR ECU 配置 ARXML：DID、DTC、例程、诊断 CAN ID、会话、安全访问、P2/S3/STmin 时序。
  触发：cdd 和 arxml 对不上、诊断数据库校验、DID 不一致、DTC 对不上、诊断地址不对、诊断进不去、0x31 requestOutOfRange、读不到 DID、诊断规范与 ECU 不一致、cdd 校验、CANdela 比对、诊断配置检查、安全访问不一致、P2 超时。
  Cross-check a CANdelaStudio CDD (diagnostic database) against an AUTOSAR ECU configuration ARXML. Covers data identifiers, DTCs, routines, diagnostic CAN addressing, sessions, security access, and P2/S3/STmin timings. Zero dependencies, standard library only, read-only.
homepage: https://me.tech-harry.top/blog/cdd-arxml-consistency.html
license: MIT
metadata:
  version: 1.1.0
  author: autosar-skills
  tags: [autosar, uds, cdd, candela, arxml, diagnostics, dcm, dem, embedded, consistency]
---

# CDD ↔ ARXML 交叉校验

诊断数据库（CDD）是**诊断仪**照着实现的规范，ECU 配置（ARXML）是 ECU **实际运行**的代码。
两者对不上时，编译不报错、诊断仪也能连上，然后 ECU 回 `0x31 requestOutOfRange` ——
或者会话能进，DID 读回来的长度不对。

零依赖，仅标准库。只读，绝不修改传入的文件。

## Step 0 — 判定模式

| 用户说什么 | 走哪个分支 |
|---|---|
| 「这两个文件对不上」「帮我比一下」「校验一下」 | `check`（默认） |
| 「先看看里面有什么」「读到什么了」「解析对不对」 | `probe` |
| 「导个台账」「给供应商一张表」「哪些 DID 没配」 | `matrix` |
| 「你自己能不能跑」「先验证工具」 | `selftest` |
| 只给了一个文件 | **不问**，直接说需要两个：CDD + ARXML |
| 提到 DBC / 通信矩阵 | **不是本 skill**，那是 `dbc-matrix-audit` |

**不要反问「你要检查哪些项」** —— 25 个检查码一次全跑，用户要的是结论不是选项。

## Step 1 — 执行准备

1. **确认参数顺序**：第一个是 CDD（根节点 `<CANDELA>`），第二个是 ARXML（AUTOSAR 命名空间）。
   传反了脚本会自己报错并说明，不要靠猜。
2. **大文件先 probe**：CDD 和 ARXML 都可能是 5 MB 以上。`probe` 只解析不比对，
   几秒内能看出「是不是读到了东西」，比直接 `check` 更容易定位问题。
3. **编码不用管**：脚本按 UTF-8 → GB18030 → latin-1 依次尝试，中英文注释都能读。
   CDD 的 `<!DOCTYPE ... SYSTEM 'candela.dtd'>` 会被自动剥离，缺 DTD 不影响。

```bash
SKILL=~/.openclaw/workspace/skills/cdd-arxml-consistency

# 先看两侧各自读到了什么
python3 $SKILL/scripts/cdd_arxml_check.py probe <cdd> <arxml>

# 完整比对
python3 $SKILL/scripts/cdd_arxml_check.py check <cdd> <arxml>
```

## Step 2 — 执行

### check（默认）

```bash
python3 $SKILL/scripts/cdd_arxml_check.py check <cdd> <arxml>
python3 $SKILL/scripts/cdd_arxml_check.py check <cdd> <arxml> --json            # 机器可读
python3 $SKILL/scripts/cdd_arxml_check.py check <cdd> <arxml> --min-severity warn
```

退出码：`0` 无 error ｜ `1` 有 error ｜ `2` 参数错误或文件读不了。可直接进 CI。

### matrix（逐项台账）

```bash
python3 $SKILL/scripts/cdd_arxml_check.py matrix <cdd> <arxml> -o inventory.csv
```

每个 DID / DTC / 例程一行，`state` 列区分 `both` / `cdd_only` / `arxml_only` /
`arxml_unused` —— 直接发给供应商，不用再解释。

### selftest（先验证工具本身）

```bash
python3 $SKILL/scripts/cdd_arxml_check.py selftest
```

**两组**合成样例，跑真实文件前先跑这个：

1. **配好的 CDD + 埋了 11 类缺陷** → 期望 `6 error, 4 warn, 3 info`，
   且 13 个检查码全部触发
2. **模板另存、CAN 页未填的 CDD** → 必须触发 `CDX-013`/`CDX-025`，
   且**不许**触发 `CDX-010/011/012/020/021/022`（没有可比对的属性时不该报「不一致」）

第 2 组防的不是崩溃，是「报告干净得像没问题」：八个检查各自跳过，条数很小，
输出里没有一个字说它们没跑。

## Step 3 — 解读与汇报

**顺序不能变**：先报最严重的一条，再说总体，最后才是明细。

1. **一句话结论**：`N error, M warn, K info`，以及「能不能拿去刷 ECU」。
   有 error 就说「不要据此刷写或放行诊断」。
2. **逐条 error**：每条给出「现象 → 后果 → 该改哪一边」。
   - `CDX-010/011/012` 会**自己判断哪边错**（用硬件验收滤波器做裁决），
    照它说的方向改，不要两个文件一起改。
   - `CDX-013` = **CDD 里那些属性压根没配**。这不是「不一致」，是「没法比」。
     必须原话说出「CDX-010/011/012 未执行」，不能只说「有 1 个 error」——
     否则用户会以为地址比对过且只是差一点。报出的 0x700/0x750/0x600 是
     CANdelaStudio 模板默认值，不是这个 ECU 的地址。
   - `CDX-001/004/006` 是「CDD 有、ECU 没配」：诊断仪会发，ECU 不认。
   - `CDX-020/030/031` 是「ECU 的行为与规范不符」，通常是 ARXML 落后于规范。
3. **warn 归并**：同一条检查码超过 3 条时合并成一行，列前几个编号 + 总数，不要刷屏。
4. **info 只挑有用的**：`CDX-043`（CDD 内部两处 DTC 清单不一致）必须转述，
   因为它解释了「为什么两边数量对不上」，不解释清楚用户会以为工具漏读了。
5. **给下一步**：谁是权威（CDD 还是 ARXML）、谁去改、改完重跑什么。

**`CDX-025` 单独提醒**：它列出的检查码（`CDX-020~024`）确实没跑。
说「时序没查出问题」是错的，只能说「时序未比对」。

**不要做的事：**
- 不要把 `0 error` 说成「配置正确」—— 只说「这 25 项没查出问题」，并列出未覆盖的项（见 Step 4）。
- 不要把 warn 说成 error，也不要因为 warn 多就说「整体质量差」。

## Step 4 — 查不出来的（必须主动声明）

以下**不在**本工具覆盖范围，报告里要写清楚，否则用户会把「25 项通过」当成「诊断全对」：

| 未覆盖 | 说明 |
|---|---|
| DID 的数据长度与结构 | CDD 的 `STRUCTURE` 展开和 Dcm 的 `DcmDspData` 没有做逐位比对 |
| 服务与子功能的会话/安全依赖 | CDD 的 `trans`（状态迁移表）与 Dcm 的 `DcmDsdServiceSessionRef` 未交叉验证 |
| 否定响应码的使用范围 | 只统计两侧的 NRC 清单，不校验「哪个服务该回哪个 NRC」 |
| 安全访问算法 | 只比 Seed/Key 长度与等级，不比算法实现 |
| 快照/扩展数据记录内容 | 只比 DTC 编号是否存在，不比记录里的字段 |
| 物理寻址/功能寻址的 N_SA/N_TA | 从 CanTp 读出来了，但未与 CDD 的地址方案逐项核对 |
| DBC / 通信矩阵 | 那是 `arxml-dbc-consistency` 与 `dbc-matrix-audit` 的事 |
| CDD 的通信属性是否「正确」 | 只能判「有没有配」。配了一个值但值本身错了（比如偶发地址写错但滤波器恰好也错），工具报不出来 |

另外三条**已知误报场景**：
- 用 `0x29 Authentication` 替代 `0x27 SecurityAccess` 的项目，`CDX-031` 可能误报。
- CDD 用 `RECORDDTPOOL` 而非诊断实例记录 DTC 的项目，`CDX-004` 的数量会偏小 ——
  先看 `CDX-043` 的内容再下结论。
- CDD 从模板另存、CAN 页尚未填写时，`CDX-013`/`CDX-025` 会把模板默认值贴进报告。
  那是**诊断规范还没做完**的信号，不是工具报错，别去改 ARXML。

## 输出样例

```
[E] CDX-010  物理请求 CAN ID 不一致：CDD 0x738 / CanIf 0x72F  [CAN ID]
      CanIf 的 CanIfRxPduCfg_Phys_Req 配的是 0x72F（1839），CDD 的 CAN.ReqCanId 是 0x738（1848）。
      两者相差 9。诊断仪按 CDD 发，ECU 按 CanIf 收 —— 请求根本进不了 Dcm。
      硬件验收滤波器里有 0x738，没有 0x72F —— 即芯片只会把 0x738 的帧交给上层。
      所以错的是 CanIf 的 CanIfRxPduCfg_Phys_Req（应为 0x738），不是 CDD。
```

注意最后三句：**不是「两个文件不一致」，而是「CanIf 写错了，证据是硬件滤波器」。**
这就是这个工具和普通 diff 的区别。

## 与其他 skill 的关系

```
cdd-arxml-consistency   CDD ↔ ARXML（诊断规范 ↔ ECU 诊断配置）  ← 本 skill
arxml-dbc-consistency   DBC ↔ ARXML（通信矩阵 ↔ ECU 通信配置）
dbc-matrix-audit        单个 DBC 的静态检查与版本对比
```

三者互不重叠，可以组合使用。诊断链路的问题先跑本 skill，
通信链路的问题先跑 `arxml-dbc-consistency`。

详细的 25 个检查码判定逻辑见 `references/checks.md`（中文）/ `references/checks.en.md`（English）。

## Links

- 源码与 issue：https://github.com/autosar-skills/autosar-agent-skills
- 相邻 skill：`arxml-dbc-consistency`、`dbc-matrix-audit`
