# DBC 文件编码问题

DBC 是纯文本格式，**没有编码声明**。这导致同一个文件在不同工具里表现不同。

## 为什么会遇到

国内主机厂和供应商的矩阵多由中文团队维护，注释（`CM_`）里直接写中文。生成工具（Excel 宏、MATLAB 脚本、自研导出器）常按 Windows 默认代码页写盘，即 **GBK / CP936**。

## 各工具的表现

| 工具 | GBK 文件的表现 |
|---|---|
| Vector CANoe / CANdb++ | 正常显示中文 |
| Python `open(f)` 默认 UTF-8 | `UnicodeDecodeError` 崩溃 |
| `cantools` | **静默跳过**坏字节，注释全丢，看起来「成功」 |
| `git diff` | 视作二进制，无法逐行比较 |
| 多数 CI/日志工具 | 乱码 |

第二行最危险：**它不报错**，所以问题会一直藏着。

## 识别

```bash
python skills/dbc-matrix-audit/scripts/dbc_analyze.py info matrix.dbc
```

输出里看 `encoding` 一行：

```
encoding        gbk  [not UTF-8]
```

## 定位第一个坏字节

```python
raw = open("matrix.dbc", "rb").read()
try:
    raw.decode("utf-8")
except UnicodeDecodeError as e:
    print("first bad byte at offset", e.start)
    print("context:", raw[max(0, e.start - 40):e.start + 10])
```

典型输出：

```
first bad byte at offset 27075
context: b'design this message`\r\n(VIU_2A4\xa3\xa8x2A4))a'
```

`\xa3\xa8` 是 GBK 的全角左括号 `（`。逐字节看就能确认是 GBK 而非其他编码。

## 转码

```bash
python skills/dbc-matrix-audit/scripts/dbc_analyze.py fix-encoding \
    matrix.dbc matrix_utf8.dbc
```

内部逻辑：按检出的编码解码 → 以 UTF-8 重新写盘（换行统一为 `\n`）。

## 转码后要验证什么

1. **结构不变**：报文数、信号数、位定义应完全一致（`fix-encoding` 的测试覆盖了这一点）
2. **中文正常**：`signals` 子命令能看到注释
3. **再跑一次 lint**：`ENC-001` 应消失

```bash
python skills/dbc-matrix-audit/scripts/dbc_analyze.py lint matrix_utf8.dbc
```

## 附：CRLF 与混合换行

部分导出器会混用 `\r\n` 与 `\n`。`fix-encoding` 统一写成 `\n`；若上游工具链要求 CRLF，转码后自行转换：

```bash
unix2dos matrix_utf8.dbc
```

## 附：BOM

UTF-8 带 BOM 的文件（`\xef\xbb\xbf` 开头）多数工具能读，但某些严格解析器会把首行的 `VERSION` 认成 `\ufeffVERSION` 而报未知关键字。本工具把 `utf-8-sig` 视为干净，并在读取时自动剥离。
