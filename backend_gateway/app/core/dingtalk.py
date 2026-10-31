"""钉钉机器人通知 (自定义机器人 · 加签模式).

加签算法 (官方):
    timestamp = 毫秒时间戳
    string_to_sign = f"{timestamp}\\n{secret}"
    sign = url_quote_plus( base64( hmac_sha256(key=secret, msg=string_to_sign) ) )

最后一步 url_quote_plus **最易漏** —— 漏了会返回 "sign not match".

用法:
    from app.core.dingtalk import notify_market
    await notify_market("publish", name="SSD 日志医生", version="1.0.0", actor="jarvs")

失败一律只记日志, 绝不抛给调用方 —— 通知失败不应该让发布事务回滚.
但**失败不能就这么算了**: 每次尝试都落一张回执 (asset_notifications),
后台按指数退避重试, 前端能查到"这条通知到底送没送到".
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import time
import urllib.parse
from contextvars import ContextVar
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select

from app.core.settings_store import get, to_bool
from app.db.session import AsyncSessionLocal
from app.models.asset import AssetNotification

logger = logging.getLogger(__name__)

TIMEOUT = 10.0
# 单条通知最多自动重试几次
MAX_ATTEMPTS = 5
# 退避基数 (秒): 30s, 60s, 120s, 240s
RETRY_BASE_SEC = 30
# 重试扫描间隔 (秒)
RETRY_SCAN_SEC = 30

# ---------- 「平台是从哪个地址被访问的」 (2026-10-31 · 第十三轮) ----------
#
# 通知正文里那个「去市场看看 / 去软件库看看」的链接, 得是**同事点得开**的地址.
# ⚠️ 写死一个地址 (如 http://127.0.0.1:8081) 有三个问题:
#    ① 换台机部署 → 链接指到别的机器去了;
#    ② 同事从 http://10.0.0.5:8081 访问 → 那个 127.0.0.1 是**他自己**的电脑;
#    ③ 用域名访问 → 链接还是 IP, 看着就不对.
#    所以改成**动态推断**: 从这次请求的 Host 头反推"用户实际访问的地址".
#
# _request_base_url —— ContextVar, **当前请求**的基地址 (请求链里共享).
# _last_base_url    —— 进程内缓存「最近一次推断到的」, 给**后台任务**用
#                     (聚合汇总 worker / 重试 worker 不在请求上下文里, 但它们也要发带链接的消息).
_request_base_url: ContextVar[str] = ContextVar("tm_request_base_url", default="")
_last_base_url: str = ""


def _sanitize_host(host: str) -> str:
    """主机头清洗 —— 只留「像主机名/端口」的东西.

    ⚠️ 为什么必须洗: host 是**客户端可控**的请求头, 直接拼进通知里的链接,
       就能被构造成钓鱼链接 (比如 `evil.com/#` 这种带路径的).
       这里只放行字母数字、点、横线、冒号 —— 域名和端口够了.
    """
    h = (host or "").strip()
    if not h:
        return ""
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-:")
    if any(c not in allowed for c in h):
        return ""
    return h


def set_request_base_url(base: str) -> None:
    """中间件调用: 记下"这次请求是从哪个地址进来的".

    传空串 = 清掉**当前请求**的记录 (但保留进程内缓存, 供后台任务用).
    """
    global _last_base_url
    b = (base or "").strip().rstrip("/")
    if b:
        _last_base_url = b
    _request_base_url.set(b)


def get_request_base_url() -> str:
    """当前请求的基地址 —— 没有请求上下文时回落到「最近一次推断到的」."""
    return _request_base_url.get() or _last_base_url


def reset_base_url_cache() -> None:
    """清掉「进程内缓存的基地址」—— **只给测试用**.

    ⚠️ 生产里这个缓存是**故意**跨请求保留的 (后台 worker 没请求上下文, 要靠它),
       所以别在业务代码里调 —— 只有单测需要 (免得一个用例推断出的地址漏给下一个).
    """
    global _last_base_url
    _last_base_url = ""
    _request_base_url.set("")


# ---------- 平台账号 → 钉钉 userid 映射 (2026-10-31 · 第十三轮) ----------
#
# ⚠️ 为什么需要这个表:
#    通知里要 @ 某个**具体的人** (如「审核不通过, @发布者」), 钉钉接口的
#    `atUserIds` 要的是**钉钉 userid**, 不是平台账号名.
#    平台这边只知道账号名 (admin / zhangsan / xxx@twsc.com.cn),
#    两边对不上 → 把账号名塞进 atUserIds 是**无效的**, 人根本收不到提醒.
#    (只有账号名恰好等于钉钉 userid 的情况才会中 —— 那属于巧合.)
#
# ⚠️ 仓库里没有"账号 ↔ 钉钉 userid"的对照表, 也不该写死在代码里 ——
#    让管理员在设置里自己填:  dingtalk.userid_map = "admin=manager1234;zhangsan=lin.san"
#
# ⚠️ 填不上怎么办: **只保留正文里的 "@账号名" 文字点名**, atUserIds 里**不放无效 id**
#    —— 塞一个钉钉不认识的 id 只会变成噪音, 还会让 at 名单看起来"我明明 @ 了人".
_USERID_MAP_KEY = "dingtalk.userid_map"


def parse_userid_map(raw: str) -> dict[str, str]:
    """解析 `账号=userid;账号2=userid2` → {账号(小写): userid}.

    容错: 逗号/换行/多余空格都吃掉; 缺 "=" 的片段直接跳过 (不报错, 免得一行写错
    就让**所有**通知都发不出去).
    """
    out: dict[str, str] = {}
    for chunk in (raw or "").replace("\n", ";").replace(",", ";").split(";"):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        acc, _, uid = chunk.partition("=")
        acc = acc.strip().lower()
        uid = uid.strip()
        if acc and uid:
            out[acc] = uid
    return out


async def resolve_userid(account: str) -> str:
    """平台账号名 → 钉钉 userid. 查不到返回空串 (调用方据此决定不 @)."""
    acc = (account or "").strip().lower()
    if not acc:
        return ""
    raw = (await get(_USERID_MAP_KEY, "")) or ""
    mapping = parse_userid_map(raw)
    if acc in mapping:
        return mapping[acc]
    # ⚠️ 跟 isAuthor() 一个口径: 全邮箱 `zhangsan@twsc.com.cn` 也认短名 `zhangsan`
    local = acc.split("@", 1)[0]
    return mapping.get(local, "")

# ---------- 审核类通知的窗口合并 (2026-10-28) ----------
#
# 为什么只合并**审核类**事件 (review / unpublish_request):
#   · 审核类是「要人去做一件事」—— 管理员的动作是"打开审核台看全部待办",
#     逐条消息反而刷屏, 合并成一条汇总更省事.
#   · 市场群那几类 (publish / update / unpublish / reject / delete) 是
#     「资产已经变了」的**事实通告**, 而且 @所有人 —— 合并会丢信息,
#     谁上架了什么都要看得见, 保持一条一个.
_AGGREGATED_EVENTS = ("review", "unpublish_request")
# 合并窗口 (秒): 窗口内的同类事件只发第一条, 其余攒成一条汇总.
# 可在设置里改 (dingtalk.aggregate_window_seconds).
AGGREGATE_WINDOW_DEFAULT = 60
# 汇总消息最多列出几个资产名 (超了只报数量)
AGGREGATE_MAX_NAMES = 8
# 聚合扫描间隔 (秒) —— 窗口到了要把攒着的发出去
AGGREGATE_SCAN_SEC = 10

_worker: asyncio.Task | None = None
_aggregate_worker: asyncio.Task | None = None


def sign(secret: str, timestamp_ms: int) -> str:
    """钉钉加签. 返回可直接放进 URL 的签名串."""
    string_to_sign = f"{timestamp_ms}\n{secret}"
    digest = hmac.new(
        secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256
    ).digest()
    return urllib.parse.quote_plus(base64.b64encode(digest).decode("utf-8"))


def build_signed_url(webhook: str, secret: str) -> str:
    ts = int(round(time.time() * 1000))
    return (
        f"{webhook}{'&' if '?' in webhook else '?'}"
        f"timestamp={ts}&sign={sign(secret, ts)}"
    )


async def send_markdown(
    webhook: str,
    title: str,
    text: str,
    *,
    secret: str = "",
    at_mobiles: list[str] | None = None,
    at_user_ids: list[str] | None = None,
    is_at_all: bool = False,
) -> dict[str, Any]:
    """发一条 markdown 消息. 失败抛异常, 由调用方决定怎么处理.

    ⚠️ @人的规矩: **正文里必须带上 @xxx**, 钉钉才会把它渲染成提醒 ——
       只在 at 字段里写是不生效的.
    """
    url = build_signed_url(webhook, secret) if secret else webhook
    body: dict[str, Any] = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": text},
    }
    if at_mobiles or at_user_ids or is_at_all:
        body["at"] = {
            "atMobiles": at_mobiles or [],
            "atUserIds": at_user_ids or [],
            "isAtAll": bool(is_at_all),
        }
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(url, json=body)
    if r.status_code >= 400:
        raise RuntimeError(f"钉钉 HTTP {r.status_code}: {r.text[:200]}")
    try:
        return r.json()
    except Exception:
        return {"raw": r.text[:200]}


# ---------- 市场通知 ----------

# 通知事件表 (2026-10-24 重排):
#
#   审核群 (审核钉钉) —— 需要管理员**处理**的事:
#       review            上架待审核
#       unpublish_request 下架申请
#   市场群 (用户群钉钉) —— 资产**已经变了**的事:
#       publish  上架成功 @所有人
#       update   版本更新 @所有人
#       unpublish 彻底下架 @所有人
#       reject   上架审核不通过 @发布者
#       delete   管理员直接删除 @所有人
#   软件库 (也走市场群, 同一个机器人) —— 2026-10-30 加:
#       software_publish 新软件上架
#       software_update  软件新版本
#       ⚠️ 这两个**共用一个开关** (dingtalk.notify_on_software) ——
#          用户原话「上架和发布新版本共有一个配置」.
_EVENT_TEXT = {
    "review": "📋 新资产待审核",
    "unpublish_request": "🗑 申请下架, 待确认",
    "publish": "🎉 新资产上架",
    "update": "📦 资产版本更新",
    # ⚠️ 2026-10-30 (第十一轮): 软件库的通知 —— 走市场群, 但文案要说清是"软件包"
    "software_publish": "📦 新软件上架",
    "software_update": "🆙 软件新版本",
    # ⚠️ 2026-10-31 (第十三轮): 软件**下架**也要通知 ——
    #    之前软件库根本没有"下架"这条通知 (静默下架, 谁都不知道那个软件没了).
    "software_unpublish": "🗑 软件已下架",
    # ⚠️ unpublish = **彻底下架** (资产已从市场移除), 不是"有人申请下架".
    #    申请阶段走 unpublish_request 事件 (发审核群).
    "unpublish": "🗑 资产已下架",
    "delete": "🗑 资产已删除",
    "reject": "❌ 资产审核未通过",
}

# 窗口合并时用的汇总标题 (按事件分开 —— 审核和下架是两件事, 混一起会让人看不懂)
# ⚠️ 2026-10-30 (第十二轮): 审核汇总标题**去掉「上架」** ——
#    审核队列里现在不只有"上新东西", 还有"只改了信息" (meta) 的,
#    写成「等上架审核」会让管理员以为都是新包.
_AGGREGATE_SUMMARY_TITLE = {
    "review": "📋 另有资产在等审核",
    "unpublish_request": "🗑 另有资产在等下架确认",
}

_SWITCH_KEY = {
    "review": "dingtalk.notify_on_review",
    "unpublish_request": "dingtalk.notify_on_unpublish_request",
    "publish": "dingtalk.notify_on_publish",
    "update": "dingtalk.notify_on_update",
    "unpublish": "dingtalk.notify_on_unpublish",
    "delete": "dingtalk.notify_on_delete",
    "reject": "dingtalk.notify_on_reject",
    # ⚠️ 2026-10-30 (第十一轮): 软件库的「上架」和「发布新版本」**共用一个开关** ——
    #    用户原话「上架和发布新版本共有一个配置」.
    #    所以两个 event 映射到**同一个**设置项 —— 开关打开 = 两个都发, 关掉 = 两个都不发.
    # ⚠️ 2026-10-31 (第十三轮): 「下架」也归到**同一个**开关 ——
    #    软件库的事就一个开关, 免得设置页里一堆软件相关的开关.
    "software_publish": "dingtalk.notify_on_software",
    "software_update": "dingtalk.notify_on_software",
    "software_unpublish": "dingtalk.notify_on_software",
}

# ---------- 两个通知频道 (两个群) ----------
# 审核群: 需要管理员处理的事 (上架审核 / 下架申请)
# 市场群: 资产已经变了的事 (上架 / 更新 / 彻底下架 / 审核不通过 / 删除)
#
# 每个频道有自己的一套 webhook / 加签密钥 / 关键词 —— 两个群通常是两个不同的机器人,
# 密钥和关键词校验都不一样. (测试环境可以把两边配成一样的)
_CHANNEL_OF_EVENT = {
    # 审核群
    "review": "review",
    "unpublish_request": "review",
    # 市场群
    "publish": "market",
    "update": "market",
    "unpublish": "market",
    "reject": "market",
    "delete": "market",
    # ⚠️ 2026-10-30 (第十一轮): 软件库**也走市场群** ——
    #    用户原话「钉钉在设置中配置……为了测试, 可以用市场的通知中配置的钉钉信息」.
    #    也就是说: 不新增第三个机器人, 直接复用市场那套 webhook/加签/关键词.
    #    以后想分开群, 再加一套独立配置也不迟 —— 那时只要改这里的映射.
    "software_publish": "market",
    "software_update": "market",
    # ⚠️ 2026-10-31 (第十三轮): 软件下架也走市场群 (同一个机器人)
    "software_unpublish": "market",
}

_CHANNEL_KEYS = {
    "market": (
        "dingtalk.market_webhook",
        "dingtalk.market_secret",
        "dingtalk.market_keyword",
    ),
    "review": (
        "dingtalk.review_webhook",
        "dingtalk.review_secret",
        "dingtalk.review_keyword",
    ),
}

_CHANNEL_LABEL = {"market": "市场群", "review": "审核群"}

# 资产类型 → 中文 (通知里要说明"这是个啥": skill 还是插件)
# ⚠️ 跟 UI 的说法**保持一致** (页签/形态选择器/上传表单都叫「技能」) ——
#    这里以前叫「技能包」, 同一件事两种叫法, 收到通知的人会以为是两种东西.
_KIND_LABEL = {
    "skill": "技能",
    "plugin": "插件",
    "mcp": "连接器",
    # ⚠️ 2026-10-30 (第十一轮): 软件库的条目 —— 通知里要跟插件/技能/连接器**区分开**
    "software": "软件包",
}

# 各事件默认 @ 谁:
#   at_all=True  → @所有人 (资产变了, 大家都该知道)
#   at_author    → @发布者 (他的东西被拒了, 得让他知道)
_EVENT_AT = {
    "review": {"at_all": False, "at_author": False},
    "unpublish_request": {"at_all": False, "at_author": False},
    "publish": {"at_all": True, "at_author": False},
    "update": {"at_all": True, "at_author": False},
    "unpublish": {"at_all": True, "at_author": False},
    "reject": {"at_all": False, "at_author": True},
    "delete": {"at_all": True, "at_author": False},
    # ⚠️ 2026-10-31 (第十三轮): 软件库三个事件**都 @所有人** ——
    #    用户原话「软件上架要@所有人的, 下架软件也要通知@所有人」.
    #    · 上架   → 有新软件了, 大家都该知道;
    #    · 新版本 → 有新版可下, 跟资产的 update 一个口径;
    #    · 下架   → 那个软件没了, **更**要所有人知道 (别再去找它了).
    "software_publish": {"at_all": True, "at_author": False},
    "software_update": {"at_all": True, "at_author": False},
    "software_unpublish": {"at_all": True, "at_author": False},
}

# ⚠️ 2026-10-30 (第十一轮): 通知里「说明/更新」那一行的**标签** ——
#    上架说的是"这东西是干嘛的", 更新说的是"这次改了啥" —— 标签得分开.
_NOTE_LABEL = {
    "publish": "说明",
    "update": "更新",
    "software_publish": "说明",
    "software_update": "更新",
    # ⚠️ 2026-10-31 (第十三轮): 下架说的是"这个软件没了", 不是"它干嘛的"
    "software_unpublish": "下架说明",
}

# 通知里「查看详情」链接的**相对路径** (按事件) + 链接文字.
# ⚠️ 用户要求: 插件/技能/连接器 → /market; 软件包 → /software.
_DEFAULT_LINK_PATH = {
    "publish": "/market",
    "update": "/market",
    "software_publish": "/software",
    "software_update": "/software",
    # ⚠️ 2026-10-31 (第十三轮): 软件下架 → 也指向软件库
    "software_unpublish": "/software",
}
_LINK_TEXT = {
    "/market": "去市场看看",
    "/software": "去软件库看看",
}


async def _channel_config(channel: str) -> tuple[str, str, str]:
    """取某个频道的 (webhook, 加签密钥, 关键词)."""
    wh_key, sec_key, kw_key = _CHANNEL_KEYS.get(channel, _CHANNEL_KEYS["market"])
    webhook = (await get(wh_key, "")) or ""
    secret = (await get(sec_key, "")) or ""
    keyword = ((await get(kw_key, "")) or "").strip()
    return webhook, secret, keyword


async def _deliver(
    webhook: str,
    secret: str,
    title: str,
    text: str,
    *,
    at_user_ids: list[str] | None = None,
    is_at_all: bool = False,
) -> None:
    await send_markdown(
        webhook, title, text, secret=secret,
        at_user_ids=at_user_ids, is_at_all=is_at_all,
    )


# ---------- 审核类通知的窗口合并 (2026-10-28) ----------
#
# 背景: 审核通知是「要人去做一件事」—— 管理员的动作是"打开审核台看全部待办",
#   逐条消息只会把群刷屏 (10 个人同时上架 = 10 条消息).
# 做法: **首条照常发** (带完整详情, 管理员第一时间知道有人上传了),
#   **窗口内的其余攒起来**, 窗口末发一条「另有 N 个在等审核」的汇总.
#
# ⚠️ 状态存 DB (asset_notifications) 而不是内存 —— 进程重启不能把攒着的通知弄丢.
# ⚠️ 市场群那几类 (publish / update / unpublish / reject / delete) **不合并**:
#    那是「资产已经变了」的事实通告而且 @所有人, 合并会让人漏看谁上架了什么.


async def _aggregate_window_seconds() -> int:
    """合并窗口 (秒). 0 = 不合并 (一条一个, 恢复原行为)."""
    raw = await get("dingtalk.aggregate_window_seconds", AGGREGATE_WINDOW_DEFAULT)
    try:
        n = int(str(raw).strip())
    except (TypeError, ValueError):
        n = AGGREGATE_WINDOW_DEFAULT
    return max(0, n)


async def _last_sent_at(event: str) -> datetime | None:
    """最近一条**已发出**的同类通知时间 —— 窗口的起点.

    ⚠️ 汇总消息本身也算"已发出": 刚发过汇总, 后面窗口内的事件应该并进
       **下一轮**汇总, 而不是又单独发一条 (否则汇总完又立刻来一条单发).
    """
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(AssetNotification)
                .where(
                    AssetNotification.event == event,
                    AssetNotification.status.in_(("sent", "summary_sent")),
                )
                .order_by(AssetNotification.id.desc())
                .limit(1)
            )
        ).scalars().first()
    return row.created_at if row is not None else None


async def _within_window(event: str, window: int) -> bool:
    """现在还在窗口里吗 (窗口内 → 并入汇总, 不单独发)."""
    last = await _last_sent_at(event)
    if last is None:
        return False
    return (datetime.utcnow() - last).total_seconds() < window


async def _review_entry_link() -> str:
    """审核入口链接 —— 没有对外基地址就**不给链接** (别发一个打不开的地址)."""
    base = (await get("marketplace.public_base_url", "") or "").strip().rstrip("/")
    if not base:
        return ""
    return f"{base}/market?status=pending"


async def _notify_base_url() -> str:
    """通知正文里「查看详情」链接的基地址 (2026-10-30 加, 2026-10-31 改动态).

    ⚠️ 取值顺序 (2026-10-31 第十三轮改成**动态优先**):
        ① `dingtalk.notify_base_url` —— 显式配置, **优先**.
           留空 = 自动按实际访问地址推断 (见下面的 ②).
           用户主动配了就听用户的 (比如要发公网域名给外部人看).
        ② **动态推断** —— "这次请求是从哪个地址进来的".
           同事在浏览器里打开 `http://10.0.0.5:8081`, 通知里的链接就该是
           `http://10.0.0.5:8081/market`, 点开就在他眼前 —— 而不是某个写死的 IP.
           ⚠️ 请求头 `Host` 被 nginx 改成了 `$host` (**不含端口**),
              所以后端优先读 nginx 专门透传的 `X-Forwarded-Host` ($http_host, 含端口).
        ③ `marketplace.public_base_url` —— 市场的对外基地址 (给 Qoder 装包用的).
        ④ 都没有 → **不给链接** (别发一个打不开的地址).

    ⚠️ 为什么不只用 `marketplace.public_base_url`:
        那个是给 **Qoder 装包**用的对外地址 (可能是公网域名/CDN),
        而通知链接是给**同事**点的 —— 同一台机器上, 内网地址更顺手.
        两个用途分开配, 才不会一边改坏另一边.
    """
    # ① 显式配置优先 (用户主动指定了就听用户的)
    base = (await get("dingtalk.notify_base_url", "") or "").strip().rstrip("/")
    if base:
        return base
    # ② 动态推断 (这次请求实际是从哪个地址进来的)
    base = get_request_base_url().strip().rstrip("/")
    if base:
        return base
    # ③ 市场的对外基地址
    base = (await get("marketplace.public_base_url", "") or "").strip().rstrip("/")
    return base


async def _pending_summary_receipt(event: str, summary_title: str):
    """还没发出去的**汇总**回执 (上一轮发送失败留下的).

    ⚠️ 为什么要复用它: 汇总发送失败时, 聚合 worker 和重试 worker 都会盯着这条 ——
       两个 worker 各发一遍 = 群里收到两条一样的汇总. 复用同一条回执,
       谁先发成功就只发出去一次.
    """
    async with AsyncSessionLocal() as session:
        row = (
            await session.execute(
                select(AssetNotification)
                .where(
                    AssetNotification.event == event,
                    AssetNotification.status.in_(("pending", "failed")),
                    AssetNotification.title.contains(summary_title),
                )
                .order_by(AssetNotification.id.desc())
                .limit(1)
            )
        ).scalars().first()
    return row


async def _flush_event(event: str, window: int) -> int:
    """把某事件攒着的通知发成**一条**汇总. 返回 1 (发了) / 0 (没发)."""
    now = datetime.utcnow()
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(AssetNotification)
                .where(
                    AssetNotification.event == event,
                    AssetNotification.status == "aggregated",
                )
                .order_by(AssetNotification.id.asc())
            )
        ).scalars().all()
    if not rows:
        return 0
    last = await _last_sent_at(event)
    if last is not None and (now - last).total_seconds() < window:
        return 0        # 窗口还没到, 继续等

    channel = _CHANNEL_OF_EVENT.get(event, "market")
    webhook, secret, keyword = await _channel_config(channel)
    if not webhook:
        return 0

    summary_title = _AGGREGATE_SUMMARY_TITLE.get(event, "📋 另有资产待处理")
    n = len(rows)
    body = "\n".join((r.text or "").strip() for r in rows if (r.text or "").strip())
    text = f"### {summary_title} · 另有 {n} 个"
    if body:
        text += f"\n{body}"
    link = await _review_entry_link()
    if link:
        text += f"\n- [去审核台]({link})"
    title = f"{summary_title} · 另有 {n} 个"
    if keyword:
        text = f"{keyword}\n{text}"
        title = f"{keyword} · {title}"

    # 上一轮发送失败 → 复用那条回执 (别再造一条, 否则两个 worker 各发一遍)
    existing = await _pending_summary_receipt(event, summary_title)
    if existing is not None:
        if existing.next_retry_at is not None and existing.next_retry_at > now:
            return 0        # 还在退避窗口里 —— 交给重试 worker, 别硬发
        async with AsyncSessionLocal() as session:
            cur = await session.get(AssetNotification, existing.id)
            if cur is None:
                return 0
            cur.asset_name = f"{n} 个资产"
            cur.title = title
            cur.text = text
            await session.commit()
        row = existing
    else:
        row = await _create_receipt(event, "", f"{n} 个资产", title, text, status="pending")
    ok = await _attempt(row, webhook, secret, sent_status="summary_sent")
    if not ok:
        return 0
    # 被这条汇总涵盖的几条, 标成"已并入汇总" —— 以后别再发一遍
    async with AsyncSessionLocal() as session:
        for r in rows:
            cur = await session.get(AssetNotification, r.id)
            if cur is not None:
                cur.status = "aggregated_sent"
        await session.commit()
    logger.info("dingtalk 聚合汇总已发送: event=%s count=%d", event, n)
    return 1


async def flush_aggregated_notifications() -> int:
    """窗口到期 → 把攒着的审核通知发成汇总. 返回发了几条."""
    window = await _aggregate_window_seconds()
    if window <= 0:
        return 0
    n = 0
    for event in _AGGREGATED_EVENTS:
        try:
            n += await _flush_event(event, window)
        except Exception as e:  # noqa: BLE001 — 一条失败不能影响别的
            logger.warning("dingtalk 聚合汇总失败 event=%s err=%s", event, e)
    return n


async def _render_market_body(
    event: str,
    *,
    name: str,
    version: str = "",
    actor: str = "",
    detail: str = "",
    link: str = "",
    code: str = "",
    kind: str = "",
    category: str = "",
    project: str = "",
    author: str = "",
    title_override: str = "",
    summary: str = "",
    release_notes: str = "",
    at_all: bool | None = None,
    at_author: bool | None = None,
) -> tuple[list[str], list[str], str]:
    """构造通知正文 —— 返回 (行, 汇总用的属性, 标题文案).

    ⚠️ **抽出来是为了两件事** (2026-10-30 第十一轮):
        ① `notify_market` 发送时用;
        ② `preview_market_message` **干跑预览**时用 ——
           消息长什么样要能**单独看**, 不能为了看一眼就得真往群里发一条.

    body_bits 是**汇总用的**: 审核类通知在窗口里会合并成一条汇总,
    每个资产只占一行 (名字 + 属性), 正常消息的名字在标题行里.
    """
    # ⚠️ 标题可覆盖 (如「重新上架」别写成「新资产上架」), 但事件 key 不变 ——
    #    开关映射 (dingtalk.notify_on_publish 等) 靠 key, 改了会关掉/打开错开关.
    event_text = title_override or _EVENT_TEXT.get(event, "通知")
    lines = [f"### {event_text} · {name}"]
    body_bits: list[str] = []
    # 类型要说清楚 —— 收到通知的人得知道这是个技能还是插件 (还是软件包)
    kind_line = f"- 类型: {_KIND_LABEL.get(kind, kind)}" if kind else ""
    if category:
        kind_line += f" · {category}"
    if kind_line:
        lines.append(kind_line)
        body_bits.append(kind_line.removeprefix("- 类型: "))
    if project:
        # 适用项目: 只有**项目特有**的资产才写这行 (通用的不占地方)
        line = f"- 适用项目: {project} 项目"
        lines.append(line)
        body_bits.append(f"{project} 项目")
    if version:
        lines.append(f"- 版本: `{version}`")
        body_bits.append(f"v{version}")
    if actor:
        lines.append(f"- 操作人: {actor}")
        body_bits.append(f"操作人 {actor}")
    # ⚠️ 2026-10-30 (第十一轮): 「这玩意儿是干嘛的 / 这次改了啥」——
    #    有简介或更新说明时**取代** detail (detail 只是"发生了什么"的套话,
    #    跟标题重复), 并且**标签按事件分**:
    #      上架 → 说明: xxx  (是干嘛的)
    #      更新 → 更新: xxx  (这次改了啥)
    #    都没有 → 退回 detail (老逻辑: 这次操作发生了什么).
    note = (release_notes or summary or "").strip()
    if note:
        label = _NOTE_LABEL.get(event, "说明")
        lines.append(f"- {label}: {note}")
        body_bits.append(note)
    elif detail:
        # ⚠️ detail 是**这次操作发生了什么** (如"审核不通过"), 不是资产的简介 ——
        #    把简介塞进来会变成"说明: 把测试数据整理成报告", 看着像重复了一遍简介.
        # ⚠️ 2026-10-31 (第十三轮): 标签也走 _NOTE_LABEL ——
        #    软件下架的 detail 说的是"它没了", 标成「说明」读着别扭, 该标「下架说明」.
        lines.append(f"- {_NOTE_LABEL.get(event, '说明')}: {detail}")
        body_bits.append(detail)
    # ---- 链接 ----
    # ⚠️ 2026-10-30 (第十一轮): 没显式传 link 时**按事件给默认链接** ——
    #    用户要求「最后附上链接: 插件相关的 /market, 软件库相关的 /software」.
    #    没有对外基地址就**不给链接** (别发一个打不开的地址).
    link_path = ""
    if not link:
        link_path = _DEFAULT_LINK_PATH.get(event, "")
        if link_path:
            base = await _notify_base_url()
            link = f"{base}{link_path}" if base else ""
    if link:
        text = _LINK_TEXT.get(link_path, "查看详情")
        lines.append(f"- [{text}]({link})")
    elif event in _AGGREGATED_EVENTS:
        # 审核类通知**带入口** —— 收到消息的人得知道去哪儿审,
        # 不然又是一条"看到了但不知道该干嘛"的通知.
        entry = await _review_entry_link()
        if entry:
            lines.append(f"- [去审核台]({entry})")

    # ---------- @谁 (2026-10-31 第十三轮: 挪进渲染层) ----------
    # ⚠️ 以前 @ 是在 `notify_market` 里发送前才拼的 → **预览里看不到**,
    #    管理员在设置页「👀 预览消息」看到的正文跟真发出去的不一样.
    #    现在统一在渲染层拼: 预览 = 真发出去的样子.
    # ⚠️ 钉钉要正文里带 "@xxx" 才渲染成提醒 (at 字段只是"谁被 @" 的名单).
    at_rule = _EVENT_AT.get(event, {"at_all": False, "at_author": False})
    do_at_all = at_rule["at_all"] if at_all is None else at_all
    do_at_author = at_rule["at_author"] if at_author is None else at_author
    if do_at_all:
        lines.append("@所有人")
    if do_at_author and author:
        # ⚠️ 账号名是**平台账号**, 不是钉钉 userid ——
        #    真能 @ 到人得靠 `dingtalk.userid_map` (见 resolve_userid).
        #    这里只是正文点名, 渲染层不该去查表 (预览是纯渲染).
        if actor and actor != author:
            lines.append(f"@{author} (提交人: {actor})")
        else:
            lines.append(f"@{author}")
    return lines, body_bits, event_text


async def preview_market_message(event: str, **kw) -> dict[str, Any]:
    """**干跑**: 只渲染消息, **不发送** —— 用来预览/自检消息长什么样.

    ⚠️ 绝对不碰 webhook —— 这个函数只拼字符串, 一行网络请求都不发.
       (线上要真发, 走 notify_market.)
    """
    lines, body_bits, event_text = await _render_market_body(event, **kw)
    title = f"{event_text} · {kw.get('name', '')}"
    return {
        "event": event,
        "title": title,
        "text": "\n".join(lines),
        "lines": lines,
        "body_bits": body_bits,
    }


async def notify_market(
    event: str,
    *,
    name: str,
    version: str = "",
    actor: str = "",
    detail: str = "",
    link: str = "",
    code: str = "",
    kind: str = "",
    category: str = "",
    author: str = "",
    project: str = "",
    at_all: bool | None = None,
    at_author: bool | None = None,
    title_override: str = "",
    summary: str = "",
    release_notes: str = "",
) -> bool:
    """发一条市场通知. 返回是否发送成功 (失败只记日志, 不抛).

    event: review | unpublish_request | publish | update | unpublish | reject | delete
           | software_publish | software_update   (2026-10-30 加软件库两个)
    按事件自动选频道:
      审核群 —— 需要管理员处理的事 (上架审核 / 下架申请)
      市场群 —— 资产已经变了的事 (上架 / 更新 / 彻底下架 / 审核不通过 / 删除)
      软件库那两个也走市场群 (同一个机器人)

    kind / category: 通知里要说明"这是个啥" (技能? 插件? 连接器? 软件包?)
    project: 适用项目 (空 = 通用; 有值才写这一行)
    author: 发布者 —— 审核不通过时要 @他
    at_all / at_author: 覆盖事件默认的 @ 策略 (一般不用传)
    title_override: 覆盖标题文案 —— **事件 key 不变** (开关映射必须稳定),
        只是同一个事件在不同场景下标题不一样 (如「重新上架」不是「新资产上架」)

    ⚠️ summary / release_notes (2026-10-30 加) —— 通知正文里那一行"这玩意儿是干嘛的":
        · summary       = 资产/软件的**简介** (上架时最该说清楚的就是这个);
        · release_notes = **这次更新了啥** (软件库有, 市场没有这个字段);
        · 两者都传 → release_notes 优先 (更新事件更该说"改了啥");
        · 都没有 → 退回 detail (老逻辑: 这次操作发生了什么).
    """
    if event not in _EVENT_TEXT:
        logger.warning("dingtalk.notify_market 未知事件: %s", event)
        return False

    channel = _CHANNEL_OF_EVENT.get(event, "market")
    try:
        webhook, secret, keyword = await _channel_config(channel)
        # ⚠️ 默认**不通知** —— 开关默认关, 要发自己去设置里打开.
        #    (值可能是 JSON 布尔 / "true" 字符串 / 1, 统一用 to_bool 判)
        enabled = to_bool(await get(_SWITCH_KEY[event], False))
        if not enabled:
            logger.info("dingtalk 通知开关已关闭, 跳过 (%s)", event)
            return False
        if not webhook:
            logger.info(
                "dingtalk 未配置 %s 频道的 webhook, 跳过通知 (%s)",
                _CHANNEL_LABEL.get(channel, channel), event,
            )
            return False
    except Exception as e:  # noqa: BLE001
        logger.warning("dingtalk 读取配置失败, 跳过通知: %s", e)
        return False

    at_rule = _EVENT_AT.get(event, {"at_all": False, "at_author": False})
    do_at_all = at_rule["at_all"] if at_all is None else at_all
    do_at_author = at_rule["at_author"] if at_author is None else at_author

    lines, body_bits, event_text = await _render_market_body(
        event,
        name=name, version=version, actor=actor, detail=detail, link=link,
        code=code, kind=kind, category=category, project=project,
        author=author, title_override=title_override,
        summary=summary, release_notes=release_notes,
        at_all=at_all, at_author=at_author,
    )

    # ---------- 审核类通知: 窗口合并 ----------
    # 首条照常发 (带完整详情), 窗口内的其余攒起来, 窗口末发一条汇总.
    if event in _AGGREGATED_EVENTS:
        window = await _aggregate_window_seconds()
        if window > 0:
            if await _within_window(event, window):
                # 窗口内 → 并入汇总, **不单独发** (但回执要留痕, 能在操作记录里看到)
                body = f"- {name}" + (f" ({' · '.join(body_bits)})" if body_bits else "")
                await _create_receipt(
                    event, code, name, _EVENT_TEXT[event], body, status="aggregated",
                )
                logger.info("dingtalk 通知并入汇总 (窗口内不发): event=%s code=%s", event, code)
                return True
            # 窗口已过 → 先把之前攒的汇总发出去, 这条作为新窗口的第一条单独发
            try:
                await _flush_event(event, window)
            except Exception as e:  # noqa: BLE001 — 汇总失败不能挡住这条正常通知
                logger.warning("dingtalk 汇总发送失败 (已忽略): %s", e)

    text = "\n".join(lines)
    title = f"{event_text} · {name}"

    # ---------- @谁: 只算「at 名单」, 正文里的 @ 已经在渲染层拼好了 ----------
    # ⚠️ 2026-10-31 (第十三轮): @ 文本挪进 `_render_market_body` 了 (预览要能看到),
    #    这里**只**负责算出钉钉接口要的 atUserIds / isAtAll.
    at_user_ids: list[str] = []
    if do_at_author and author:
        # ⚠️ atUserIds 要的是**钉钉 userid**, 不是平台账号名.
        #    以前直接塞账号名 → 钉钉 @ 不到人 (只有账号名恰好是 userid 才行).
        #    现在查映射表 (dingtalk.userid_map); 查不到就**不放无效 id**,
        #    只保留正文里的 "@账号名" 文字点名 —— 至少群里看得出在说谁.
        uid = await resolve_userid(author)
        if uid:
            at_user_ids.append(uid)

    # ⚠️ 自定义机器人默认开启**关键词校验**: 消息里必须含指定关键词, 否则报
    #    310000 "关键词不匹配", 消息根本发不出去. 关键词配在设置里 (留空则不加).
    if keyword:
        text = f"{keyword}\n{text}"
        title = f"{keyword} · {title}"

    # 先落回执 —— 哪怕进程在发送途中挂掉, 也知道"该发一条通知"
    row = await _create_receipt(event, code, name, title, text)
    ok = await _attempt(row, webhook, secret, at_user_ids=at_user_ids, is_at_all=do_at_all)
    return ok


async def _create_receipt(
    event: str, code: str, asset_name: str, title: str, text: str,
    status: str = "pending",
) -> AssetNotification:
    row = AssetNotification(
        event=event,
        code=code or "",
        asset_name=asset_name or "",
        status=status,
        title=title,
        text=text,
    )
    async with AsyncSessionLocal() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
    return row


def _parse_mentions(text: str) -> tuple[bool, list[str]]:
    """从消息正文里解析 @ 了谁 —— 重试时要用 (回执里没单独存 at 名单).

    正文里 @ 的人都是**独占一行**的 (我们拼消息就是这么拼的).
    """
    is_at_all = False
    users: list[str] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("@"):
            continue
        name = line[1:].split(" ")[0].strip()
        if not name:
            continue
        if name == "所有人":
            is_at_all = True
        else:
            users.append(name)
    return is_at_all, users


async def _attempt(
    row: AssetNotification,
    webhook: str,
    secret: str,
    *,
    at_user_ids: list[str] | None = None,
    is_at_all: bool = False,
    sent_status: str = "sent",
) -> bool:
    """发一次并更新回执. 返回是否成功."""
    try:
        await _deliver(
            webhook, secret, row.title, row.text,
            at_user_ids=at_user_ids, is_at_all=is_at_all,
        )
    except Exception as e:  # noqa: BLE001
        async with AsyncSessionLocal() as session:
            cur = await session.get(AssetNotification, row.id)
            if cur is not None:
                cur.status = "failed"
                cur.attempts = (cur.attempts or 0) + 1
                cur.error = f"{type(e).__name__}: {e}"[:1000]
                cur.last_attempt_at = datetime.utcnow()
                if cur.attempts < MAX_ATTEMPTS:
                    delay = RETRY_BASE_SEC ** min(cur.attempts, 4)
                    cur.next_retry_at = datetime.utcnow() + timedelta(seconds=delay)
                else:
                    cur.next_retry_at = None
                await session.commit()
        logger.warning(
            "dingtalk 通知发送失败 (将重试): event=%s code=%s err=%s",
            row.event, row.code, e,
        )
        return False

    async with AsyncSessionLocal() as session:
        cur = await session.get(AssetNotification, row.id)
        if cur is not None:
            # ⚠️ 汇总消息用 summary_sent —— 它跟"单独发出的一条"要能区分开
            #    (窗口起点算的是"最近发过的同类消息", 汇总也算).
            cur.status = sent_status
            cur.attempts = (cur.attempts or 0) + 1
            cur.error = ""
            cur.last_attempt_at = datetime.utcnow()
            cur.next_retry_at = None
            await session.commit()
    logger.info("dingtalk 通知已发送: event=%s name=%s", row.event, row.asset_name)
    return True


async def list_notifications(limit: int = 50) -> tuple[list[AssetNotification], int]:
    """最近的回执 (新的在前). 返回 (列表, 总数)."""
    from sqlalchemy import func

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(AssetNotification)
                .order_by(AssetNotification.id.desc())
                .limit(limit)
            )
        ).scalars().all()
        total = (
            await session.execute(select(func.count()).select_from(AssetNotification))
        ).scalar() or 0
    return list(rows), int(total)


async def send_test_market_message(channel: str = "market") -> tuple[bool, str, dict[str, Any] | None]:
    """发一条测试消息 (不落回执 —— 测试不是市场事件).

    返回 (ok, 给人看的说明, 钉钉原始响应).
    用当前配置 (webhook / 关键词 / 加签密钥) 走**完整**的发送路径 ——
    配置对不对, 一按就知道, 不用靠猜.

    channel: market(市场群) | review(审核群) —— 两个群各配各的, 所以要分别自检.
    """
    channel = channel if channel in _CHANNEL_KEYS else "market"
    label = _CHANNEL_LABEL.get(channel, channel)
    webhook, secret, keyword = await _channel_config(channel)
    if not webhook:
        return False, f"未配置钉钉 webhook (dingtalk.{channel}_webhook)", None

    title = "TestMate 通知配置自检"
    text = (
        f"### ✅ TestMate 通知配置自检（{label}）\n"
        "这是一条来自 TestMate 的**测试消息**, 看到即说明配置正确。\n"
        + (
            # ⚠️ 2026-10-30 (第十一轮): 市场群现在还收**软件库**的上架/发版本
            "- 上架 / 更新 / 彻底下架 / 软件库上架 / 软件库新版本 通知发到这个群"
            if channel == "market"
            else "- 待审核 / 驳回 / 删除 通知发到这个群"
        )
    )
    if keyword:
        text = f"{keyword}\n{text}"
        title = f"{keyword} · {title}"

    try:
        resp = await send_markdown(webhook, title, text, secret=secret)
    except Exception as e:  # noqa: BLE001
        return False, f"发送失败: {type(e).__name__}: {e}", None

    # 钉钉的业务错误是 HTTP 200 + errcode != 0, 所以必须看 errcode
    errcode = resp.get("errcode")
    if errcode not in (0, None):
        errmsg = resp.get("errmsg") or str(resp)
        hint = ""
        if errcode == 310000:
            hint = (
                " —— 机器人开启了关键词校验: 请把群里配置的那个关键词"
                "填到「钉钉机器人关键词」里 (消息必须含该词)"
            )
        elif errcode == 310000 or errcode == 300001:
            hint = " —— 机器人 token 无效, 请检查 webhook 地址"
        return False, f"钉钉拒绝 (errcode={errcode}): {errmsg}{hint}", resp
    return True, f"已送达{label}", resp


# ---------- 失败重试 ----------

async def retry_failed_notifications() -> int:
    """重试到期的失败通知. 返回重试条数."""
    now = datetime.utcnow()
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(AssetNotification)
                .where(
                    AssetNotification.status.in_(("pending", "failed")),
                    AssetNotification.attempts < MAX_ATTEMPTS,
                )
                .order_by(AssetNotification.id.asc())
                .limit(20)
            )
        ).scalars().all()
        due = [
            r for r in rows
            if r.next_retry_at is None or r.next_retry_at <= now
        ]

    if not due:
        return 0

    n = 0
    skipped = 0
    for r in due:
        # ⚠️ 汇总回执**不归重试 worker 管** —— 归聚合 worker.
        #    汇总只有聚合 worker 知道当前还攒着哪些资产, 两个 worker 同时发
        #    同一条汇总会让人收到两条一样的消息.
        summary_title = _AGGREGATE_SUMMARY_TITLE.get(r.event)
        if summary_title and summary_title in (r.title or ""):
            continue
        # ⚠️ 开关关了就不再发 —— 否则管理员把开关关掉, 之前排队的通知还在继续刷屏
        if not to_bool(await get(_SWITCH_KEY.get(r.event, ""), False)):
            await _mark_skipped(r)
            skipped += 1
            continue
        # ⚠️ 频道要**按事件**取 —— 审核类通知不能重试到市场群去!
        #    (之前只有一个群, 现在分两个了)
        channel = _CHANNEL_OF_EVENT.get(r.event, "market")
        try:
            webhook, secret, _kw = await _channel_config(channel)
        except Exception as e:  # noqa: BLE001
            logger.warning("dingtalk 重试读取配置失败: %s", e)
            continue
        if not webhook:
            await _mark_skipped(r)
            skipped += 1
            continue
        # @ 了谁要从正文里还原 (回执里没单独存 at 名单)
        at_all, at_users = _parse_mentions(r.text)
        # ⚠️ 正文里存的是**平台账号名**, 钉钉要的是 userid ——
        #    查映射表换一下; 查不到的**丢掉** (塞无效 id 钉钉只会当噪音).
        resolved: list[str] = []
        for u in at_users:
            uid = await resolve_userid(u)
            if uid:
                resolved.append(uid)
        if await _attempt(r, webhook, secret, at_user_ids=resolved, is_at_all=at_all):
            n += 1
    if skipped:
        logger.info("dingtalk 跳过 %d 条待发通知 (开关关了或没配 webhook)", skipped)
    if n:
        logger.info("dingtalk 重试成功 %s 条", n)
    return n


async def _mark_skipped(row: AssetNotification) -> None:
    """开关关了 → 这条通知标记成"未发送", 不要再重试."""
    async with AsyncSessionLocal() as session:
        cur = await session.get(AssetNotification, row.id)
        if cur is not None:
            cur.status = "skipped"
            cur.error = "通知开关已关闭, 未发送"
            cur.next_retry_at = None
            await session.commit()


async def _retry_loop() -> None:
    logger.info("dingtalk.retry worker running")
    while True:
        try:
            await asyncio.sleep(RETRY_SCAN_SEC)
            await retry_failed_notifications()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — worker 不能因为单次失败崩掉
            logger.exception("dingtalk.retry 轮询异常 (已忽略)")


def start_retry_worker() -> None:
    """启动重试 worker (应用启动时调一次)."""
    global _worker
    if _worker is None or _worker.done():
        _worker = asyncio.create_task(_retry_loop())
        logger.info("dingtalk.retry worker started")


# ---------- 聚合 worker ----------

async def _aggregate_loop() -> None:
    logger.info("dingtalk.aggregate worker running")
    while True:
        try:
            await asyncio.sleep(AGGREGATE_SCAN_SEC)
            await flush_aggregated_notifications()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — worker 不能因为单次失败崩掉
            logger.exception("dingtalk.aggregate 轮询异常 (已忽略)")


def start_aggregate_worker() -> None:
    """启动聚合 worker (应用启动时调一次).

    ⚠️ 必须有它: 窗口到期后**没人再触发事件**, 攒着的那批就永远发不出去 ——
       审核人会在"最后一条通知之后"完全不知道还有东西等着审.
    """
    global _aggregate_worker
    if _aggregate_worker is None or _aggregate_worker.done():
        _aggregate_worker = asyncio.create_task(_aggregate_loop())
        logger.info("dingtalk.aggregate worker started")
