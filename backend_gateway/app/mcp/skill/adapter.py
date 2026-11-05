"""Thin adapters from authenticated MCP calls to existing extensions routes."""
from __future__ import annotations

import base64
import binascii
import io
import json
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException, UploadFile

from app.api import extensions
from app.core import ext_naming, ext_rules, pkg
from app.core.security import create_asset_download_ticket
from app.core.settings_store import get as get_setting
from app.mcp.common.context import McpContext
from app.schemas.asset import AssetMetaUpdateIn


def _json(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json")


_EXTENSION_KINDS = ("skill", "plugin", "mcp")


def _validate_kind(kind: str) -> str:
    if kind not in _EXTENSION_KINDS:
        raise HTTPException(
            status_code=422, detail="kind 必须是 skill / plugin / mcp 之一"
        )
    return kind


async def _list_assets(
    ctx: McpContext,
    *,
    kind: str | None,
    keyword: str | None,
    category: str | None,
    project: str | None,
    include_unpublished: bool,
    limit: int,
    offset: int,
):
    """Supply every FastAPI Query default explicitly for a direct call."""
    return await extensions.list_assets(
        kind=kind,
        category=category,
        project=project,
        q=keyword,
        sort="hot",
        include_unpublished=include_unpublished,
        status="all" if include_unpublished else "published",
        limit=limit,
        offset=offset,
        client_id="local",
        user=ctx.principal.user,
    )


async def search(
    ctx: McpContext,
    kind: str | None = None,
    keyword: str | None = None,
    category: str | None = None,
    project: str | None = None,
    tag: str | None = None,
    author: str | None = None,
    include_unpublished: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    if kind is not None:
        _validate_kind(kind)
    if tag is None and author is None:
        result = await _list_assets(
            ctx,
            kind=kind,
            keyword=keyword,
            category=category,
            project=project,
            include_unpublished=include_unpublished,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        return {
            "items": [_json(item) for item in result.items],
            "total": result.total,
            "page": page,
            "page_size": page_size,
        }

    # The REST list has no exact tag/author parameters. Keep its query and
    # visibility authoritative, then apply those two exact filters before paging.
    matched = []
    offset = 0
    while True:
        result = await _list_assets(
            ctx,
            kind=kind,
            keyword=keyword,
            category=category,
            project=project,
            include_unpublished=include_unpublished,
            limit=500,
            offset=offset,
        )
        for item in result.items:
            if tag is not None and tag not in (item.tags or []):
                continue
            if author is not None and (item.author or "").casefold() != author.casefold():
                continue
            matched.append(item)
        offset += len(result.items)
        if not result.items or offset >= result.total:
            break

    start = (page - 1) * page_size
    return {
        "items": [_json(item) for item in matched[start : start + page_size]],
        "total": len(matched),
        "page": page,
        "page_size": page_size,
    }


async def get(ctx: McpContext, code: str) -> dict[str, Any]:
    result = await extensions.get_asset(
        code=code, client_id="local", user=ctx.principal.user
    )
    return _json(result)


async def read_doc(ctx: McpContext, code: str) -> dict[str, Any]:
    return _json(await extensions.get_asset_doc(code=code, user=ctx.principal.user))


async def list_files(ctx: McpContext, code: str) -> dict[str, Any]:
    return _json(await extensions.get_asset_files(code=code, user=ctx.principal.user))


def _validate_file_path(path: str) -> None:
    normalized = path.replace("\\", "/")
    if (
        not path
        or PurePosixPath(path).is_absolute()
        or PureWindowsPath(path).is_absolute()
        or path.startswith("\\")
        or ".." in normalized.split("/")
    ):
        raise HTTPException(status_code=400, detail="文件路径必须是包内相对路径")


async def read_file(ctx: McpContext, code: str, path: str) -> dict[str, Any]:
    _validate_file_path(path)
    bundle = await extensions.get_asset_bundle(code=code, user=ctx.principal.user)
    selected = next((item for item in bundle.files if item.path == path), None)
    if selected is None:
        raise HTTPException(status_code=404, detail="资产包内没有该文件")
    if selected.encoding != "text" or any(
        (ord(character) < 32 or 127 <= ord(character) <= 159)
        and character not in "\n\r\t"
        for character in selected.content
    ):
        raise HTTPException(status_code=422, detail="只能读取文本文件")
    return {
        "code": bundle.code,
        "version": bundle.version,
        "path": selected.path,
        "encoding": "text",
        "content": selected.content,
    }


async def package_info(
    ctx: McpContext, code: str, version: str | None = None
) -> dict[str, Any]:
    asset = await extensions.get_asset(
        code=code, client_id="local", user=ctx.principal.user
    )
    selected_version = version or asset.version
    base = extensions._asset_dir(asset)
    package_dir = base / "package"
    candidates = []
    if not package_dir.is_symlink() and package_dir.is_dir():
        expected_names = {
            f"{selected_version}{suffix}" for suffix in ext_naming.PACKAGE_SUFFIXES
        }
        candidates = [
            item
            for item in package_dir.iterdir()
            if not item.is_symlink() and item.is_file() and item.name in expected_names
        ]
    if not candidates:
        raise HTTPException(status_code=404, detail="请求版本的安装包不存在")
    package = sorted(candidates, key=lambda item: item.name)[0]
    ticket, _ = create_asset_download_ticket(
        user_id=ctx.principal.user.id, code=asset.code, version=selected_version
    )
    public_base = str(
        await get_setting("extensions.public_base_url", "") or ""
    ).strip().rstrip("/")
    download_url = (
        f"{public_base}/api/v1/extensions/{quote(asset.code, safe='')}"
        f"/versions/{quote(selected_version, safe='')}/ticket-download"
        f"?ticket={quote(ticket, safe='')}"
    )

    return {
        "code": asset.code,
        "version": selected_version,
        # ⚠️ 不带版本号 —— 下载到本地就该是 dml-xxx.zip, 不是 dml-xxx-1.0.0.zip
        "filename": ext_naming.download_filename(asset.code, package.name),
        "size_bytes": package.stat().st_size,
        "sha256": pkg.sha256_file(package),
        "download_url": download_url,
    }


async def categories(ctx: McpContext) -> dict[str, Any]:
    rules = await ext_rules.rules_payload()
    return {"items": rules["categories"]}


async def projects(ctx: McpContext) -> dict[str, Any]:
    rules = await ext_rules.rules_payload()
    return {"items": rules["projects"]}


async def job_status(ctx: McpContext, job_id: int) -> dict[str, Any]:
    return _json(await extensions.get_job(job_id=job_id, user=ctx.principal.user))


async def _package_uploads(
    code: str,
    files: dict[str, str] | None,
    package_base64: str | None,
) -> tuple[list[UploadFile] | None, UploadFile | None]:
    """Validate package input completely before any extensions side effect."""
    if (files is None) == (package_base64 is None):
        raise HTTPException(
            status_code=422, detail="files 与 package_base64 必须且只能提供一个"
        )
    if files is not None:
        if not files:
            raise HTTPException(status_code=422, detail="files 不能为空")
        return [
            UploadFile(filename=path, file=io.BytesIO(content.encode("utf-8")))
            for path, content in files.items()
        ], None

    if not package_base64:
        raise HTTPException(status_code=422, detail="package_base64 不能为空")
    try:
        raw = base64.b64decode(package_base64, validate=True)
    except (binascii.Error, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="package_base64 不是严格 Base64") from exc
    max_bytes = await extensions._max_package_bytes()
    if max_bytes is not None and len(raw) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"{code}.zip 超过大小上限 ({max_bytes // 1024 // 1024} MB)",
        )
    return None, UploadFile(filename=f"{code}.zip", file=io.BytesIO(raw))


def _json_field(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


async def _extension_source(
    code: str,
    kind: str,
    *,
    files: dict[str, str] | None,
    package_base64: str | None,
    mcp_config: dict[str, Any] | None,
) -> tuple[list[UploadFile] | None, UploadFile | None, str]:
    """Split extension kinds into package-backed vs config-only before side effects."""
    if kind == "mcp":
        if files is not None or package_base64 is not None:
            raise HTTPException(
                status_code=422, detail="连接器不需要安装包，只提供 mcp_config"
            )
        if mcp_config is None:
            raise HTTPException(
                status_code=422, detail="连接器必须提供 MCP 配置 (mcp_config)"
            )
        return None, None, _json_field(mcp_config)
    if mcp_config is not None:
        raise HTTPException(
            status_code=422, detail="只有连接器 (kind=mcp) 才能提供 mcp_config"
        )
    uploads, package = await _package_uploads(code, files, package_base64)
    return uploads, package, ""


async def publish(
    ctx: McpContext,
    code: str,
    name: str,
    version: str,
    summary: str,
    kind: str = "skill",
    description: str = "",
    use_when: str = "",
    not_for: str = "",
    category: str = "",
    project: str = "",
    icon: str = "🧩",
    tags: list[str] | None = None,
    keywords: list[str] | None = None,
    featured: bool = False,
    permissions: dict[str, Any] | None = None,
    install_steps: list[str] | None = None,
    bindings: dict[str, Any] | None = None,
    mcp_config: dict[str, Any] | None = None,
    files: dict[str, str] | None = None,
    package_base64: str | None = None,
) -> dict[str, Any]:
    kind = _validate_kind(kind)
    uploads, package, config_text = await _extension_source(
        code,
        kind,
        files=files,
        package_base64=package_base64,
        mcp_config=mcp_config,
    )
    user = ctx.principal.user
    await extensions.require_publisher(user)
    result = await extensions.upload_asset(
        code=code,
        kind=kind,
        name=name,
        summary=summary,
        version=version,
        description=description,
        use_when=use_when,
        not_for=not_for,
        category=category,
        project=project,
        icon=icon,
        tags=_json_field(tags if tags is not None else []),
        keywords=_json_field(keywords if keywords is not None else []),
        featured=featured,
        permissions=_json_field(permissions if permissions is not None else {}),
        install_steps=_json_field(install_steps if install_steps is not None else []),
        bindings=_json_field(bindings if bindings is not None else {}),
        mcp_config=config_text,
        files=uploads,
        package=package,
        user=user,
    )
    return _json(result)


async def update(
    ctx: McpContext,
    code: str,
    version: str,
    name: str | None = None,
    summary: str | None = None,
    description: str | None = None,
    use_when: str | None = None,
    not_for: str | None = None,
    category: str | None = None,
    project: str | None = None,
    icon: str | None = None,
    tags: list[str] | None = None,
    keywords: list[str] | None = None,
    featured: bool | None = None,
    permissions: dict[str, Any] | None = None,
    install_steps: list[str] | None = None,
    bindings: dict[str, Any] | None = None,
    kind: str | None = None,
    mcp_config: dict[str, Any] | None = None,
    files: dict[str, str] | None = None,
    package_base64: str | None = None,
) -> dict[str, Any]:
    user = ctx.principal.user
    current = await extensions.get_asset(code=code, client_id="local", user=user)
    if version == current.version:
        raise HTTPException(status_code=409, detail="version 必须不同于当前版本")
    if kind is not None and kind != current.kind:
        raise HTTPException(
            status_code=422, detail="资产类型不可变更，kind 必须与已发布类型一致"
        )
    effective_kind = _validate_kind(current.kind)
    uploads, package, config_text = await _extension_source(
        code,
        effective_kind,
        files=files,
        package_base64=package_base64,
        mcp_config=mcp_config,
    )
    await extensions.require_publisher(user)
    result = await extensions.update_asset(
        code=code,
        kind=effective_kind,
        name=current.name if name is None else name,
        summary=current.summary if summary is None else summary,
        version=version,
        description=current.description if description is None else description,
        use_when=current.use_when if use_when is None else use_when,
        not_for=current.not_for if not_for is None else not_for,
        category=current.category if category is None else category,
        project=current.project if project is None else project,
        icon=current.icon if icon is None else icon,
        tags=_json_field(current.tags if tags is None else tags),
        keywords=_json_field(current.keywords if keywords is None else keywords),
        featured=current.featured if featured is None else featured,
        permissions=_json_field(current.permissions if permissions is None else permissions),
        install_steps=_json_field(
            current.install_steps if install_steps is None else install_steps
        ),
        bindings=_json_field(current.bindings if bindings is None else bindings),
        mcp_config=config_text,
        files=uploads,
        package=package,
        user=user,
    )
    return _json(result)


async def edit_meta(
    ctx: McpContext,
    code: str,
    name: str | None = None,
    icon: str | None = None,
    summary: str | None = None,
    description: str | None = None,
    use_when: str | None = None,
    not_for: str | None = None,
    category: str | None = None,
    project: str | None = None,
    tags: list[str] | None = None,
    keywords: list[str] | None = None,
    permissions: dict[str, Any] | None = None,
    install_steps: list[str] | None = None,
    bindings: dict[str, Any] | None = None,
    mcp_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    changes = {
        key: value
        for key, value in {
            "name": name,
            "icon": icon,
            "summary": summary,
            "description": description,
            "use_when": use_when,
            "not_for": not_for,
            "category": category,
            "project": project,
            "tags": tags,
            "keywords": keywords,
            "permissions": permissions,
            "install_steps": install_steps,
            "bindings": bindings,
            "mcp_config": mcp_config,
        }.items()
        if value is not None
    }
    if not changes:
        raise HTTPException(status_code=422, detail="至少提供一个可编辑字段")
    user = ctx.principal.user
    if mcp_config is not None:
        current = await extensions.get_asset(code=code, client_id="local", user=user)
        if current.kind != "mcp":
            raise HTTPException(
                status_code=422, detail="只有连接器 (kind=mcp) 才能修改 MCP 配置"
            )
    await extensions.require_publisher(user)
    result = await extensions.update_asset_meta(
        code=code, payload=AssetMetaUpdateIn(**changes), user=user
    )
    return _json(result)


async def submit_review(
    ctx: McpContext, code: str, comment: str = ""
) -> dict[str, Any]:
    user = ctx.principal.user
    await extensions.require_publisher(user)
    return await extensions.submit_for_review(code=code, comment=comment, _user=user)


async def unpublish_request(
    ctx: McpContext, code: str, reason: str = ""
) -> dict[str, Any]:
    user = ctx.principal.user
    await extensions.require_publisher(user)
    return await extensions.unpublish_asset(
        code=code, confirm_code=code, comment=reason, user=user
    )
