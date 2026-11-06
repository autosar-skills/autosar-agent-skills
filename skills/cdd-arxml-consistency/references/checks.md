# 检查码参考 — cdd-arxml-consistency

共 **25 个**检查码：**10 error / 12 warn / 3 info**。

级别含义：
- **error** —— 诊断会失败或读数错误，据此刷写/放行会出事故。
- **warn** —— 能跑，但规范与实现不一致，迟早变成问题。
- **info** —— 供理解用的事实，不是缺陷。

---

## 一、数据标识符（DID）

| 码 | 级别 | 判据 | 后果与指向 |
|---|---|---|---|
| `CDX-001` | error | DID 在 CDD 的 `DIDS` 中，Dcm 的 `DcmDspDid` 里没有 | 诊断仪照规范去读，ECU 回 `0x31`。**改 ARXML**：漏配 |
| `CDX-002` | warn | DID 在 `DcmDspDid` 中，CDD 里没有 | ECU 支持但规范没写，测试仪不会读。**改 CDD**：规范滞后 |
| `CDX-003` | warn | 两侧都有，但 `DcmDspDidUsed=false` | 容器存在但未启用，读请求仍回 `0x31`。**改 ARXML**：忘了置 true |

**判定依据**：`DcmDspDidIdentifier` 与 CDD `<DID n='...'>` 的十进制 `n` 属性。
两侧都按数值比较，**不按名字** —— 名字是给人看的，跨厂商一定会漂。

---

## 二、故障码（DTC）

| 码 | 级别 | 判据 | 后果与指向 |
|---|---|---|---|
| `CDX-004` | error | DTC 在 CDD 诊断实例的记录中，`DemDTC` 里没有 | 规范能读出该 DTC 的参数，ECU 却永不置位它。**改 ARXML** |
| `CDX-005` | warn | DTC 在 `DemDTC` 中，CDD 里没有 | ECU 会置位但测试仪读不出含义。**改 CDD** |
| `CDX-043` | info | CDD 内部两处 DTC 清单不一致（`RECORDDTPOOL` vs 诊断实例记录） | 说明为何两侧数量对不上，**不是让你去补 DTC** |

### `CDX-043` 为什么必须存在

CANdela 导出里 DTC 出现在两个不同位置：

```
ECUDOC/RECORDDTPOOL/RECORDDT/RECORD        ← 故障内存池（模板/规划）
ECUDOC/…/DIAGINST/RECORDDATAOBJ/RECORD     ← 诊断实例实际引用的
```

**这两份不是同一类清单**。实测某工程：池 37 个、实例引用 129 个、**交集 0**。
如果拿池去比 Dem，会得出「73 个 DTC 全都没配」这种彻底错误的结论。

因此：
- 比对 Dem 时**只用诊断实例引用的那批**。
- 两者不相等时打 `CDX-043` 说明情况，分两种措辞：
  - 有交集 → 「自相矛盾」，列出各方向差集；
  - 交集为 0 → 「完全不相交」，明确说明是两类清单，不是缺漏。

---

## 三、例程（Routine）

| 码 | 级别 | 判据 | 后果与指向 |
|---|---|---|---|
| `CDX-006` | error | 例程 ID 在 CDD 中有，`DcmDspRoutine` 里没有 | 诊断序列调用即失败。**改 ARXML** |
| `CDX-007` | warn | 例程 ID 在 `DcmDspRoutine` 中，CDD 里没有 | 规范未定义，测试仪不会调。**改 CDD** |

例程 ID 取 `DcmDspRoutineIdentifier`；CDD 侧取 `rtn` 类实例的 `STATICVALUE`。

---

## 四、诊断 CAN 寻址

| 码 | 级别 | CDD 属性 | CanIf 角色 | 后果 |
|---|---|---|---|---|
| `CDX-010` | error | `CAN.ReqCanId` | `phys_req` | 请求进不了 Dcm |
| `CDX-011` | warn | `CAN.ReqCanIdFunc` | `func_req` | 功能寻址（如 OBD 广播）失效 |
| `CDX-012` | error | `CAN.ResCanId` | `resp` | 响应发出但测试仪收不到 |
| `CDX-013` | error | 三个属性都缺 | — | 上面三行根本没比对，报告不能当成通过 |

### 角色识别规则

CanIf 里 PDU 的命名一家一个样，**按角色认，不按名字认**：

- 名字含 `func` → 功能请求
- 名字含 `phys` / `physical` / `phy` → 物理请求（`DiagPhyReq_LDLP` 这类缩写很常见）
- 名字含 `resp` → 响应

取 `CanIfRxPduCanId` / `CanIfTxPduCanId` 的值与 CDD 比对。

### `CDX-013` 为什么必须存在

这一条是本工具自己踩过的坑，不是假想。

CDD 里 `CAN.ReqCanId` 这类值有两种来源：

1. `<ECU>` 节点下的属性**实例**：`<UNS attrref='_...' v='1848'/>` —— 这是本 ECU 的配置
2. `DEFATTS/ECUATTS` 下的属性**定义**：`<UNSDEF id='_...' v='1792'>` —— 这是模板默认值

模板另存后没填 CAN 页，第 1 类一个都没有，只有第 2 类。此时解析器读不到属性，
`CDX-010/011/012` 三个分支各自 `continue` 掉 —— **报告里看不到任何 CAN ID 相关内容**。

问题在于「报告没提 CAN ID」和「CAN ID 没问题」在同一份输出里长得一模一样。
一份 DID/DTC/例程全中的报告会让人以为诊断规范是完整的，实际上诊断地址压根没填。

`CDX-013` 把这个缺口变成一条 error，并且把 DEFATTS 里的模板默认值**明确标为模板值**
而不是配置值 —— 因为拿 `0x700` 去导出 ODX，诊断仪会按 `0x700` 发请求。

同理 `CDX-025` 管的是时序那五项，级别降为 warn：P2 没配不会让 CDD 不可用，
但读者必须知道 `CDX-020~024` 没跑。

### 「哪一边错了」的裁决

这是本工具与普通 diff 的核心区别。发现不一致后**不猜**，而是查
`Can/CanConfigSet/CanHwFilter` 的 `CanHwFilterCode` + `CanHwFilterMask`：

```
匹配条件：(frame_id & mask) == (code & mask)
```

四种结论：

| 滤波器情况 | 结论 |
|---|---|
| 接受 CDD 的 ID、不接受 CanIf 的 ID | **CanIf 错了**，应为 CDD 的 ID |
| 接受 CanIf 的 ID、不接受 CDD 的 ID | **CDD 错了**，应为 CanIf 的 ID |
| 两个都接受（mask 有 don't-care 位） | 无法裁决，需人工确认 |
| 两个都不接受 | 滤波器本身也错了，三处一起核对 |
| ARXML 里没有 `CanHwFilter` | 无法裁决，需人工确认 |

实测案例：CDD `0x738` / CanIf `0x72F`，滤波器只接受 `0x738`（mask `0x7FE`）——
**错的是 CanIf**。改动方向明确，不用来回试。

---

## 五、时序

| 码 | 级别 | 判据 | 后果 |
|---|---|---|---|
| `CDX-020` | error | 会话的 `DcmDspSessionP2ServerMax` ≠ CDD `CAN.P2Server` | ECU 响应慢于测试仪等待，报无响应 |
| `CDX-021` | warn | `P2StarServerMax` ≠ `CAN.P2ExServer` | `0x78` 后的长耗时处理超时点不同，刷写中断 |
| `CDX-022` | warn | CDD 内部 `S3Client < S3Server` | 服务端保活短于客户端间隔，会话周期性掉回 Default |
| `CDX-023` | warn | `CanTpSTmin` ≠ CDD `CAN.StMin` | 多帧传输易丢帧 |
| `CDX-024` | warn | `CanTpBs` ≠ CDD `CAN.Blocksize` | 流控节奏错位 |
| `CDX-025` | warn | 上面五项属性有缺失 | `CDX-020~024` 未执行，报告不能当成通过 |

### 为什么用整数毫秒比较

CDD 写 `50`（毫秒），AUTOSAR 写 `0.05`（秒）。二进制浮点无法精确表示 `0.05`，
用相等判断会导致**每一个 P2 值都被报错**。所以统一转成整数毫秒，容差 `±1 ms`。

`CDX-022` 是**CDD 内部**自洽性检查，与 ARXML 无关 —— 它抓的是规范自己的笔误。

---

## 六、会话与安全访问

| 码 | 级别 | 判据 | 后果与指向 |
|---|---|---|---|
| `CDX-030` | error | 会话等级只在 CDD 定义，`DcmDspSessionRow` 里没有 | 切会话收 `0x12`。**改 ARXML** |
| `CDX-031` | error | 安全等级只在 CDD 定义，`DcmDspSecurityRow` 里没有 | 该等级下受保护服务全部无法解锁。**改 ARXML** |
| `CDX-032` | warn | 同一等级的 Seed 与 Key 长度不同 | 多数实现要求等长，需与供应商确认 |

### 安全等级的解析陷阱

CDD 的 `sec` 类诊断实例长这样：

```xml
<DIAGINST tmplref="...">
  <QUAL><TUV>SeedLevel1</TUV></QUAL>      ← 等级在这里（Level1）
  <STATICVALUE v='1'/>                     ← 这是子功能（1 = requestSeed）
</DIAGINST>
<DIAGINST tmplref="...">
  <QUAL><TUV>KeyLevel1</TUV></QUAL>
  <STATICVALUE v='2'/>                     ← 这是子功能（2 = sendKey）
</DIAGINST>
```

**`STATICVALUE` 是子功能，不是等级。** 若把它当等级，一个等级会被读成两个，
于是对只有 1 个 `DcmDspSecurityRow` 的 ARXML 报出「等级 2 缺失」的假错误。

解析顺序（`security_level_from_name()`）：

1. 名字里的 `Level<N>`（`SeedLevel1` → 1）
2. 名字整体是数字（`Level_1` → 1）
3. 都没有才退回子功能值

---

## 七、健全性

| 码 | 级别 | 判据 | 说明 |
|---|---|---|---|
| `CDX-040` | error | 一项都没比对上 | **不是「通过」**：文件拿错了或结构不符，先跑 `probe` |
| `CDX-041` | warn | 同一侧出现重复标识符 | 后者覆盖前者，行为取决于工具 |
| `CDX-042` | info | 文件概况 | 协议、DTD 版本、编码、模块数 |
| `CDX-044` | info | 服务覆盖 | CDD 的协议服务有多少能解析出服务号、哪些无法映射、Dcm 显式配了哪些 |

`CDX-040` 是本工具的**兜底闸门**：`0 error` 只有在「确实比较过东西」时才有意义。
如果 DID / DTC / CAN ID / 会话全都为空，脚本强制失败而不是报成功。

---

## 八、检查码清单（与代码双向断言）

```
error (10) CDX-001 004 006 010 012 013 020 030 031 040
warn  (12) CDX-002 003 005 007 011 021 022 023 024 025 032 041
info  (3)  CDX-042 043 044
```

`scripts/test_contract.py` 断言本文件列出的码与代码实际 emit 的码完全一致：
文档写了没实现 → 红；实现了没写文档 → 也红。

---

## 九、已知误报场景

| 场景 | 表现 | 处理 |
|---|---|---|
| 用 `0x29 Authentication` 替代 `0x27` | `CDX-031` 可能误报 | 确认后忽略，或等工具支持 0x29 |
| CDD 用 `RECORDDTPOOL` 而诊断实例不挂 DTC | `CDX-004` 数量偏大 | 先读 `CDX-043` 的说明再判断 |
| 同一 DID 在 CDD 中分多条定义（不同会话） | `CDX-041` 提示重复 | 属正常建模，非缺陷 |
| ARXML 未配 `CanHwFilter` | `CDX-010` 只说「无法判断哪边错」 | 属正常，人工裁决 |
