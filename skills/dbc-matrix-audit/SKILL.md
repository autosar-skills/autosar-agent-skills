---
name: dbc-matrix-audit
slug: dbc-matrix-audit
displayName: DBC 通信矩阵审计
summary: 审计 CAN / CAN FD DBC 通信矩阵：位域重叠、信号越界、值表缺失、左右不对称、命名漂移、GBK 编码；支持两版差异对比。零依赖。
description: |
  审计和检查 DBC 通信矩阵文件。当用户提到「分析这个 dbc」「看看这个通信矩阵」「dbc 检查」「CAN 矩阵审计」「信号有没有重叠」「左右不对称」「dbc 乱码」「GBK 编码」「解码这帧报文」时使用。
  覆盖 11 类结构检查：GBK/UTF-8 编码、位域重叠、信号越界、DLC 非法、ENUM 属性写成数字、左右/AB 对称性、命名大小写漂移、跨报文重名、启动值缺失、发送节点未声明、短信号缺值表。
  Audit DBC communication matrices (CAN / CAN FD). Detects bit-field overlaps, out-of-range signals, illegal DLC, enum attributes written as numbers, left/right asymmetry, case-only spelling drift, duplicate signal names, missing start values, undeclared transmitters, and GBK-encoded comments. Also decodes raw frames and exports the signal inventory.
  支持两版 DBC 差异对比（`diff` 子命令）：报文增删改、CAN ID 迁移、信号位移、缩放系数变更、值表变更、CRC DataID 变更。当用户提到「对比两版 dbc」「版本差异」「升级改了什么」「两个 dbc 有什么不同」时使用。
  Compare two DBC revisions for breaking changes: renames, CAN id moves, bit geometry shifts, scaling, value tables, and CRC data ids.
version: 1.1.0
author: autosar-agent-skills
license: MIT
tags: [autosar, can, canfd, dbc, communication-matrix, lint, embedded]
---

# DBC Matrix Audit

DBC 通信矩阵的静态审计工具。**纯标准库**，不依赖 cantools、不依赖任何第三方包。

## 为什么自己写解析器

主流 DBC 库（含 cantools）解析时**丢掉了审计最需要的东西**：

| 数据 | cantools `.messages` | 本工具 |
|---|---|---|
| 报文周期 `GenMsgCycleTime` | ✗ | ✓ |
| 值表 `VAL_`（枚举文字含义） | 部分 | ✓ |
| 注释 `CM_` | ✗ | ✓ |
| 报文/信号属性 `BA_` | ✗ | ✓ |

没有这四类，就没法判断「这个 2 bit 信号到底代表什么」「这条报文多久发一次」。

## 用法

```bash
# 概览
python dbc_analyze.py info matrix.dbc

# 报文清单
python dbc_analyze.py messages matrix.dbc

# 单个报文的信号明细（含值表、注释、范围）
python dbc_analyze.py signals matrix.dbc --frame 0x1D2

# 结构审计（有 error 时退出码 1，可直接接 CI）
python dbc_analyze.py lint matrix.dbc
python dbc_analyze.py lint matrix.dbc --json
python dbc_analyze.py lint matrix.dbc --min-severity warn

# 解一帧真实报文
python dbc_analyze.py decode matrix.dbc 0x1D2 1234052a00000000

# 导出信号总表（Excel 可直接打开）
python dbc_analyze.py export matrix.dbc --csv inventory.csv

# GBK -> UTF-8
python dbc_analyze.py fix-encoding matrix.dbc matrix_utf8.dbc

# 对比两版（positional 参数是基线/旧版）
python dbc_analyze.py diff old.dbc new.dbc
python dbc_analyze.py diff old.dbc new.dbc --json
python dbc_analyze.py diff old.dbc new.dbc --min-severity warn
```

## 检查项清单

| 代码 | 严重度 | 说明 |
|---|---|---|
| `ENC-001` | error | 文件不是 UTF-8（典型是 GBK 中文注释） |
| `BIT-001` | error | 同一帧内两个信号占用同一位 |
| `RNG-001` | error | 信号超出报文长度 |
| `DLC-001` | error | 非法 DLC（CAN FD 只有 0-8/12/16/20/24/32/48/64） |
| `ENU-001` | warn | ENUM 类型属性被赋值为数字索引 |
| `SYM-001` | warn | 左右（L/R、A/B、FL/FR…）信号集不对称 |
| `TYP-001` | warn | 去掉左右标识后，同一个信号拼写不一致（`FctSt` vs `Fctst`） |
| `DUP-001` | warn | 信号名跨报文重复 |
| `STA-001` | info | 大量信号未设 `GenSigStartValue` |
| `NOD-001` | info | 发送节点未在 `BU_` 中声明 |
| `VAL-001` | info | 短信号（≤4 bit）没有值表 |

每项规则的判定细节和**误报场景**见 `references/checks.md`。
复用信号（multiplexed）尚未感知，已知局限见该文件末尾。

## 版本对比（diff）

```
python dbc_analyze.py diff <基线/旧> <目标/新>
```

| 代码 | 严重度 | 说明 |
|---|---|---|
| `DIF-GEO` | error | 信号位定义变了（起始位 / 长度 / 字节序 / 符号） |
| `DIF-DLC` | error | 报文长度变了 |
| `DIF-REN` | error | 报文 / 信号 / 节点重命名 —— 按旧名查值的代码会静默取不到 |
| `DIF-ID` | error | 同名报文换了 CAN ID —— 路由表和过滤器仍指向旧地址 |
| `DIF-CRC` | error | 校验和注释里的 DataID 变了 —— 接收方会拒收整帧 |
| `DIF-DEL` | warn | 报文或信号被删除 |
| `DIF-SCL` | warn | 系数 / 偏移变了 —— 数值静默偏移 |
| `DIF-RNG` | warn | 最小值 / 最大值 / 单位变了 |
| `DIF-VAL` | warn | 值表增删或改标签 |
| `DIF-CYC` | warn | 周期变了 |
| `DIF-TX` | warn | 发送节点变了 |
| `DIF-TYP` | warn | 发送类型变了 |
| `DIF-ADD` | info | 新增报文或信号 |
| `DIF-CMT` | info | 仅注释变更 |

**两个容易漏判的场景做了专门处理：**

1. **同名报文换 ID**。只按 ID 比对会退化成「删一条 + 加一条」，真正的原因（地址变了）被埋在中间。工具先按名字配对，报 `DIF-ID`，并抑制那条误导性的增删。
2. **CRC DataID 变更**。它藏在信号的 `CM_` 注释里（`CRC16 checksum (DataID: 0x61D2)`），普通注释比对只会当 `info`。工具用正则提取 DataID，一变就报 `error` —— 因为接收方校验 CRC 会**拒收该帧全部内容**，表现是「模块没反应」而不是报错。

信号重命名按**位定义**配对（名字正是变了的东西，只能靠位置锚定），所以 `Bus_Off_Count` → `Bus_Off_Cnt` 会识别为 `DIF-REN` 而不是一删一加。

`diff` 的退出码：有 `error` 级差异返回 1，`--no-fail` 强制返回 0。

## 为什么这些检查值得做

通信矩阵的错**不会在编译期暴露**，只会在联调时以「某个灯不亮」「某帧解出来是负数」的形式出现，而且往往已经跨了两个团队。四类最常见的真实事故：

1. **GBK 编码** —— Vector 工具链能忍，Python 脚本一读就崩，CI 里才炸。
2. **位域重叠** —— 两个信号抢同一位，收发双方都「正常」跑，数值永远错。
3. **左右不对称** —— 一侧多一个信号，另一侧代码按名字取值拿到默认 0。
4. **大小写漂移** —— `FLM_L_AFSFctst` vs `FLM_R_AFSFctSt`，按 A 侧名字写的代码在 B 侧取不到值。

## 退出码

| 码 | 含义 |
|---|---|
| 0 | 无 error（可能仍有 warn / info） |
| 1 | 存在 error |
| 2 | 参数或文件问题 |

`--no-fail` 可强制返回 0，适合「先跑起来看看」的场景。

## 示例文件

- `examples/demo.dbc` —— 合成的干净矩阵（20 报文 / 167 信号），0 error 0 warn
- `examples/demo_broken.dbc` —— 同一矩阵埋了 9 类缺陷，`lint` 会全部报出

两个文件都是虚构的，不含任何真实车型、供应商或人员信息。由 `tools/gen_demo_dbc.py` 生成，位分配由程序计算而非手工填写，因此干净文件中结构上不可能重叠。

## 局限

- 只读 DBC，不写回（除 `fix-encoding` 转码）
- 不解 `.arxml` / `.ldf` / `.kcd`，只处理 DBC
- 对称性检查是启发式：需要报文名形如 `X_L_Y` / `X_R_Y` 或 `X_A_Y` / `X_B_Y`
- 不校验 CRC / rolling counter 算法，只检查它们是否存在
