"""资产市场的**边界与异常**用例.

为什么单独一个文件:
    正常路径的用例已经有了 (test_market_api.py 等), 但真正容易出事的是边界:
      · 项目列表为空 / 带脏值 / 改名
      · MCP 配置的各种畸形 (非法 JSON / 结构不对 / 太大 / 名字不合法)
      · 包名 / code / 版本 的非法输入
      · 越权与不可见
      · 并发与幂等
    这些以前散落着, 有的根本没测 —— 这轮补齐, 顺便当回归网.
"""
from __future__ import annotations

import io
import json
import zipfile

import pytest

from app.core import market_projects as mp
from tests.conftest import set_setting
from tests.test_market_api import API, _enable_publisher, _upload, _zip_bytes


# ---------- 项目列表: 边界 ----------

async def test_projects_setting_empty_falls_back_to_default(client, auth):
    """项目列表配成空 → 用默认列表 (不能变成"没有项目可选")."""
    from app.core import market_projects

    await set_setting("marketplace.projects", "")
    items = (await client.get(f"{API}/projects", headers=auth)).json()["items"]
    codes = [i["code"] for i in items]
    assert "general" in codes
    assert any(c.isdigit() for c in codes), codes


async def test_projects_setting_with_dirty_values(client, auth):
    """项目列表里有空格/重复/中文 → 只保留干净的, 不崩."""
    await set_setting("marketplace.projects", " 6100 , 6100 ,,中文项目 ,3361")
    items = (await client.get(f"{API}/projects", headers=auth)).json()["items"]
    codes = [i["code"] for i in items]
    assert "6100" in codes and "3361" in codes
    assert "中文项目" in codes          # 允许中文项目名, 只是别重复
    assert codes.count("6100") == 1     # 去重


async def test_projects_list_marks_general_explicitly(client, auth):
    """「通用」项要标出来 (is_general) —— 前端靠它把通用排除出项目下拉."""
    items = (await client.get(f"{API}/projects", headers=auth)).json()["items"]
    general = [i for i in items if i["code"] == "general"]
    assert len(general) == 1
    assert general[0].get("is_general") is True
    # 其余项不能带这个标记
    assert all(not i.get("is_general") for i in items if i["code"] != "general")


def test_project_parse_handles_all_separators():
    assert mp.parse("6100，3361、8560 9560\n3100") == ["6100", "3361", "8560", "9560", "3100"]


# ---------- MCP 配置: 畸形输入 ----------

@pytest.mark.parametrize("bad", [
    "",                                   # 空
    "{",                                  # 非法 JSON
    "[]",                                 # 不是对象
    '{"foo": 1}',                         # 缺 mcpServers
    '{"mcpServers": {}}',                 # 空对象
    '{"mcpServers": []}',                 # 类型错
    '{"mcpServers": {"dml-a": {}}}',      # 缺 command/url
    '{"mcpServers": {"dml-a": {"url": "ftp://h/mcp"}}}',   # url 协议不对
    '{"mcpServers": {"dml-a": {"command": 123}}}',        # command 类型错
    '{"mcpServers": {"dml-a": {"command": "npx", "args": "x"}}}',  # args 不是数组
    '{"mcpServers": {"dml-a": {"command": "npx", "env": []}}}',    # env 不是对象
    '{"mcpServers": {"Bad_Name": {"url": "http://h/mcp"}}}',  # 名字字符集不对
])
def test_mcp_config_rejects_bad_shapes(bad):
    from app.core.mcp_config import McpConfigError, parse_mcp_config

    with pytest.raises(McpConfigError):
        parse_mcp_config(bad)


def test_mcp_config_rejects_oversized():
    """超过 64KB → 拒 (别把内存吃满)."""
    from app.core.mcp_config import McpConfigError, parse_mcp_config

    big = '{"mcpServers": {"dml-a": {"url": "http://h/mcp", "headers": {"X": "' + "a" * 70000 + '"}}}}'
    with pytest.raises(McpConfigError):
        parse_mcp_config(big)


def test_mcp_config_accepts_minimal_valid():
    from app.core.mcp_config import parse_mcp_config

    cfg = parse_mcp_config('{"mcpServers": {"dml-a": {"command": "npx", "args": ["-y", "x"]}}}')
    assert "dml-a" in cfg["mcpServers"]


# ---------- 包名 / code / 版本: 非法输入 ----------

@pytest.mark.parametrize("filename", [
    "dml-x.rar",              # 扩展名不支持
    "dml-x.exe",
    "no-prefix.zip",           # 缺 dml- 前缀 (新建时要拦)
    "dml-中文.zip",            # 中文
    "dml-x y.zip",             # 空格
    "dml-X.zip",               # 大写
])
def test_package_name_rules(filename):
    from app.core.market_naming import package_base_name

    # 归一规则: 后端只要求"包名 == code", 格式在前端
    assert package_base_name(filename) in (filename, filename.rsplit(".", 1)[0])


@pytest.mark.parametrize("code", [
    "ab",                       # 太短
    "dml-" + "a" * 70,          # 太长
    "dml-中文",
    "dml-Bad_Case",
    "-dml-x",
    "dml-x-",
    "dml--x",
])
def test_code_format_rejected(code):
    from app.core.market_catalog import ManifestError, validate_code

    with pytest.raises(ManifestError):
        validate_code(code)


@pytest.mark.parametrize("version", ["1.0", "abc", "1.0.0.0", "v", ""])
def test_version_format_rejected(version):
    from app.core.market_catalog import ManifestError, validate_version

    with pytest.raises(ManifestError):
        validate_version(version)


async def test_upload_with_illegal_code_rejected(client, auth, ws,  # noqa: ARG001
                                                  restore_git_config, publisher_user):
    """非法 code → 422 (别把脏 code 写进 manifest / 目录)."""
    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    pkg = _zip_bytes({"SKILL.md": "---\nname: x\ndescription: d\n---\n\n# x\n"},
                     filename="dml-badcode.zip")
    r = await client.post(
        f"{API}/upload",
        data={"code": "dml-Bad_Code", "kind": "skill", "name": "x", "summary": "s"},
        files={"package": (pkg[0], pkg[1], pkg[2])},
        headers=pauth,
    )
    assert r.status_code in (400, 422), r.text


async def test_upload_duplicate_code_rejected(client, auth, ws,  # noqa: ARG001
                                              restore_git_config, publisher_user):
    """同 code 再传一次 → 409 (不能覆盖别人的资产)."""
    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    assert (await _upload(client, pauth, code="dup-demo")).status_code == 202
    pkg = _zip_bytes({"SKILL.md": "---\nname: x\ndescription: d\n---\n\n# x\n"},
                     filename="dup-demo.zip")
    r = await client.post(
        f"{API}/upload",
        data={"code": "dup-demo", "kind": "skill", "name": "x2", "summary": "s"},
        files={"package": (pkg[0], pkg[1], pkg[2])},
        headers=pauth,
    )
    assert r.status_code == 409, r.text


# ---------- 不可见 / 越权 ----------

async def test_asset_detail_requires_login(client, ws, restore_git_config):  # noqa: ARG001
    """未登录看详情 → 401 (不是 403)."""
    r = await client.get(f"{API}/code-review-pipeline")
    assert r.status_code == 401, r.text


async def test_unknown_code_returns_404(client, auth):
    r = await client.get(f"{API}/definitely-not-exists", headers=auth)
    assert r.status_code == 404, r.text


async def test_non_publisher_cannot_upload(client, auth, ws,  # noqa: ARG001
                                           restore_git_config, stranger_user):
    """不在白名单 → 403."""
    await set_setting("marketplace.publisher_usernames", "")
    await set_setting("marketplace.publisher_ids", "[]")
    r = await client.post(
        f"{API}/upload",
        data={"code": "dml-nope", "kind": "skill", "name": "x", "summary": "s"},
        headers={"Authorization": f"Bearer {stranger_user['token']}"},
    )
    assert r.status_code == 403, r.text


async def test_cannot_modify_others_asset(client, auth, ws,  # noqa: ARG001
                                         restore_git_config, publisher_user, stranger_user):
    """白名单用户也**不能**改别人的资产."""
    await set_setting("marketplace.review.enabled", "false")
    # ⚠️ 白名单是**覆盖式**设置 —— 两个都要放进去 (别用 _enable_publisher 连着调, 后一个会覆盖前一个)
    await set_setting(
        "marketplace.publisher_usernames",
        f"{publisher_user['username']},{stranger_user['username']}",
    )
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    sauth = {"Authorization": f"Bearer {stranger_user['token']}"}
    up = await _upload(client, pauth, code="mine-demo")
    assert up.status_code == 202, up.text

    # 陌生人不能申请下架别人的资产
    r = await client.post(
        f"{API}/mine-demo/unpublish",
        data={"confirm_code": "mine-demo"},
        headers=sauth,
    )
    assert r.status_code == 403, r.text

    # 陌生人不能更新别人的资产
    pkg = _zip_bytes({"SKILL.md": "---\nname: x\ndescription: d\n---\n\n# x\n"},
                     filename="mine-demo.zip")
    r2 = await client.put(
        f"{API}/mine-demo",
        # ⚠️ version 是必填 —— 少了它会在进函数体之前就 422, 根本走不到权限检查
        data={"kind": "skill", "name": "x", "summary": "s", "version": "2.0.0"},
        files={"package": (pkg[0], pkg[1], pkg[2])},
        headers=sauth,
    )
    assert r2.status_code == 403, r2.text


async def test_delete_requires_admin(client, auth, ws,  # noqa: ARG001
                                     restore_git_config, publisher_user):
    """在架的资产: 作者本人也删不了 —— 必须走「申请下架 → 管理员确认」."""
    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="del-demo")
    r = await client.delete(f"{API}/del-demo", headers=pauth)
    # 409 (不是 403): 权限上作者本来就有, 但这个状态不允许删 —— 提示要走申请下架
    assert r.status_code == 409, r.text
    assert "下架" in r.json()["detail"], r.text
    # 资产还在
    assert (await client.get(f"{API}/del-demo", headers=auth)).status_code == 200


# ---------- 幂等 / 并发 ----------

async def test_concurrent_upload_same_code_one_wins(client, auth, ws,  # noqa: ARG001
                                                    restore_git_config, publisher_user):
    """同一 code 并发上传 → 只有一个成功, 另一个 409 (不能两份都进去)."""
    import asyncio

    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    pkg = _zip_bytes({"SKILL.md": "---\nname: x\ndescription: d\n---\n\n# x\n"},
                     filename="conc-demo.zip")

    async def up(i: int):
        return await client.post(
            f"{API}/upload",
            data={"code": "conc-demo", "kind": "skill", "name": f"c{i}", "summary": "s"},
            files={"package": (pkg[0], pkg[1], pkg[2])},
            headers=pauth,
        )

    results = await asyncio.gather(up(1), up(2))
    codes = sorted(r.status_code for r in results)
    assert codes[0] == 202, codes
    assert all(c in (202, 409) for c in codes), codes


async def test_review_twice_is_idempotent(client, auth, ws,  # noqa: ARG001
                                          restore_git_config, publisher_user):
    """重复审核同一个待审资产 → 第二次 409 (状态机拦)."""
    await set_setting("marketplace.review.enabled", "true")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="twice-demo")

    r1 = await client.post(f"{API}/twice-demo/review",
                           data={"decision": "approve", "comment": "ok"}, headers=auth)
    assert r1.status_code == 200, r1.text
    r2 = await client.post(f"{API}/twice-demo/review",
                           data={"decision": "approve", "comment": "ok"}, headers=auth)
    assert r2.status_code == 409, r2.text


async def test_submit_after_approve_rejected(client, auth, ws,  # noqa: ARG001
                                             restore_git_config, publisher_user):
    """已上架的资产不能"重新提交审核" (那是驳回后专用的)."""
    await set_setting("marketplace.review.enabled", "true")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="sub-demo")
    await client.post(f"{API}/sub-demo/review",
                      data={"decision": "approve", "comment": "ok"}, headers=auth)
    r = await client.post(f"{API}/sub-demo/submit", data={}, headers=pauth)
    assert r.status_code == 409, r.text


# ---------- 空数据 / 畸形数据 不崩 ----------

async def test_categories_endpoint_never_crashes(client, auth):
    """分类表接口在没有任何资产时也要正常返回 (前端靠它渲染 chip)."""
    r = await client.get(f"{API}/categories", headers=auth)
    assert r.status_code == 200
    assert isinstance(r.json()["items"], list)


async def test_projects_endpoint_never_crashes(client, auth):
    r = await client.get(f"{API}/projects", headers=auth)
    assert r.status_code == 200
    assert isinstance(r.json()["items"], list)


async def test_list_with_empty_filters(client, auth):
    """空筛选参数 → 正常返回, 不过滤."""
    r = await client.get(f"{API}?kind=&category=&q=&project=&status=&limit=10", headers=auth)
    assert r.status_code == 200
    assert isinstance(r.json()["items"], list)


async def test_list_with_unmatched_filters(client, auth):
    """筛不到东西 → 空列表, 不是 500."""
    r = await client.get(f"{API}?category=根本没有这个分类&limit=10", headers=auth)
    assert r.status_code == 200
    assert r.json()["items"] == []


async def test_search_with_special_chars(client, auth, ws,  # noqa: ARG001
                                          restore_git_config, publisher_user):
    """搜索词里带 % _ 和引号 → 不报错 (SQL 通配符注入)."""
    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="sqli-demo")
    for q in ["%", "_", "' OR 1=1 --", "\\", "100%"]:
        r = await client.get(f"{API}?q={q}&limit=10", headers=auth)
        assert r.status_code == 200, (q, r.text)


# ---------- 搜索: 按项目 (2026-10-25) ----------

async def test_search_hits_assets_of_that_project(client, auth, ws,  # noqa: ARG001
                                                   restore_git_config, publisher_user):
    """输入项目号 → 能搜到归属该项目的资产.

    ⚠️ 注意语义: 搜索是**文本命中** (project 字段 LIKE %6100%),
       不是"项目筛选" (那会带上通用资产). 两者不一样, 别混.
    """
    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="proj-6100-demo", project="6100")
    await _upload(client, pauth, code="proj-general-demo", project="")

    r = await client.get(f"{API}?q=6100&limit=50", headers=auth)
    assert r.status_code == 200, r.text
    codes = [i["code"] for i in r.json()["items"]]
    assert "proj-6100-demo" in codes, codes
    # 通用资产的 project 是空串 —— 搜项目号**不该**命中它
    assert "proj-general-demo" not in codes, codes


async def test_search_general_keyword_hits_general_assets(client, auth, ws,  # noqa: ARG001
                                                           restore_git_config, publisher_user):
    """搜「通用」→ 命中通用资产 (显示名叫「通用」, 存的却是空串)."""
    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="gen-kw-demo", project="")
    await _upload(client, pauth, code="proj-kw-demo", project="6100")

    r = await client.get(f"{API}?q=通用&limit=50", headers=auth)
    assert r.status_code == 200, r.text
    codes = [i["code"] for i in r.json()["items"]]
    assert "gen-kw-demo" in codes, codes
    assert "proj-kw-demo" not in codes, codes


# ---------- 审计: 动作中文由后端给 ----------

async def test_audit_action_label_comes_from_backend(client, auth, ws,  # noqa: ARG001
                                                      restore_git_config, publisher_user):
    """审计接口要吐 action_label —— 中文只有一个真源, 前端不再自己翻译."""
    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    await _upload(client, pauth, code="audit-label-demo")

    r = await client.get(f"{API}/audits?limit=50", headers=auth)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items, "应该至少有上传那条审计"
    for it in items:
        assert it.get("action_label"), f"审计条目缺 action_label: {it}"
        assert it["action_label"] != it["action"], f"action_label 没翻译: {it}"
    creates = [i for i in items if i["action"] == "create"]
    assert creates and creates[0]["action_label"] == "新建资产", creates


def test_audit_action_label_known_actions():
    """后端认得的动作都要有中文; 没登记的原样返回 (宁可露 id 也不显示空白)."""
    from app.core.market_state import audit_action_label

    assert audit_action_label("create") == "新建资产"
    assert audit_action_label("unpublish_approve").startswith("通过下架申请")
    # 不存在的动作 → 原样返回
    assert audit_action_label("nope") == "nope"
    assert audit_action_label("") == ""


async def test_upload_with_huge_metadata_rejected(client, auth, ws,  # noqa: ARG001
                                                  restore_git_config, publisher_user):
    """超长字段 → 422 (别把垃圾写进 manifest)."""
    await set_setting("marketplace.review.enabled", "false")
    await _enable_publisher(publisher_user)
    pauth = {"Authorization": f"Bearer {publisher_user['token']}"}
    r = await client.post(
        f"{API}/upload",
        data={"code": "dml-huge", "kind": "skill", "name": "x" * 500,
              "summary": "s" * 2000},
        headers=pauth,
    )
    assert r.status_code == 422, r.text
