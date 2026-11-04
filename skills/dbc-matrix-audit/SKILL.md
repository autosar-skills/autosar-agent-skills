---
name: dbc-matrix-audit
slug: dbc-matrix-audit
displayName: DBC 通信矩阵审计
summary: 审计 CAN / CAN FD DBC 通信矩阵：位域重叠、信号越界、值表缺失、左右不对称、命名漂移、GBK 编码。零依赖。
description: |
  审计和检查 DBC 通信矩阵文件。当用户提到「分析这个 dbc」「看看这个通信矩阵」「dbc 检查」「CAN 矩阵审计」「信号有没有重叠」「左右不对称」「dbc 乱码」「GBK 编码」「解码这帧报文」时使用。
  覆盖 12 类结构检查：GBK/UTF-8 编码、位域重叠、信号越界、DLC 非法、ENUM 属性写成数字、左右/AB 对称性、命名大小写漂移、跨报文重名、启动值缺失、发送节点未声明、短信号缺值表。
  Audit DBC communication matrices (CAN / CAN FD). Detects bit-field overlaps, out-of-range signals, illegal DLC, enum attributes written as numbers, left/right asymmetry, case-only spelling drift, duplicate signal names, missing start values, undeclared transmitters, and GBK-encoded comments. Also decodes raw frames and exports the signal inventory.
version: 1.0.0
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
| `MUX-001` | info | 复用信号（multiplexed）结构可疑 |

每项规则的判定细节和**误报场景**见 `references/checks.md`。

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
