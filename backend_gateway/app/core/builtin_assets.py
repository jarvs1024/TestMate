"""平台内置连接器 —— 扩展库里的那张「内置 MCP」卡片.

为什么不是普通资产 (2026-11-04, 用户要求):
    · **不落 GitLab** —— 它是平台自己的一部分, 不该出现在仓库 index.json 里;
    · **静态展示** —— 永远在连接器分类里, 不参与上传/审核/下架流程;
    · **配置随环境自适应** —— MCP 地址 (base + /mcp/skill) 不入库,
      每次返回时按当前部署的 public_base_url / 请求地址现拼,
      本地 8081 和生产域名各自正确.

实现: 启动时幂等种一条 Asset 行 (种子数据), 元信息每次启动刷新回常量
(内置内容以代码为准), 但**保留运行时指标** (download_count / created_at).
同步器 (`apply_index_to_db`) 会跳过这条 code, 远端 index 覆盖不到它.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset

BUILTIN_CODE = "testmate-extensions"
BUILTIN_MCP_SERVER = "testmate-extensions"
BUILTIN_MCP_PATH = "/mcp/skill"

BUILTIN_FIELDS: dict[str, Any] = {
    "code": BUILTIN_CODE,
    "name": "TestMate 扩展库助手",
    "icon": "🏪",
    "kind": "mcp",
    "version": "1.0.0",
    "summary": "让 Agent 通过 MCP 直接检索、读取、上架与更新 TestMate 扩展库的插件 / 技能",
    "description": (
        "TestMate 平台自带的资产管理 MCP 连接器。Agent 连上之后可以检索扩展库资产、"
        "查看文档与包内文件、上架新资产、发新版本、修改元信息并跟踪上传任务状态。"
    ),
    "use_when": "需要让 Agent 直接在会话里找扩展、看文档、上架或更新资产",
    "not_for": "不需要 Agent 操作扩展库的场景 —— 网页端操作即可",
    "category": "其他",
    "project": "",
    "tags": ["内置", "扩展库", "MCP"],
    "keywords": ["内置", "扩展库", "资产", "MCP", "上架", "检索", "更新"],
    "author": "admin",
    "featured": 0,
    "homepage": None,
    "permissions": {},
    "install_steps": [
        "在宿主 MCP 配置中新增 server: testmate-extensions",
        "url 填本平台的 /mcp/skill 地址 (下方配置里已带好)",
        "按 Agent 提示完成 OAuth 授权",
        "重启 Agent 会话",
    ],
    "bindings": {},
    "git_path": "",
    "git_commit_sha": "",
    "sync_status": "pushed",
    "last_error": "",
    "publish_status": "published",
    "pending_action": "",
    "review_note": "",
    # mcp_config 故意**不写** —— 按请求动态生成 (见 builtin_mcp_config)
    "mcp_config": None,
}


def is_builtin_code(code: str) -> bool:
    return (code or "").strip() == BUILTIN_CODE


def builtin_mcp_config(base: str) -> dict[str, Any]:
    """按部署地址现拼 MCP 配置 —— base 是"平台从外面访问的根地址". """
    b = (base or "").strip().rstrip("/")
    return {"mcpServers": {BUILTIN_MCP_SERVER: {"url": f"{b}{BUILTIN_MCP_PATH}"}}}


async def ensure_builtin_asset(session: AsyncSession) -> Asset | None:
    """幂等种子: 没有就建, 有就刷新元信息 (保留 download_count / created_at)."""
    a = (
        await session.execute(select(Asset).where(Asset.code == BUILTIN_CODE))
    ).scalar_one_or_none()
    if a is None:
        a = Asset(**BUILTIN_FIELDS)
        session.add(a)
    else:
        for key, value in BUILTIN_FIELDS.items():
            if key not in ("code", "mcp_config"):
                setattr(a, key, value)
    await session.commit()
    return a
