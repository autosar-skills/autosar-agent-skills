# Changelog

所有值得注意的变更都记录在此文件。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

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
