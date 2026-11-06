"""Deployment proxy and real FastAPI MCP mounting contracts."""
from __future__ import annotations

import re
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from starlette.routing import Mount

from app.core import settings_store
from app.mcp.skill.server import build_skill_server

REPO_ROOT = Path(__file__).resolve().parents[2]
NGINX_CONFIGS = (
    (
        REPO_ROOT / "frontend_web" / "nginx.conf",
        "http://backend:8000",
    ),
    (
        REPO_ROOT / "deploy" / "native" / "units" / "nginx.conf.tpl",
        "http://127.0.0.1:@@BACKEND_PORT@@",
    ),
)


def _location(config: str, path: str) -> str | None:
    match = re.search(
        rf"(?m)^\s*location\s+{re.escape(path)}\s*\{{", config
    )
    if match is None:
        return None
    opening = config.find("{", match.start())
    depth = 0
    for index in range(opening, len(config)):
        if config[index] == "{":
            depth += 1
        elif config[index] == "}":
            depth -= 1
            if depth == 0:
                return config[opening : index + 1]
    raise AssertionError(f"Unclosed location {path}")


@pytest.mark.parametrize(("path", "upstream"), NGINX_CONFIGS)
def test_nginx_proxies_mcp_oauth_and_discovery_with_original_host(path, upstream):
    config = path.read_text(encoding="utf-8")
    for location_path in ("/mcp", "/oauth/", "/.well-known/oauth-"):
        block = _location(config, location_path)
        assert block is not None, f"{path}: missing {location_path}"
        assert f"proxy_pass {upstream};" in block
        assert "proxy_set_header X-Forwarded-Host $http_host;" in block

    mcp = _location(config, "/mcp")
    assert mcp is not None
    assert "proxy_buffering off;" in mcp


@pytest.mark.parametrize(("path", "_upstream"), NGINX_CONFIGS)
def test_connect_paths_remain_spa_routes(path, _upstream):
    config = path.read_text(encoding="utf-8")
    root = _location(config, "/")
    assert root is not None
    assert "try_files $uri $uri/ /index.html;" in root
    assert _location(config, "/connect") is None
    assert _location(config, "/connect/") is None


def test_allowed_hosts_setting_preserves_bare_host_and_host_port():
    setting = next(
        (item for item in settings_store.SETTING_SCHEMA if item["key"] == "mcp.allowed_hosts"),
        None,
    )
    assert setting is not None
    assert setting["value_type"] == "string"

    server = build_skill_server(
        public_base_url="http://test:8081",
        allowed_hosts="mcp.example.test,mcp.example.test:8081",
    )
    allowed = set(server.settings.transport_security.allowed_hosts)
    assert {"mcp.example.test", "mcp.example.test:8081"} <= allowed


def test_native_mcp_rejects_multiple_workers_instead_of_warning():
    script = (REPO_ROOT / "deploy" / "native" / "tmctl.sh").read_text(
        encoding="utf-8"
    )
    render = script.split("render_app_configs() {", 1)[1].split(
        "# ---- 生成 systemd", 1
    )[0]
    guard = script.split("require_single_worker() {", 1)[1].split("\n}", 1)[0]
    assert "require_single_worker" in render
    assert "MCP" in guard
    assert "die " in guard
    assert "已按你填的值继续" not in guard


def _run_native_start_harness(entrypoint: str, *, workers: str, tmp_path: Path):
    """Run real start functions with every process/service boundary stubbed."""
    script = (REPO_ROOT / "deploy" / "native" / "tmctl.sh").read_text(
        encoding="utf-8"
    )
    definitions = script.split("# ==================== 分发", 1)[0]
    definitions = definitions.replace(
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"',
        f'SCRIPT_DIR="{REPO_ROOT / "deploy" / "native"}"',
        1,
    )
    harness = tmp_path / "native-start-harness.sh"
    harness.write_text(
        definitions
        + f"""
ENV_FILE="$TMPDIR/native.env"
printf 'BACKEND_WORKERS={workers}\\n' > "$ENV_FILE"
ATTEMPTS="$TMPDIR/native-start-attempts"
: > "$ATTEMPTS"
systemctl() {{ printf 'systemctl %s\\n' "$*" >> "$ATTEMPTS"; }}
launchctl() {{ printf 'launchctl %s\\n' "$*" >> "$ATTEMPTS"; }}
local_spawn() {{ printf 'local_spawn %s\\n' "$*" >> "$ATTEMPTS"; }}
need_root() {{ :; }}
need_systemd() {{ :; }}
wait_healthy() {{ :; }}
warn_docker_frontend() {{ :; }}
warn_concurrent_backend() {{ :; }}
local_launchd_loaded() {{ return 1; }}
DRIVER=systemd
{entrypoint}
""",
        encoding="utf-8",
    )
    return subprocess.run(
        ["bash", str(harness)],
        cwd=REPO_ROOT,
        env={"PATH": "/usr/bin:/bin", "TMPDIR": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("entrypoint", ["cmd_start", "cmd_restart"])
def test_native_service_start_and_restart_reject_multiple_workers_before_systemctl(
    entrypoint, tmp_path
):
    result = _run_native_start_harness(entrypoint, workers="2", tmp_path=tmp_path)

    assert result.returncode != 0
    assert "BACKEND_WORKERS" in result.stderr
    assert not (tmp_path / "native-start-attempts").read_text()


def test_native_local_backend_rejects_multiple_workers_before_spawn(tmp_path):
    venv_bin = tmp_path / "runtime" / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "uvicorn").touch()
    (venv_bin / "uvicorn").chmod(0o755)
    result = _run_native_start_harness(
        'RUNTIME_DIR="$TMPDIR/runtime"; DRIVER=local; local_start_backend',
        workers="2",
        tmp_path=tmp_path,
    )

    assert result.returncode != 0
    assert "BACKEND_WORKERS" in result.stderr
    assert not (tmp_path / "native-start-attempts").read_text()


@pytest.mark.parametrize("entrypoint", ["cmd_start", "cmd_restart"])
def test_native_service_start_and_restart_preserve_single_worker(entrypoint, tmp_path):
    result = _run_native_start_harness(entrypoint, workers="1", tmp_path=tmp_path)

    assert result.returncode == 0, result.stderr
    assert "systemctl" in (tmp_path / "native-start-attempts").read_text()


def test_native_local_backend_preserves_single_worker(tmp_path):
    venv_bin = tmp_path / "runtime" / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "uvicorn").touch()
    (venv_bin / "uvicorn").chmod(0o755)
    result = _run_native_start_harness(
        'RUNTIME_DIR="$TMPDIR/runtime"; DRIVER=local; local_start_backend',
        workers="1",
        tmp_path=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert "local_spawn backend" in (tmp_path / "native-start-attempts").read_text()


def _mounted_dispatcher(app):
    mount = next(
        (
            route
            for route in app.routes
            if isinstance(route, Mount) and route.path == "/mcp"
        ),
        None,
    )
    assert mount is not None, "The real FastAPI app must mount MCP at /mcp"
    return mount.app


def test_real_app_mounts_skill_dispatcher():
    from app.main import app

    dispatcher = _mounted_dispatcher(app)
    assert callable(dispatcher)


async def test_real_app_lifespan_configures_after_seed_and_runs_mcp_manager(
    monkeypatch,
):
    from app import main
    from app.core import asset_jobs, dingtalk, sync_puller

    dispatcher = _mounted_dispatcher(main.app)
    seeded = False

    async def fake_noop():
        return None

    async def fake_seed_defaults():
        nonlocal seeded
        seeded = True

    settings = {
        "extensions.public_base_url": "http://test:8081",
        "mcp.allowed_hosts": "test,test:8081",
        "extensions.git.remote": "",
        "extensions.git.branch": "main",
        "software.storage_path": "",
    }

    async def fake_get(key, default=None):
        assert seeded, f"Setting {key} was read before settings seed"
        return settings.get(key, default)

    async def fake_recover():
        return 0

    async def fake_start_puller(_interval):
        return None

    monkeypatch.setattr(main, "init_db", fake_noop)
    monkeypatch.setattr(main, "seed_agents", fake_noop)
    monkeypatch.setattr(main, "seed_defaults", fake_seed_defaults)
    monkeypatch.setattr(settings_store, "get", fake_get)
    monkeypatch.setattr(asset_jobs, "recover_pending_jobs", fake_recover)
    monkeypatch.setattr(asset_jobs, "start_worker", lambda: None)
    monkeypatch.setattr(dingtalk, "start_retry_worker", lambda: None)
    monkeypatch.setattr(dingtalk, "start_aggregate_worker", lambda: None)
    monkeypatch.setattr(sync_puller, "start_puller", fake_start_puller)

    real_mcp_lifespan = main.run_mcp_lifespan
    managed = []

    @asynccontextmanager
    async def observed_mcp_lifespan(domains):
        managed.append(domains)
        async with real_mcp_lifespan(domains):
            yield

    monkeypatch.setattr(main, "run_mcp_lifespan", observed_mcp_lifespan)

    async with main.app.router.lifespan_context(main.app):
        assert managed == [dispatcher]
        assert set(dispatcher.domains) == {"extensions", "kb"}
        for domain in ("extensions", "kb"):
            allowed = set(
                dispatcher.domains[domain].settings.transport_security.allowed_hosts
            )
            assert {"test", "test:8081"} <= allowed
        assert dispatcher.domains["kb"].settings.streamable_http_path == "/kb"
