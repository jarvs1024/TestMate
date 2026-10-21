"""DB-backed settings 加载层。

设计:
- 优先级: 显式 env var > DB > 代码默认
- 后端代码不直接 import settings_store, 而是通过 get(key, default) 异步拿
- seed 把 .env 里的值首次落库, 后续 UI 改的就是 DB 里的
"""
from __future__ import annotations
import logging
import re
from typing import Any

from app.core.config import settings


def _rewrite_loopback(base: str) -> str:
    """用户在容器外用 127.0.0.1/localhost 配的地址,在容器内改成 host.docker.internal 才能到 host.

    生产环境如果服务在另一个 docker 容器里(用 service name),保持原样;
    只在 URL 用了 loopback 时改写.
    """
    if not base:
        return base
    return re.sub(
        r"https?://(?:127\.0\.0\.1|localhost)(?=[:/])",
        "http://host.docker.internal",
        base,
    )

logger = logging.getLogger(__name__)


# ===== 静态注册表 (P0 阶段用, 后期改成查 DB schema) =====
# value_type 告诉前端怎么渲染: string / secret / bool / int / url
SETTING_SCHEMA: list[dict] = [
    {
        "key": "ragflow.base_url",
        "category": "data-source",
        "value_type": "url",
        "default": settings.RAGFLOW_BASE_URL,
        "description": "RAGFlow API 基础地址 (例: http://host:9380/api/v1)",
        "is_secret": False,
    },
    {
        "key": "ragflow.api_key",
        "category": "data-source",
        "value_type": "secret",
        "default": settings.RAGFLOW_API_KEY,
        "description": "RAGFlow API Key (ragflow-xxxxx)",
        "is_secret": True,
    },
    {
        "key": "review_agent.base_url",
        "category": "data-source",
        "value_type": "url",
        "default": settings.REVIEW_AGENT_BASE_URL,
        "description": "ReviewAgent telemetry API 基础地址 (例: http://host.docker.internal:3000)",
        "is_secret": False,
    },
    {
        "key": "review_agent.api_token",
        "category": "data-source",
        "value_type": "secret",
        "default": settings.REVIEW_AGENT_API_TOKEN,
        "description": "ReviewAgent telemetry Bearer token (留空 = 不校验)",
        "is_secret": True,
    },
    {
        "key": "dify.base_url",
        "category": "data-source",
        "value_type": "url",
        "default": settings.DIFY_BASE_URL,
        "description": "Dify API 基础地址",
        "is_secret": False,
    },
    {
        "key": "dify.api_key",
        "category": "data-source",
        "value_type": "secret",
        "default": settings.DIFY_API_KEY,
        "description": "Dify API Key (app-xxxxx)",
        "is_secret": True,
    },
    {
        "key": "dify.mock_mode",
        "category": "data-source",
        "value_type": "bool",
        "default": settings.DIFY_MOCK,
        "description": "Dify mock 模式: 开则不调外部 Dify, 用 demo 流式返回 (沙箱环境用)",
        "is_secret": False,
    },
    {
        "key": "general.platform_name",
        "category": "general",
        "value_type": "string",
        "default": settings.APP_NAME,
        "description": "平台显示名 (顶栏 + 标题)",
        "is_secret": False,
    },

    # ===== 知识检索源 (知识库页 KB 嵌入的 iframe URL) =====
    # 设计: 任意 URL 都能塞, 换 RAGFlow / Dify / 其他都不需要改代码
    {
        "key": "search.engine",
        "category": "search",
        "value_type": "string",
        "default": "ragflow-share",
        "description": "检索源引擎: ragflow-share (RAGFlow 共享 Search App) / dify-chatbot / custom-url / none (显示建设中)",
        "is_secret": False,
    },
    {
        "key": "search.embed_url",
        "category": "search",
        "value_type": "url",
        "default": "http://127.0.0.1:18080/search/share?shared_id=ea62499872bb11f1a82f771aafbe4f81&from=search&auth=ir7sYP4h2kMSxcjSi2IfailLxbATmCdm&tenantId=7ddaa0b472b511f1a82f771aafbe4f81&visible_avatar=1&locale=zh-Hans",
        "description": "iframe 直接嵌入的 URL (RAGFlow 共享 search app / Dify chatbot / 任意可嵌入 URL)",
        "is_secret": False,
    },
    {
        "key": "search.label",
        "category": "search",
        "value_type": "string",
        "default": "基于 RAGFlow 共享 Search App",
        "description": "知识检索卡副标题 (说明底层引擎)",
        "is_secret": False,
    },
    {
        "key": "search.open_url_label",
        "category": "search",
        "value_type": "string",
        "default": "↗ 新窗口打开 RAGFlow 共享搜索",
        "description": "新窗口打开按钮文字",
        "is_secret": False,
    },
    {
        "key": "search.min_height",
        "category": "search",
        "value_type": "int",
        "default": 600,
        "description": "iframe 最小高度 (px), 搜索/对话两个 tab 共用",
        "is_secret": False,
    },
    {
        "key": "search.append_user_id",
        "category": "search",
        "value_type": "bool",
        "default": True,
        "description": "嵌入 URL 是否自动拼 &userId=<当前登录用户名>",
        "is_secret": False,
    },
    {
        "key": "search.append_theme",
        "category": "search",
        "value_type": "bool",
        "default": True,
        "description": "嵌入 URL 是否自动拼 &theme=<light/dark> (按浏览器当前主题)",
        "is_secret": False,
    },

    # ===== 知识对话源 (KB 页第二个 tab: chats/share, RAGFlow 共享 Chat App) =====
    {
        "key": "chat.embed_url",
        "category": "chat",
        "value_type": "url",
        "default": "http://127.0.0.1:18080/chats/share?shared_id=5338072a72bf11f1a82f771aafbe4f81&from=chat&auth=ir7sYP4h2kMSxcjSi2IfailLxbATmCdm&theme=dark",
        "description": "iframe 直接嵌入的 URL (RAGFlow 共享 Chat App / 任意可嵌入聊天页)",
        "is_secret": False,
    },
    {
        "key": "chat.label",
        "category": "chat",
        "value_type": "string",
        "default": "基于 RAGFlow 共享 Chat App",
        "description": "知识对话卡副标题 (说明底层引擎)",
        "is_secret": False,
    },
    {
        "key": "chat.open_url_label",
        "category": "chat",
        "value_type": "string",
        "default": "↗ 新窗口打开 RAGFlow 共享对话",
        "description": "新窗口打开按钮文字",
        "is_secret": False,
    },
    {
        "key": "chat.append_user_id",
        "category": "chat",
        "value_type": "bool",
        "default": True,
        "description": "嵌入 URL 是否自动拼 &userId=<当前登录用户名>",
        "is_secret": False,
    },
    {
        "key": "chat.append_theme",
        "category": "chat",
        "value_type": "bool",
        "default": True,
        "description": "嵌入 URL 是否自动拼 &theme=<light/dark> (按浏览器当前主题)",
        "is_secret": False,
    },
    # ===== AI 资产市场 =====
    {
        "key": "marketplace.publisher_ids",
        "category": "marketplace",
        "value_type": "string",
        "default": "[]",
        "description": "允许发布的用户 ID (JSON 数组, 如 [1,2]; admin 恒可发布)",
        "is_secret": False,
    },
    {
        "key": "marketplace.install.skill_dir",
        "category": "marketplace",
        "value_type": "string",
        "default": "~/.qoder-cn/skills",
        "description": "skill 安装目录 (宿主路径; 容器内 ~ 会翻译成 /host-home)",
        "is_secret": False,
    },
    {
        "key": "marketplace.install.plugin_dir",
        "category": "marketplace",
        "value_type": "string",
        "default": "~/.qoder-cn/plugins/cache/qoder-marketplace",
        "description": "plugin 安装目录 (对齐 Qoder 的 cache/<market>/<plugin>/<version> 布局)",
        "is_secret": False,
    },
    {
        "key": "marketplace.install.enabled",
        "category": "marketplace",
        "value_type": "bool",
        "default": "true",
        "description": "是否允许在服务端写盘安装 (关掉后只能走前端通道)",
        "is_secret": False,
    },
    {
        "key": "marketplace.sync.interval_seconds",
        "category": "marketplace",
        "value_type": "int",
        "default": "30",
        "description": "从 GitLab 拉取对齐的周期 (秒)",
        "is_secret": False,
    },
    {
        "key": "marketplace.max_package_mb",
        "category": "marketplace",
        "value_type": "int",
        "default": "50",
        "description": "上传安装包体积上限 (MB)",
        "is_secret": False,
    },
    {
        "key": "marketplace.marketplace_name",
        "category": "marketplace",
        "value_type": "string",
        "default": "testmate",
        "description": "对外 marketplace.json 的 name 字段 (决定 Qoder 缓存目录名)",
        "is_secret": False,
    },
    {
        "key": "marketplace.public_base_url",
        "category": "marketplace",
        "value_type": "url",
        "default": "",
        "description": "对外可达的基地址 (Qoder 拉 marketplace.json 与安装包用; 留空则用请求来源)",
        "is_secret": False,
    },
    # ===== 钉钉 (市场通知) =====
    {
        "key": "dingtalk.market_webhook",
        "category": "notification",
        "value_type": "url",
        "default": "",
        "description": "钉钉自定义机器人 webhook (市场上下架/更新通知用)",
        "is_secret": False,
    },
    {
        "key": "dingtalk.market_secret",
        "category": "notification",
        "value_type": "secret",
        "default": "",
        "description": "钉钉机器人加签密钥 (SEC 开头; 留空表示未开加签)",
        "is_secret": True,
    },
    {
        "key": "dingtalk.notify_on_publish",
        "category": "notification",
        "value_type": "bool",
        "default": "true",
        "description": "上架时通知钉钉群",
        "is_secret": False,
    },
    {
        "key": "dingtalk.notify_on_update",
        "category": "notification",
        "value_type": "bool",
        "default": "true",
        "description": "版本更新时通知钉钉群",
        "is_secret": False,
    },
    {
        "key": "dingtalk.notify_on_unpublish",
        "category": "notification",
        "value_type": "bool",
        "default": "true",
        "description": "下架时通知钉钉群",
        "is_secret": False,
    },
]


def get_schema() -> list[dict]:
    return SETTING_SCHEMA


# ===== DB 加载 / 兜底 =====

async def seed_defaults() -> None:
    """启动时:
    1) 把 SCHEMA 里有但 DB 里没有的, 用 .env default 落库
    2) 修正 DB 里 category 跟 SCHEMA 不一致的 (旧版本 category='knowledge' 现在拆成 'knowledge-source')
    """
    from app.db.session import AsyncSessionLocal
    from app.models.system_setting import SystemSetting
    from sqlalchemy import select

    expected_cat = {s["key"]: s["category"] for s in SETTING_SCHEMA}

    async with AsyncSessionLocal() as session:
        for s in SETTING_SCHEMA:
            existing = await session.get(SystemSetting, s["key"])
            if existing:
                # category 漂移修复: 跟 SCHEMA 对齐
                if existing.category != s["category"]:
                    logger.info("settings: fix category %s: %s -> %s", s["key"], existing.category, s["category"])
                    existing.category = s["category"]
                # .env 后填的非空值同步到 DB (DB 是空时, 用户后续改了 UI 不会被覆盖)
                env_v = s["default"]
                cur_v = existing.value.get("v") if isinstance(existing.value, dict) else existing.value
                if (cur_v in (None, "", [])) and env_v not in (None, "", []):
                    logger.info("settings: sync empty DB value from env: %s", s["key"])
                    existing.value = {"v": env_v} if not isinstance(env_v, (dict, list)) else env_v
                continue
            row = SystemSetting(
                key=s["key"],
                value=s["default"] if isinstance(s["default"], (dict, list)) else {"v": s["default"]},
                category=s["category"],
                description=s["description"],
                is_secret=s["is_secret"],
            )
            session.add(row)
        await session.commit()


async def get(key: str, default: Any = None) -> Any:
    """读一个 key 的值, fallback 到 schema default / 传入 default."""
    from app.db.session import AsyncSessionLocal
    from app.models.system_setting import SystemSetting

    async with AsyncSessionLocal() as session:
        row = await session.get(SystemSetting, key)
        if row is None:
            schema = next((s for s in SETTING_SCHEMA if s["key"] == key), None)
            return schema["default"] if schema else default
        v = row.value
        return v.get("v", default) if isinstance(v, dict) else v


async def get_all() -> dict[str, Any]:
    """批量读所有 setting (DB 优先, 缺则用 schema default)."""
    from app.db.session import AsyncSessionLocal
    from app.models.system_setting import SystemSetting
    from sqlalchemy import select

    out: dict[str, Any] = {}
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(SystemSetting))
        rows = {r.key: r for r in result.scalars().all()}
    for s in SETTING_SCHEMA:
        v = rows.get(s["key"])
        if v is None:
            out[s["key"]] = s["default"]
        else:
            raw = v.value
            out[s["key"]] = raw.get("v", s["default"]) if isinstance(raw, dict) else raw
    return out
