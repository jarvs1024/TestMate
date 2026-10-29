"""业务分类表 —— "这个资产在研发/测试协作里承担什么角色".

为什么要有这张表:
  以前分类是**前端硬编码的中文名** + 后端一张 `CATEGORY_SLUGS` 映射, 后果:
    · 上传时 allow-create 自填的分类, 前端**没有筛选 chip** → 孤儿分类(筛不出来)
    · 分类改名 / 新增分类 要改两个地方, 容易漂移
    · 目录 slug 和中文名是两套东西, 改名就搬家

现在这张表是**唯一真源**:
    后端校验 —— 只认表里的分类, 自定义的一律归「其他」
    目录 slug —— assets/{kind}/{slug}/{code}/, slug 冻结 (改名不搬家)
    前端 chip —— 从 /assets/categories 动态渲染 (带顺序和说明)

⚠️ 对外契约: `Asset.category` / manifest.json / index.json 里存的**仍是中文名**
   (Qoder 那边在消费), 这里只把"有哪些分类"收敛到一处.

2026-10-26 分类重排: 从"按测试流程阶段分"改成"按**协作角色**分" ——
   旧分类是流程视角 (方案用例/环境运维/任务调度/流程管控/质量诊断/知识资产),
   回答的是"这件事在流程的哪一步"; 新分类是**能力视角**, 回答的是
   "这个资产替我兜什么底 / 提什么效 / 走什么流程 / 管什么事" ——
   后者对**上传的人**更有指导意义 (知道自己该往哪一类放), 也更稳定
   (流程阶段会随项目变, 角色分工不会).
"""
from __future__ import annotations

from typing import Any

# 兜底分类 —— 任何不认识 / 自定义的分类都归它
MISC = "其他"
MISC_SLUG = "misc"


# 分类表: slug ↔ 中文名 ↔ 顺序 ↔ 说明
#   slug   —— GitLab 目录名, **冻结**: 改了要搬目录, 所以只在必要时动
#   name   —— 显示名 (中文), 可以随时改 (不影响目录)
#   order  —— 展示顺序
#   desc   —— 一句话说明, 给上传的人看 (下拉框里就显示它)
#
# ⚠️ **desc 要短** (2026-10-29) —— 它显示在「分类」下拉框的选项右侧,
#    跟分类名并排一行. 原来那种"对功能、性能、可靠性的全方位兜底 —— 定位问题、
#    判定结果、给出判据"的长句, 在下拉框里被**硬截断**成"…", 用户根本读不到.
#    短的才读得完 —— 长解释挪到表单下面的说明文字里.
CATEGORIES: list[dict[str, Any]] = [
    {
        "slug": "quality",
        "name": "质量保障",
        "order": 10,
        "desc": "兜住质量 · 定位问题、给判据",
    },
    {
        "slug": "efficiency",
        "name": "效率工具",
        "order": 20,
        "desc": "提效 · 自动化、造数、脚本",
    },
    {
        "slug": "process",
        "name": "流程规范",
        "order": 30,
        "desc": "守流程 · CI/CD、门禁、标准化",
    },
    {
        "slug": "management",
        "name": "管理协同",
        "order": 40,
        "desc": "管协同 · 进度、风险、沟通",
    },
    {
        "slug": MISC_SLUG,
        "name": MISC,
        "order": 99,
        "desc": "归不到上面任何一类",
    },
]

# 旧分类名 → 新分类名
# 用途: 迁移老数据 (DB / manifest / index.json / GitLab 目录) 时把旧名字换成新的.
#
# ⚠️ 2026-10-26 这一轮把"按流程阶段"改成"按协作角色", **每个旧分类都要落到新分类**,
#    而且不是一对一 —— 旧分类内部的资产会**拆到不同新分类**去 (见 migrate 脚本),
#    所以这里只提供"名字 → 名字"的兜底映射 (给不认识名字的老数据一条退路),
#    精确归类由 scripts/migrate_categories.py 按资产逐个判定.
LEGACY_ALIASES: dict[str, str] = {
    # ---- 2026-10-26 之前的那一轮改名 (流程阶段口径内的调整) ----
    "Spec 问答": "方案用例",
    "机台运维": "环境运维",
    "环境助手": "环境运维",
    "老化任务": "任务调度",
    "测试报告": "流程管控",
    "Trace 诊断": "质量诊断",
    "FW 比对": "质量诊断",
    "自动化代码": "流程管控",
    # ---- 2026-10-26: 流程阶段 → 协作角色 (按"这个资产替我干什么"归) ----
    "质量诊断": "质量保障",
    "知识资产": "效率工具",
    "方案用例": "效率工具",
    "环境运维": "效率工具",
    "任务调度": "效率工具",
    "流程管控": "管理协同",
}

_BY_NAME: dict[str, dict[str, Any]] = {c["name"]: c for c in CATEGORIES}
_BY_SLUG: dict[str, dict[str, Any]] = {c["slug"]: c for c in CATEGORIES}


def normalize(category: str | None) -> str:
    """把任意分类名归一成表里的正式分类名 (不认识的一律归「其它」).

    ⚠️ 别名是**链式**的: "Spec 问答" → "方案用例" → "效率工具" ——
       只查一次表会把中间那层当成终点, 而它现在已经不是正式名了,
       结果是"Spec 问答"被归到「其它」(老数据全丢分类).
       所以要一直查到不动点.
    """
    name = (category or "").strip()
    if not name:
        return MISC
    seen: set[str] = set()
    while name not in _BY_NAME:
        if name in seen:      # 别名成环 (不该有, 但别死循环)
            return MISC
        seen.add(name)
        alias = LEGACY_ALIASES.get(name)
        if not alias:
            return MISC
        name = alias
    return name


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
