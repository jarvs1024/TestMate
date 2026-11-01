"""市场规则端点: 前端与 MCP 共用后端现有命名/分类/项目规则."""
from __future__ import annotations

from app.core import market_projects
from tests.conftest import set_setting


async def test_market_rules_returns_complete_existing_contract(client, auth):
    response = await client.get("/api/v1/assets/rules", headers=auth)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "code": {
            "prefix": "dml-",
            "pattern": "^(?=.{3,64}$)dml-[a-z0-9]+(?:-[a-z0-9]+)*$",
            "example": "dml-ssd-log-doctor",
            "min_length": 3,
            "max_length": 64,
        },
        "segment": {
            "pattern": "^(?=.{3,64}$)[a-z0-9]+(?:-[a-z0-9]+)*$",
            "min_length": 3,
            "max_length": 64,
        },
        "package": {"suffixes": [".zip", ".tar.gz", ".tgz"]},
        "required": {
            "create": {
                "common": ["code", "name", "summary", "category", "version"],
                "skill": ["package"],
                "plugin": ["package"],
                "mcp": ["mcp_config"],
            },
            "update": {
                "common": ["name", "summary", "category", "version"],
                "skill": ["package"],
                "plugin": ["package"],
                "mcp": ["mcp_config"],
            },
            "edit": ["name", "summary", "category"],
        },
        "categories": [
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
                "slug": "misc",
                "name": "其他",
                "order": 99,
                "desc": "归不到上面任何一类",
            },
        ],
        "projects": ["6100", "3361", "8560", "9560", "3100"],
        "enforcement": {
            "require_code_prefix_on_create": True,
            "require_code_prefix_on_update": False,
            "code_must_match_package": True,
            "code_must_match_mcp_server": True,
            "unknown_category": "其他",
            "unknown_project": "",
        },
    }


async def test_market_rules_uses_configured_projects(client, auth):
    await set_setting(market_projects.SETTINGS_KEY, "7000, 7100")

    response = await client.get("/api/v1/assets/rules", headers=auth)

    assert response.status_code == 200, response.text
    assert response.json()["projects"] == ["7000", "7100"]
