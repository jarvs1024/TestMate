"""知识库 — 代理 RAGFlow。

提供:
- GET  /api/v1/kb/datasets        列出 RAGFlow datasets
- POST /api/v1/kb/search          检索 (代理 RAGFlow /retrieval)
- GET  /api/v1/kb/health          健康检查

2026-10-29 新增 (普通用户也能往知识库加内容了):
- POST /api/v1/kb/datasets/{id}/documents            上传文档 (tester 及以上)
- GET  /api/v1/kb/datasets/{id}/documents/{doc}/download  下载文档 (所有登录用户)
- GET  /api/v1/kb/audits                             操作审计 (所有登录用户)

⚠️ **删除仍然只有 admin 能做** —— 用户上传的内容进的是**共享**知识库,
   要能删就意味着能把别人的东西删掉, 那不能给普通用户.
"""
import logging
import os
import re
from urllib.parse import quote as _quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.auth import get_current_user
from app.core.ragflow_client import (
    list_datasets, retrieval, probe,
    list_documents, ingest_documents, delete_documents,
    list_doc_chunks,
    upload_documents, download_document,
    create_dataset, delete_dataset,
)
from app.models.user import User
from app.models.user import UserRole

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------- 上传限制 (2026-10-29 用户拍板) ----------
# ⚠️ 网关侧要挡, RAGFlow 自己不限制 —— 不挡的话一个人传个 10G 文件就能把
#    服务端内存和磁盘撑爆 (本项目其它上传入口都是这么挡的).
MAX_UPLOAD_FILE_MB = 20          # 单文件 20MB
MAX_UPLOAD_FILES = 5             # 单次最多 5 个
MAX_UPLOAD_BYTES = MAX_UPLOAD_FILE_MB * 1024 * 1024


def _can_write(user: User) -> bool:
    """能不能**写**知识库 (上传文档).

    ⚠️ admin / tester 可以, **viewer 不行** —— viewer 的语义是"只读".
       删除更严 (只有 admin), 见下面的 delete_docs.
    """
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    return role in (UserRole.admin.value, UserRole.tester.value)


#: 知识库文档名的清洗规则 —— **故意比软件包那套宽得多**
#: ⚠️ 知识库的文件名只是 RAGFlow 里的 location/name, **不落我们的磁盘目录**,
#:    所以空格/括号/中文都得留着 —— 用户是按原名找文件的,
#:    静默改成 "xxx_yyy_.pdf" 用户根本认不出那是自己的文件.
#:    (软件包那套 `sanitize_filename` 是给"文件名会变目录名"的场景用的, 不能套用)
#:    只挡两样: 路径分隔符 (路径穿越) + 控制字符 (HTTP 头注入).
_KB_UNSAFE_CHARS = re.compile(r"[\x00-\x1f\x7f/\\]")

#: 知识库文档名长度上限 (跟软件包那套一致)
MAX_KB_FILE_NAME_LEN = 200


def _sanitize_kb_filename(raw: str, fallback: str) -> str:
    """洗知识库文档名 —— 保留空格/括号/中文, 只挡路径穿越和控制字符.

    ⚠️ 别用 :func:`app.core.software_store.sanitize_filename` —— 那个会把
       空格/括号换成下划线, 那是"文件名会落成目录名"场景的要求.
    """
    name = (raw or "").strip().replace("\x00", "")
    name = name.replace("\\", "/")
    name = name.split("/")[-1]          # 只取 basename (防 ../../etc/passwd)
    name = _KB_UNSAFE_CHARS.sub("_", name)
    name = name.strip().strip(".")      # 前导/结尾的点 (挡 ".." 和隐藏文件)
    if not name:
        name = fallback
    return name[:MAX_KB_FILE_NAME_LEN]


async def _read_upload_limited(upload: UploadFile, max_bytes: int, label: str) -> bytes:
    """分块读上传内容, 边读边限量 (超限立即 413).

    ⚠️ 别用 `await upload.read()` 全量进内存再校验 —— 那样一个超大文件
       就能把服务端内存打爆. 读多少收多少.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"「{label}」超过单文件上限 ({max_bytes // 1024 // 1024} MB)",
            )
        chunks.append(chunk)


class CreateDatasetIn(BaseModel):
    """新建数据集的入参."""

    name: str = Field(..., min_length=1, max_length=128, description="数据集名称")
    description: str = Field("", max_length=500, description="说明 (一句话讲清这个库放什么)")
    #: RAGFlow v0.26.1 的 chunk_method: naive(通用/自动分段) | manual(手动切分)
    chunk_method: str = Field("naive", description="切片方式")
    embedding_model: str = Field("", description="嵌入模型 (空=跟现有数据集一致)")


@router.post("/datasets")
async def create_kb_dataset(
    payload: CreateDatasetIn,
    user: User = Depends(get_current_user),
) -> dict:
    """新建一个知识库数据集 (代理 RAGFlow POST /datasets).

    权限: **tester 及以上** (跟上传文档同一档, viewer 是只读角色).

    ⚠️ 新建的库会**立刻出现在所有人的列表里** —— 所以名字要能讲清楚这个库放什么.
    ⚠️ 重名直接报错: RAGFlow 自己会加数字后缀(`项目管理` → `项目管理(1)`),
       用户以为建了个新库, 结果是两个几乎一样的库.
    """
    if not _can_write(user):
        raise HTTPException(status_code=403, detail="只读账号不能创建数据集")

    chunk_method = (payload.chunk_method or "naive").strip().lower()
    if chunk_method not in ("naive", "manual"):
        raise HTTPException(status_code=422, detail="切片方式只能是 naive 或 manual")

    # 嵌入模型: 用户没指定就**跟现有数据集保持一致** ——
    # RAGFlow 租户默认值未必是这台机器上真装着的那个, 跟现有的走最稳
    emb = (payload.embedding_model or "").strip()
    if not emb:
        try:
            for d in await list_datasets(page=1, page_size=50):
                if d.get("embedding_model"):
                    emb = str(d["embedding_model"])
                    break
        except Exception as e:  # noqa: BLE001
            logger.debug("取现有数据集的 embedding_model 失败: %s", e)

    try:
        ds = await create_dataset(
            name=payload.name,
            description=(payload.description or "").strip(),
            chunk_method=chunk_method,
            embedding_model=emb,
        )
    except ValueError as e:
        # 重名 / 名称不合法 —— 是用户能自己改的, 不是服务器故障
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("create_dataset failed")
        raise HTTPException(status_code=502, detail=f"ragflow error: {e}")

    ds = ds or {}
    result = {
        "ok": True,
        "dataset": {
            "id": ds.get("id"),
            "name": ds.get("name") or payload.name,
            "description": ds.get("description") or (payload.description or "").strip(),
            "chunk_method": ds.get("chunk_method") or chunk_method,
            "embedding_model": ds.get("embedding_model") or emb,
            "permission": ds.get("permission", "me"),
            "document_count": ds.get("document_count", 0),
            "chunk_count": ds.get("chunk_count", 0),
        },
    }
    # 归属: 记下「这个库是谁建的」—— RAGFlow 那边记不了 TestMate 的账号
    await _save_dataset_owner(ds, user)
    await _audit(
        action="create", user=user,
        dataset_id=str(ds.get("id") or ""),
        dataset_name=str(ds.get("name") or payload.name),
    )
    return result


@router.delete("/datasets/{dataset_id}")
async def delete_kb_dataset(
    dataset_id: str,
    user: User = Depends(get_current_user),
) -> dict:
    """删除整个数据集. **admin only**.

    权限跟「删除文档」同一档 —— 都是**不可逆**的破坏性操作, 只给 admin.

    ⚠️ **硬删, 不可逆** —— 库里的所有文档、它们的分段、MinIO 里的源文件
       一起没了, **没有回收站**. RAGFlow 是逐个文档走 `remove_document`,
       删掉一个 1000 段的库要跑一会儿.
    ⚠️ RAGFlow 那边清 ES / 对象存储是**后台任务** —— 接口已经返回 200,
       列表里可能还短暂看得到那个库. 所以前端删完要**刷新**列表,
       别以为没删掉就再点一次 (那会真删第二遍).
    """
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="admin only")

    # 先把库名和内容规模捞出来 —— 审计要用, 前端确认文案也要
    ds_name, doc_count, chunk_count = "", 0, 0
    try:
        # ⚠️ page_size 只能是 100 以内 —— 传 200 RAGFlow 会返回 code=101 + 空 data
        for d in await list_datasets(page=1, page_size=100):
            if str(d.get("id") or "") == dataset_id:
                ds_name = str(d.get("name") or "")
                doc_count = int(d.get("document_count") or 0)
                chunk_count = int(d.get("chunk_count") or 0)
                break
    except Exception as e:  # noqa: BLE001
        # ⚠️ 这里不能当成"数据集不存在"(404) —— 那是**误导**:
        #    实际是 RAGFlow 挂了, 说的是"找不到"但真实原因是"连不上".
        logger.warning("删库前取数据集信息失败: %s", e)
        raise HTTPException(status_code=502, detail=f"ragflow error: {e}")

    if not ds_name:
        # 库里根本没有这个 id —— 别去调 RAGFlow 删一个不存在的东西
        raise HTTPException(status_code=404, detail="数据集不存在")

    try:
        await delete_dataset(dataset_id)
    except Exception as e:  # noqa: BLE001
        logger.exception("delete_dataset failed")
        await _audit(
            action="delete", user=user, dataset_id=dataset_id,
            dataset_name=ds_name, error=str(e)[:500],
        )
        raise HTTPException(status_code=502, detail=f"ragflow error: {e}")

    # 本地的归属记录也清掉 —— 库都没了, 归属也就没了
    await _drop_dataset_ownership(dataset_id)
    await _audit(action="delete", user=user, dataset_id=dataset_id, dataset_name=ds_name)
    return {
        "ok": True,
        "deleted": {
            "dataset_id": dataset_id,
            "name": ds_name,
            "documents": doc_count,
            "chunks": chunk_count,
        },
    }


@router.get("/datasets")
async def get_datasets(_user: User = Depends(get_current_user)) -> dict:
    """列出 RAGFlow datasets (代理)."""
    try:
        items = await list_datasets()
        # 精简: 去掉大字段 (avatar / create_time / update_time)
        cleaned = [
            {
                "id": d.get("id"),
                "name": d.get("name"),
                "description": d.get("description", ""),
                "chunk_count": d.get("chunk_count", 0),
                "document_count": d.get("document_count", 0),
                "chunk_method": d.get("chunk_method", ""),
                "create_date": d.get("create_date", ""),
                # P1: 多放一些字段, 前端可展示 embedding_model / 权限 / 切片参数等
                "embedding_model": d.get("embedding_model", ""),
                "permission": d.get("permission", "me"),
                "status": d.get("status", "1"),
                "language": d.get("language", ""),
                "token_num": d.get("token_num", 0),
                "similarity_threshold": d.get("similarity_threshold", 0.2),
                "vector_similarity_weight": d.get("vector_similarity_weight", 0.3),
                "pagerank": d.get("pagerank", 0),
                "update_date": d.get("update_date", ""),
                "create_time": d.get("create_time", 0),
                "update_time": d.get("update_time", 0),
                "parser_config": d.get("parser_config") or {},
            }
            for d in items
        ]
        # 归属: 补上「谁建的」—— RAGFlow 那边记不了 TestMate 的账号
        owners = await _owners_for_datasets([str(x.get("id") or "") for x in cleaned])
        for item in cleaned:
            o = owners.get(str(item.get("id") or ""), {})
            item["created_by"] = o.get("created_by")
            item["created_by_name"] = o.get("created_by_name", "")
            item["created_at"] = o.get("created_at")
        return {"items": cleaned, "total": len(cleaned)}
    except Exception as e:
        logger.exception("list_datasets failed")
        raise HTTPException(status_code=502, detail=f"ragflow error: {e}")





# ============ Documents (P2: 数据集下文档列表 / 重跑 / 删除) ============

@router.get("/datasets/{dataset_id}/documents")
async def get_documents(
    dataset_id: str,
    page: int = 1,
    page_size: int = 30,
    orderby: str = "create_time",
    desc: bool = True,
    keywords: str = "",
    run: str = "",
    _user: User = Depends(get_current_user),
) -> dict:
    """列出某 dataset 下的 documents (代理 RAGFlow)."""
    try:
        data = await list_documents(
            dataset_id=dataset_id, page=page, page_size=page_size,
            orderby=orderby, desc=desc, keywords=keywords, run=run,
        )
        docs = data.get("docs") or []
        # 精简字段, 不传 thumbnail (RAGFlow 相对路径没法直接展示)
        cleaned = [
            {
                "id": d.get("id"),
                "name": d.get("name"),
                "location": d.get("location", ""),
                "type": d.get("type", ""),
                "size": d.get("size", 0),
                "chunk_count": d.get("chunk_count", 0),
                "token_count": d.get("token_count", 0),
                "chunk_method": d.get("chunk_method", ""),
                "run": d.get("run", "UNSTART"),
                "progress": d.get("progress", 0.0),
                "progress_msg": d.get("progress_msg", ""),
                "process_begin_at": d.get("process_begin_at"),
                "process_duration": d.get("process_duration", 0.0),
                "source_type": d.get("source_type", ""),
                "status": d.get("status", "1"),
                "create_date": d.get("create_date", ""),
                "update_date": d.get("update_date", ""),
                "create_time": d.get("create_time", 0),
                "update_time": d.get("update_time", 0),
                "parser_config": d.get("parser_config") or {},
            }
            for d in docs
        ]
        # 归属: 补上「谁传的」—— RAGFlow 那边记不了 TestMate 的账号
        owners = await _owners_for_documents([str(x.get("id") or "") for x in cleaned])
        for item in cleaned:
            o = owners.get(str(item.get("id") or ""), {})
            item["uploaded_by"] = o.get("uploaded_by")
            item["uploaded_by_name"] = o.get("uploaded_by_name", "")
            item["uploaded_at"] = o.get("uploaded_at")
        # ⚠️ total 必须是**全量**文档数, 不是本页条数!
        #    RAGFlow 的 data.total 就是全量; 以前这里返回 len(cleaned) (本页数),
        #    前端那圈翻页循环 `for (page=2; all.length < total)` 于是永远不执行
        #    → 超过一页的数据集, 概览统计和预热都只拿到第一页.
        try:
            total = int(data.get("total") or 0)
        except (TypeError, ValueError):
            total = 0
        return {"docs": cleaned, "total": max(total, len(cleaned))}
    except Exception as e:
        logger.exception("list_documents failed")
        raise HTTPException(status_code=502, detail=f"ragflow error: {e}")


@router.get("/datasets/{dataset_id}/documents/{document_id}/chunks")
async def get_doc_chunks(
    dataset_id: str,
    document_id: str,
    page: int = 1,
    page_size: int = 100,
    keywords: str = "",
    _user: User = Depends(get_current_user),
) -> dict:
    """列出某 document 下的 chunks (代理 RAGFlow).

    注意: RAGFlow API 限制 page_size <= 100. 前端想要看完整分段列表应自己分页.
    """
    # 兜底: 防止前端传超过 100
    if page_size > 100:
        page_size = 100
    if page_size < 1:
        page_size = 30
    try:
        data = await list_doc_chunks(dataset_id, document_id, page=page, page_size=page_size, keywords=keywords)
        # 精简 chunks: content 不裁, 但去掉 content_ltks (很大)
        chunks = data.get("chunks") or []
        cleaned = []
        for c in chunks:
            cleaned.append({
                "id": c.get("id"),
                "content": c.get("content", ""),
                "docnm_kwd": c.get("docnm_kwd", ""),
                "document_id": c.get("document_id"),
                "available": c.get("available", True),
                "image_id": c.get("image_id", ""),
                "important_keywords": c.get("important_keywords", []),
                "tag_kwd": c.get("tag_kwd", []),
                "positions": c.get("positions", []),
                "create_time": c.get("create_time", ""),
                "create_timestamp": c.get("create_timestamp", 0),
            })
        return {
            "chunks": cleaned,
            "total": data.get("total", len(cleaned)),
            "doc": data.get("doc") or {},
        }
    except Exception as e:
        logger.exception("list_doc_chunks failed")
        raise HTTPException(status_code=502, detail=f"ragflow error: {e}")



async def _audit(
    *,
    action: str,
    user: User,
    dataset_id: str = "",
    dataset_name: str = "",
    document_id: str = "",
    doc_name: str = "",
    size: int = 0,
    error: str = "",
) -> None:
    """写一条知识库操作审计.

    ⚠️ **审计写不进去也不能让主流程失败** —— 审计是旁路, 不是主路.
       (RAGFlow 已经收下文件了, 却因为审计表写不进而报错, 那是"文件传了但显示失败")
    """
    try:
        from app.db.session import AsyncSessionLocal
        from app.models.kb import KbAudit

        async with AsyncSessionLocal() as s:
            s.add(KbAudit(
                dataset_id=dataset_id or "",
                dataset_name=dataset_name or "",
                document_id=document_id or "",
                doc_name=doc_name or "",
                action=action,
                actor_id=user.id,
                actor_name=user.username or "",
                error=error or "",
                size=int(size or 0),
            ))
            await s.commit()
    except Exception as e:  # noqa: BLE001 — 审计失败不能挡住业务
        logger.warning("写知识库审计失败 (已忽略): %s", e)


async def _dataset_info(dataset_id: str) -> tuple[str, str]:
    """取数据集的 (名称, 分块方式) —— 给审计和提示用.

    ⚠️ 取不到就返回空串, **不能因此失败** —— 上传本身跟这个没关系.
    """
    try:
        for d in await list_datasets(page=1, page_size=100):
            if d.get("id") == dataset_id:
                return str(d.get("name") or ""), str(d.get("chunk_method") or "")
    except Exception as e:  # noqa: BLE001
        logger.debug("取数据集信息失败: %s", e)
    return "", ""


# ============ 归属 (谁建的库 / 谁传的文档) ============
#
# ⚠️ **RAGFlow 记不了 TestMate 的账号** —— 它的 `created_by` 指的是 RAGFlow 用户,
#    而 TestMate 的所有登录用户共用**同一把 API key**.
#    所以「这个库是谁建的」「这篇是谁传的」只能存在 TestMate 自己的库里.
#
# ⚠️ 这些是**旁路** —— 写失败不能挡住业务 (跟审计一个待遇).


async def _save_dataset_owner(ds: dict, user: User) -> None:
    """记下「这个数据集是谁建的」."""
    ds_id = str(ds.get("id") or "")
    if not ds_id:
        return
    try:
        from app.db.session import AsyncSessionLocal
        from app.models.kb import KbDatasetMeta

        async with AsyncSessionLocal() as s:
            row = await s.get(KbDatasetMeta, ds_id)
            if row is None:
                row = KbDatasetMeta(dataset_id=ds_id)
                s.add(row)
            row.name = str(ds.get("name") or "")
            row.description = str(ds.get("description") or "")
            row.chunk_method = str(ds.get("chunk_method") or "")
            row.embedding_model = str(ds.get("embedding_model") or "")
            row.created_by = user.id
            row.created_by_name = user.username or ""
            await s.commit()
    except Exception as e:  # noqa: BLE001 — 归属写失败不能挡住业务
        logger.warning("写数据集归属失败 (已忽略): %s", e)


async def _save_document_owner(doc: dict, dataset_id: str, user: User) -> None:
    """记下「这篇文档是谁传的」.

    ⚠️ 语义是「**当前这一版**是谁传的」—— 重新上传过就更新成最后那个人.
    """
    doc_id = str(doc.get("id") or "")
    if not doc_id:
        return
    try:
        from app.db.session import AsyncSessionLocal
        from app.models.kb import KbDocumentMeta

        async with AsyncSessionLocal() as s:
            row = await s.get(KbDocumentMeta, doc_id)
            if row is None:
                row = KbDocumentMeta(document_id=doc_id)
                s.add(row)
            row.dataset_id = dataset_id
            row.doc_name = str(doc.get("name") or "")
            row.size = int(doc.get("size") or 0)
            row.uploaded_by = user.id
            row.uploaded_by_name = user.username or ""
            await s.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning("写文档归属失败 (已忽略): %s", e)


async def _owners_for_datasets(ids: list[str]) -> dict[str, dict]:
    """批量取数据集归属 —— 详情里显示「谁建的」.

    ⚠️ 取不到就返回空 dict, **不能因此失败** —— 归属只是展示用的附加信息.
    ⚠️ 历史数据集 (建库功能上线前手工建的) 在表里没有记录 → 详情显示「—」.
    """
    if not ids:
        return {}
    try:
        from sqlalchemy import select

        from app.db.session import AsyncSessionLocal
        from app.models.kb import KbDatasetMeta

        async with AsyncSessionLocal() as s:
            rows = (await s.execute(
                select(KbDatasetMeta).where(KbDatasetMeta.dataset_id.in_(ids))
            )).scalars().all()
            return {
                r.dataset_id: {
                    "created_by": r.created_by,
                    "created_by_name": r.created_by_name or "",
                    # ⚠️ 库里存的是 naive UTC, 这里**手动加 Z** ——
                    #    这个接口返回的是 plain dict, 走不到 schemas/base.py 的
                    #    UTCModel 序列化器, 不加 Z 前端会按本地时区解析, 差 8 小时.
                    "created_at": (r.created_at.isoformat() + "Z") if r.created_at else "",
                }
                for r in rows
            }
    except Exception as e:  # noqa: BLE001
        logger.warning("读数据集归属失败 (已忽略): %s", e)
        return {}


async def _owners_for_documents(ids: list[str]) -> dict[str, dict]:
    """批量取文档归属 —— 详情里显示「谁传的」."""
    if not ids:
        return {}
    try:
        from sqlalchemy import select

        from app.db.session import AsyncSessionLocal
        from app.models.kb import KbDocumentMeta

        async with AsyncSessionLocal() as s:
            rows = (await s.execute(
                select(KbDocumentMeta).where(KbDocumentMeta.document_id.in_(ids))
            )).scalars().all()
            return {
                r.document_id: {
                    "uploaded_by": r.uploaded_by,
                    "uploaded_by_name": r.uploaded_by_name or "",
                    # ⚠️ 同上 —— plain dict 走不到 UTCModel, 手动加 Z
                    "uploaded_at": (r.uploaded_at.isoformat() + "Z") if r.uploaded_at else "",
                }
                for r in rows
            }
    except Exception as e:  # noqa: BLE001
        logger.warning("读文档归属失败 (已忽略): %s", e)
        return {}


async def _drop_dataset_ownership(dataset_id: str) -> None:
    """删数据集时清掉本地归属记录 (RAGFlow 那边的库已经没了, 这边也该没)."""
    try:
        from sqlalchemy import delete as sa_delete

        from app.db.session import AsyncSessionLocal
        from app.models.kb import KbDatasetMeta, KbDocumentMeta

        async with AsyncSessionLocal() as s:
            await s.execute(
                sa_delete(KbDocumentMeta).where(KbDocumentMeta.dataset_id == dataset_id)
            )
            await s.execute(
                sa_delete(KbDatasetMeta).where(KbDatasetMeta.dataset_id == dataset_id)
            )
            await s.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning("清理数据集归属失败 (已忽略): %s", e)


#: RAGFlow 里 "手动分块" 的数据集 —— 它的解析器 (rag/app/manual.py) **只支持
#: pdf / docx**, 传 .txt/.md 会直接 NotImplementedError, 文档卡在 FAIL.
#: 所以这种数据集我们不自动发起解析, 直接把话说明白.
MANUAL_CHUNK_METHOD = "manual"
MANUAL_AUTO_PARSE_EXTS = (".pdf", ".docx")


@router.post("/datasets/{dataset_id}/documents")
async def upload_docs(
    dataset_id: str,
    file: list[UploadFile] = File(...),
    user: User = Depends(get_current_user),
) -> dict:
    """上传文档到指定数据集 (multipart/form-data, 字段名 `file`).

    权限: **tester 及以上** (viewer 是只读角色).

    ⚠️ 参数名**必须**叫 `file` —— FastAPI 是拿参数名去表单里取值的
       (`form.getlist(参数名)`), 字段名对不上就变成"没传文件" 422.
       多个文件就传多个同名的 `file` 字段 (和 RAGFlow 的接口一致).

    ⚠️ 上传完文档状态是 UNSTART —— **不启动解析它就不参与检索**, 等于白传.
       所以上传成功后会自动跟一次 ingest (解析是异步的, 这里只负责发起).
    """
    files = file
    if not _can_write(user):
        raise HTTPException(status_code=403, detail="只读账号不能上传文档")
    if not files:
        raise HTTPException(status_code=422, detail="没有选择文件")
    if len(files) > MAX_UPLOAD_FILES:
        raise HTTPException(
            status_code=422,
            detail=f"单次最多上传 {MAX_UPLOAD_FILES} 个文件 (这次 {len(files)} 个)",
        )

    # 文件名要洗过 —— 文件名会变成 RAGFlow 里的 location, 路径穿越的斜杠不能带过去
    prepared: list[tuple[str, bytes, str]] = []
    for f in files:
        raw_name = (f.filename or "").strip()
        if not raw_name:
            continue
        name = _sanitize_kb_filename(raw_name, f"doc-{len(prepared) + 1}")
        data = await _read_upload_limited(f, MAX_UPLOAD_BYTES, name)
        if not data:
            continue
        prepared.append((name, data, f.content_type or "application/octet-stream"))
    if not prepared:
        raise HTTPException(status_code=422, detail="没有可上传的文件 (空文件)")

    ds_name, chunk_method = await _dataset_info(dataset_id)
    try:
        created = await upload_documents(dataset_id, prepared)
    except Exception as e:  # noqa: BLE001
        logger.exception("upload_documents failed")
        await _audit(
            action="upload", user=user, dataset_id=dataset_id, dataset_name=ds_name,
            doc_name=", ".join(n for n, _, _ in prepared),
            size=sum(len(d) for _, d, _ in prepared),
            error=str(e)[:500],
        )
        raise HTTPException(status_code=502, detail=f"ragflow error: {e}")

    # ⚠️ 自动启动解析 —— 否则文档永远停在 UNSTART, 检索不到
    ids = [str(d.get("id")) for d in created if d.get("id")]
    ingest_ok = False
    warning = ""
    if chunk_method == MANUAL_CHUNK_METHOD and not all(
        n.lower().endswith(MANUAL_AUTO_PARSE_EXTS) for n, _, _ in prepared
    ):
        # ⚠️ 手动分块的数据集只认 pdf/docx —— 硬发解析必然 FAIL,
        #    文档会被标成 FAIL, 用户还以为是自己传坏了. 不如直接说清楚.
        warning = (
            f"「{ds_name or dataset_id}」是「手动分块」数据集, RAGFlow 只支持 "
            f"pdf/docx 自动解析 —— 文档已上传, 但需要管理员手动切分后才能被检索."
        )
        logger.info("数据集 %s 是 manual 分块, 跳过自动解析: %s", dataset_id, warning)
    elif ids:
        try:
            ingest_ok = await ingest_documents(ids, run="1")
        except Exception as e:  # noqa: BLE001 — 解析失败不该让上传失败 (文件已经在库里了)
            logger.warning("上传后启动解析失败 (文档已入库, 需手动重跑): %s", e)

    for d in created:
        await _audit(
            action="upload", user=user, dataset_id=dataset_id, dataset_name=ds_name,
            document_id=str(d.get("id") or ""), doc_name=str(d.get("name") or ""),
            size=int(d.get("size") or 0),
            # ⚠️ error 只放**真的失败** —— manual 数据集那条是"没解析"不是"没上传",
            #    塞进来前端会显示成「失败」(用户以为白传了).
            #    "没参与检索"这件事在上传时已经明确提示过了, 文档状态也在列表里看得到.
        )
        # 归属: 记下「这篇是谁传的」—— RAGFlow 那边记不了 TestMate 的账号
        await _save_document_owner(d, dataset_id, user)

    return {
        "ok": True,
        "uploaded": len(created),
        "ingest_started": ingest_ok,
        "warning": warning,
        "docs": [
            {
                "id": d.get("id"),
                "name": d.get("name"),
                "size": d.get("size", 0),
                "location": d.get("location", ""),
                "run": d.get("run", "UNSTART"),
            }
            for d in created
        ],
    }


def _ascii_fallback_name(filename: str, fallback: str) -> str:
    """给 Content-Disposition 的 ``filename=`` 准备一个**纯 ASCII**的兜底名.

    ⚠️ HTTP 头是 latin-1 的 —— starlette 编码头值时用的是 latin-1,
       中文直接抛 UnicodeEncodeError (整个下载 500).
    ⚠️ 空格可以留 (外面有引号) —— 但引号和反斜杠必须换掉, 它们会**截断头**.
    """
    stem, ext = os.path.splitext(filename)
    ascii_stem = stem.encode("ascii", "ignore").decode("ascii")
    ascii_stem = re.sub(r'["\\]', "_", ascii_stem).strip()
    if not ascii_stem:
        ascii_stem = fallback
    # 扩展名也要是纯 ASCII, 否则照样编不了
    ascii_ext = ext if ext.encode("ascii", "ignore").decode("ascii") == ext else ""
    return f"{ascii_stem}{ascii_ext}"


def _content_disposition(filename: str, fallback: str) -> str:
    """拼 Content-Disposition —— **必须 latin-1 安全**.

    ⚠️ 中文文件名**不能**直接放进 `filename="..."` —— 头是 latin-1 的,
       放进去整个响应 500. 规矩:
         · `filename="xxx"`   → 纯 ASCII 兜底名 (老浏览器 / 老客户端认这个)
         · `filename*=UTF-8''xxx` → RFC 5987, 真名 (浏览器优先用这个)
    """
    ascii_name = _ascii_fallback_name(filename, fallback)
    return (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{_quote(filename, safe='')}"
    )


@router.get("/datasets/{dataset_id}/documents/{document_id}/download")
async def download_doc(
    dataset_id: str,
    document_id: str,
    _user: User = Depends(get_current_user),
) -> Response:
    """下载文档的**原始文件**.

    权限: 所有登录用户 —— 知识库本来就是共享的, 下载是只读操作.

    ⚠️ RAGFlow 这个接口返回的是**文件字节流**(不是 JSON), 所以这里必须
       原样透传, 不能包成 {"data": ...}.
    """
    try:
        content, filename, ctype = await download_document(dataset_id, document_id)
    except Exception as e:  # noqa: BLE001
        logger.exception("download_document failed")
        raise HTTPException(status_code=502, detail=f"ragflow error: {e}")

    # 文件名兜底 —— RAGFlow 的 content-disposition 偶尔没有文件名
    safe = _sanitize_kb_filename(filename, f"document-{document_id[:8]}")
    disposition = _content_disposition(safe, f"document-{document_id[:8]}")
    return Response(
        content=content,
        media_type=ctype or "application/octet-stream",
        headers={"Content-Disposition": disposition},
    )


@router.get("/audits")
async def get_audits(
    limit: int = 50,
    _user: User = Depends(get_current_user),
) -> dict:
    """知识库操作审计 (谁在什么时候传了什么).

    ⚠️ 内容存在 RAGFlow 里, RAGFlow 自己记不了 TestMate 的账号
       (所有人共用一把 API key) —— "谁传的"只能靠这张表.
    """
    from sqlalchemy import desc, select

    from app.db.session import AsyncSessionLocal
    from app.models.kb import KbAudit

    limit = max(1, min(int(limit or 50), 200))
    try:
        async with AsyncSessionLocal() as s:
            rows = (
                await s.execute(
                    select(KbAudit).order_by(desc(KbAudit.id)).limit(limit)
                )
            ).scalars().all()
        return {
            "items": [
                {
                    "id": r.id,
                    "dataset_id": r.dataset_id,
                    "dataset_name": r.dataset_name,
                    "document_id": r.document_id,
                    "doc_name": r.doc_name,
                    "action": r.action,
                    "actor_name": r.actor_name,
                    "error": r.error,
                    "size": r.size,
                    "created_at": r.created_at.isoformat() + "Z" if r.created_at else "",
                }
                for r in rows
            ],
            "total": len(rows),
        }
    except Exception as e:  # noqa: BLE001
        logger.exception("list kb audits failed")
        raise HTTPException(status_code=500, detail=f"读取审计失败: {e}")


class IngestIn(BaseModel):
    doc_ids: list[str] = Field(..., min_length=1)
    run: str = Field("1", description="1=start, 2=cancel")
    delete: bool = False


@router.post("/datasets/{dataset_id}/documents/ingest")
async def ingest(
    dataset_id: str,
    payload: IngestIn,
    user: User = Depends(get_current_user),
) -> dict:
    """启动/取消文档解析. admin only."""
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="admin only")
    try:
        ok = await ingest_documents(payload.doc_ids, run=payload.run, delete=payload.delete)
        return {"ok": ok}
    except Exception as e:
        logger.exception("ingest failed")
        raise HTTPException(status_code=502, detail=f"ragflow error: {e}")


class DeleteDocsIn(BaseModel):
    ids: list[str] | None = None
    delete_all: bool = False


@router.delete("/datasets/{dataset_id}/documents")
async def delete_docs(
    dataset_id: str,
    payload: DeleteDocsIn,
    user: User = Depends(get_current_user),
) -> dict:
    """删除 dataset 下的文档. admin only."""
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="admin only")
    try:
        ok = await delete_documents(dataset_id, doc_ids=payload.ids, delete_all=payload.delete_all)
        return {"ok": ok}
    except Exception as e:
        logger.exception("delete_docs failed")
        raise HTTPException(status_code=502, detail=f"ragflow error: {e}")

class SearchIn(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    dataset_ids: list[str] = Field(..., min_length=1, description="至少 1 个 dataset")
    document_ids: list[str] | None = None
    top_k: int = 5
    similarity_threshold: float = 0.2
    vector_similarity_weight: float = 0.3
    keyword: bool = False
    highlight: bool = True
    page_size: int = 10


@router.post("/search")
async def search(payload: SearchIn, _user: User = Depends(get_current_user)) -> dict:
    """RAGFlow 检索代理."""
    try:
        data = await retrieval(
            question=payload.question,
            dataset_ids=payload.dataset_ids,
            document_ids=payload.document_ids,
            top_k=payload.top_k,
            similarity_threshold=payload.similarity_threshold,
            vector_similarity_weight=payload.vector_similarity_weight,
            keyword=payload.keyword,
            highlight=payload.highlight,
            page_size=payload.page_size,
        )
        # 精简 chunks: 去掉 content_ltks (很大, 前端不用)
        chunks = data.get("chunks", [])
        cleaned = []
        for c in chunks:
            cleaned.append({
                "id": c.get("id"),
                "content": c.get("content", ""),
                "highlight": c.get("highlight") or c.get("content", ""),
                "dataset_id": c.get("dataset_id"),
                "document_id": c.get("document_id"),
                "document_keyword": c.get("document_keyword", ""),
                "positions": c.get("positions", []),
                "similarity": c.get("similarity", 0.0),
                "vector_similarity": c.get("vector_similarity", 0.0),
                "term_similarity": c.get("term_similarity", 0.0),
                "tag_kwd": c.get("tag_kwd", []),
            })
        return {
            "total": data.get("total", len(cleaned)),
            "chunks": cleaned,
            "doc_aggs": data.get("doc_aggs", []),
            "elapsed_ms": data.get("elapsed_ms", 0),
        }
    except Exception as e:
        logger.exception("search failed")
        raise HTTPException(status_code=502, detail=f"ragflow error: {e}")


@router.get("/health")
async def health(_user: User = Depends(get_current_user)) -> dict:
    """知识库 (RAGFlow) 可达性.

    ⚠️ **要登录**: 以前这个端点无鉴权, 谁都能探到 RAGFlow 的地址/错误详情
       (探针报错里带 base_url 和 api_key 的一部分) —— 登录用户之间的情报没必要共享.
    """
    status, msg = await probe()
    return {"status": status, "message": msg}

