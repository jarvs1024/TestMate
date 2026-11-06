"""平台内置连接器注册表 —— 扩展库助手 + 知识库助手.

为什么不是普通资产:
    · 不落 GitLab —— 平台自己的一部分, 不该出现在仓库 index.json 里;
    · 静态展示 —— 永远在连接器分类里, 不参与上传/审核/下架流程;
    · 配置随环境自适应 —— MCP 地址不入库, 每次返回时按当前部署地址现拼;
    · 纯 HTTP 部署引导走 API Token —— 官方 MCP SDK 会拒绝明文 http 的
      OAuth token 端点, 所以生成配置时预置 headers 占位符.

实现: 启动时幂等种 Asset 行, 元信息每次启动刷新回常量 (内置内容以代码为准),
但保留运行时指标 (download_count / created_at). 同步器按 code 跳过.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset

BUILTIN_TOKEN_PLACEHOLDER = "<你的API Token>"


@dataclass(frozen=True, slots=True)
class BuiltinAsset:
    code: str
    mcp_path: str
    fields: dict[str, Any]


def _fields(code: str, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "code": code,
        "kind": "mcp",
        "version": "1.0.0",
        "project": "",
        "author": "admin",
        "featured": 0,
        "homepage": None,
        "permissions": {},
        "bindings": {},
        "git_path": "",
        "git_commit_sha": "",
        "sync_status": "pushed",
        "last_error": "",
        "publish_status": "published",
        "pending_action": "",
        "review_note": "",
        "mcp_config": None,
    }
    base.update(overrides)
    return base


EXTENSIONS_ASSET = BuiltinAsset(
    code="testmate-extensions",
    mcp_path="/mcp/skill",
    fields=_fields(
        "testmate-extensions",
        name="TestMate 扩展库助手",
        icon="🏪",
        summary="让 Agent 通过 MCP 直接检索、读取、上架与更新 TestMate 扩展库的插件 / 技能",
        description=(
            "TestMate 平台自带的资产管理 MCP 连接器。Agent 连上之后可以检索扩展库资产、"
            "查看文档与包内文件、上架新资产、发新版本、修改元信息并跟踪上传任务状态。"
        ),
        use_when="需要让 Agent 直接在会话里找扩展、看文档、上架或更新资产",
        not_for="不需要 Agent 操作扩展库的场景 —— 网页端操作即可",
        category="其他",
        tags=["内置", "扩展库", "MCP"],
        keywords=["内置", "扩展库", "资产", "MCP", "上架", "检索", "更新"],
        install_steps=[
            "复制本页的 MCP 配置 JSON, 把 server 条目加到 Agent 的连接器配置里 (Qoder: 设置 → 连接器 → 添加连接器 → 自定义)",
            "新建 API Token: 登录 TestMate → 个人中心 → 授权管理 → 新建 Token, 勾选 extensions:read",
            "把配置里 headers.Authorization 的「<你的API Token>」替换成刚建的 token",
            "重启 Agent 会话即可使用",
            "备注: token 绑定账号, 改密码会失效, 失效后换新 token 重新替换即可; 平台若改走 HTTPS, 可跳过第 2-3 步, 直接按 Agent 提示完成 OAuth 授权",
        ],
    ),
)

KB_ASSET = BuiltinAsset(
    code="testmate-kb",
    mcp_path="/mcp/kb",
    fields=_fields(
        "testmate-kb",
        name="TestMate 知识库助手",
        icon="📚",
        summary="让 Agent 检索知识库、读取分段，并向数据集上传或更新文档",
        description=(
            "TestMate 平台自带的知识库 MCP 连接器。Agent 连上之后可以浏览数据集与文档、"
            "查看分段、按问题检索，并上传或替换文档；二进制文件用上传票直传。"
        ),
        use_when="需要让 Agent 在会话里检索知识库、读取分段或上传 / 更新文档",
        not_for="只需要人工整理知识库的场景 —— 网页端操作即可",
        category="其他",
        tags=["内置", "知识库", "MCP"],
        keywords=["内置", "知识库", "文档", "检索", "MCP", "上传"],
        install_steps=[
            "复制本页的 MCP 配置 JSON, 把 server 条目加到 Agent 的连接器配置里",
            "新建 API Token: 登录 TestMate → 个人中心 → 授权管理 → 新建 Token, 勾选 kb:read, 需要写入再勾 kb:write",
            "把配置里 headers.Authorization 的「<你的API Token>」替换成刚建的 token",
            "重启 Agent 会话即可使用",
            "备注: PDF / Word / Excel 等二进制文件用 kb_document_write_ticket 签票后 curl 直传; 上传 / 替换只代表「已提交」, 解析完成情况用 kb_document_status 查询",
        ],
    ),
)

BUILTIN_ASSETS = (EXTENSIONS_ASSET, KB_ASSET)
_BY_CODE = {asset.code: asset for asset in BUILTIN_ASSETS}


def is_builtin_code(code: str) -> bool:
    return (code or "").strip() in _BY_CODE


def builtin_path(code: str) -> str | None:
    asset = _BY_CODE.get((code or "").strip())
    return asset.mcp_path if asset else None


def builtin_mcp_config(code: str, base: str) -> dict[str, Any]:
    """按部署地址现拼 MCP 配置 —— base 是平台从外面访问的根地址."""
    asset = _BY_CODE.get((code or "").strip())
    if asset is None:
        return {}
    b = (base or "").strip().rstrip("/")
    server: dict[str, Any] = {"url": f"{b}{asset.mcp_path}"}
    if not b.startswith("https://"):
        server["headers"] = {"Authorization": f"Bearer {BUILTIN_TOKEN_PLACEHOLDER}"}
    return {"mcpServers": {asset.code: server}}


async def ensure_builtin_assets(session: AsyncSession) -> None:
    """幂等种子: 没有就建, 有就刷新元信息 (保留 download_count / created_at)."""
    for asset in BUILTIN_ASSETS:
        row = (
            await session.execute(select(Asset).where(Asset.code == asset.code))
        ).scalar_one_or_none()
        if row is None:
            session.add(Asset(**asset.fields))
            continue
        for key, value in asset.fields.items():
            if key not in ("code", "mcp_config"):
                setattr(row, key, value)
    await session.commit()
