"""add download_alias (永久下载别名)

背景 (2026-11-04 · 第二十四轮):
    固定下载链接是"给别的软件 wget 用"的地址, 必须**永不变**.
    但 code 是从**上传文件名**派生的, 而文件名里常带版本号:

        aitestx-v2.1.zip  →  code = "aitestx-v2.1"
        → 固定链接 = /api/v1/software/aitestx-v2.1/download

    URL 里**带着版本号** —— 看着像"这是 2.1 的链接", 跟"链接永不变"的承诺打架.
    用户原话: "这个地址要是更新了版本变成了 V2.1 这个地址会变么? 变了就不是固定地址了".

    真会变: 走"发新版本"时 code 不变 (链接安全), 但走"**重新上架一个新包**"
    (文件名变成 aitestx-v2.2.zip) 时, 系统会派生出**新 code** → 新条目 →
    旧链接 404. 用户没法区分这两种操作, 所以链接必须**从结构上**就不含版本号.

做法:
    新增 software_items.download_alias —— 与版本号无关的稳定标识.
    存量数据**回填**: 从 code 剥掉版本号后缀 (aitestx-v2.1 → aitestx),
    剥不出或撞名的加序号, 保证唯一.

    ⚠️ 旧的 /api/v1/software/{code}/download **保留不动** ——
       已经贴到别的软件里的链接不能因为这次升级就断.

Revision ID: 0033_add_software_download_alias
Revises: 0032_rename_market_to_extensions
Create Date: 2026-11-04
"""
import re

from alembic import op
import sqlalchemy as sa


revision = "0033_add_software_download_alias"
down_revision = "0032_rename_market_to_extensions"
branch_labels = None
depends_on = None


# ⚠️ 与 app/core/software_store.py 的 _VERSION_SUFFIX_RE 保持一致.
#    这里必须**内联**而不是 import —— 迁移脚本要能在**未来**的代码里独立跑
#    (那时候那个常量可能已经变了, import 会让老迁移的行为漂移).
_VERSION_SUFFIX_RE = re.compile(
    r"[-_.](?:v\d+(?:[._]\d+)*|\d+(?:[._]\d+)+)$",
    re.IGNORECASE,
)


def _alias_from_code(code: str) -> str:
    """从 code 剥出版本号后缀 —— 与 software_store.alias_from_code 同规则."""
    c = (code or "").strip().lower()
    if not c:
        return "software"
    stripped = _VERSION_SUFFIX_RE.sub("", c).strip("-._")
    if len(stripped) < 2:
        stripped = c
    return stripped[:64].strip("-._") or c[:64]


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("software_items")}
    if "download_alias" not in cols:
        op.add_column(
            "software_items",
            sa.Column(
                "download_alias",
                sa.String(64),
                nullable=False,
                server_default="",
                index=True,
                comment="永久下载别名 (与版本无关) —— 固定下载链接用它",
            ),
        )

    # ---- 回填: 存量条目从 code 派生别名, 保证唯一 ----
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, code, download_alias FROM software_items")
    ).all()
    taken: set[str] = set()
    # 先把**已填好**的别名收进 taken (避免抢别人手填的)
    for _id, _code, alias in rows:
        if alias:
            taken.add(alias)

    for row_id, code, alias in rows:
        if alias:
            continue
        base = _alias_from_code(code)
        candidate = base
        n = 1
        while candidate in taken:
            n += 1
            suffix = str(n)
            candidate = base[: 64 - len(suffix)] + suffix
        taken.add(candidate)
        bind.execute(
            sa.text("UPDATE software_items SET download_alias = :a WHERE id = :i"),
            {"a": candidate, "i": row_id},
        )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("software_items")}
    if "download_alias" in cols:
        op.drop_column("software_items", "download_alias")
