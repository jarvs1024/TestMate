"""业务分类表 —— "这条资产在测试全流程里承担哪一步".

为什么要有这张表:
  以前分类是**前端硬编码的 7 个中文名** + 后端一张 `CATEGORY_SLUGS` 映射, 后果:
    · 上传时 allow-create 自填的分类, 前端**没有筛选 chip** → 孤儿分类(筛不出来)
    · 分类改名 / 新增分类 要改两个地方, 容易漂移
    · 目录 slug 和中文名是两套东西, 改名就搬家

现在这张表是**唯一真源**:
    后端校验 —— 只认表里的分类, 自定义的一律归「其它」
    目录 slug —— assets/{kind}/{slug}/{code}/, slug 冻结 (改名不搬家)
    前端 chip —— 从 /assets/categories 动态渲染 (带顺序和说明)

⚠️ 对外契约: `Asset.category` / manifest.json / index.json 里存的**仍是中文名**
   (Qoder 那边在消费), 这里只把"有哪些分类"收敛到一处.
"""
from __future__ import annotations

from typing import Any

# 兜底分类 —— 任何不认识 / 自定义的分类都归它
MISC = "其他"
MISC_SLUG = "misc"


# 分类表: slug ↔ 中文名 ↔ 顺序 ↔ 说明
#   slug   —— GitLab 目录名, **冻结**: 改了要搬目录, 所以只在必要时动
#   name   —— 显示名 (中文), 可以随时改 (不影响目录)
#   order  —— 展示顺序 (按测试全流程的阶段排, 小的在前)
#   desc   —— 一句话说明, 给上传的人看
CATEGORIES: list[dict[str, Any]] = [
    {
        "slug": "cases",
        "name": "方案用例",
        "order": 10,
        "desc": "测试方案 / 计划 / 用例 —— 测什么、怎么测",
    },
    {
        "slug": "env",
        "name": "环境运维",
        "order": 20,
        "desc": "机台 / 设备 / 测试环境的准备与操作",
    },
    {
        "slug": "schedule",
        "name": "任务调度",
        "order": 30,
        "desc": "老化 / 批量测试任务的调度、执行与结果读取",
    },
    {
        "slug": "flow",
        "name": "流程管控",
        "order": 40,
        "desc": "流程流转与管控 (PR 审核、看板、报表、变更单)",
    },
    {
        "slug": "diagnose",
        "name": "质量诊断",
        "order": 50,
        "desc": "日志 / Trace / 固件问题的定位与诊断",
    },
    {
        "slug": "knowledge",
        "name": "知识资产",
        "order": 60,
        "desc": "速查表 / 规范 / 经验沉淀",
    },
    {
        "slug": MISC_SLUG,
        "name": MISC,
        "order": 99,
        "desc": "暂时归不到上面任何一类",
    },
]

# 旧分类名 → 新分类名 (2026-10-24 分类重排时的一次性映射)
# 用途: 迁移老数据 (DB / manifest / index.json / GitLab 目录) 时把旧名字换成新的.
LEGACY_ALIASES: dict[str, str] = {
    "Spec 问答": "方案用例",
    "机台运维": "环境运维",
    "环境助手": "环境运维",
    "老化任务": "任务调度",
    "测试报告": "流程管控",
    "Trace 诊断": "质量诊断",
    "FW 比对": "质量诊断",
    "自动化代码": "流程管控",
}

_BY_NAME: dict[str, dict[str, Any]] = {c["name"]: c for c in CATEGORIES}
_BY_SLUG: dict[str, dict[str, Any]] = {c["slug"]: c for c in CATEGORIES}


def normalize(category: str | None) -> str:
    """把任意分类名归一成表里的正式分类名 (不认识的一律归「其它」)."""
    name = (category or "").strip()
    if not name:
        return MISC
    if name in _BY_NAME:
        return name
    alias = LEGACY_ALIASES.get(name)
    if alias and alias in _BY_NAME:
        return alias
    return MISC


def slug_of(category: str | None) -> str:
    """分类 → GitLab 目录 slug (冻结, 改名不搬家)."""
    item = _BY_NAME.get(normalize(category))
    return item["slug"] if item else MISC_SLUG


def name_of_slug(slug: str | None) -> str:
    item = _BY_SLUG.get((slug or "").strip())
    return item["name"] if item else MISC


def is_valid(category: str | None) -> bool:
    """这个分类名是不是表里的正式分类 (自填的不算)."""
    return (category or "").strip() in _BY_NAME


def table() -> list[dict[str, Any]]:
    """分类表 (按展示顺序) —— 给接口和前端用."""
    return sorted(CATEGORIES, key=lambda c: c["order"])


def names() -> list[str]:
    """正式分类名 (按展示顺序)."""
    return [c["name"] for c in table()]
