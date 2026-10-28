"""DB-backed settings 加载层。

设计:
- 优先级: 显式 env var > DB > 代码默认
- 后端代码不直接 import settings_store, 而是通过 get(key, default) 异步拿
- seed 把 .env 里的值首次落库, 后续 UI 改的就是 DB 里的
"""
from __future__ import annotations
import logging
import os
import re
from typing import Any

from app.core.config import settings


# 容器判定结果缓存 —— 只算一次, 进程生命周期内不会变
_IN_CONTAINER: bool | None = None


def _detect_container() -> bool:
    """后端是不是跑在容器里.

    ⚠️ 这个判断决定 `_rewrite_loopback` 改不改写地址, 搞错会让"能连的服务"
       连不上 —— 所以宁可多判几个信号.
    """
    if os.path.exists("/.dockerenv"):
        return True
    if os.environ.get("KUBERNETES_SERVICE_HOST"):
        return True
    try:
        with open("/proc/1/cgroup", "r", encoding="utf-8") as f:
            cgroup = f.read()
    except OSError:
        return False
    return any(k in cgroup for k in ("docker", "containerd", "kubepods", "podman", "lxc"))


def _in_container() -> bool:
    """后端是不是跑在容器里 (带缓存).

    容器里的 127.0.0.1 是**容器自己**, 要到宿主得用 host.docker.internal;
    而**裸机部署**(systemd / macOS local)的后端就在宿主上跑, 这时 127.0.0.1
    正是宿主自己 —— 所以改写必须只在容器里做.
    """
    global _IN_CONTAINER
    if _IN_CONTAINER is None:
        _IN_CONTAINER = _detect_container()
    return _IN_CONTAINER


def _rewrite_loopback(base: str) -> str:
    """把地址里的"本机"改成**当前这个进程能连上的那个本机** —— 两个方向都改.

    为什么要有这层: 用户在设置页填 `http://127.0.0.1:3000` 指的是**宿主上**
    跑着的服务 (ReviewAgent / RAGFlow 都是宿主进程). 后端在容器里时, 容器的
    127.0.0.1 是容器自己, 必须换成 host.docker.internal 才到得了宿主.

    ⚠️ **以前是无条件改写的, 那是错的** ——
    裸机部署 (deploy/native 的 systemd 与 macOS local 两种 driver) 的后端
    就跑在宿主上, 此时的 127.0.0.1 正是宿主自己; 再改写成 host.docker.internal
    就连不通了 (宿主上那个名字解析到 Docker 虚拟网卡 198.18.x.x, 从宿主侧
    TCP 能连上但**没有服务应答** —— 症状是"测试连接"超时/502).
    症状: 设置页里把 ReviewAgent 地址填成 127.0.0.1, "测试连接"却报 HTTP 502,
    而且**用户改不回来** —— 改完还是被改写掉.

    所以现在是**双向**的:
      · 后端在容器里 → 127.0.0.1 / localhost  换成  host.docker.internal
      · 后端在宿主上 → host.docker.internal 换成  127.0.0.1

    好处: **同一个设置值在两种部署模式下都通** —— 填 127.0.0.1 或填
    host.docker.internal 都行, 不用为了切部署模式去改设置, 也不用改
    /etc/hosts (那要 root).

    生产环境如果服务在另一个 docker 容器里 (用 service name), 保持原样;
    只在 URL 用了 loopback / host.docker.internal 时改写.
    """
    if not base:
        return base
    if _in_container():
        # 容器里的 127.0.0.1 是容器自己 → 换成宿主名 (保留原协议!)
        return re.sub(
            r"(https?)://(?:127\.0\.0\.1|localhost)(?=[:/])",
            r"\1://host.docker.internal",
            base,
        )
    # 裸机部署: 后端就在宿主上, host.docker.internal 从宿主侧连不通 → 换回 127.0.0.1
    return re.sub(
        r"(https?)://host\.docker\.internal(?=[:/])",
        r"\1://127.0.0.1",
        base,
    )

logger = logging.getLogger(__name__)


# ===== 布尔值归一 =====
# DB 里同一个"开关"可能有三种存法: JSON 布尔 (true/false)、字符串 ("true"/"false")、
# 还有 1/0 —— 谁存的全看历史. 读的时候必须统一成真正的 bool, 否则:
#   - 前端 `!!"false"` → true → 开关显示成"开", 但后端当"关" (界面骗人)
#   - 后端 `bool("false")` → true → 以为功能开着, 其实早就关了
_TRUE_STRINGS = {"true", "1", "yes", "on"}
_FALSE_STRINGS = {"false", "0", "no", "off", ""}


def to_bool(value: Any, default: bool = False) -> bool:
    """把设置值统一成真正的 bool.

    ``default`` 只在**认不出**时用 (比如值是 "maybe"); 明确的 false 不会被当成空.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    if s in _TRUE_STRINGS:
        return True
    if s in _FALSE_STRINGS:
        return False
    return default


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
        "key": "general.platform_name",
        "category": "general",
        "value_type": "string",
        "default": settings.APP_NAME,
        "description": "平台显示名 (顶栏 + 标题)",
        "is_secret": False,
    },

    # ===== 知识检索源 (知识库页 KB 嵌入的 iframe URL) =====
    # 设计: 任意 URL 都能塞, 换 RAGFlow 或其他都不需要改代码
    {
        "key": "search.engine",
        "category": "search",
        "value_type": "string",
        "default": "ragflow-share",
        "description": "检索源引擎: ragflow-share (RAGFlow 共享 Search App) / custom-url / none (显示建设中)",
        "is_secret": False,
    },
    {
        "key": "search.embed_url",
        "category": "search",
        "value_type": "url",
        "default": "http://127.0.0.1:18080/search/share?shared_id=ea62499872bb11f1a82f771aafbe4f81&from=search&auth=ir7sYP4h2kMSxcjSi2IfailLxbATmCdm&tenantId=7ddaa0b472b511f1a82f771aafbe4f81&visible_avatar=1&locale=zh-Hans",
        "description": "iframe 直接嵌入的 URL (RAGFlow 共享 search app / 任意可嵌入 URL)",
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
    # ===== 插件·技能·连接 =====
    {
        "key": "marketplace.projects",
        "category": "marketplace",
        "value_type": "string",
        "default": "6100,3361,8560,9560,3100",
        "description": (
            "项目列表 (逗号分隔, 如 6100,3361) —— 上架资产时选「通用」或某个项目特有, "
            "市场页按项目筛选也用这份列表 (项目会增减, 加项目改这里就行, 不用发版)"
        ),
        "is_secret": False,
    },
    {
        "key": "marketplace.publisher_roles",
        "category": "marketplace",
        "value_type": "string",
        "default": "tester",
        "description": (
            "默认可发布的**角色** (逗号分隔, 如 tester) —— "
            "tester = 测试工程, 默认就能往市场里上传/更新资产; "
            "admin 恒可发布, 跟这里无关; "
            "清空 = 退回「只看白名单」的老行为"
        ),
        "is_secret": False,
        # ⚠️ 显式标 admin_only: 这条是**发布权限策略**, 泄露出去等于告诉
        #    普通用户"怎么绕过白名单" —— 别指望正则能一直兜住 (见 settings.py 的说明).
        "admin_only": True,
    },
    {
        "key": "marketplace.publisher_ids",
        "category": "marketplace",
        "value_type": "string",
        "default": "[]",
        "description": (
            "**额外**允许发布的用户 ID (JSON 数组, 如 [1,2]) —— "
            "给角色不在「publisher_roles」里的人开的口子; admin 恒可发布"
        ),
        "is_secret": False,
    },
    {
        "key": "marketplace.publisher_usernames",
        "category": "marketplace",
        "value_type": "string",
        "default": "",
        "description": (
            "**额外**允许发布的用户名 (逗号分隔, 如 zhangsan, lisi) —— 比填用户 ID 友好; "
            "与「publisher_ids」任一命中即可"
        ),
        "is_secret": False,
    },
    {
        "key": "marketplace.review.enabled",
        "category": "marketplace",
        "value_type": "bool",
        "default": "true",
        "description": (
            "上架是否需要管理员审核: 开 = 发布者上传后进入「待审核」, 管理员通过后才在市场可见; "
            "关 = 有发布权限的人直接上架 (恢复旧行为)"
        ),
        "is_secret": False,
    },
    {
        "key": "marketplace.review.reviewer_usernames",
        "category": "marketplace",
        "value_type": "string",
        "default": "",
        "description": (
            "可以审上架审核的用户 (逗号分隔, 如 zhangsan,lisi) —— "
            "团队里 admin 一个人审不过来时用. 管理员永远有审核权; "
            "审核人**只能审**, 不能改别人上传的资产"
        ),
        "is_secret": False,
    },
    {
        "key": "marketplace.review.admin_self_approve",
        "category": "marketplace",
        "value_type": "bool",
        "default": "true",
        "description": "管理员自己上传的资产是否免审 (免审 = 直接上架, 不用等别人审)",
        "is_secret": False,
    },
    {
        "key": "marketplace.git.max_push_attempts",
        "category": "marketplace",
        "value_type": "int",
        "default": "3",
        "description": "推送到 GitLab 失败时的自动重试次数 (超过就停下来等人工处理)",
        "is_secret": False,
    },
    {
        "key": "marketplace.upload.max_files",
        "category": "marketplace",
        "value_type": "int",
        "default": "200",
        "description": "单次上传允许的附加文本文件数上限",
        "is_secret": False,
    },
    {
        "key": "marketplace.upload.max_total_mb",
        "category": "marketplace",
        "value_type": "int",
        "default": "2",
        "description": "单次上传的文本文件总体积上限 (MB)",
        "is_secret": False,
    },
    {
        "key": "marketplace.git.remote",
        "category": "marketplace",
        "value_type": "string",
        "default": "ssh://git@host.docker.internal:8922/root/testmate-market.git",
        "description": (
            "GitLab 仓库地址 (SSH). 资产就是提交到这个仓库的 —— "
            "改完立即生效, 下次同步会用新地址"
        ),
        "is_secret": False,
        # ⚠️ SSH 地址里带**内网 host + 仓库路径** → 普通用户看到等于把
        #    资产仓库的位置交出去. 非管理员的 schema 里整条不给.
        "admin_only": True,
    },
    {
        "key": "marketplace.git.branch",
        "category": "marketplace",
        "value_type": "string",
        "default": "main",
        "description": "GitLab 分支 (资产提交到哪个分支)",
        "is_secret": False,
        # ⚠️ 和 remote 配套 —— remote 藏了 branch 露出来, 等于只藏了一半.
        "admin_only": True,
    },
    {
        "key": "marketplace.git.web_url",
        "category": "marketplace",
        "value_type": "url",
        "default": "",
        "description": (
            "GitLab 网页地址 (如 http://gitlab.local:8929/root/testmate-market), "
            "用于市场页上的「在 GitLab 查看」链接; 留空则不显示"
        ),
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
    {
        "key": "marketplace.public_download",
        "category": "marketplace",
        "value_type": "bool",
        "default": "false",
        "description": (
            "**允许未登录下载已上架资产的安装包** (只对 publish_status=published 的资产生效) —— "
            "关 = 下载必须带登录 token. "
            "开这个是因为 Qoder 原生安装器拉 marketplace.json 是公开的, 但它下载安装包时"
            "**带不了 TestMate 的登录 token**, 不开的话安装器必然 401. "
            "⚠️ 开了之后: 知道地址的人 (不用登录) 就能下载**已上架**资产的包; "
            "待审核/已下架的资产照旧要登录. 用之前先想清楚这批资产能不能对外."
        ),
        "is_secret": False,
        # ⚠️ 这是**对外暴露策略** —— 只给管理员看/改
        "admin_only": True,
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
        "default": True,
        "description": "**上架成功**时通知市场群, @所有人 (默认开启)",
        "is_secret": False,
    },
    {
        "key": "dingtalk.notify_on_update",
        "category": "notification",
        "value_type": "bool",
        "default": True,
        "description": "**版本更新**时通知市场群, @所有人 (默认开启)",
        "is_secret": False,
    },
    {
        "key": "dingtalk.notify_on_unpublish",
        "category": "notification",
        "value_type": "bool",
        "default": True,
        "description": "资产被**彻底下架**(移除)时通知市场群, @所有人 (默认开启)",
        "is_secret": False,
    },
    {
        "key": "dingtalk.notify_on_unpublish_request",
        "category": "notification",
        "value_type": "bool",
        "default": True,
        "description": "有人**申请下架**时通知审核群 (提醒管理员去确认; 默认开启)",
        "is_secret": False,
    },
    {
        "key": "dingtalk.notify_on_delete",
        "category": "notification",
        "value_type": "bool",
        "default": False,
        "description": "管理员**直接删除**资产时通知市场群, @所有人 (默认关闭)",
        "is_secret": False,
    },
    {
        "key": "dingtalk.notify_on_review",
        "category": "notification",
        "value_type": "bool",
        "default": True,
        "description": "有资产**待上架审核**时通知审核群 (默认开启)",
        "is_secret": False,
    },
    {
        "key": "dingtalk.notify_on_reject",
        "category": "notification",
        "value_type": "bool",
        "default": True,
        "description": "**上架审核未通过**时通知市场群, @发布者 (默认开启)",
        "is_secret": False,
    },
    {
        "key": "dingtalk.market_keyword",
        "category": "notification",
        "value_type": "string",
        "default": "",
        "description": (
            "钉钉机器人关键词 (自定义机器人默认开启关键词校验, "
            "消息里必须包含该词, 否则发不出去; 留空表示不启用)"
        ),
        "is_secret": False,
    },
    # ===== 审核通知频道 (另一个群) =====
    # 市场动作 (上架/更新/彻底下架) 走市场群, 审核相关 (待审核/驳回/删除) 走审核群.
    # 两个群通常是两个不同的机器人 —— 密钥和关键词各配各的.
    # (测试环境可以把两边配成一样的)
    {
        "key": "dingtalk.review_webhook",
        "category": "notification",
        "value_type": "url",
        "default": "",
        "description": "审核通知的钉钉机器人 webhook (待审核/驳回/删除 发到这个群)",
        "is_secret": False,
    },
    {
        "key": "dingtalk.review_secret",
        "category": "notification",
        "value_type": "secret",
        "default": "",
        "description": "审核群机器人的加签密钥 (SEC 开头; 留空表示未开加签)",
        "is_secret": True,
    },
    {
        "key": "dingtalk.review_keyword",
        "category": "notification",
        "value_type": "string",
        "default": "",
        "description": (
            "审核群机器人的关键词 (该群开了关键词校验才需要填; 留空表示不启用)"
        ),
        "is_secret": False,
    },
    # ===== 软件库 =====
    # ⚠️ 存储根目录是**部署形态**相关的:
    #    裸机 (tmctl.sh) 会把 SOFTWARE_STORAGE_PATH 写进 backend.env;
    #    容器 (docker-compose) 里是 /data/software (命名卷).
    #    这里留空 = 用环境变量; 都没配时退到 <repo>/data/software.
    {
        "key": "software.storage_path",
        "category": "software",
        "value_type": "string",
        "default": "",
        "description": (
            "软件包存放根目录. 留空 = 用环境变量 SOFTWARE_STORAGE_PATH, 都没有则用 <仓库>/data/software. "
            "⚠️ 填的是**当前进程能看到的路径**: 裸机填宿主路径, 容器模式通常留空 "
            "(compose 已用 /data/software 挂好卷, 手填宿主路径容器里看不见). "
            "⚠️ 改这里等于**换根目录** —— 老文件不会自动搬过去, "
            "点「体检存储目录」看缺哪些."
        ),
        "is_secret": False,
        # ⚠️ 显式标 admin_only: 这是**服务端文件路径**, 泄露等于告诉别人
        #    服务的目录结构 —— 而且只有管理员该有权限改它.
        "admin_only": True,
    },
    {
        "key": "software.max_size_mb",
        "category": "software",
        "value_type": "int",
        "default": "5120",
        "description": (
            "单个软件包大小上限 (MB). 默认 5120 = 5G. "
            "⚠️ 改大之前先确认 nginx 的 client_max_body_size 也放得开 —— "
            "两边都要够大, 否则会在 nginx 层被截掉 (返回 413)"
        ),
        "is_secret": False,
    },
    {
        "key": "software.keep_versions",
        "category": "software",
        "value_type": "int",
        "default": "10",
        "description": (
            "每个软件保留几个历史版本 —— 发新版本时超出就把**最老的**清掉 "
            "(文件也从磁盘上删). 设为 0 = 不清理, 全部保留. "
            "⚠️ 被标成「推荐下载」的版本**永远不会被清掉** —— "
            "所以实际最多留 N+1 个 (N 个最近的 + 1 个推荐版本)"
        ),
        "is_secret": False,
    },
    {
        "key": "software.public_download",
        "category": "software",
        "value_type": "bool",
        "default": "false",
        "description": (
            "未登录的人能不能下载软件包 (默认关). "
            "跟「插件·技能·连接」的同名开关一个口径 —— 开了等于把安装包公开出去"
        ),
        "is_secret": False,
    },
]

# 已废弃的设置项 —— 从 SCHEMA 移除后, DB 里的残留行在启动时一并清掉.
# 只列**明确废弃**的 key, 不会误伤用户自定义的设置.
# 服务端写盘安装通道下线: 安装统一在用户本机完成 (选目录 / 下载安装包),
# 服务端不再有"可配置的安装目录"这回事.
DEPRECATED_KEYS = (
    "marketplace.install.skill_dir",
    "marketplace.install.plugin_dir",
    "marketplace.install.enabled",
    # Dify 数据源整个下线 (2026-10-25): 平台不再接入 Dify,
    # 这三项从 SCHEMA 移除后, DB 里的残留行在启动时一并清掉.
    "dify.base_url",
    "dify.api_key",
    "dify.mock_mode",
)

# 默认值改版 —— DB 里还留着**旧默认值**的行, 启动时跟着改成新默认值.
#
# 为什么需要: seed_defaults 只在 DB 里**没有**这一行时才写默认值, 已经存在的行
# 永远不会被改回 —— 改了 SCHEMA 里的 default, 老环境还是老行为.
# 所以改默认值必须在这里登记一条, 启动时做一次性迁移.
#
# 规则: 只有 DB 值**等于旧默认值**时才改 (说明用户没自己动过); 用户手动改过的
# 值一律不动 —— 动了就说明那是用户的决定, 不能被默认值覆盖.
DEFAULT_CHANGES: dict[str, tuple[Any, Any]] = {
    # 钉钉市场通知的默认值改过一次又调回来 (2026-10-24):
    #   原始默认 "true" → 一律改成"默认不发" (别刷屏) → 最后只留
    #   **上架 / 更新 / 下架** 三个市场动作默认打开, 其余 (删除 / 待审核 / 驳回) 关闭.
    #
    # 登记的是**当前这一跳**: 旧默认 False → 新默认 True.
    # DB 里存着 false 的行 (等于旧默认) 迁到 true;
    # 一直就是 true 的行不动 (值不等于旧默认 = 用户自己设过).
    "dingtalk.notify_on_publish": (False, True),
    "dingtalk.notify_on_update": (False, True),
    "dingtalk.notify_on_unpublish": (False, True),
    # ---- 通知流程重排 (2026-10-24 晚): 审核相关的也默认开 ----
    # 上架待审核 / 审核不通过 / 下架申请 —— 都是"要有人处理"的事, 默认该通知.
    "dingtalk.notify_on_review": (False, True),
    "dingtalk.notify_on_reject": (False, True),
}


def _same_value(cur: Any, target: Any) -> bool:
    """DB 里的值跟目标默认值是否等价 (bool 认 "true"/True/1 都一样)."""
    if isinstance(target, bool) or isinstance(cur, bool):
        return to_bool(cur) == to_bool(target)
    return str(cur).strip() == str(target).strip()


def get_schema() -> list[dict]:
    return SETTING_SCHEMA


# ===== DB 加载 / 兜底 =====

async def seed_defaults() -> None:
    """启动时:
    1) 把 SCHEMA 里有但 DB 里没有的, 用 .env default 落库
    2) 修正 DB 里 category 跟 SCHEMA 不一致的 (旧版本 category='knowledge' 现在拆成 'knowledge-source')
    3) 清掉已废弃的 key (从 SCHEMA 移除后, DB 里的残留行一并删掉)
    4) 把还留着**旧默认值**的行迁移到新默认值 (见 DEFAULT_CHANGES)
    """
    from app.db.session import AsyncSessionLocal
    from app.models.system_setting import SystemSetting
    from sqlalchemy import select

    expected_cat = {s["key"]: s["category"] for s in SETTING_SCHEMA}

    async with AsyncSessionLocal() as session:
        for s in SETTING_SCHEMA:
            existing = await session.get(SystemSetting, s["key"])
            is_bool = s["value_type"] == "bool"
            if existing:
                # category 漂移修复: 跟 SCHEMA 对齐
                if existing.category != s["category"]:
                    logger.info("settings: fix category %s: %s -> %s", s["key"], existing.category, s["category"])
                    existing.category = s["category"]
                cur_v = existing.value.get("v") if isinstance(existing.value, dict) else existing.value
                # 默认值改版迁移 —— DB 值还等于旧默认值 → 换成新默认值
                change = DEFAULT_CHANGES.get(s["key"])
                if change is not None:
                    old_v, new_v = change
                    if _same_value(cur_v, old_v):
                        logger.info(
                            "settings: 默认值已变更, 同步旧值 %s: %r -> %r", s["key"], cur_v, new_v
                        )
                        existing.value = {"v": new_v}
                        cur_v = new_v
                # .env 后填的非空值同步到 DB (DB 是空时, 用户后续改了 UI 不会被覆盖)
                env_v = s["default"]
                if (cur_v in (None, "", [])) and env_v not in (None, "", []):
                    logger.info("settings: sync empty DB value from env: %s", s["key"])
                    existing.value = {"v": env_v} if not isinstance(env_v, (dict, list)) else env_v
                # bool 开关统一存成真正的 JSON 布尔 —— 字符串 "false" 会让前端开关显示成"开"
                if is_bool and isinstance(existing.value, dict) and "v" in existing.value:
                    norm = to_bool(existing.value.get("v"))
                    if existing.value.get("v") != norm:
                        logger.info("settings: 归一 bool 值 %s: %r -> %r", s["key"], existing.value.get("v"), norm)
                        existing.value = {"v": norm}
                continue
            row = SystemSetting(
                key=s["key"],
                value=s["default"] if isinstance(s["default"], (dict, list)) else {"v": s["default"]},
                category=s["category"],
                description=s["description"],
                is_secret=s["is_secret"],
            )
            if is_bool:
                row.value = {"v": to_bool(s["default"])}
            session.add(row)

        # 废弃 key 清理 —— 只删**明确列出来的**, 不会误伤用户自定义的设置
        for key in DEPRECATED_KEYS:
            row = await session.get(SystemSetting, key)
            if row is not None:
                logger.info("settings: 清理已废弃的设置项 %s", key)
                await session.delete(row)

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
    """批量读所有 setting (DB 优先, 缺则用 schema default).

    bool 类型的设置统一返回**真正的布尔** —— 前端开关是 `!!value` 判定的,
    字符串 "false" 会被当成真, 界面显示成"开"但后端其实当"关"在跑.
    """
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
            raw = s["default"]
        else:
            stored = v.value
            raw = stored.get("v", s["default"]) if isinstance(stored, dict) else stored
        if s["value_type"] == "bool":
            raw = to_bool(raw, to_bool(s["default"]))
        out[s["key"]] = raw
    return out
