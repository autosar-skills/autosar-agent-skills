# 示例文件

| 文件 | 说明 |
|---|---|
| `demo.dbc` | 干净的合成矩阵：20 报文 / 167 信号 / 12 个 CAN FD 帧。`lint` 输出 0 error 0 warn。 |
| `demo_broken.dbc` | 同一矩阵，埋了 9 类缺陷，`lint` 输出 4 error 4 warn。**故意用 GBK 编码**。 |

## 内容

虚构的车辆辅助控制网络：两个灯控模块 `ACM_A` / `ACM_B`，加一个后控制模块 `RCM`。

覆盖的场景：节点心跳、车辆运动输入、环境光/雨量、灯具控制指令、时间同步、场景位图、
传感器融合、双节点状态反馈、诊断快照、标定块、日志块、网络管理、热状态、电压轨、诊断请求/响应。

**所有实体均为虚构**，不含任何真实车型代号、供应商名称或人员姓名。

## 重新生成

```bash
python tools/gen_demo_dbc.py
```

位分配由程序计算（Motorola 游标从 bit 7 起按 7,6,…,0,15,14,… 推进），因此干净文件中
信号重叠在结构上不可能发生 —— 干净示例的「0 error」不是碰巧，而是构造保证的。

`demo_broken.dbc` 的缺陷是在生成后**注入**的，注入点见 `tools/gen_demo_dbc.py` 的
`corrupt()` 函数，每处缺陷对应一个检查码。

## 演示

```bash
python skills/dbc-matrix-audit/scripts/dbc_analyze.py lint examples/demo.dbc
python skills/dbc-matrix-audit/scripts/dbc_analyze.py lint examples/demo_broken.dbc
python skills/dbc-matrix-audit/scripts/dbc_analyze.py decode examples/demo.dbc 0x100 0000002100000000
```
