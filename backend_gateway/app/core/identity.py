"""身份口径 —— 普通用户的"用户名"就是公司邮箱, 管理员是账号名.

2026-10-25 账号管理重构:
  · 账号**必须管理员先建过**才能登录 (建号入口: 设置页「用户管理」);
  · 普通用户: 公司邮箱 (**后缀固定** @twsc.com.cn), 建号时没给密码 → 免密登录;
  · 管理员: 账号名不含 @, **必须密码**登录.

为什么要一个专门模块:
  登录、建号、资产白名单 (publisher / reviewer)、资产作者比对, 全都涉及
  "同一个人的几种写法" —— 'zhangsan' / 'zhangsan@twsc.com.cn'. 口径散在各处
  就会各写各的, 迟早对不上. 这里给一份**唯一**的实现.

⚠️ 白名单容错的意义: 设置页里「允许发布的用户名」是手填的逗号分隔列表,
   admin 很可能照着邮箱写全名, 也可能只写前缀. 两种都得认.
"""
from __future__ import annotations

import re

from app.core.config import settings


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def email_domain() -> str:
    """公司邮箱域名 (含 @), 如 '@twsc.com.cn'."""
    d = settings.AUTH_EMAIL_DOMAIN.strip().lower()
    if d and not d.startswith("@"):
        d = "@" + d
    return d


def local_part(username: str | None) -> str:
    """'zhangsan@twsc.com.cn' → 'zhangsan' (没有 @ 就原样返回)."""
    return _norm(username).split("@", 1)[0]


# 邮箱本地部分的合法字符 (RFC 5322 的简化版, 够用且能挡掉明显的垃圾输入)
_LOCAL_RE = re.compile(r"^[a-z0-9._%+-]+$")


def to_email(raw: str | None) -> str | None:
    """输入 → 公司邮箱; 不是公司邮箱就返回 None.

        'zhangsan'            → 'zhangsan@twsc.com.cn'
        'ZhangSan'            → 'zhangsan@twsc.com.cn'   (统一小写)
        'zhangsan@twsc.com.cn' → 'zhangsan@twsc.com.cn' (原样)
        'zhangsan@other.com'  → None                    (不是本公司的域)
        'admin'               → 'admin@twsc.com.cn'     (合法形式, 但库里未必有)
    """
    s = _norm(raw)
    if not s:
        return None
    domain = email_domain().lstrip("@")
    if "@" in s:
        local, _, dom = s.partition("@")
        if not local or dom != domain:
            return None
        if not _LOCAL_RE.match(local):
            return None
        return f"{local}@{domain}"
    if not _LOCAL_RE.match(s):
        return None
    return f"{s}@{domain}"


def lookup_candidates(raw: str | None) -> list[str]:
    """查库时的用户名候选 (按优先级).

    1) 原样 —— 管理员账号 ('admin') 走这条
    2) 邮箱形式 —— 'zhangsan' → 'zhangsan@twsc.com.cn'
    3) 本地部分 —— 兼容老库里存着 'zhangsan' 的行 (迁移前的数据)

    ⚠️ 顺序不能乱: 'admin' 必须先按原样命中, 否则会被当成
       'admin@twsc.com.cn' 去命中另一个普通账号.

    ⚠️ 撞名的边界情况: 管理员账号名是不含 @ 的短名 ('zhangsan'), 而普通用户的
       邮箱前缀恰好也是短名 ('zhangsan') —— 两者撞名时, 用户用短名登录会
       **先命中管理员账号** (精确匹配优先是合理的: 用户明明白白输的就是这个名字).
       这种情况由**建号时的撞名校验**挡住 (app/api/auth.py 的 _check_name_collision),
       登录侧不做特殊处理 —— 否则"精确匹配优先"这条普遍规则会被打破.
    """
    s = _norm(raw)
    out: list[str] = []

    def add(x: str | None) -> None:
        if x and x not in out:
            out.append(x)

    add(s)
    add(to_email(s))
    add(local_part(s) or None)
    return out


def name_matches(names: set[str], username: str | None) -> bool:
    """白名单里填 'zhangsan' 或 'zhangsan@twsc.com.cn' 都算命中.

    白名单是 admin 手填的, 两种写法都见过 —— 只认一种会让人"配了却不生效",
    而这种问题极难排查. 两个方向都认:
      · 白名单短名 / 用户名邮箱形式
      · 白名单全邮箱 / 用户名短名 (老库里的存量数据)
    """
    u = _norm(username)
    if not u:
        return False
    if u in names:
        return True
    lp = local_part(u)
    if lp in names:
        return True
    # 白名单写的是全邮箱, 用户名是短名
    return any(local_part(n) == lp for n in names if n)


def author_forms(username: str | None) -> list[str]:
    """资产作者名可能的写法 (给 SQL 的 IN 用).

    存量数据的作者名可能是短名 ('zhangsan'), 而登录用户名已经是邮箱形式
    ('zhangsan@twsc.com.cn') —— 迁移 0020 会统一, 但万一某个环境漏跑,
    "我的资产"就会整片消失. 这里把两种写法都带上, 少一次诡异故障.
    """
    u = _norm(username)
    if not u:
        return []
    out = [u]
    lp = local_part(u)
    if lp and lp != u:
        out.append(lp)
    return out
