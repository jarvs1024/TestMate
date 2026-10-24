"""发布者白名单 —— 解析容错 + 权限边界.

背景: 设置页里「允许发布的用户 ID (JSON 数组)」和「允许发布的用户名 (逗号分隔)」
两个输入框紧挨着, 用户照抄彼此的格式太常见了. 而格式写错**没有任何报错** ——
只是白名单被解析成空集, 结果是"配了白名单, 但除 admin 外所有人都发不了布",
排查起来极其痛苦. 所以解析必须容错: 两种口径任一命中即可.

覆盖: _split_list 各格式 / 两个口径的解析 / API 层权限边界.
"""
from __future__ import annotations

import io
import zipfile

from tests.conftest import set_setting


def _zip_bytes(files: dict[str, str], filename: str = "pkg.zip") -> tuple[str, bytes, str]:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return (filename, buf.getvalue(), "application/zip")


async def _upload(client, auth, code="wl-demo"):
    """上传一个资产 (走 require_publisher)."""
    # ⚠️ 包名必须与 code 一致 (命名契约)
    pkg = _zip_bytes(
        {"SKILL.md": f"---\nname: {code}\ndescription: d\n---\n\n# {code}\n"},
        filename=f"{code}.zip",
    )
    data = {
        "code": code, "kind": "skill", "name": f"资产-{code}", "version": "1.0.0",
        "summary": "摘要", "description": "说明", "use_when": "何时", "not_for": "何时不",
        "category": "misc", "icon": "🧩", "tags": "[]", "keywords": "[]",
        "featured": "false", "permissions": "{}", "install_steps": "[]", "bindings": "{}",
    }
    return await client.post(
        "/api/v1/assets/upload", data=data,
        files={"package": (pkg[0], pkg[1], pkg[2])},
        headers=auth,
    )


def _auth(user):
    return {"Authorization": f"Bearer {user['token']}"}


# ---------- _split_list: 纯函数 ----------

def test_split_list_empty():
    from app.core.market_policy import split_list as _split_list

    assert _split_list("") == []
    assert _split_list("   ") == []
    assert _split_list("[]") == []


def test_split_list_comma_separated():
    from app.core.market_policy import split_list as _split_list

    assert _split_list("zhangsan,lisi") == ["zhangsan", "lisi"]


def test_split_list_json_array():
    from app.core.market_policy import split_list as _split_list

    assert _split_list('["zhangsan","lisi"]') == ["zhangsan", "lisi"]


def test_split_list_json_array_with_spaces():
    from app.core.market_policy import split_list as _split_list

    assert _split_list('["zhangsan", "lisi"]') == ["zhangsan", "lisi"]


def test_split_list_chinese_and_semicolon_separators():
    from app.core.market_policy import split_list as _split_list

    assert _split_list("zhangsan、lisi") == ["zhangsan", "lisi"]
    assert _split_list("zhangsan，lisi") == ["zhangsan", "lisi"]
    assert _split_list("zhangsan;lisi") == ["zhangsan", "lisi"]


def test_split_list_broken_json_array_falls_back_to_delimiters():
    """坏 JSON (少个 ]) 不能整个丢掉 —— 退化成按分隔符切."""
    from app.core.market_policy import split_list as _split_list

    assert _split_list('["zhangsan","lisi"') == ["zhangsan", "lisi"]
    assert _split_list('["zhangsan", "lisi"') == ["zhangsan", "lisi"]


def test_split_list_strips_stray_quotes():
    from app.core.market_policy import split_list as _split_list

    assert _split_list('"zhangsan","lisi"') == ["zhangsan", "lisi"]
    assert _split_list("['zhangsan','lisi']") == ["zhangsan", "lisi"]


def test_split_list_keeps_numeric_ids():
    from app.core.market_policy import split_list as _split_list

    assert _split_list("[1,2]") == ["1", "2"]
    assert _split_list("1,2") == ["1", "2"]


def test_split_list_json_array_of_non_strings():
    from app.core.market_policy import split_list as _split_list

    # 数字正常转字符串; 布尔跳过 —— str(True) 会变成 "True" 这种鬼名字
    assert _split_list("[1,true]") == ["1"]


# ---------- 两个口径的解析 ----------

async def test_publisher_names_accepts_json_array_format():
    """用户名口径写成 JSON 数组 (照抄隔壁那项) 也要认."""
    from app.core.market_policy import publisher_names as _publisher_names

    await set_setting("marketplace.publisher_usernames", '["ZhangSan","LiSi"]')
    assert await _publisher_names() == {"zhangsan", "lisi"}


async def test_publisher_names_accepts_comma_format():
    from app.core.market_policy import publisher_names as _publisher_names

    await set_setting("marketplace.publisher_usernames", "ZhangSan,LiSi")
    assert await _publisher_names() == {"zhangsan", "lisi"}


async def test_publisher_names_empty_gives_empty_set():
    from app.core.market_policy import publisher_names as _publisher_names

    await set_setting("marketplace.publisher_usernames", "")
    assert await _publisher_names() == set()


async def test_publisher_ids_accepts_json_array_format():
    from app.core.market_policy import publisher_ids as _publisher_ids

    await set_setting("marketplace.publisher_ids", "[1,2]")
    assert await _publisher_ids() == {1, 2}


async def test_publisher_ids_accepts_comma_format():
    """ID 口径写成逗号分隔 (照抄隔壁那项) 也要认."""
    from app.core.market_policy import publisher_ids as _publisher_ids

    await set_setting("marketplace.publisher_ids", "1,2")
    assert await _publisher_ids() == {1, 2}


async def test_publisher_ids_ignores_non_numeric():
    from app.core.market_policy import publisher_ids as _publisher_ids

    await set_setting("marketplace.publisher_ids", "[1,abc]")
    assert await _publisher_ids() == {1}


# ---------- API 层权限边界 ----------

async def test_upload_allowed_when_whitelist_written_as_json_array(
    client, ws, restore_git_config, publisher_user  # noqa: ARG001
):
    """白名单写成 JSON 数组时, 白名单里的用户照样能上传 (以前会被静默拒绝)."""
    await set_setting(
        "marketplace.publisher_usernames", f'["{publisher_user["username"]}"]'
    )
    r = await _upload(client, _auth(publisher_user), code="wl-json")
    assert r.status_code == 202, r.text


async def test_upload_allowed_when_whitelist_written_as_comma(
    client, ws, restore_git_config, publisher_user  # noqa: ARG001
):
    await set_setting(
        "marketplace.publisher_usernames", publisher_user["username"]
    )
    r = await _upload(client, _auth(publisher_user), code="wl-comma")
    assert r.status_code == 202, r.text


async def test_upload_allowed_by_id_whitelist_written_as_comma(
    client, ws, restore_git_config, publisher_user  # noqa: ARG001
):
    """ID 口径写成逗号分隔也要认 —— 不然也是静默拒绝."""
    await set_setting("marketplace.publisher_usernames", "")
    await set_setting("marketplace.publisher_ids", str(publisher_user["id"]))
    r = await _upload(client, _auth(publisher_user), code="wl-id-comma")
    assert r.status_code == 202, r.text


async def test_upload_denied_when_not_in_whitelist(
    client, ws, restore_git_config, stranger_user  # noqa: ARG001
):
    """不在白名单 → 403, 且提示要说人话."""
    await set_setting("marketplace.publisher_usernames", '["someone_else"]')
    r = await _upload(client, _auth(stranger_user), code="wl-deny")
    assert r.status_code == 403, r.text
    assert "白名单" in r.text


async def test_admin_can_publish_even_with_empty_whitelist(
    client, auth, ws, restore_git_config  # noqa: ARG001
):
    """admin 恒可发布, 与白名单无关."""
    await set_setting("marketplace.publisher_usernames", "")
    r = await _upload(client, auth, code="wl-admin")
    assert r.status_code == 202, r.text


async def test_empty_whitelist_denies_non_admin(
    client, ws, restore_git_config, publisher_user  # noqa: ARG001
):
    """白名单空 → 非 admin 一律拒绝 (而不是放行所有人)."""
    await set_setting("marketplace.publisher_usernames", "")
    r = await _upload(client, _auth(publisher_user), code="wl-empty")
    assert r.status_code == 403, r.text
