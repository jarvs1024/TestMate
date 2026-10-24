"""项目列表 —— "这条资产属于哪个项目 (还是通用)".

背景:
    资产是**团队共有**的, 但团队同时跑多个项目 (6100 / 3361 / 8560 / 9560 / 3100 …),
    而且项目会增减. 有的资产是**通用**的 (谁都能用), 有的是**某个项目特有**的
    (只有那个项目的人用得上 —— 比如某台机台的专用脚本).

项目列表是**配置** (设置项 `marketplace.projects`), 不写死在代码里:
    · 项目会变 —— 加一个项目不该发一次版
    · 上传表单 / 市场筛选 / 卡片徽标都要用**同一份**列表

约定:
    · `Asset.project` 为空 = **通用** (所有项目都能用)
    · `Asset.project` = "6100" = 6100 项目特有
    · 列表里没有的项目 = 归一成通用 (脏值不该进 manifest / index)
    · 一个资产只属于一个项目 —— 要多项目再说 (字段改成列表即可, 不用动目录)
"""
from __future__ import annotations

# 通用资产的 project 值 —— 空串 (不是 "general" 之类的哨兵值)
GENERAL = ""

# 设置项 key —— 项目列表存在这里 (管理员可在设置页改)
SETTINGS_KEY = "marketplace.projects"

# 默认项目 (团队当前在跑的项目) —— 设置项没配时用这个
DEFAULT_PROJECTS = ["6100", "3361", "8560", "9560", "3100"]


def parse(raw: str | None) -> list[str]:
    """把设置里的项目列表解析出来.

    逗号分隔 (也兼容顿号/空格/换行), 保持配置里的顺序, 去重, 丢掉空串.
    """
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for chunk in raw.replace("，", ",").replace("、", ",").replace("\n", ",").split(","):
        name = chunk.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def normalize(project: str | None, known: list[str]) -> str:
    """把任意项目名归一成列表里的正式项目.

    空 = 通用; 不在列表里的一律归**通用** (宁可当通用, 也不让脏值流进索引).
    """
    name = (project or "").strip()
    if not name:
        return GENERAL
    return name if name in known else GENERAL


def is_valid(project: str | None, known: list[str]) -> bool:
    """这个项目名是不是列表里的正式项目 (空 = 通用, 算合法)."""
    name = (project or "").strip()
    if not name:
        return True
    return name in known


def label(project: str | None) -> str:
    """展示用的名字 —— 空 = 通用."""
    name = (project or "").strip()
    return f"{name} 项目" if name else "通用"
