# 检查码细节

共 26 个检查码。`error` 阻塞上线，`warn` 需人工确认，`info` 仅供参考。

## 分层与真实拓扑

绑定主键是 **CAN ID**，不是名字。真实 AUTOSAR 配置里 Com 与 CanIf **不直连**：

```
DBC 帧 ──CanId──> CanIf PDU ──CanIfXxxPduRef──> EcuC Pdu(X)
                        ──PduR 路由──> EcuC Pdu(COM_X)
                        ──ComPduIdRef──> Com IPdu
```

```
              ┌── CanDrv   CanController / CanHardwareObject
DBC 帧 ───────┼── CanIf    CanIfTxPduCfg / CanIfRxPduCfg
              ├── PduR     PduRRoutingPath（IF / TP）
              └── Com      ComIPdu / ComSignal / ISignalToIPduMapping
```

按名字直连匹配是错的：`IPDU_COM_TP_Param` 与 DBC 帧 `Diag_CalData` 名字毫无关系，
但它们通过 `COM_TP_Param → CanTp_TP_Param → 0x9B` 是同一条链路。

## error 级

| 码 | 含义 | 现象 |
|---|---|---|
| `AXD-001` | DBC 帧在 CanIf 中无对应 PDU（限 COM 链路） | 收发双方都不认这帧，报文静默丢弃 |
| `AXD-003` | CanIf DLC ≠ DBC DLC（TP / 诊断帧豁免） | PDU 被截断或读越界 |
| `AXD-004` | 标准/扩展帧类型不匹配 | 报文收不到；也用于 CanHardwareObject 未覆盖某种 ID 类型 |
| `AXD-005` | Com IPdu 长度 ≠ DBC DLC（TP 豁免） | 打包长度错，整帧拒绝 |
| `AXD-006` | DBC 信号在 Com 中缺失（含整帧无 IPdu；E2E 信号豁免） | 该信号永远不更新 |
| `AXD-008` | 位几何不一致 | 值解析到错误的位，数值全错但不报错 |
| `AXD-009` | 字节序不一致 | 大端小端搞反，数值错乱 |
| `AXD-010` | 位宽或符号性不一致 | 有符号当无符号，负值变大正数 |
| `AXD-011` | 初始值不一致（**以 DBC 的 `GenSigStartValue` 为准**） | 上电到首次收发之间双方值不同，状态判断出错（例：大灯高度初始角） |
| `AXD-014` | PduR 路由引用悬空 | 路由失效，链接期或运行时才暴露 |
| `AXD-015` | Com / CanIf PDU 没有 PduR 路由 | 上下层断路，数据不流转 |
| `AXD-016` | DBC 标了 CAN FD，CanIf 却配成经典帧 | FD 帧按普通帧发，长数据丢失。**注意两边都可能错**：若该帧信号真占满 >8 字节，则 FD 是事实、错的是标记；若这帧本就不该出现在本 ECU 的矩阵里，则是 DBC 内容问题 |
| `AXD-017` | 信号越过 IPdu 边界 | 写坏相邻字节 |
| `AXD-018` | Com 内部信号位重叠 | 两个信号抢同一位 |
| `AXD-022` | CanIf 收发方向与 DBC 发送方矛盾 | 报文不进正确的缓冲 |
| `AXD-023` | DBC 无帧，或没有任何 PDU 落在其覆盖范围内 | 给错 DBC 或总线回溯失败，本次校验等于没做 |
| `AXD-025` | 同一 CanId 存在多份 CanIf 配置，且其中某份**自相矛盾**（经典帧却配 >8 字节） | 那份一定跑不起来 |

## warn 级

| 码 | 含义 | 何时可忽略 |
|---|---|---|
| `AXD-000` | ARXML 未解析出 Com IPdu | 不可忽略，说明 probe 还没跑通 |
| `AXD-002` | CanIf PDU 的 CanId 在 DBC 中不存在 | 诊断帧、网络管理帧、DBC 未收录的私有帧 |
| `AXD-007` | Com 信号 / IPdu 在 DBC 中不存在 | 已废弃配置、DBC 版本滞后 |
| `AXD-012` | 周期不一致 | 已尝试秒/毫秒互转，仍不匹配才报 |
| `AXD-019` | 命名漂移（仅大小写 / 下划线差异） | 不建议忽略 —— 手写代码按旧名取值会静默拿到 0 |
| `AXD-020` | Com 方向与 DBC 发送方矛盾 | 双 ECU 共用一份 Com 配置时可能出现 |
| `AXD-025` | 同一 CanId 有多份 CanIf 配置，但每份自身长度/FD 状态都自洽 | **两套工程合并到同一 ARXML 时属正常设计**（CAN ID 恰好撞车），确认无误即可 |

## info 级

| 码 | 含义 |
|---|---|
| `AXD-021` | 波特率数值异常小，可能单位是 kbps 而非 bps |
| `AXD-024` | NM / 诊断 / TP 帧不经过 Com —— 属正常拓扑，提示人工确认对应模块已配 |
| `AXD-026` | 该 CanIf PDU 所在总线不在本 DBC 覆盖范围（见「总线覆盖率」） |

## 位几何换算：只有一个正确公式

**AUTOSAR 的 `START-POSITION` / `ComBitPosition` 存的始终是信号的 LSB**，按平坦编号
（bit0 = byte0 的 LSB），**与小端/大端无关**。

与 DBC 的差异只有一处：DBC 对大端信号用**锯齿编号**，且起始位写的是 **MSB**。
所以换算方式是「先回退 `len-1` 步求出 MSB，再按锯齿走完整个信号」。

```python
def motorola_msb_from_lsb(lsb, length):
    pos = lsb
    for _ in range(length - 1):
        pos = pos - 15 if pos % 8 == 7 else pos + 1
    return pos

def motorola_bits(msb, length):
    bits, pos = set(), msb
    for _ in range(length):
        bits.add(pos)
        pos = pos + 15 if pos % 8 == 0 else pos - 1
    return bits
```

小端信号直接用 `range(start, start+length)`。

### 为什么不是「两种约定都试」

早期版本假设行业存在 MSB / LSB 两派，做成「两种都算，任一命中即通过」。**这个设计是错的**，
两条理由：

1. **会把真错误洗白**：起始位写错时，另一种解释偶尔也能巧合命中，真缺陷被掩盖。
2. **实测不支持**：按 PDU 分组统计，`Scene_Sync` 100% 符合锯齿(MSB)解释，
   `Node_Info` / `Time_Info` 100% 符合平坦解释。看似「两派共存」，
   实则统一按 LSB→MSB 回退后 **215/215 信号零失败** —— 分歧是假的，之前的公式方​​向写反了。

同一份某厂商标 A工程实测：统一公式 215/215 命中；旧的双约定实现 153 命中 / 61 失败。

## 命名与建模的三个真实差异

这三点都是拿真实厂商文件跑出来的，早期自造数据没覆盖到，导致测试一直「绿」但实际不可用。

### 1. 参数标签是 `-PARAM-VALUE`，不是 `-PARAMETER-VALUE`

真实文件用 `ECUC-NUMERICAL-PARAM-VALUE` / `ECUC-TEXTUAL-PARAM-VALUE`。
脚本两种都接受，但**只认长形式会一个参数都读不到**——所有 CAN ID、DLC、长度全为 None，
而 `probe` 仍能显示容器数量，很容易误判成「文件里没配」。

### 2. ComSignal 名带 PDU 后缀

厂商把信号命名为 `<信号>_<PDU名>`，如 `ECU_R_FRTurnLampOnSt_IPDU_COM_ECU_R_St`。
注意 PDU 名本身就以 `IPDU_` 开头，所以实际后缀是 `_IPDU_COM_ECU_R_St`（长）
或 `_COM_ECU_R_St`（短）。两种都要剥，且要求完整匹配，避免误伤本来带 `_IPDU_` 的信号。

不剥的后果：信号全对不上 → 数百条假 `AXD-006` / `AXD-007`。

### 3. 三类信号不走 Com，不能报缺失

| 类型 | 归属 | 处理 |
|---|---|---|
| E2E 信号（Checksum / RollingCounter / CRC / AliveCounter） | E2E 库在 Com 之外写入 | Com 未配置属正常，豁免 |
| 整帧 OPAQUE / `UINT8_DYN` | Com 用 1 个字节数组信号覆盖全帧 | DBC 拆分建模，语义等价，跳过逐信号比对 |
| NM / 诊断 / TP 帧 | CanNm / Dcm / CanTp 内部管理 | 不经过 Com，出 `AXD-024` info |

## 总线覆盖率

一份 ARXML 常同时管多条 CAN。脚本按
`CanIfBufferCfg → CanIfBufferHthRef → CanIfHthCfg → CanIfHthCanCtrlIdRef`
（RX 走 `CanIfRxPduHrhIdRef → CanIfHrhCfg`）回溯每个 PDU 的总线归属，再算每条总线
在 DBC 里的命中率：

- **≥ 20%**：该总线在 DBC 覆盖内，正常比对
- **< 20%**：判定本 DBC 不含这条网络，整体跳过，只出 `AXD-026` info

某厂商标 A实测：`CANIF_CTR_PCAN` 0/32 命中（私有 CAN，DBC 未含）；
`CANIF_CTR_BCAN` 16/21 命中（车身 CAN）。

**汇报必须写明哪条总线被跳过**，并提示补对应 DBC，否则用户会以为检查覆盖了全部总线。

## 匹配策略

1. **CanIf**：按 `CanIfRxPduCanId` / `CanIfTxPduCanId` 精确匹配 DBC CAN ID。
   数值带 `0x80000000` 标志位时自动剥离并判为扩展帧。
2. **Com**：沿 PduR 路由 `dest↔src` 双向查找 `COM_` 前缀的 EcuC Pdu，再按 `ComPduIdRef` 落到 Com IPdu。
3. **方向**：DBC 的 `BO_` 发送节点与「本配置覆盖的节点集」比对；支持多节点
   （一个 MCU 管左右两路时，对侧帧不会被误判成方向错）。
4. **信号**：同名优先；同名缺失时按「去除非字母数字字符后相同」判为命名漂移（`AXD-019`），
   归一后继续比几何，避免把真问题当成改名掩盖掉。

## 已知局限

- 只读，不改任何文件
- 只认 AUTOSAR 4.x ECUC 结构
- 不解 `.xdm`（EB tresos DataModel2）、`.ldf` / `.kcd`
- 不解析 `ComSignalGroup`：成组信号不参与逐信号比对
- 不校验 CRC / rolling counter 算法，也不校验 E2E DataID
- 不感知 multiplexed signal（含 mux 的矩阵可能误报 `AXD-018`）
- `ComTxModeTimePeriod` 单位在厂商间有秒/毫秒两种写法，用「三种解释都不中才报」规避误报，
  因此 `AXD-012` 漏报率高于其它规则
- TP 帧只核对链路连通性，不做分段参数（BS / STmin）校验
- 不做 DBC 侧静态检查（位重叠、越界等）—— 那是 `dbc-matrix-audit` 的职责
