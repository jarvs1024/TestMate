"""知识库 — 代理 RAGFlow。

提供:
- GET  /api/v1/kb/datasets        列出 RAGFlow datasets
- POST /api/v1/kb/search          检索 (代理 RAGFlow /retrieval)
- GET  /api/v1/kb/health          健康检查

2026-10-29 新增 (普通用户也能往知识库加内容了):
- POST /api/v1/kb/datasets/{id}/documents            上传文档 (tester 及以上)
- GET  /api/v1/kb/datasets/{id}/documents/{doc}/download  下载文档 (所有登录用户)
- GET  /api/v1/kb/audits                             操作审计 (admin only)
- PUT  /api/v1/kb/datasets/{id}/documents/{doc}      更新文档内容 (tester 及以上)
- POST /api/v1/kb/datasets/{id}/documents/{doc}/reparse  重新解析 (tester 及以上)

⚠️ **删除仍然只有 admin 能做** —— 用户上传的内容进的是**共享**知识库,
   要能删就意味着能把别人的东西删掉, 那不能给普通用户.
"""
import asyncio
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
    create_dataset, delete_dataset, update_dataset,
    update_document, parse_documents,
    CHUNK_METHODS, KB_LANGUAGES,
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
    #: RAGFlow v0.26.1 的 chunk_method: naive(通用/自动分段) | manual(手动切分) | ...
    #: ⚠️ **合法值是 RAGFlow 的那一套** (见 ragflow_client.CHUNK_METHODS),
    #:    传不在集合里的值 → RAGFlow 返 code 101, 库建不出来.
    chunk_method: str = Field("naive", description="切片方式")
    #: 数据集语言 (Chinese / English) —— 影响自动问答/关键词提取.
    #: ⚠️ **RAGFlow 建库接口不认这个字段** (`CreateDatasetReq` 里没有),
    #:    网关会**建完再补一次 PUT** 把它设上 (真机实测: POST 传 language → 400).
    language: str = Field("Chinese", description="数据集语言 (Chinese / English)")
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
    # ⚠️ 合法值必须**跟 RAGFlow 对齐** —— 传不在集合里的, RAGFlow 会返 code 101
    if chunk_method not in CHUNK_METHODS:
        raise HTTPException(
            status_code=422,
            detail=f"切片方式只能是 {' / '.join(CHUNK_METHODS)}",
        )

    language = (payload.language or "Chinese").strip()
    if language not in KB_LANGUAGES:
        raise HTTPException(status_code=422, detail="语言只能是 Chinese 或 English")

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

    # ⚠️ **建库接口不吃 `language`** (RAGFlow 的 `CreateDatasetReq` 里没这个字段,
    #    传了直接 400 "Extra inputs are not permitted") —— 但 `UpdateDatasetReq` 有.
    #    而且 RAGFlow 建库时的默认语言是 **English** (容器 LANG 不是 zh_CN),
    #    我们要的是中文库 —— 所以建完必须**补一次 PUT**.
    #    ⚠️ 这一步失败**不能**把整个建库搞失败 —— 库已经建出来了,
    #    只是语言没设上; 记个 warning, 让用户知道, 不谎报成功.
    ds_id = str(ds.get("id") or "")
    lang_warn = ""
    if ds_id and language:
        try:
            await update_dataset(ds_id, language=language)
        except Exception as e:  # noqa: BLE001
            logger.warning("set dataset language failed: %s", e)
            lang_warn = f"语言没能设成「{language}」(RAGFlow 拒绝了), 可以稍后在详情里改"
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
            # ⚠️ 建库响应里 language 是 RAGFlow 的**默认值** (English),
            #    不是我们要的 —— 真正生效的是刚才那次 PUT. 这里回填用户要的那个.
            "language": language,
        },
    }
    # ⚠️ 语言没设上 → 如实说, 别让用户以为建成了就是全对的
    if lang_warn:
        result["warning"] = lang_warn
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


@router.get("/documents/search")
async def search_documents(
    keywords: str = "",
    dataset_id: str = "",
    limit: int = 200,
    _user: User = Depends(get_current_user),
) -> dict:
    """按**文件名**搜文档 (默认跨**所有**数据集).

    权限: 所有登录用户 —— 搜索是**只读**操作, 跟「看数据集」「下载文档」同一档.

    ⚠️ RAGFlow 的 `keywords` 语义是 `LOWER(name).contains(keywords.lower())`
       —— **不区分大小写的子串匹配** (`api/db/services/document_service.py:135`),
       正好就是「按文件名搜」想要的. 搜不到是因为它**只搜文件名**, 不搜内容.

    ⚠️ RAGFlow 的 keywords 是**按单个数据集**过滤的 —— 搜全部库要**逐个库**查.
       这里并发发出去 (`asyncio.gather`), 别一个一个等.
    """
    kw = (keywords or "").strip()
    if not kw:
        return {"items": [], "total": 0, "keywords": "", "datasets": 0}

    limit = max(1, min(int(limit or 200), 500))

    try:
        datasets = await list_datasets(page=1, page_size=100)
    except Exception as e:  # noqa: BLE001
        logger.exception("search_documents: 取数据集列表失败")
        raise HTTPException(status_code=502, detail=f"ragflow error: {e}")

    targets = [
        d for d in datasets
        if not dataset_id or str(d.get("id") or "") == dataset_id
    ]
    if not targets:
        return {"items": [], "total": 0, "keywords": kw, "datasets": 0}

    async def one(ds: dict) -> list[dict]:
        """在**一个**数据集里搜 —— 翻页拿全 (单页上限 100)."""
        ds_id = str(ds.get("id") or "")
        ds_name = str(ds.get("name") or "")
        out: list[dict] = []
        page = 1
        while page <= 5:          # 一个库最多翻 5 页 = 500 条匹配
            try:
                data = await list_documents(
                    dataset_id=ds_id, page=page, page_size=100, keywords=kw,
                )
            except Exception as e:  # noqa: BLE001 — 一个库搜失败不能拖垮整个搜索
                logger.warning("搜文档失败 (库 %s): %s", ds_name, e)
                break
            docs = data.get("docs") or []
            for d in docs:
                out.append({
                    "id": d.get("id"),
                    "name": d.get("name"),
                    "dataset_id": ds_id,
                    "dataset_name": ds_name,
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
                    "parser_config": d.get("parser_config") or {},
                    "status": d.get("status", "1"),
                    "create_date": d.get("create_date", ""),
                    "update_date": d.get("update_date", ""),
                    "create_time": d.get("create_time", 0),
                    "update_time": d.get("update_time", 0),
                })
            if len(docs) < 100:
                break
            page += 1
        return out

    # ⚠️ 并发查 —— 4 个库串行等就是 4 倍延迟
    parts = await asyncio.gather(*(one(d) for d in targets), return_exceptions=True)
    items: list[dict] = []
    for p in parts:
        if isinstance(p, BaseException):
            logger.warning("搜文档: 某个库出错了: %s", p)
            continue
        items.extend(p)

    # 归属: 「谁传的」—— RAGFlow 那边记不了 TestMate 的账号
    owners = await _owners_for_documents([str(x.get("id") or "") for x in items])
    for item in items:
        o = owners.get(str(item.get("id") or ""), {})
        item["uploaded_by"] = o.get("uploaded_by")
        item["uploaded_by_name"] = o.get("uploaded_by_name", "")
        item["uploaded_at"] = o.get("uploaded_at")

    # 排序: 先按库名, 再按文档名 —— 结果稳定, 不会每次刷新跳来跳去
    items.sort(key=lambda x: (str(x.get("dataset_name") or ""), str(x.get("name") or "")))
    total = len(items)
    truncated = total > limit
    return {
        "items": items[:limit],
        "total": total,
        "keywords": kw,
        "datasets": len(targets),
        "truncated": truncated,
    }


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


# ============ 文档更新 / 重新解析 (2026-10-29) ============
#
# ⚠️ **RAGFlow 的文档是不可变的** —— 它压根没有"替换文件内容"的接口.
#    `PATCH /datasets/{id}/documents/{doc}` 只能改这四样:
#      name / parser_config / chunk_method / enabled   (+ meta_fields)
#    **换不了内容** (2026-10-29 从容器源码 api/apps/restful_apis/document_api.py 确认).
#
# 所以「更新文档」在网关这边是**四步拼出来的**:
#    ① 传新文件    → RAGFlow 新建一条文档记录 (同名会自动加 "(1)" 后缀)
#    ② 删旧文档    → 硬删 (旧版的分段 / MinIO 源文件一起没了)
#    ③ PATCH 新文档 → 把名字改回目标名
#    ④ 迁移归属 + 启动解析
#
# ⚠️ **先传后删** —— 中途任何一步失败, 旧文档都还在, 用户的数据不会丢.
#    (反过来先删后传, 传失败就两头空了)
# ⚠️ **旧版直接删除, 不留历史** (2026-10-29 用户拍板) —— 审计表里会留一条
#    update 记录, 但**旧文件本身找不回来**.

#: RAGFlow 的文档名长度上限 —— 是 **255 字节**, 不是 255 个字符
#: (api/constants.py: FILE_NAME_LEN_LIMIT = 255; 改名时它会按 utf-8 字节数校验)
RAGFLOW_DOC_NAME_BYTES = 255


def _fit_kb_name_bytes(name: str, limit: int = RAGFLOW_DOC_NAME_BYTES) -> str:
    """按 **UTF-8 字节数** 裁文件名 (RAGFlow 的上限是字节, 不是字符).

    ⚠️ 中文一个字 3 字节 —— 按字符裁会超, 改名时 RAGFlow 会拒.
    ⚠️ **扩展名必须留着** —— RAGFlow 不允许改扩展名 ("The extension of file can't be changed"),
       裁到一半把扩展名裁没了, 改名的请求就废了.
    ⚠️ 不能把一个多字节字符劈两半 —— 那样文件名会变成乱码.
    """
    raw = (name or "").encode("utf-8")
    if len(raw) <= limit:
        return name
    stem, ext = os.path.splitext(name)
    ext_b = ext.encode("utf-8")
    keep = max(1, limit - len(ext_b))
    stem_b = stem.encode("utf-8")[:keep].decode("utf-8", errors="ignore")
    return (stem_b + ext) or name[:limit]


async def _find_document(dataset_id: str, document_id: str) -> dict:
    """在某数据集里找到指定文档, 返回 RAGFlow 的**原始 doc dict** (找不到返回 {}).

    ⚠️ **不能用 `GET /datasets/{id}/documents/{doc}`** —— 那个接口返回的是
       **文件字节流** (不是 JSON), 拿不到 name / chunk_method / parser_config.
    ⚠️ page_size 上限 100 —— 传 200 RAGFlow 会返回 code=101 + 空 data
       (看着像"库里一篇文档都没有", 其实是参数非法).
    """
    page = 1
    while page <= 50:          # 最多翻 50 页 = 5000 篇, 够了
        data = await list_documents(dataset_id=dataset_id, page=page, page_size=100)
        docs = data.get("docs") or []
        for d in docs:
            if str(d.get("id") or "") == document_id:
                return d
        if len(docs) < 100:
            return {}
        page += 1
    return {}


async def _safe_delete_documents(dataset_id: str, doc_ids: list[str]) -> None:
    """删文档 —— **失败只记日志, 不抛异常** (用于失败回滚)."""
    if not doc_ids:
        return
    try:
        await delete_documents(dataset_id, doc_ids=doc_ids)
    except Exception as e:  # noqa: BLE001
        logger.warning("回滚删除文档失败 (%s): %s", ", ".join(doc_ids), e)


async def _move_document_owner(
    old_id: str,
    new_id: str,
    dataset_id: str,
    doc_name: str,
    size: int,
    user: User,
) -> None:
    """更新后把归属记录**挪到新文档 id** 上.

    ⚠️ **RAGFlow 里"更新" = 删旧建新** —— 文档 id 会变, 归属表的主键就是
       document_id, 不跟着挪的话新文档会显示「上传者 —」(用户会觉得"我刚传的
       怎么没人").

    ⚠️ 语义跟 :func:`_save_document_owner` 保持一致 —— 「**当前这一版**是谁传的」,
       所以上传者记成**这次更新的人**; 最初是谁传的在审计表里有完整历史.
    ⚠️ 写失败不能挡住业务 (跟其它归属操作一个待遇).
    """
    if not new_id:
        return
    try:
        from sqlalchemy import delete as sa_delete

        from app.db.session import AsyncSessionLocal
        from app.models.kb import KbDocumentMeta

        async with AsyncSessionLocal() as s:
            # ⚠️ 旧行必须删 —— 主键就是 document_id, 留着会跟新行撞
            await s.execute(
                sa_delete(KbDocumentMeta).where(
                    KbDocumentMeta.document_id.in_([x for x in (old_id, new_id) if x])
                )
            )
            s.add(KbDocumentMeta(
                document_id=new_id,
                dataset_id=dataset_id,
                doc_name=doc_name,
                size=int(size or 0),
                uploaded_by=user.id,
                uploaded_by_name=user.username or "",
            ))
            await s.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning("迁移文档归属失败 (已忽略): %s", e)


@router.put("/datasets/{dataset_id}/documents/{document_id}")
async def update_kb_document(
    dataset_id: str,
    document_id: str,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
) -> dict:
    """**替换**一篇文档的内容 (换新文件), 旧版直接删除.

    权限: **tester 及以上** (跟上传同一档; 删除仍然只有 admin).

    ⚠️ **RAGFlow 没有"换内容"的接口** —— 文档在 RAGFlow 里是不可变的,
       这里是网关自己拼的四步 (见上面的注释): 传新文件 → 删旧文档 →
       改回目标名 → 迁移归属 + 启动解析.

    ⚠️ **旧版被永久删除** (2026-10-29 用户拍板) —— 审计表里留一条 update 记录,
       但旧文件本身找不回来.

    ⚠️ **文档 id 会变** —— RAGFlow 里新文档是另一条记录, 所以返回的是
       **新的 doc id**, 前端别拿旧的 id 继续操作.
    """
    if not _can_write(user):
        raise HTTPException(status_code=403, detail="只读账号不能更新文档")

    raw_name = (file.filename or "").strip()
    if not raw_name:
        raise HTTPException(status_code=422, detail="没有选择文件")
    target_name = _fit_kb_name_bytes(_sanitize_kb_filename(raw_name, "document"))
    payload = await _read_upload_limited(file, MAX_UPLOAD_BYTES, target_name)
    if not payload:
        raise HTTPException(status_code=422, detail="文件是空的")

    # 旧文档 (拿它的名字 / 切片方式, 用来对齐)
    try:
        old = await _find_document(dataset_id, document_id)
    except Exception as e:  # noqa: BLE001
        logger.exception("更新文档: 查旧文档失败")
        raise HTTPException(status_code=502, detail=f"ragflow error: {e}")
    if not old:
        raise HTTPException(status_code=404, detail="文档不存在")

    old_name = str(old.get("name") or "")
    old_chunk_method = str(old.get("chunk_method") or "")
    ds_name, ds_chunk_method = await _dataset_info(dataset_id)

    # ⚠️ **扩展名不能变** —— RAGFlow 的改名会拒 ("The extension of file can't be changed").
    #    用户传了别的类型的文件 → 那不是"更新内容", 是"加一篇", 直接拦掉,
    #    别做出一个半成品.
    old_ext = os.path.splitext(old_name.lower())[1]
    new_ext = os.path.splitext(target_name.lower())[1]
    if new_ext != old_ext:
        raise HTTPException(
            status_code=422,
            detail=(
                f"新文件类型 ({new_ext or '无扩展名'}) 跟原文档 ({old_ext or '无扩展名'}) 不一致 —— "
                f"更新只能换内容, 换文件类型请直接上传新文档"
            ),
        )

    # ① 传新文件 —— 先传后删, 中途失败旧文档还在
    try:
        created = await upload_documents(
            dataset_id,
            [(target_name, payload, file.content_type or "application/octet-stream")],
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("更新文档: 上传新文件失败")
        await _audit(
            action="update", user=user, dataset_id=dataset_id, dataset_name=ds_name,
            document_id=document_id, doc_name=old_name, error=str(e)[:500],
        )
        raise HTTPException(status_code=502, detail=f"ragflow error: {e}")

    new_doc = (created or [{}])[0] or {}
    new_id = str(new_doc.get("id") or "")
    if not new_id:
        await _audit(
            action="update", user=user, dataset_id=dataset_id, dataset_name=ds_name,
            document_id=document_id, doc_name=old_name, error="ragflow 没返回新文档 id",
        )
        raise HTTPException(status_code=502, detail="ragflow 没有返回新文档 id")

    # ② 删旧文档 (硬删) —— 旧版的分段 / MinIO 源文件一起没了
    try:
        await delete_documents(dataset_id, doc_ids=[document_id])
    except Exception as e:  # noqa: BLE001
        logger.exception("更新文档: 删旧文档失败")
        # ⚠️ 回滚 —— 旧文档没删掉, 新文档就成了多余副本, 得清掉, 否则库里多一份垃圾
        await _safe_delete_documents(dataset_id, [new_id])
        await _audit(
            action="update", user=user, dataset_id=dataset_id, dataset_name=ds_name,
            document_id=document_id, doc_name=old_name, error=str(e)[:500],
        )
        raise HTTPException(status_code=502, detail=f"删除旧版本失败: {e}")

    # ③ PATCH 改回目标名 —— RAGFlow 同名上传会自动加 "(1)" 后缀, 这里改回去
    warnings: list[str] = []
    current_name = str(new_doc.get("name") or target_name)
    if current_name != target_name:
        try:
            await update_document(dataset_id, new_id, name=target_name)
        except Exception as e:  # noqa: BLE001 — 内容已经换掉了, 改名失败不该让整件事失败
            logger.warning("更新文档: 改名失败 (新文档仍叫 %s): %s", current_name, e)
            warnings.append(f"内容已更新, 但改名失败 —— 文档现在叫「{current_name}」(原因: {e})")
            target_name = current_name

    # ⚠️ **切片方式不搬旧的** —— 新文档天然继承**数据集**的切片方式.
    #    实机核对过: 文档级 parser_config 跟数据集级**完全一致**, 搬过去没有意义;
    #    而 RAGFlow 的 ParserConfig 是 extra=forbid 的严格模型, 搬旧值反而容易
    #    因为版本字段变动而整个 PATCH 失败.
    #    旧文档要是被手动改过切片方式, 这里会**对齐回数据集的**, 得跟用户说清楚.
    if old_chunk_method and ds_chunk_method and old_chunk_method != ds_chunk_method:
        warnings.append(
            f"切片方式已跟数据集保持一致 ({ds_chunk_method}) —— 原来这篇是 {old_chunk_method}"
        )

    # ④ 迁移归属 + 启动解析
    await _move_document_owner(document_id, new_id, dataset_id, target_name, len(payload), user)

    ingest_ok = False
    if ds_chunk_method == MANUAL_CHUNK_METHOD and not target_name.lower().endswith(MANUAL_AUTO_PARSE_EXTS):
        # ⚠️ 跟上传同一套规矩 —— 手动分块的解析器只认 pdf/docx,
        #    硬发解析必然 FAIL, 用户还以为是自己传坏了.
        warnings.append(
            f"「{ds_name or dataset_id}」是「手动分块」数据集, RAGFlow 只支持 pdf/docx 自动解析 —— "
            f"文档已更新, 但需要管理员手动切分后才能被检索."
        )
    else:
        try:
            ingest_ok = await ingest_documents([new_id], run="1")
        except Exception as e:  # noqa: BLE001 — 解析失败不该让更新失败 (文件已经换好了)
            logger.warning("更新后启动解析失败 (文档已更新, 需手动重跑): %s", e)
            warnings.append(f"解析启动失败 —— 请稍后用「重新解析」重跑 (原因: {e})")

    # 审计里写清「谁把什么换成了什么」—— 旧文档 id 已经不存在了, 名字是唯一的线索
    audit_name = target_name
    if old_name and old_name != target_name:
        audit_name = f"{old_name} → {target_name}"
    await _audit(
        action="update", user=user, dataset_id=dataset_id, dataset_name=ds_name,
        document_id=new_id, doc_name=audit_name[:255], size=len(payload),
    )

    return {
        "ok": True,
        "updated": {
            "id": new_id,
            "name": target_name,
            "size": len(payload),
        },
        "replaced": {
            "id": document_id,
            "name": old_name,
        },
        "ingest_started": ingest_ok,
        "warning": " ".join(warnings),
    }


@router.post("/datasets/{dataset_id}/documents/{document_id}/reparse")
async def reparse_kb_document(
    dataset_id: str,
    document_id: str,
    user: User = Depends(get_current_user),
) -> dict:
    """**重新解析**一篇文档 (内容不变, 重跑一遍切片 / 向量化).

    权限: **tester 及以上** —— 跟"更新"同一档. 重解析**不动数据** (只是重跑),
       比"删除"轻得多, 不该只给 admin.

    ⚠️ 跟 ingest 的"启动/取消"**不是一回事**:
       · ingest (run=1/2) 是**队列开关** —— 启动 / 取消还没跑的解析任务;
       · 这里的 parse   是**强制重跑** —— 清掉已有分段再解析一遍.
       解析失败了、或者想按新的切片参数重来 → 用这个.
    """
    if not _can_write(user):
        raise HTTPException(status_code=403, detail="只读账号不能重新解析")

    try:
        doc = await _find_document(dataset_id, document_id)
    except Exception as e:  # noqa: BLE001
        logger.exception("重新解析: 查文档失败")
        raise HTTPException(status_code=502, detail=f"ragflow error: {e}")
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    ds_name, _ = await _dataset_info(dataset_id)
    doc_name = str(doc.get("name") or "")

    try:
        await parse_documents(dataset_id, [document_id])
    except Exception as e:  # noqa: BLE001
        logger.exception("reparse_document failed")
        await _audit(
            action="reparse", user=user, dataset_id=dataset_id, dataset_name=ds_name,
            document_id=document_id, doc_name=doc_name, error=str(e)[:500],
        )
        raise HTTPException(status_code=502, detail=f"ragflow error: {e}")

    await _audit(
        action="reparse", user=user, dataset_id=dataset_id, dataset_name=ds_name,
        document_id=document_id, doc_name=doc_name,
    )
    return {"ok": True, "document_id": document_id, "name": doc_name}


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
    page: int = 1,
    page_size: int = 20,
    limit: int | None = None,
    user: User = Depends(get_current_user),
) -> dict:
    """知识库操作审计 (谁在什么时候传了什么) —— **分页**.

    权限: **admin only** (2026-10-29 收紧).

    ⚠️ 内容存在 RAGFlow 里, RAGFlow 自己记不了 TestMate 的账号
       (所有人共用一把 API key) —— "谁传的"只能靠这张表.

    ⚠️ 以前是**所有登录用户**都能看 —— 那是"共享知识库要透明"的思路,
       但操作记录里除了动作, 还有**操作人账号和文件名**, 那是治理信息.
       现在归到 admin 一档 —— 跟「删除文档」「删除数据集」同一档:
       **破坏性和治理性的操作, 都由 admin 掌握**.

    ⚠️ **分页 (2026-10-29)** —— 审计流水是只增不减的, 一次拉 50 条往后
       什么都不管, 新的记录反而看不见了. 现在按页拉:
         · `page`     从 1 开始
         · `page_size` 每页条数 (上限 200)
       返回 `total` 是**真实总条数**(以前返回的是"本页有几条" —— 跟分页
       控件对不上, 第 2 页就显示"共 N 条"还停在第 1 页的数).

    ⚠️ `limit` 保留为**向后兼容别名** —— 老脚本/老前端还在用 `?limit=50`,
       传了就当 page_size 用 (仍返回第一页).
    """
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="只有管理员能查看操作记录")

    from sqlalchemy import desc, func, select

    from app.db.session import AsyncSessionLocal
    from app.models.kb import KbAudit

    # 向后兼容: ?limit=N 等价于 page_size=N
    if limit is not None:
        page_size = limit
    try:
        page = max(1, int(page))
        # ⚠️ 别写 `page_size or 20` —— 0 是 falsy, 会被当成"没传"给成 20.
        #    用户/脚本传 0 的意思是"我要 0 条"? 不, 是"我手滑了" —— 兜到 1 更合理
        page_size = max(1, min(int(page_size), 200))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="page / page_size 必须是整数")

    try:
        async with AsyncSessionLocal() as s:
            # ⚠️ total 必须是**真实总条数**, 不是本页条数
            total = int(
                (await s.execute(select(func.count()).select_from(KbAudit))).scalar_one()
            )
            rows = (
                await s.execute(
                    select(KbAudit)
                    .order_by(desc(KbAudit.id))
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).scalars().all()
        pages = max(1, (total + page_size - 1) // page_size)
        # ⚠️ 页码越界 (比如刚删过数据, 或前端还停在旧页码) → 回到最后一页
        #    而不是给一个空表 + "共 N 条" 的怪状态
        if rows == [] and total > 0 and page > pages:
            page = pages
            async with AsyncSessionLocal() as s:
                rows = (
                    await s.execute(
                        select(KbAudit)
                        .order_by(desc(KbAudit.id))
                        .offset((page - 1) * page_size)
                        .limit(page_size)
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
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }
    except HTTPException:
        raise
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
    """删除 dataset 下的文档. admin only.

    ⚠️ **删除文档也必须写审计** (2026-10-29 整改) ——
       以前删完直接 `return {"ok": ok}`, 操作记录里**查无此事**.
       可这个页面把「操作记录」定位成知识库唯一的治理台账
       (谁传的、谁删的, 只能靠这张表) —— 删文档不记, 台账就漏了一半,
       admin 事后根本查不出"这篇文档是谁删的".
    """
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="admin only")

    # ⚠️ 删之前先把**要删的那些文档的名字**捞出来 ——
    #    审计里要写清楚删的是哪几篇 (删完就查不到了).
    #    顺带把库名也取一下, 免得审计里只有一个光秃秃的 dataset_id.
    ds_name = ""
    try:
        for d in await list_datasets(page=1, page_size=100):
            if str(d.get("id") or "") == dataset_id:
                ds_name = str(d.get("name") or "")
                break
    except Exception as e:  # noqa: BLE001
        logger.warning("删文档前取数据集名失败: %s", e)

    doc_names: list[str] = []
    try:
        wanted = set(payload.ids or [])
        docs = (await list_documents(dataset_id, page=1, page_size=100)).get("docs") or []
        if payload.delete_all or not wanted:
            doc_names = [str(d.get("name") or "") for d in docs]
        else:
            doc_names = [str(d.get("name") or "") for d in docs if str(d.get("id") or "") in wanted]
    except Exception as e:  # noqa: BLE001
        logger.warning("删文档前取文档名失败: %s", e)

    # doc_name 字段只有 255 字符 —— 多篇一起删时截断, 别让数据库报错
    doc_label = ", ".join(n for n in doc_names if n)[:250]

    try:
        ok = await delete_documents(dataset_id, doc_ids=payload.ids, delete_all=payload.delete_all)
    except Exception as e:
        logger.exception("delete_docs failed")
        await _audit(
            action="delete_doc", user=user, dataset_id=dataset_id,
            dataset_name=ds_name, doc_name=doc_label, error=str(e)[:500],
        )
        raise HTTPException(status_code=502, detail=f"ragflow error: {e}")

    # ⚠️ action 用 **delete_doc**, 不是 delete ——
    #    delete 已经被「删除数据集」占着了 (历史上那条记录也是删库).
    #    混用的话 admin 在操作记录里分不清删的是库还是文档.
    await _audit(
        action="delete_doc", user=user, dataset_id=dataset_id,
        dataset_name=ds_name, doc_name=doc_label,
    )
    return {"ok": ok}

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

