#!/usr/bin/env python3
"""构造**真实**的 skill 包 / plugin 包 (给端到端用).

之前 e2e 造的包是占位级的 (一个 SKILL.md + 一行 reference), 测不出:
- 多文件目录结构能不能正确落盘
- 非文本文件/子目录/隐藏目录 (如 .qoder-plugin/) 的处理
- 安装后产物是不是和包里逐字一致

所以这里造两个**结构完整、内容真实**的包:
  1. ssd-log-triage      —— skill:   SKILL.md + references/ + scripts/ + assets/
  2. qoder-trace-kit     —— plugin: .qoder-plugin/plugin.json + commands/ + agents/ + skills/ + hooks/

包内路径符合后端的约束:
- code 小写字母/数字/连字符, 3-64 字符
- 文件后缀必须在 ALLOWED_SUFFIXES 白名单内
- 不含 .git/.env/.ssh 等 FORBIDDEN_PARTS
- skill 必须有 SKILL.md, plugin 必须有 README.md 且含 .qoder-plugin/plugin.json

用法: python3 scripts/make_real_packages.py [--out-dir .e2e-out]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

# ======================= skill 包内容 =======================

SKILL_MD = """---
name: ssd-log-triage
description: 快速分诊 SSD/NVMe 失败日志, 定位介质错误、超时与掉盘根因。当用户提供 smartctl 输出、nvme-cli 日志或含 I/O error、Media and Data Integrity Error、Timeout、reset 的内核日志时使用。
allowed-tools: Read, Grep, Glob, Bash
metadata:
  version: 1.3.0
  maintainer: TestMate 平台组
  support: ssd-triage@internal.example.com
---

# SSD 日志分诊

给 SSD 现场故障做**第一轮分诊**: 读日志 → 判介质健康度 → 给下一步动作。

## 适用症状

- `I/O error`、`blk_update_request: critical medium error`
- `nvme timeout`、`Controller reset`
- SMART 里 `Media and Data Integrity Errors` 持续增长
- 盘偶发掉线、重挂后报 `rejecting I/O to offline device`

## 分诊步骤

1. **先看介质计数** —— `Media and Data Integrity Errors` 或 `Unsafe Shutdowns` 在增长,
   说明介质本身在坏, 换盘, 别再查链路。读 `references/nvme-error-codes.md` 对照错误码表。
2. **再看是不是超时** —— `nvme timeout` + `Abort Command` 通常是链路或控制器固件问题,
   介质计数不动。走 `scripts/scan_nvme_log.py` 扫一遍日志定位首次出现位置。
3. **最后看主机侧** —— `blk_update_request` 之后没有 I/O, 说明盘已经 offline,
   此时换盘也没用, 要先修 Host Bus / 驱动。

## 快速上手

```bash
python3 scripts/scan_nvme_log.py /var/log/messages --since "2026-10-01"
```

输出按错误类别聚合计数, 并打印每类首次出现的行号与时间。

## 输出

用 `assets/report-template.md` 的结构写分诊报告, 至少包含: 根因分类、证据行、
下一步动作、是否需要换盘。

## 不适用

- 固件升级 (走设备厂商流程, 不在本技能范围)
- RAID 重建期间的误报 (先看 RAID 卡状态)
"""

README_SKILL = """# SSD 日志分诊 (ssd-log-triage)

第一轮分诊工具: 读 SMART / nvme-cli / 内核日志, 判断是介质坏还是链路问题。

## 安装

放到 `~/.qoder-cn/skills/ssd-log-triage/` 即可被 Qoder 识别。

## 内容

| 路径 | 说明 |
|---|---|
| `SKILL.md` | 技能主文件 (frontmatter + 分诊流程) |
| `references/nvme-error-codes.md` | NVMe 错误码对照表 |
| `references/log-patterns.md` | 常见日志模式与含义 |
| `scripts/scan_nvme_log.py` | 日志扫描脚本 (可直接跑) |
| `assets/report-template.md` | 分诊报告模板 |
"""

NVME_ERROR_CODES = """# NVMe 错误码对照表

按 NVMe 1.4 规范的状态码整理, 附现场判断。

## 通用状态码

| 码 | 名称 | 含义 | 现场动作 |
|---|---|---|---|
| 0x01 | Invalid Command Opcode | 命令不支持 | 确认盘型号与主机 NVMe 驱动版本 |
| 0x02 | Invalid Field in Command | 字段非法 | 固件 bug, 升级固件 |
| 0x03 | SGL Invalid Data Length | SGL 长度错 | 驱动/固件不匹配 |
| 0x04 | Data Transfer Length Error | DMA 长度错 | 链路问题, 换线/换槽 |
| 0x05 | Commands Aborted due to Power Loss Notification | 掉电中止 | 检查供电与掉电保护 |
| 0x06 | Internal Error | 内部错误 | 换盘 |
| 0x07 | Command Abort Requested | 主机主动中止 | 多为超时后重试 |
| 0x18 | Namespace Not Found | 命名空间缺失 | 确认 nsid |
| 0x1F | Namespace Already Exists | 命名空间重复 | 检查挂载脚本 |
| 0x20 | Namespace In Capacity | 容量写满 | 清理/扩容 |
| 0x21 | Namespace Out of Capacity | 超容量写 | 检查 LBA 越界 |

## 媒体与数据完整性 (重点)

| 码 | 名称 | 含义 | 现场动作 |
|---|---|---|---|
| 0x81 | Write Fault | 写故障 | **换盘** |
| 0x82 | Unreliable Data | 数据不可靠 | **换盘**, 先备份 |
| 0x83 | Checksum Error | 校验错 | 介质坏, 换盘 |
| 0x84 | Degraded or Overwritten Data | 数据降级 | **换盘** |
| 0x85 | Media and Data Integrity Error | 介质与数据完整性错误 | **换盘**, 这是最常见的换盘信号 |

## 队列/超时类

| 码 | 名称 | 含义 | 现场动作 |
|---|---|---|---|
| 0x28 | Namespace Not Ready | 命名空间未就绪 | 重试 |
| 0x29 | Reservation Conflict | 保留冲突 | 多路径冲突 |
| 0x2A | Reservation Type Not Supported | 不支持保留类型 | 配置问题 |
| 0x70 | Completion Queue Timeout | 完成队列超时 | 链路/控制器 |
| 0x71 | Completion Queue Invalid | 完成队列失效 | 控制器复位 |
| 0x72 | Abort Command Timeout | 中止超时 | 盘无响应, **换盘或复位** |
| 0x73 | Aborted due to SQ Deletion | SQ 被删 | 驱动问题 |
| 0x74 | Aborted due to Failed Fused Command | 融合命令失败 | 固件问题 |

## 判读要点

- 出现 **0x85 / 0x81 / 0x84** 中任意一个 → 介质问题, 直接走换盘流程
- 只出现 **0x70 / 0x72** 而介质计数不涨 → 链路/控制器, 先换线换槽再考虑换盘
- SMART 的 `Media and Data Integrity Errors` 计数增长比日志更可靠
"""

LOG_PATTERNS = """# 常见日志模式

## 内核层

```
blk_update_request: I/O error, dev nvme0n1, sector 123456
blk_update_request: critical medium error, dev nvme0n1, sector 123456
```
→ 介质坏. `critical medium error` 是换盘的硬信号.

```
nvme nvme0: I/O 1234 at 0x0 timeout, reset controller
nvme nvme0: controller is down
```
→ 控制器超时/复位. 介质计数不动的话是链路问题.

```
rejecting I/O to offline device
```
→ 盘已经 offline. 换盘之前先修 Host Bus 或驱动.

```
nvme0n1: p1 p2 p3 ... (page 状态位)
```

## SMART (nvme-cli)

```
Critical Warning:        0x00
Temperature:            35 Celsius
Available Spare:        100%
Percentage Used:        3%
Data Units Written:     12,345,678
Media and Data Integrity Errors: 0
Error Information Log Entries: 0
```
→ `Media and Data Integrity Errors` 持续增长 = 介质坏.

## smartctl (SATA/SAS)

```
SMART overall-health self-assessment test result: PASSED
  187 Reallocated_Sector_Ct   0x0033   100   100   010    Pre-fail  Always       -       0
  188 Offline_Uncorrectable   0x0030   100   100   000    Old_age   Always       -       0
```
→ `Reallocated_Sector_Ct` 增长 = 介质开始坏; `Offline_Uncorrectable` > 0 = 已有不可恢复数据.

## 区分表

| 现象 | 介质 | 链路 | 主机 |
|---|---|---|---|
| critical medium error | ✓ | | |
| Media/Data Integrity Errors 增长 | ✓ | | |
| nvme timeout / reset | | ✓ | |
| DMA length error | | ✓ | |
| offline device | | | ✓ |
| I/O error 但介质计数不涨 | | ✓ | ✓ |
"""

SCAN_SCRIPT = '''#!/usr/bin/env python3
"""扫 NVMe/内核日志, 按错误类别聚合计数.

用法:
    python3 scan_nvme_log.py /var/log/messages [--since "2026-10-01"]
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
from pathlib import Path

CATEGORIES = [
    ("media", re.compile(r"critical medium error|media and data integrity|"
                         r"unreliable data|write fault|reallocated_sector", re.I)),
    ("offline", re.compile(r"rejecting I/O to offline device|device offline", re.I)),
    ("timeout", re.compile(r"nvme.*timeout|abort command|timed out", re.I)),
    ("reset", re.compile(r"controller reset|reset controller|nvme reset", re.I)),
    ("link", re.compile(r"pcie.*error|aer.*error|dma.*error|uncorrectable", re.I)),
    ("blk_io", re.compile(r"blk_update_request.*I/O error", re.I)),
]


def classify(line: str) -> str | None:
    for name, pat in CATEGORIES:
        if pat.search(line):
            return name
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="扫描 SSD/NVMe 日志并按类别聚合")
    ap.add_argument("logfile", help="日志文件路径")
    ap.add_argument("--since", default="", help="只看该日期之后的行 (YYYY-MM-DD)")
    args = ap.parse_args()

    path = Path(args.logfile)
    if not path.is_file():
        print(f"找不到日志文件: {path}", file=sys.stderr)
        return 2

    counts: collections.Counter[str] = collections.Counter()
    first: dict[str, tuple[int, str]] = {}
    since_re = re.compile(re.escape(args.since)) if args.since else None

    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, 1):
            if since_re and not since_re.search(line):
                continue
            cat = classify(line)
            if cat is None:
                continue
            counts[cat] += 1
            first.setdefault(cat, (lineno, line.rstrip()))

    if not counts:
        print("没有匹配到已知错误模式")
        return 0

    print("=== SSD/NVMe 日志分诊 ===")
    for cat, n in counts.most_common():
        lineno, text = first[cat]
        print(f"\\n[{cat}] {n} 次")
        print(f"  首次: 行 {lineno}: {text[:160]}")
        print(f"  建议: {_advice(cat)}")

    if counts.get("media", 0) > 0:
        print("\\n结论: 存在介质类错误 —— 优先走换盘流程。")
    elif counts.get("link", 0) or counts.get("timeout", 0):
        print("\\n结论: 未见介质错误, 更像链路/控制器问题 —— 先换线换槽。")
    else:
        print("\\n结论: 未见介质/链路错误 —— 检查主机侧与供电。")
    return 0


def _advice(cat: str) -> str:
    return {
        "media": "换盘 (介质坏, 软件无法修复)",
        "offline": "盘已 offline, 先修 Host Bus/驱动再换盘",
        "timeout": "换线换槽, 核对控制器固件版本",
        "reset": "查控制器固件与散热",
        "link": "PCIe AER / DMA 错误, 换槽并检查 BIOS 设置",
        "blk_io": "结合介质计数判断: 增长=换盘, 不涨=查链路",
    }.get(cat, "人工复核")


if __name__ == "__main__":
    sys.exit(main())
'''

REPORT_TEMPLATE = """# SSD 分诊报告

- **资产编号**:
- **盘型号 / 序列号**:
- **故障时间**:
- **分诊人**:

## 1. 根因分类

介质 / 链路 / 控制器 / 主机侧 / 待定

## 2. 证据

```
<关键日志行, 带时间戳与来源文件>
```

SMART 关键计数:
- Media and Data Integrity Errors:
- Percentage Used:
- Error Information Log Entries:

## 3. 判定依据

<为什么归到这一类, 对照 references/nvme-error-codes.md>

## 4. 下一步动作

- [ ] 备份数据 (Unreliable Data 时必须先备份)
- [ ] 换盘 / 换线 / 换槽
- [ ] 复测并记录

## 5. 是否需要换盘

是 / 否 —— 理由:
"""

SKILL_FILES = {
    "ssd-log-triage/SKILL.md": SKILL_MD,
    "ssd-log-triage/README.md": README_SKILL,
    "ssd-log-triage/references/nvme-error-codes.md": NVME_ERROR_CODES,
    "ssd-log-triage/references/log-patterns.md": LOG_PATTERNS,
    "ssd-log-triage/scripts/scan_nvme_log.py": SCAN_SCRIPT,
    "ssd-log-triage/assets/report-template.md": REPORT_TEMPLATE,
}

# ======================= plugin 包内容 =======================

PLUGIN_JSON = {
    "name": "trace-kit",
    "displayName": "Trace 分析工具包",
    "version": "1.2.0",
    "description": "SSD 抓 trace 的命令集、审查 agent 与采集后置校验, 覆盖从采集到出报告的全流程。",
    "author": {"name": "TestMate 平台组", "email": "trace-kit@internal.example.com"},
    "homepage": "https://internal.example.com/trace-kit",
    "license": "MIT",
    "keywords": ["trace", "ssd", "nvme", "抓取", "分析"],
    "commands": "./commands",
    "agents": "./agents",
    "skills": "./skills",
    "hooks": "./hooks/hooks.json",
}

PLUGIN_README = """# Trace 分析工具包 (trace-kit)

给 SSD trace 抓取场景用的 Qoder 插件: 命令集 + 审查 agent + 基础技能 + 采集后置校验。

## 组成

| 目录 | 内容 |
|---|---|
| `.qoder-plugin/plugin.json` | 插件清单 (Qoder 靠它识别插件) |
| `commands/` | 斜杠命令: `/trace:collect` 采集, `/trace:analyze` 分析 |
| `agents/` | `trace-reviewer` —— 审查 trace 完整性与异常 |
| `skills/trace-basics/SKILL.md` | trace 基础概念技能 |
| `hooks/hooks.json` | 采集结束后的后置校验 hook |

## 用法

1. `/trace:collect` —— 交互式引导采集 (指定盘符、时长、缓冲大小)
2. 采完自动触发 `hooks` 里的 `after-trace.sh` 做完整性校验
3. `/trace:analyze` —— 解析并出报告
4. 让 `trace-reviewer` agent 复核一遍

## 安装

放到 `~/.qoder-cn/plugins/cache/qoder-marketplace/trace-kit/<version>/`。
"""

TRACE_COLLECT_CMD = """---
description: 交互式采集 SSD trace
---

采集 SSD trace。

按顺序问用户并收集参数:

1. **目标盘** —— `/dev/nvme0n1` 或 `/dev/sda`, 必须确认
2. **时长** —— 默认 60s, 采集期间不要跑其他 IO
3. **缓冲大小** —— 默认 64MB, 内存不够就减
4. **模式** —— `ring` (环形覆盖) 或 `linear` (写满即停)

确认参数后执行:

```bash
sudo bpftrace trace-block -d $DEV 2>&1 | tee /tmp/trace-$(date +%Y%m%d-%H%M%S).txt
```

采完提示用户跑 `/trace:analyze`。
"""

TRACE_ANALYZE_CMD = """---
description: 解析 trace 并出报告
---

解析采集好的 trace 文件。

1. 定位文件 —— 默认取 `/tmp/trace-*.txt` 里最新的那个
2. 按 `skills/trace-basics/SKILL.md` 里的指标口径统计:
   - 延迟分布 (P50 / P99 / 最大)
   - 队列深度 (QD) 与延迟的对应关系
   - 错误与重试次数
   - 是否有写放大异常
3. 输出 Markdown 报告, 结构见下方

```markdown
## Trace 分析报告
- 文件:
- 采集时长:
- IO 总数:
### 延迟
| 指标 | 读 | 写 |
|---|---|---|
| P50 | | |
| P99 | | |
| Max | | |

### 异常
- ...

### 结论
- ...
```
"""

TRACE_REVIEWER_AGENT = """---
name: trace-reviewer
description: 审查 SSD trace 的完整性与异常, 在分析结论交付前做一遍独立复核。
tools: Read, Grep, Glob, Bash
---

你是 trace 审查员。拿到一份 trace 分析结论后, 独立复核。

## 审查清单

1. **采集完整性** —— 时长够不够? 有没有中途重启/丢段的迹象? 缓冲有没有写满?
2. **指标自洽** —— P99 和 Max 的比例是否合理? QD 与延迟是否单调?
3. **漏项** —— 有没有只看读没看写? 有没有忽略错误/重试?
4. **结论是否过度** —— 样本不足却下了确定性结论, 要指出来。

## 输出

```markdown
### 复核意见
- 结论: 通过 / 需修正
- 问题:
  1. ...
- 补充建议:
```

只报**具体问题**, 不复述原结论。
"""

TRACE_BASICS_SKILL = """---
name: trace-basics
description: SSD trace 采集与指标解读的基础口径, 涉及 latency、queue depth、IO 模式判断时使用。
---

# Trace 基础

## 采集

| 参数 | 常用值 | 说明 |
|---|---|---|
| 时长 | 30-120s | 越长越稳, 别在采集期跑其他 IO |
| 缓冲 | 32-128MB | 写满会丢最早的样本 |
| 模式 | ring | 环形覆盖, 适合长时间采集 |

## 指标口径

- **延迟** —— 从提交到完成, 分读/写; 报 P50/P99/Max, 不要只报平均
- **队列深度 QD** —— 同时在飞的请求数; QD 越高延迟越差是**正常**的,
  不随 QD 增长的延迟才是异常
- **写放大** —— 主机写入量 / NAND 实际写入量; SSD 内部有 FTL, 正常值在 1.1-3 之间

## 判读

- 延迟随 QD 线性增长 → 设备已饱和, 是容量问题
- QD 低但延迟高 → 单个请求慢, 查超时/重试
- 写时读放大异常高 → 查 FTL 垃圾回收
"""

HOOKS_JSON = json.dumps(
    {
        "hooks": {
            "afterTraceCollect": [
                {
                    "command": "hooks/after-trace.sh",
                    "timeout": 60,
                }
            ]
        }
    },
    ensure_ascii=False,
    indent=2,
)

AFTER_TRACE_SH = """#!/usr/bin/env bash
# trace 采集结束后的完整性校验.
set -uo pipefail

TRACE_FILE="${1:-}"
if [ -z "$TRACE_FILE" ] || [ ! -f "$TRACE_FILE" ]; then
  echo "[trace-kit] 未找到 trace 文件, 跳过校验" >&2
  exit 1
fi

SIZE=$(wc -c < "$TRACE_FILE" | tr -d ' ')
LINES=$(wc -l < "$TRACE_FILE" | tr -d ' ')
echo "[trace-kit] trace 文件: $TRACE_FILE (${LINES} 行, ${SIZE} 字节)"

if [ "$LINES" -lt 100 ]; then
  echo "[trace-kit] ⚠ 样本过少 (${LINES} 行), 结论可能不可靠" >&2
  exit 1
fi
if [ "$SIZE" -eq 0 ]; then
  echo "[trace-kit] ✗ trace 为空 —— 采集可能被中断" >&2
  exit 1
fi

echo "[trace-kit] ✓ 采集完整性校验通过"
exit 0
"""

PLUGIN_FILES = {
    "qoder-trace-kit/.qoder-plugin/plugin.json": json.dumps(
        PLUGIN_JSON, ensure_ascii=False, indent=2
    ),
    "qoder-trace-kit/README.md": PLUGIN_README,
    "qoder-trace-kit/commands/trace-collect.md": TRACE_COLLECT_CMD,
    "qoder-trace-kit/commands/trace-analyze.md": TRACE_ANALYZE_CMD,
    "qoder-trace-kit/agents/trace-reviewer.md": TRACE_REVIEWER_AGENT,
    "qoder-trace-kit/skills/trace-basics/SKILL.md": TRACE_BASICS_SKILL,
    "qoder-trace-kit/hooks/hooks.json": HOOKS_JSON,
    "qoder-trace-kit/hooks/after-trace.sh": AFTER_TRACE_SH,
}


# ======================= 打包 =======================

def write_zip(dest: Path, files: dict[str, str]) -> Path:
    """把 {归档内路径: 内容} 写成 zip (内容是 str → UTF-8)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, content in files.items():
            zi = zipfile.ZipInfo(rel, date_time=(2026, 10, 1, 12, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            z.writestr(zi, content.encode("utf-8"))
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description="构造真实的 skill / plugin 包")
    ap.add_argument("--out-dir", default=".e2e-out")
    args = ap.parse_args()

    out = Path(args.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)

    # ⚠️ 包名必须与资产 code 一致 (命名契约, 前后端都强制):
    #    skill → ssd-log-triage, plugin → qoder-trace-kit
    skill_zip = write_zip(out / "ssd-log-triage.zip", SKILL_FILES)
    plugin_zip = write_zip(out / "qoder-trace-kit.zip", PLUGIN_FILES)

    for label, zp, files in (
        ("skill ", skill_zip, SKILL_FILES),
        ("plugin", plugin_zip, PLUGIN_FILES),
    ):
        data = zp.read_bytes()
        print(f"[{label}] {zp}")
        print(f"        {len(files)} 个文件, {len(data)} 字节, sha256={hashlib.sha256(data).hexdigest()[:16]}")
        for rel in files:
            print(f"          - {rel}")

    # 顺便产出一份 JSON 清单, 端到端脚本用它逐字比对安装产物
    manifest = {
        "skill": {
            "zip": str(skill_zip),
            "files": {k: v for k, v in SKILL_FILES.items()},
        },
        "plugin": {
            "zip": str(plugin_zip),
            "files": {k: v for k, v in PLUGIN_FILES.items()},
        },
    }
    mpath = out / "real-packages-manifest.json"
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[清单] {mpath}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
