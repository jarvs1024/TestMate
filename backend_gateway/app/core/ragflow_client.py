"""RAGFlow API 客户端 — 配置从 DB 读, 兜底用 .env."""
from __future__ import annotations
import logging
import re
from typing import Any

import httpx

from app.core.settings_store import get, _rewrite_loopback
from urllib.parse import quote, unquote

logger = logging.getLogger(__name__)


async def _config() -> tuple[str, str]:
    """(base_url, api_key) 实时从 DB / 兜底 .env 读."""
    base = (await get("ragflow.base_url", "")) or ""
    key = (await get("ragflow.api_key", "")) or ""
    return _rewrite_loopback(base).rstrip("/"), key


async def _headers() -> dict[str, str]:
    _, key = await _config()
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


async def list_datasets(page: int = 1, page_size: int = 50) -> list[dict[str, Any]]:
    # ⚠️ **page_size 上限是 100** —— 传更大的 RAGFlow 会返回 `code=101`(错误)
    #    + **空的 data**, 看起来就像"一个库都没有" (真机踩过: 传 200 导致
    #    "数据集不存在"的假象). 这里直接夹住, 别让调用方踩.
    if page_size > 100:
        page_size = 100
    if page_size < 1:
        page_size = 1
    base, key = await _config()
    if not base or "xxxxx" in key or "mock" in key:
        return []
    url = f"{base}/datasets"
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(url, headers=await _headers(), params={"page": page, "page_size": page_size})
        r.raise_for_status()
        data = r.json()
        if data.get("code", 0) != 0:
            raise RuntimeError(f"ragflow list_datasets: {data.get('message') or data}")
        return data.get("data") or []


#: RAGFlow v0.26.1 的切片方式.
#:
#: ⚠️ 对外字段是 **`chunk_method`**, **不是 `parser_id`** ——
#:    `parser_id` 只是 RAGFlow 服务内部的别名 (CreateDatasetReq 里标了
#:    serialization_alias="parser_id"), 直接当请求字段传会被判
#:    "Extra inputs are not permitted" 而 400.
#: ⚠️ 通用切片的值是 **`naive`** —— "general" 是更新的说法, v0.26.1 不认.
CHUNK_NAIVE = "naive"
CHUNK_MANUAL = "manual"


async def create_dataset(
    name: str,
    description: str = "",
    chunk_method: str = CHUNK_NAIVE,
    embedding_model: str = "",
    permission: str = "me",
) -> dict[str, Any]:
    """新建一个数据集 (代理 RAGFlow POST /datasets).

    ⚠️ 三个坑 (都是真机跑出来才发现的, 单测的假 httpx 测不出来):
      ① 对外字段叫 **`chunk_method`**, 值用 `naive` / `manual`;
         传 `parser_id` + `parse_type` 会被 RAGFlow 当成多余字段拒掉.
      ② 响应的 `data` 是**一个对象**, 不是数组 —— 列表接口才是数组.
         写成 `data[0]` 会直接 IndexError.
      ③ `description` **可以直接在 create 时传** (旧版文档说不行, v0.26.1 可以),
         所以不用建完再补一次 —— 少一次请求就少一次失败机会.

    ⚠️ RAGFlow 的数据集名**大小写不敏感且唯一** —— 重名会自动加数字后缀
       (`项目管理` → `项目管理(1)`), 所以这里先查重名, 撞了就直接报错,
       不让用户以为建出来的是个新库.
    """
    base, key = await _config()
    if not base or "xxxxx" in key or "mock" in key:
        raise RuntimeError("RAGFlow 未配置")
    name = (name or "").strip()
    if not name:
        raise ValueError("数据集名称不能为空")
    if len(name) > 128:
        raise ValueError("数据集名称最长 128 个字符")

    # 重名检查 —— RAGFlow 会自动加后缀, 与其建出个 `xx(1)` 不如当场报错
    for d in await list_datasets(page=1, page_size=100):
        if (d.get("name") or "").strip().lower() == name.lower():
            raise ValueError(f"已经有一个叫「{name}」的数据集了")

    body: dict[str, Any] = {
        "name": name,
        "chunk_method": chunk_method,
        "permission": permission,
    }
    if description:
        body["description"] = description
    if embedding_model:
        body["embedding_model"] = embedding_model
    url = f"{base}/datasets"
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, headers=await _headers(), json=body)
        r.raise_for_status()
        data = r.json()
        if data.get("code", 0) != 0:
            raise RuntimeError(f"ragflow create_dataset: {data.get('message') or data}")
        created = data.get("data") or {}

    # ⚠️ create 的 data 是**对象**; 万一哪天变回数组也要扛得住
    if isinstance(created, list):
        created = created[0] if created else {}
    if not isinstance(created, dict):
        created = {}
    return created


async def update_dataset(
    dataset_id: str,
    name: str | None = None,
    description: str | None = None,
    chunk_method: str | None = None,
) -> dict[str, Any]:
    """改数据集 (代理 RAGFlow PUT /datasets/{id}).

    ⚠️ 改 `chunk_method` 只影响**之后**的解析, 不会重跑已有文档.

    ⚠️ 实测过: 只传 `description` 不会把库名冲成空串
       (UpdateDatasetReq 虽然继承自 CreateDatasetReq 且 name 默认 "",
        但服务端只把**实际传的字段**带进更新).
    """
    base, key = await _config()
    if not base or "xxxxx" in key or "mock" in key:
        raise RuntimeError("RAGFlow 未配置")
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if description is not None:
        body["description"] = description
    if chunk_method is not None:
        body["chunk_method"] = chunk_method
    if not body:
        return {}
    url = f"{base}/datasets/{quote(dataset_id, safe='')}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.put(url, headers=await _headers(), json=body)
        r.raise_for_status()
        data = r.json()
        if data.get("code", 0) != 0:
            raise RuntimeError(f"ragflow update_dataset: {data.get('message') or data}")
        return data.get("data") or {}


async def delete_dataset(dataset_id: str) -> bool:
    """删掉一个数据集 (连同里面的文档 / 分段 / 源文件).

    ⚠️ **路由是 `DELETE /datasets` + body `{"ids": [...]}`** ——
       RAGFlow **没有** `DELETE /datasets/{id}` 这条路由 (写了会 404).
    ⚠️ 这是**硬删**, 不可逆: 库里的每个文档都会走 `remove_document`,
       连带 MinIO 里的源文件和 ES 里的分段一起清掉, 没有回收站.
    ⚠️ RAGFlow 侧清 ES/对象存储是**后台任务** —— 接口已经返回 200 了,
       但列表里可能还短暂看得到那个库. 所以调用方删完要**刷新**列表,
       别以为没删掉就再点一次 (那会真删第二遍).
    """
    base, key = await _config()
    if not base or "xxxxx" in key or "mock" in key:
        raise RuntimeError("RAGFlow 未配置")
    url = f"{base}/datasets"
    # 删一个大库要清不少文件, 给足超时
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.request(
            "DELETE", url, headers=await _headers(), json={"ids": [dataset_id]},
        )
        r.raise_for_status()
        data = r.json()
        if data.get("code", 0) != 0:
            raise RuntimeError(f"ragflow delete_dataset: {data.get('message') or data}")
        return True


async def list_documents(
    dataset_id: str,
    page: int = 1,
    page_size: int = 30,
    orderby: str = "create_time",
    desc: bool = True,
    keywords: str = "",
    run: str = "",
) -> dict[str, Any]:
    """列出某个 dataset 下的 documents (代理 RAGFlow GET /datasets/{id}/documents)."""
    base, key = await _config()
    if not base or "xxxxx" in key or "mock" in key:
        return {"docs": [], "total": 0, "_mock": True}
    url = f"{base}/datasets/{quote(dataset_id, safe='')}/documents"
    params: dict[str, Any] = {
        "page": page, "page_size": page_size, "orderby": orderby, "desc": desc,
    }
    if keywords:
        params["keywords"] = keywords
    if run:
        params["run"] = run
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(url, headers=await _headers(), params=params)
        r.raise_for_status()
        data = r.json()
        if data.get("code", 0) != 0:
            raise RuntimeError(f"ragflow list_documents: {data.get('message') or data}")
        return data.get("data") or {"docs": [], "total": 0}
async def list_doc_chunks(
    dataset_id: str,
    document_id: str,
    page: int = 1,
    page_size: int = 100,
    keywords: str = "",
) -> dict[str, Any]:
    """列出某 document 下的 chunks (代理 RAGFlow GET .../documents/{doc_id}/chunks).

    返回 RAGFlow 原始 data: { chunks: [...], doc: {...}, total: int }
    """
    base, key = await _config()
    if not base or "xxxxx" in key or "mock" in key:
        return {"chunks": [], "doc": {}, "total": 0, "_mock": True}
    url = f"{base}/datasets/{quote(dataset_id, safe='')}/documents/{quote(document_id, safe='')}/chunks"
    params: dict[str, Any] = {"page": page, "page_size": page_size}
    if keywords:
        params["keywords"] = keywords
    async with httpx.AsyncClient(timeout=20.0) as client:
        r = await client.get(url, headers=await _headers(), params=params)
        r.raise_for_status()
        data = r.json()
        if data.get("code", 0) != 0:
            raise RuntimeError(f"ragflow list_doc_chunks: {data.get('message') or data}")
        return data.get("data") or {"chunks": [], "doc": {}, "total": 0}


async def ingest_documents(doc_ids: list[str], run: str = "1", delete: bool = False) -> bool:
    """重跑 / 取消 / 启动 documents 解析 (代理 RAGFlow POST /documents/ingest).

    run: "1" = start, "2" = cancel
    """
    base, key = await _config()
    if not base or "xxxxx" in key or "mock" in key:
        return False
    url = f"{base}/documents/ingest"
    body = {"doc_ids": doc_ids, "run": run, "delete": delete}
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(url, headers=await _headers(), json=body)
        r.raise_for_status()
        data = r.json()
        if data.get("code", 0) != 0:
            raise RuntimeError(f"ragflow ingest_documents: {data.get('message') or data}")
        return bool(data.get("data"))


# ---------- 上传 / 下载文档 (2026-10-29) ----------
#
# RAGFlow HTTP API 原文 (docs/references/http_api_reference.md):
#   POST /api/v1/datasets/{dataset_id}/documents
#     · type=local (默认): multipart/form-data, 字段名 **`file`** (可多个同名 field)
#     · 返回 {code:0, data:[{id, name, location, run:"UNSTART", size, ...}]}
#   GET  /api/v1/datasets/{dataset_id}/documents/{document_id}
#     · **直接返回文件字节流** (不是 JSON!) —— 带 content-disposition 头
#
# ⚠️ 上传完 run 是 UNSTART —— **不启动解析它就不参与检索**, 等于白传.
#    所以上传后要跟上一次 ingest (run="1").

async def upload_documents(
    dataset_id: str,
    files: list[tuple[str, bytes, str]],
) -> list[dict[str, Any]]:
    """上传文档到 dataset (multipart/form-data).

    files: [(文件名, 内容, content-type), ...] —— 每个都会作为**同名 `file` 字段**发出去.

    ⚠️ headers 里**不能**带 Content-Type —— httpx 要自己算 multipart 的 boundary,
       写死了 boundary 就对不上了 (RAGFlow 会报 "No file part!").
    """
    base, key = await _config()
    if not base or "xxxxx" in key or "mock" in key:
        return []
    if not files:
        return []
    url = f"{base}/datasets/{quote(dataset_id, safe='')}/documents"
    multipart = [("file", (name, data, ctype or "application/octet-stream")) for name, data, ctype in files]
    async with httpx.AsyncClient(timeout=180.0) as client:
        r = await client.post(url, headers={"Authorization": f"Bearer {key}"}, files=multipart)
        r.raise_for_status()
        data = r.json()
        if data.get("code", 0) != 0:
            raise RuntimeError(f"ragflow upload_documents: {data.get('message') or data}")
        return data.get("data") or []


def _filename_from_disposition(value: str) -> str:
    """从 content-disposition 里取文件名.

    支持两种写法:
      · ``attachment; filename=xxx.pdf``          (RAGFlow 现在的写法)
      · ``attachment; filename*=UTF-8''xxx.pdf``  (RFC 5987, 中文名会用这个)
    """
    if not value:
        return ""
    # RFC 5987 优先 (filename*=UTF-8''...)
    m = re.search(r"filename\*\s*=\s*([^']*)'([^']*)'([^;]+)", value, re.I)
    if m:
        try:
            return unquote(m.group(3).strip().strip('"'))
        except Exception:  # noqa: BLE001 — 解不出来就用原始的
            return m.group(3).strip().strip('"')
    m = re.search(r'filename\s*=\s*"([^"]*)"', value, re.I)
    if m:
        return m.group(1).strip()
    m = re.search(r"filename\s*=\s*([^;]+)", value, re.I)
    if m:
        return m.group(1).strip().strip('"')
    return ""


async def download_document(dataset_id: str, document_id: str) -> tuple[bytes, str, str]:
    """下载文档的**原始文件**.

    返回 (内容, 文件名, content-type).

    ⚠️ RAGFlow 失败时返回的是 **JSON** (`{"code":102,"message":"You do not own..."}`),
       不是文件 —— 必须先看 content-type 再决定是不是当文件返回,
       否则用户会下载到一个叫「xxx.pdf」的 JSON 错误, 打开全是乱码.
    """
    base, key = await _config()
    if not base or "xxxxx" in key or "mock" in key:
        raise RuntimeError("RAGFlow 未配置")
    url = f"{base}/datasets/{quote(dataset_id, safe='')}/documents/{quote(document_id, safe='')}"
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.get(url, headers={"Authorization": f"Bearer {key}"})
        r.raise_for_status()
        ctype = (r.headers.get("content-type") or "application/octet-stream").lower()
        if "json" in ctype:
            try:
                err = r.json()
            except Exception:  # noqa: BLE001 — 不是 JSON 就当纯文本错误
                raise RuntimeError(f"ragflow download_document: {r.text[:200]}")
            raise RuntimeError(f"ragflow download_document: {err.get('message') or err}")
        name = _filename_from_disposition(r.headers.get("content-disposition") or "")
        return r.content, name, ctype


async def update_document(
    dataset_id: str,
    document_id: str,
    name: str | None = None,
    parser_config: dict[str, Any] | None = None,
    chunk_method: str | None = None,
    enabled: int | None = None,
) -> dict[str, Any]:
    """改文档的**配置** (代理 RAGFlow PATCH /datasets/{id}/documents/{doc}).

    ⚠️ **换不了文件内容** —— RAGFlow 的文档是**不可变**的, 压根没有"替换内容"的接口.
       能改的只有这些:
         · `name`          —— 文档名 (只改名字, **不动已有分段**)
         · `parser_config` —— 切片参数 (`ext` 子字典会被合并进去)
         · `chunk_method`  —— 切片法
         · `enabled`       —— 启用/禁用

    ⚠️ 改 `chunk_method` 会让 RAGFlow **重置文档并重新解析**
       (清掉它在 doc store 里的分段) —— 所以「更新内容」的流程里
       **故意不传 chunk_method**, 只搬 `parser_config`,
       解析由我们自己用 ingest 启动 (可控, 失败也能重试).
    """
    base, key = await _config()
    if not base or "xxxxx" in key or "mock" in key:
        raise RuntimeError("RAGFlow 未配置")
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if parser_config is not None:
        body["parser_config"] = parser_config
    if chunk_method is not None:
        body["chunk_method"] = chunk_method
    if enabled is not None:
        body["enabled"] = enabled
    if not body:
        return {}
    url = f"{base}/datasets/{quote(dataset_id, safe='')}/documents/{quote(document_id, safe='')}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.patch(url, headers=await _headers(), json=body)
        r.raise_for_status()
        data = r.json()
        if data.get("code", 0) != 0:
            raise RuntimeError(f"ragflow update_document: {data.get('message') or data}")
        return data.get("data") or {}


async def parse_documents(dataset_id: str, document_ids: list[str]) -> bool:
    """**重新解析**已存在的文档 (代理 RAGFlow POST /datasets/{id}/documents/parse).

    ⚠️ 这是「重新跑一遍解析」, **不换文件内容** ——
       用来在改了切片参数 / 解析失败了之后重跑.
    ⚠️ 跟 `ingest_documents` 的区别: ingest 是「启动/取消」队列,
       parse 是「强制重新解析」(会清掉旧分段重来).
    """
    base, key = await _config()
    if not base or "xxxxx" in key or "mock" in key:
        return False
    if not document_ids:
        return False
    url = f"{base}/datasets/{quote(dataset_id, safe='')}/documents/parse"
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, headers=await _headers(), json={"document_ids": document_ids})
        r.raise_for_status()
        data = r.json()
        if data.get("code", 0) != 0:
            raise RuntimeError(f"ragflow parse_documents: {data.get('message') or data}")
        return True


async def delete_documents(dataset_id: str, doc_ids: list[str] | None = None, delete_all: bool = False) -> bool:
    """删除 documents (代理 RAGFlow DELETE /datasets/{id}/documents)."""
    base, key = await _config()
    if not base or "xxxxx" in key or "mock" in key:
        return False
    url = f"{base}/datasets/{quote(dataset_id, safe='')}/documents"
    body: dict[str, Any] = {}
    if doc_ids:
        body["ids"] = doc_ids
    else:
        body["delete_all"] = delete_all
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.request("DELETE", url, headers=await _headers(), json=body)
        r.raise_for_status()
        data = r.json()
        if data.get("code", 0) != 0:
            raise RuntimeError(f"ragflow delete_documents: {data.get('message') or data}")
        return True


async def retrieval(
    question: str,
    dataset_ids: list[str],
    document_ids: list[str] | None = None,
    top_k: int = 5,
    similarity_threshold: float = 0.2,
    vector_similarity_weight: float = 0.3,
    keyword: bool = False,
    highlight: bool = True,
    page_size: int = 10,
) -> dict[str, Any]:
    base, key = await _config()
    if not base or "xxxxx" in key or "mock" in key:
        return {"chunks": [], "doc_aggs": [], "total": 0, "_mock": True}
    url = f"{base}/retrieval"
    body: dict[str, Any] = {
        "question": question,
        "dataset_ids": dataset_ids,
        "top_k": top_k,
        "similarity_threshold": similarity_threshold,
        "vector_similarity_weight": vector_similarity_weight,
        "keyword": keyword,
        "highlight": highlight,
        "page_size": page_size,
    }
    if document_ids:
        body["document_ids"] = document_ids
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, headers=await _headers(), json=body)
        r.raise_for_status()
        data = r.json()
        if data.get("code", 0) != 0:
            raise RuntimeError(f"ragflow retrieval: {data.get('message') or data}")
        return data.get("data") or {"chunks": [], "doc_aggs": [], "total": 0}


async def probe() -> tuple[str, str]:
    base, key = await _config()
    if not base or "xxxxx" in key or "mock" in key:
        return ("off", "未配置")
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{base}/datasets?page=1&page_size=1", headers=await _headers())
            if r.status_code < 500 and r.json().get("code") == 0:
                return ("ok", "正常")
            return ("warn", f"HTTP {r.status_code}")
    except Exception as e:
        return ("off", f"不可达: {type(e).__name__}")
