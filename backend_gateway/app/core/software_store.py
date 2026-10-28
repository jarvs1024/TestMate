"""软件库 存储层 —— 路径解析 / 文件名清洗 / 流式落盘 / 清理 / 占用统计.

为什么单独一层 (而不是塞进 api/software.py):
    · **路径安全**的逻辑必须只有一份 —— code 会变成目录名, file_path 会变成
      相对路径, 一旦拼错就是路径穿越 (读到 /etc/passwd 或写坏系统目录);
    · **落盘**是重活 (边收边算 sha256 / 限流 / 原子改名), 值得单独测;
    · api 层只管 HTTP 语义 (谁能干 / 返回什么), 不碰文件系统.

存储布局:
    <root>/
      <code>/
        <version>/
          <清洗后的原始文件名>     ← 文件本体
          release.json             ← 该版本的元信息快照
      .tmp/
        <uuid>.part               ← 上传中的临时文件 (中断的残留, 定期清理)

⚠️ **file_path 存相对路径** (相对 root), 绝对路径只在运行时拼 ——
   换机器 / 改设置项 (storage_path) 后绝对路径会失效, 相对路径不会.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

# ---- 异常 (api 层翻译成人话) ----


class SoftwareStoreError(Exception):
    """存储层通用错误基类."""


class UploadTooLarge(SoftwareStoreError):
    """文件超过上限 —— api 层转 413."""

    def __init__(self, size: int, limit: int) -> None:
        super().__init__(f"文件超过大小上限 ({size} > {limit})")
        self.size = size
        self.limit = limit


class StorageFull(SoftwareStoreError):
    """磁盘写满 —— api 层转 500 + 人话提示."""


class SizeMismatch(SoftwareStoreError):
    """实收字节数与声明的大小对不上 —— api 层转 409 (文件不完整)."""

    def __init__(self, got: int, declared: int) -> None:
        super().__init__(f"文件大小对不上 (收到 {got} 字节, 声明 {declared} 字节)")
        self.got = got
        self.declared = declared


class InvalidPath(SoftwareStoreError):
    """路径非法 / 越界 —— api 层转 400."""


# ---- 常量 ----

#: code 的合法形态: 小写字母数字开头, 后跟字母数字/._- (总共 2~64 位)
#: ⚠️ code 会**直接变成目录名** —— 所以必须严: 不许 "/" 不许 ".." 不许大写.
CODE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")

#: **软件包文件名**的合法形态 (2026-10-28): 字母/数字/点/下划线/连字符.
#: ⚠️ 为什么比 :data:`_UNSAFE_CHARS` 严那么多:
#:    文件名会直接落进 ``<root>/<code>/<version>/<file_name>``,
#:    也是下载时 Content-Disposition 的名字. 允许中文/空格/括号的话:
#:      · 目录名在各种工具里转义不一致 (curl / unzip / Windows 资源管理器);
#:      · 下载回来的文件名在别人机器上可能变成乱码.
#:    所以上架时**当场校验并拒绝**, 而不是静默改名 (静默改名用户根本不知道).
#:    规则: 必须以字母或数字开头, 后面跟字母/数字/点/下划线/连字符.
FILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")

#: 文件名白名单: 字母数字/下划线/点/连字符 + 中文.
#: ⚠️ \w 在 Python 的 unicode 模式下已含中文 —— 显式写出来是为了让规则可读.
_UNSAFE_CHARS = re.compile(r"[^\w.\-]", re.UNICODE)

#: 文件名长度上限 (字节不是字符 —— 磁盘上按字节算)
MAX_FILE_NAME_LEN = 200

#: 临时文件后缀
TMP_SUFFIX = ".part"

#: 孤儿临时文件的最长存活时间 (小时) —— 超过就当上传中断的残留清掉
ORPHAN_TTL_HOURS = 24


# ---- 路径 ----


def repo_root() -> Path:
    """仓库根目录 —— 相对路径都相对于它解析.

    ⚠️ **容器里的布局不一样**, 所以这里不能只按"上三层"算:
      · 裸机: <repo>/backend_gateway/app/core/software_store.py → 仓库根 = 上三层
      · 容器: /app/app/core/software_store.py → 上三层是 "/" (整份 backend_gateway
        的内容被 COPY 进 /app, 容器里没有 "仓库" 这个概念)
    所以先**认标志目录** (backend_gateway / frontend_web), 认不到再退回上三层 ——
    容器里退到 "/" 也正好: 兜底的存放目录 /data/software 正好就是挂载卷。
    """
    here = Path(__file__).resolve()
    for p in here.parents:
        if (p / "backend_gateway").is_dir() or (p / "frontend_web").is_dir():
            return p
    return here.parents[3]


def default_root() -> Path:
    """默认存储根目录.

    优先级: ``SOFTWARE_STORAGE_PATH`` 环境变量 → ``<repo>/data/software``.

    ⚠️ 环境变量优先是**部署形态**决定的:
      · 裸机 (tmctl.sh) → 写进 backend.env, 指向 <runtime>/data/software
      · 容器 (docker-compose) → /data/software (命名卷)
    """
    env = (os.environ.get("SOFTWARE_STORAGE_PATH") or "").strip()
    if env:
        p = Path(env).expanduser()
        return p if p.is_absolute() else (repo_root() / p).resolve()
    return (repo_root() / "data" / "software").resolve()


def resolve_root(configured: str | None = None) -> Path:
    """把设置项里的路径解析成**绝对**根目录.

    · 空 → 用 :func:`default_root`
    · 绝对路径 → 直接用
    · 相对路径 → 相对**仓库根**解析 (这样 ``data/software`` 两种部署模式都能用)

    ⚠️ 不在这里 mkdir —— 目录不可写要**报出来** (设置页红字), 不是静默建一个。
    """
    raw = (configured or "").strip()
    if not raw:
        return default_root()
    p = Path(raw).expanduser()
    return p if p.is_absolute() else (repo_root() / p).resolve()


def validate_code(code: str) -> str:
    """校验 code —— 不合法直接抛 :class:`InvalidPath`.

    ⚠️ code 会变成目录名, 所以这是**安全边界**, 不是格式洁癖:
       "../../etc" 这种 code 拼进路径就能写到系统目录外面去.
    """
    c = (code or "").strip()
    if not CODE_RE.match(c):
        raise InvalidPath(
            "软件标识只能是小写字母/数字/点/下划线/连字符, 且以字母或数字开头 (2~64 位)"
        )
    return c


def sanitize_filename(raw: str, fallback: str) -> str:
    """把用户给的文件名洗成**安全的 basename**.

    处理:
      · 只取 basename (丢掉目录部分) —— ``../../etc/passwd`` → ``passwd``
      · 反斜杠也当分隔符 (Windows 风格路径)
      · 非法字符 → ``_``
      · 去掉前导点 (挡掉 ``..`` 与隐藏文件)
      · 长度截断

    ⚠️ 注意: 这是**兜底**, 不是主路径. 上架时应该先用 :func:`validate_file_name`
       当场拒绝不合规的文件名 (2026-10-28) —— 静默改名用户不知道, 下载回来
       名字对不上更麻烦.
    """
    name = (raw or "").strip().replace("\x00", "")
    name = name.replace("\\", "/")
    name = name.split("/")[-1]
    name = _UNSAFE_CHARS.sub("_", name)
    name = name.lstrip(".")
    if not name or name in (".", ".."):
        name = fallback
    return name[:MAX_FILE_NAME_LEN]


def validate_file_name(name: str) -> str:
    """校验**软件包文件名** —— 不合法直接抛 :class:`InvalidPath`.

    ⚠️ 规则 (2026-10-28): 只允许字母 / 数字 / 点 / 下划线 / 连字符, 且必须以
       字母或数字开头 (不许以点开头 —— 那会变成隐藏文件).

    为什么这么严: 文件名会变成 ``<root>/<code>/<version>/<file_name>`` 里的
    一段, 也是下载时给用户的文件名. 带上中文/空格/括号的话, 在别的机器上
    (curl / unzip / Windows 资源管理器) 很容易变成乱码或转义不一致.
       → 与其事后怪, 不如上架时就说清楚.
    """
    n = (name or "").strip()
    if not n:
        raise InvalidPath("文件名不能为空")
    if not FILE_NAME_RE.match(n):
        raise InvalidPath(
            f"文件名「{n}」不合规 —— 只能用英文字母、数字、点(.)、下划线(_)、连字符(-), "
            "且必须以字母或数字开头 (不能有中文、空格、括号等)"
        )
    return n


def code_from_file_name(file_name: str) -> str:
    """从软件包文件名派生出**软件标识 (code)** (2026-10-28).

    ⚠️ 为什么 code 不让用户填了:
       code 会**直接变成服务端存储目录名** (``<root>/<code>/<version>/``),
       用户手填就会出现 "SSD 日志医生" → 目录名带中文/空格, 或者两个人
       填成 `ssd-log-doctor` / `ssd_log_doctor` 撞车.
       文件名本来就是英文的, 拿它派生最省事, 也最不容易错.

    规则:
      · 去掉扩展名 (``dify-web-entrypoint.sh`` → ``dify-web-entrypoint``)
      · 转小写
      · 非法字符 → ``-``
      · 合并连续的 ``-``, 去掉首尾 ``-``
      · 最多 64 位; 太短就补 ``-tool``

    ⚠️ 派生的结果**仍可能撞名** —— 真正的唯一性由 api 层加序号保证
       (见 app/api/software.py 的 _unique_code).
    """
    base = (file_name or "").strip()
    base = base.replace("\\", "/").split("/")[-1]
    # 去掉扩展名 (只去最后一段, `a.tar.gz` → `a.tar`)
    if "." in base:
        base = base.rsplit(".", 1)[0]
    base = base.lower()
    base = re.sub(r"[^a-z0-9._-]+", "-", base)
    base = re.sub(r"-{2,}", "-", base).strip("-._")
    if not base:
        base = "software"
    base = base[:64].strip("-._")
    if len(base) < 2:
        base = (base or "so")[:2].ljust(2, "0")
    return base


def resolve_under(root: Path, rel: str) -> Path | None:
    """把**相对路径**解析成 root 下的绝对路径; 越界返回 None.

    ⚠️ 这是读侧的第二道闸 (落库时也校验过一次, 见 :func:`safe_rel_path`):
       数据库里万一已经有脏数据 (老版本留下的 / 被人改过), 读侧也要挡住.
    """
    if not rel:
        return None
    try:
        root_r = root.resolve()
        p = (root_r / rel).resolve()
        p.relative_to(root_r)
    except (ValueError, OSError):
        return None
    return p


def safe_rel_path(code: str, version: str, file_name: str) -> str:
    """拼出**相对**存储根的路径 (落库用).

    ⚠️ 三段都必须是"单段" —— code 与 version 已由 validate_code / 版本号校验
       保证, file_name 由 sanitize_filename 保证 (不含分隔符).
    """
    validate_code(code)
    if "/" in version or "\\" in version or version in ("", ".", ".."):
        raise InvalidPath("版本号不合法")
    if "/" in file_name or "\\" in file_name or file_name in ("", ".", ".."):
        raise InvalidPath("文件名不合法")
    return f"{code}/{version}/{file_name}"


def version_dir(root: Path, code: str, version: str) -> Path:
    """某软件某版本的目录 (绝对路径) —— 已做越界防护."""
    validate_code(code)
    if "/" in version or "\\" in version or version in ("", ".", ".."):
        raise InvalidPath("版本号不合法")
    p = (root / code / version).resolve()
    try:
        p.relative_to(root.resolve())
    except ValueError as e:
        raise InvalidPath("路径越界") from e
    return p


def tmp_dir(root: Path) -> Path:
    """临时文件目录 (上传中的 .part 落这儿)."""
    return root / ".tmp"


# ---- 落盘 ----


async def save_stream(
    stream: AsyncIterator[bytes],
    *,
    root: Path,
    code: str,
    version: str,
    file_name: str,
    max_bytes: int,
    declared_size: int = 0,
    chunk_size: int = 1024 * 1024,
) -> dict[str, Any]:
    """把一条字节流**边收边写盘**, 同时算 sha256 / 限大小, 最后原子改名.

    ⚠️ 为什么必须流式 (而不是像市场那样 ``b"".join(chunks)``):
       5G 的包整包进内存 = 进程直接被 OOM 打死, 而且还要在内存里再拷一份.

    ⚠️ **原子改名** (``os.replace``): 先写 ``.tmp/<uuid>.part``, 收完再改名到
       最终位置 —— 中途断线时目录里只会多一个 .part 残留, 不会多一个"半个软件包"
       (半个包被当成完整版本, 用户下下来才发现是坏的).

    返回: {"rel_path", "size", "sha256"}
    """
    validate_code(code)
    tmp_root = tmp_dir(root)
    try:
        tmp_root.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise StorageFull(f"存储目录不可写: {e}") from e

    tmp_file = tmp_root / f"{uuid.uuid4().hex}{TMP_SUFFIX}"
    digest = hashlib.sha256()
    total = 0

    final_dir = version_dir(root, code, version)
    try:
        final_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise StorageFull(f"无法创建版本目录: {e}") from e
    final_path = final_dir / file_name

    try:
        with open(tmp_file, "wb") as fh:
            async for chunk in stream:
                if not chunk:
                    continue
                total += len(chunk)
                if max_bytes and total > max_bytes:
                    raise UploadTooLarge(total, max_bytes)
                digest.update(chunk)
                fh.write(chunk)
    except UploadTooLarge:
        _unlink(tmp_file)
        raise
    except OSError as e:
        _unlink(tmp_file)
        # ENOSPC = 磁盘满 —— 这是一个**要人话提示**的故障, 不是 500 完事
        if getattr(e, "errno", None) == 28:
            raise StorageFull("服务端磁盘空间不足") from e
        raise StorageFull(f"写入失败: {e}") from e
    except Exception:
        _unlink(tmp_file)
        raise

    if total == 0:
        _unlink(tmp_file)
        raise InvalidPath("文件是空的, 没有收到任何字节")

    # ⚠️ 实收与声明对不上 → **在改名之前**就中止 —— 半截文件绝不能落到正式目录.
    #    (声明 0 = 没声明大小, 不校验 —— 允许)
    if declared_size and total != declared_size:
        _unlink(tmp_file)
        raise SizeMismatch(total, declared_size)

    rel = safe_rel_path(code, version, file_name)
    try:
        os.replace(tmp_file, final_path)
    except OSError as e:
        _unlink(tmp_file)
        raise StorageFull(f"保存文件失败: {e}") from e

    _write_release_json(final_dir, rel, total, digest.hexdigest())
    return {"rel_path": rel, "size": total, "sha256": digest.hexdigest()}


def _write_release_json(final_dir: Path, rel_path: str, size: int, sha256: str) -> None:
    """在版本目录里写一份元信息快照 —— 磁盘上自解释 (换机器/搬目录时不依赖数据库)."""
    import json

    try:
        (final_dir / "release.json").write_text(
            json.dumps(
                {
                    "file": rel_path,
                    "size": size,
                    "sha256": sha256,
                    "saved_at": int(time.time()),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        # 快照只是辅助信息 —— 写不进去不该让整个上传失败
        pass


def _unlink(p: Path) -> None:
    try:
        p.unlink()
    except OSError:
        pass


# ---- 清理 ----


def cleanup_orphan_parts(root: Path, ttl_hours: int = ORPHAN_TTL_HOURS) -> int:
    """清理 ``.tmp`` 里超时的 .part 残留 (上传中断留下的).

    返回清掉的文件数.
    """
    tmp_root = tmp_dir(root)
    if not tmp_root.is_dir():
        return 0
    cutoff = time.time() - ttl_hours * 3600
    n = 0
    for p in tmp_root.glob(f"*{TMP_SUFFIX}"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                n += 1
        except OSError:
            continue
    return n


def remove_version_dir(root: Path, code: str, version: str) -> None:
    """删掉某个版本的整个目录 (版本清理/条目删除时用)."""
    try:
        d = version_dir(root, code, version)
    except InvalidPath:
        return
    shutil.rmtree(d, ignore_errors=True)


def remove_item_dir(root: Path, code: str) -> None:
    """删掉某个软件的整个目录 (彻底清理时用)."""
    try:
        validate_code(code)
    except InvalidPath:
        return
    p = (root / code).resolve()
    try:
        p.relative_to(root.resolve())
    except ValueError:
        return
    shutil.rmtree(p, ignore_errors=True)


# ===== 多根定位 (2026-10-28 修: 改存储根目录后老文件"失联") =====


def candidate_roots(
    current: Path | None = None,
    history: list[str] | None = None,
) -> list[Path]:
    """所有**可能**存放软件包的根目录 (按优先级, 去重).

    ⚠️ 为什么要有多个根 (这是一个真 bug, 不是过度设计):
       落库的 ``file_path`` 是**相对**路径 (``code/version/file_name``) ——
       这本身是对的 (换机器时绝对路径会失效). 但相对路径的**基准是"当前根"**:
       一旦管理员改了 ``software.storage_path``, "当前根 + 相对路径" 就找不到
       老文件了 —— 文件还在旧根躺着, 但下载 404、删除删不掉, 成了**删不掉的孤儿**.

       实测踩到的现场 (2026-10-28):
         设置项根  = /Users/jarvs/Code/TestMate/software        (管理员改的)
         环境变量根 = .../deploy/native/runtime/data/software    (文件实际在这)
       管理员下架了所有版本, 目录却还在 —— 因为删除用的是"当前根 + 相对路径".

       所以查找文件时要把**所有可能的根**都试一遍:
         ① 当前生效根 (设置项)          —— 现在在用的
         ② 历史根 (设置项变更时记下的)   —— 改过好几次时的老根
         ③ 环境变量根 (部署时固定)        —— 覆盖"改设置项之前"的存放位置
         ④ 默认根 (仓库内 data/software)  —— 兜底
       ③④ 天然覆盖绝大多数情况, 不用额外维护.
    """
    out: list[Path] = []

    def push(p: Path | str | None) -> None:
        if not p:
            return
        try:
            pp = Path(str(p)).expanduser()
            if not pp.is_absolute():
                pp = (repo_root() / pp).resolve()
            else:
                pp = pp.resolve()
        except (OSError, ValueError):
            return
        if pp not in out:
            out.append(pp)

    push(current)
    for h in history or []:
        push(h)
    push(os.environ.get("SOFTWARE_STORAGE_PATH") or "")
    push(default_root())
    return out


def locate_under(roots: list[Path], rel: str) -> Path | None:
    """在候选根里找相对路径对应的**文件** —— 找到返回绝对路径, 找不到 None."""
    if not rel:
        return None
    for root in roots:
        p = resolve_under(root, rel)
        if p is not None and p.is_file():
            return p
    return None


def locate_version_dir(roots: list[Path], code: str, version: str) -> Path | None:
    """在候选根里找某版本的目录 —— 找到返回绝对路径."""
    for root in roots:
        try:
            d = version_dir(root, code, version)
        except InvalidPath:
            return None
        if d.is_dir():
            return d
    return None


def locate_item_dir(roots: list[Path], code: str) -> Path | None:
    """在候选根里找某条目的目录 —— 找到返回绝对路径."""
    try:
        validate_code(code)
    except InvalidPath:
        return None
    for root in roots:
        p = (root / code).resolve()
        try:
            p.relative_to(root.resolve())
        except (ValueError, OSError):
            continue
        if p.is_dir():
            return p
    return None


def remove_version_dir_anywhere(roots: list[Path], code: str, version: str) -> int:
    """在**所有候选根**里删掉某版本的目录 —— 返回删掉几个.

    ⚠️ 为什么要删"所有"而不是"找到的第一个":
       管理员来回改过存储根目录时, 同一个 ``<code>/<version>/`` 可能在两个根下
       都存在 (一半在新根一半在旧根). 只删一个的话, 另一半永远留着.
    """
    n = 0
    seen: set[str] = set()
    for root in roots:
        try:
            d = version_dir(root, code, version)
        except InvalidPath:
            return n
        key = str(d)
        if key in seen:
            continue
        seen.add(key)
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            n += 1
    return n


def remove_item_dir_anywhere(roots: list[Path], code: str) -> int:
    """在**所有候选根**里删掉某条目的整个目录 —— 返回删掉几个."""
    n = 0
    seen: set[str] = set()
    for root in roots:
        try:
            validate_code(code)
        except InvalidPath:
            return n
        p = (root / code).resolve()
        try:
            p.relative_to(root.resolve())
        except (ValueError, OSError):
            continue
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
            n += 1
    return n


def remove_item_dir_if_empty(root: Path, code: str) -> bool:
    """版本都删光后, 条目目录会剩个**空壳** (``<root>/<code>/``) —— 顺手删掉.

    ⚠️ 2026-10-28 用户报的坑: "全下架了多个版本, 但根目录下的这个目录没删除".
       原因就是删版本只删了 ``<root>/<code>/<version>/``, 上面那层 ``<root>/<code>/``
       空了却没人管 —— 目录还在, 看着像"东西没删干净", 白占地方.

    返回 True = 确实删掉了空壳.
    """
    try:
        validate_code(code)
    except InvalidPath:
        return False
    p = (root / code).resolve()
    try:
        p.relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    if not p.is_dir():
        return False
    try:
        # 还有东西就不动 —— 只清空壳
        if any(p.iterdir()):
            return False
        p.rmdir()
        return True
    except OSError:
        return False


# ---- 占用统计 ----


def usage_info(root: Path) -> dict[str, Any]:
    """存储根的**磁盘**情况 —— 设置页/健康探针用.

    返回: {"root", "exists", "writable", "total_bytes", "free_bytes", "used_bytes"}

    ⚠️⚠️ **`used_bytes` 是整块磁盘的已用空间, 不是软件库目录自己占的** ——
       它来自 ``shutil.disk_usage()``. 软件库目录自身的占用要用另一个函数
       :func:`used_bytes` (同名, 但完全不同的东西 —— 这个坑真的踩过:
       体检端点把磁盘的 725GB 当成"软件库占了 725GB" 显示了出来).

       要"软件库占了多少" → :func:`used_bytes`
       要"磁盘还剩多少"   → 这里的 ``free_bytes``
    """
    info: dict[str, Any] = {
        "root": str(root),
        "exists": root.is_dir(),
        "writable": os.access(root, os.W_OK) if root.is_dir() else False,
        "total_bytes": 0,
        "free_bytes": 0,
        "used_bytes": 0,
    }
    if root.is_dir():
        try:
            usage = shutil.disk_usage(root)
            info["total_bytes"] = usage.total
            info["free_bytes"] = usage.free
            info["used_bytes"] = usage.used
        except OSError:
            pass
    return info


def probe_storage(root: Path) -> dict[str, Any]:
    """启动时的存储根体检 —— 返回可读的状态说明.

    ⚠️ 为什么要在**启动时**查一遍 (而不是等第一次上传失败):
       存储根不可写的典型原因是"容器里没挂卷"或"systemd 没放行 ReadWritePaths" ——
       这两个都是**部署**问题, 等到用户传文件才报"存储目录不可写", 运维会一头雾水.
    """
    info = usage_info(root)
    if not info["exists"]:
        try:
            root.mkdir(parents=True, exist_ok=True)
            info["exists"] = root.is_dir()
            info["writable"] = os.access(root, os.W_OK)
        except OSError as e:
            info["error"] = f"建不出来: {e}"
    if info["exists"] and not info["writable"]:
        info["error"] = "目录存在但不可写 (权限? 容器里没挂卷? systemd 的 ReadWritePaths 没放行?)"
    return info


def used_bytes(root: Path) -> int:
    """软件库目录里实际占用的字节数 (只算 ``<code>/`` 下的, 不算 .tmp)."""
    total = 0
    if not root.is_dir():
        return 0
    for p in root.iterdir():
        if not p.is_dir() or p.name.startswith("."):
            continue
        for f in p.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    continue
    return total


def file_exists(root: Path, rel_path: str) -> bool:
    """某个相对路径的文件是否真的在盘上 (设置项换根目录后用来查"缺哪些文件")."""
    p = resolve_under(root, rel_path)
    return bool(p and p.is_file())
