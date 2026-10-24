"""资产命名契约 —— code / 安装包名 / MCP 连接器名 三者的关系.

⚠️ 前后端**各有一份**实现 (前端 frontend_web/src/views/Market/assetForm.ts),
   改规则时**两边都要改** —— 这里定的是"宽松到不破坏存量"的那一版:

     · code 的**格式**: 前端要求 dml- 开头 (团队命名约定),
       后端只要求小写字母/数字/连字符 (存量 14 个资产的 code 不带前缀, 一刀切会锁死它们的更新)
     · **一致性** (code == 安装包名 / code == MCP 里的某个连接器名): **两端都强制**
       —— 这条是 2026-10-25 补上的: 以前只有前端管, 绕过前端直接调 API
       就能上架一个"资产号与包名对不上"的资产, 装出来/抄下来都对不上.
"""
from __future__ import annotations

# ⚠️ code 的**格式**规则不在这里 —— 唯一真源是 market_catalog.CODE_RE
#    (与前端 assetForm.CODE_PATTERN / SEGMENT_PATTERN 同一套分段规则).
#    这里以前自己留了一份**宽松的旧正则** —— 没人引用, 还跟权威版本不一致
#    (它收 "dml--x", 权威版本拒) → 已删, 免得两处规则各说各话.

# 安装包允许的扩展名 (前端 assetForm.ts 同款)
PACKAGE_SUFFIXES: tuple[str, ...] = (".zip", ".tar.gz", ".tgz")


def package_base_name(filename: str) -> str:
    """安装包文件名 → 资产 code (去掉扩展名)."""
    name = (filename or "").strip()
    lowered = name.lower()
    for suf in PACKAGE_SUFFIXES:
        if lowered.endswith(suf):
            return name[: -len(suf)]
    return name


def check_package_consistency(filename: str, code: str) -> str:
    """安装包名必须与资产 code 一致 —— 返回错误文案 (空串 = 一致).

    ⚠️ 只在**有包**的形态 (技能 / 插件) 上要求; 连接器没有包.
    """
    base = package_base_name(filename)
    if not base:
        return ""
    target = (code or "").strip()
    if base == target:
        return ""
    return f"安装包名必须与资产 code 一致 (包名是 {base}, 资产 code 是 {target})"


def check_mcp_code_consistency(mcp_config: dict | None, code: str) -> str:
    """连接器: 资产 code 必须是 MCP 配置里的**某一个**连接器名.

    详情页会**原样展示**这份配置, 用户照着加进自己的 MCP 配置里 ——
    资产号和配置里的名字对不上, 用户就分不清自己加的是哪个连接器.
    """
    if not mcp_config:
        return ""
    servers = mcp_config.get("mcpServers") or {}
    names = [n for n in servers.keys()]
    if not names:
        return ""
    target = (code or "").strip()
    if target in names:
        return ""
    return (
        f"资产 code 必须与 MCP 配置里的连接器名一致 "
        f"(配置里是 {', '.join(names)})"
    )
