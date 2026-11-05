---
name: dbc-matrix-audit
description: |
  审计、检查、对比 CAN / CAN FD 的 DBC 通信矩阵。触发：分析这个 dbc、通信矩阵、dbc 检查、CAN 矩阵审计、信号重叠、信号越界、左右不对称、命名漂移、dbc 乱码、GBK 编码、解码这帧报文、值表缺失、对比两版 dbc、版本差异、升级改了什么、两个 dbc 有什么不同。
  Audit, lint and diff CAN / CAN FD DBC communication matrices: bit-field overlaps, out-of-range signals, illegal DLC, enum attributes written as numbers, left/right asymmetry, case-only spelling drift, duplicate signal names, missing start values, undeclared transmitters, GBK-encoded comments, raw frame decoding, signal inventory export, and two-revision comparison (renames, CAN id moves, geometry shifts, scaling, value tables, CRC data ids).
homepage: https://me.tech-harry.top/blog/dbc-matrix-audit-skill.html
license: MIT
metadata:
  version: 1.3.1
  author: autosar-agent-skills
  tags: [autosar, can, canfd, dbc, communication-matrix, lint, embedded]
---

# DBC Matrix Audit

零依赖，纯标准库。全部子命令走同一个脚本：

```bash
python3 <skill>/scripts/dbc_analyze.py <subcommand> ...
```

`<skill>` 是本文件所在目录。仓库内是 `skills/dbc-matrix-audit/`。

## Step 0 — 判定模式

按用户原话直接选，**不要反问**。命中多个时按本表从上到下执行。

| 用户提到 | 跑 |
|---|---|
| 概览、几帧、多少信号、有哪些节点 | `info` |
| 报文清单、有哪些帧、谁发的 | `messages` |
| 某个帧的信号、0x1D2 里有什么、什么含义 | `signals --frame` |
| 检查、审计、审一下、有没有问题、帮我看下 | `lint` |
| 对比、两版、升级改了什么、差异、有什么不同 | `diff` |
| 解这帧、这串字节、0x... 是什么值 | `decode` |
| 导出、给供应商、Excel、台账 | `export --csv` |
| 乱码、GBK、中文变问号、打开是乱码 | `fix-encoding` |

「检查」和「对比」同时出现 → **先 `diff`**。跨版本差异比单版静态缺陷更紧急：已经上线的东西变了，比还没上线的东西有瑕疵严重。

## Step 1 — 先探规模

```bash
python3 <skill>/scripts/dbc_analyze.py info <dbc>
```

拿到报文数 / 信号数 / 节点数 / 总线负载。**信号数 > 500 时不要裸跑 `signals`**，用 `--frame` 或 `export` 收窄。

## Step 2 — 编码先于一切

`lint` 报 `ENC-001`（不是 UTF-8）时，**先转码再重跑 lint**：

```bash
python3 <skill>/scripts/dbc_analyze.py fix-encoding <dbc> <dbc>_utf8.dbc
python3 <skill>/scripts/dbc_analyze.py lint <dbc>_utf8.dbc
```

原因：GBK 文件里所有 `CM_` 注释是坏字节。位域类检查仍有效，但**依赖注释的判断会失效**——包括 CRC DataID 提取、信号用途说明。不转码就解读输出，会把「注释读不到」误判成「注释缺失」，然后错误地建议用户补注释。

后续所有命令都使用转码后的文件。

**⚠️ 转码后 `lint` 报 0 error，不等于原文件没问题。**
`ENC-001` 是 error 级 —— 它是原文件真实存在的缺陷，只是被「转码」这个动作修掉了。
如果只在转码后的文件上跑 lint 就汇报「0 error」，用户会以为原始文件本来干净。
**汇报必须写明「原文件是 GBK，已转码后审计」**，见 Step 4。

`diff` 场景同理：**两个文件都要先转码**，否则注释类差异（含 CRC DataID）读不出来。

### 自检工具是否可用

首次使用或怀疑环境有问题时，用内置示例验证：

```bash
python3 <skill>/scripts/dbc_analyze.py lint <skill>/examples/demo.dbc           # 期望 0 error 0 warn
python3 <skill>/scripts/dbc_analyze.py lint <skill>/examples/demo_broken.dbc   # 期望 10 类缺陷全报（4 error / 4 warn / 2 info）
```

## Step 3 — 执行

### lint

```bash
python3 <skill>/scripts/dbc_analyze.py lint <dbc>
python3 <skill>/scripts/dbc_analyze.py lint <dbc> --json          # 脚本消费
python3 <skill>/scripts/dbc_analyze.py lint <dbc> --min-severity warn
```

有 error 时退出码 1（可直接接 CI）。

### diff

```bash
python3 <skill>/scripts/dbc_analyze.py diff <基线/旧> <目标/新>
```

第一个 positional 是**基线**。顺序反了所有方向的结论都会反（`0x457 -> 0x46B` 变成 `0x46B -> 0x457`）。

反向对比一次可以验证结论是否对称——两边 error 数应当一致。不一致说明有单侧新增/删除，值得单独看。

### decode

```bash
python3 <skill>/scripts/dbc_analyze.py decode <dbc> 0x1D2 1234052a00000000
```

hex 长度可短于 DLC（缺的补 0），不能长于 DLC。

### export

```bash
python3 <skill>/scripts/dbc_analyze.py export <dbc> --csv inventory.csv
```

用户说「发给供应商」时用这个，不要手写表格。

## Step 4 — 解读与汇报

**error 必须翻译成现象**，不能只报代码。用户不关心 `BIT-001` 这个编号，关心「为什么我的灯不亮」。

| 代码 | 说成人话 |
|---|---|
| `BIT-001` | 两个信号抢同一位，收发双方都正常跑，但数值永远错 |
| `SYM-001` | 一侧少信号，另一侧代码按名字取值拿到默认 0 |
| `TYP-001` | 按 A 侧名字写的代码在 B 侧取不到值 |
| `ENC-001` | Vector 能忍，Python/CI 一读就崩 |
| `DIF-CRC` | 接收方校验失败会拒收整帧，现象是「模块没反应」而不是报错 |
| `DIF-ID` | 路由表和过滤器还指向旧地址，报文收不到 |
| `DIF-REN` | 按旧名查值的代码静默取不到，不报错 |

**汇报固定三段**：

1. **结论** —— 几个 error、能不能上线。**若做过转码，必须在此说明「原文件是 GBK」**
2. **证据** —— 关键 error 原样贴工具输出
3. **待确认** —— 工具查不出、必须人工看的部分（见下）

`warn` 按类型归并批量报（「26 条信号删除，集中在 DLP 投影功能」），不要逐条念。
`info` 一句带过或省略。

**自检**：汇报里如果出现「0 error」，回看一遍原文件编码。0 error 的干净报告 +
GBK 原文件 = 漏报了一次 error。

## 工具查不出来的（必须人工交叉核对）

`lint` 只看单文件结构。以下问题只能靠 `diff` + `messages` 对照人工判断，**发现不了不等于没有**：

- **节点声明了但零发送** —— `BU_` 里有，`BO_` 里从没作为发送方出现
- **同名报文 CAN ID 不一致** —— 两份矩阵对同一帧给了不同地址
- **版本记录与实际不符** —— changelog 只到 V1.2，文件名却是 V1.4
- **changelog 声称新增但文件里没有** —— 记录与实际脱节
- **属性被批量填同一个值** —— 如 `GenSigASIL` 全部 = 5，不是真实安全分析

确认「要不要报」的判断标准：**凡是会导致联调时现象异常、但编译期不报错的，都报。**

## 检查码

**error**：`ENC-001` `BIT-001` `RNG-001` `DLC-001`
**warn**：`ENU-001` `SYM-001` `TYP-001` `DUP-001`
**info**：`STA-001` `NOD-001` `VAL-001`

**diff error**：`DIF-GEO` 位定义变 / `DIF-DLC` 长度变 / `DIF-REN` 重命名 / `DIF-ID` CAN ID 迁移 / `DIF-CRC` DataID 变
**diff warn**：`DIF-DEL` 删除 / `DIF-SCL` 系数偏移 / `DIF-RNG` 范围单位 / `DIF-VAL` 值表 / `DIF-CYC` 周期 / `DIF-TX` 发送节点 / `DIF-TYP` 发送类型
**diff info**：`DIF-ADD` 新增 / `DIF-CMT` 注释

判定细节、误报场景、已知局限 → `references/checks.md`

## 退出码

`0` 无 error ｜ `1` 存在 error ｜ `2` 参数或文件问题

`--no-fail` 强制返回 0。

## 局限

- 只读；除 `fix-encoding` 外不写回
- 只处理 DBC，不解 `.arxml` / `.ldf` / `.kcd`
- 对称性检查靠命名启发式，需要报文名形如 `X_L_Y` / `X_R_Y` 或 `X_A_Y` / `X_B_Y`
- 不校验 CRC / rolling counter 算法，只检查它们是否存在
- 复用信号（multiplexed）未感知，含 mux 的矩阵会有 `BIT-001` 误报

## 示例

`<skill>/examples/demo.dbc` —— 20 报文 / 167 信号，0 error 0 warn（仅 1 条 `STA-001` info）
`<skill>/examples/demo_broken.dbc` —— 同矩阵埋 10 类缺陷（4 error / 4 warn / 2 info），故意 GBK。
信号数比干净版少 1（166 vs 167）：埋 `TYP-001`/`SYM-001`/`DUP-001` 必须真的增删信号，
否则那三个检查不会触发。细节见 `examples/README.md`。

两个文件都是虚构的，不含真实车型、供应商或人员信息。
