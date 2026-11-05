"""软件库存储层的**纯函数**单测 —— 路径安全与校验 (``app/core/software_store.py``).

⚠️ 这个模块是路径安全的**唯一真源** (code → 目录名, file_path → 相对路径),
   拼错就是路径穿越 (读到 /etc/passwd 或写坏系统目录). 之前 30 个函数里只有
   3 个有直接单测, 全靠 API 层间接测 —— 而 API 层测的是"接口返回什么",
   测不到"这个相对路径到底能不能逃出 root".

⚠️ 全部用例都是**纯内存 / tmp_path**, 不连数据库、不发 HTTP.

⚠️ 注意: ``software_store.safe_rel_path`` 与 ``app/core/git_sync.py`` 里的
   ``safe_rel_path`` 是**两个完全不同的实现**:
      · git_sync.safe_rel_path(rel_path)         -> str | None   (仓库内相对路径)
      · software_store.safe_rel_path(code, version, file_name) -> str  (存储相对路径)
   本文件只测**后者**; 前者由 tests/test_path_traversal.py 覆盖.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core import git_sync, software_store as ss


# ---------- 夹具 ----------


@pytest.fixture
def store_root(tmp_path) -> Path:
    """一个存储根 (tmp_path 下)."""
    root = tmp_path / "software"
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def outside_dir(tmp_path) -> Path:
    """存储根**外面**的一个目录 —— 用来验证越界防护."""
    out = tmp_path / "outside"
    out.mkdir(parents=True, exist_ok=True)
    (out / "secret.txt").write_text("top secret", encoding="utf-8")
    return out


# ---------- validate_code ----------


@pytest.mark.parametrize("code", [
    "ab",
    "a1",
    "a-b",
    "a_b",
    "a.b",
    "a_b-c.d",
    "9x",
    "a" * 64,
])
def test_validate_code_accepts_legal(code: str):
    """合法 code 原样返回 (去首尾空白)."""
    assert ss.validate_code(code) == code


@pytest.mark.parametrize("code", [
    "",              # 空
    "a",             # 只有 1 位 (下限 2)
    "A",             # 大写
    "Ab",
    "aB",
    ".hidden",       # 点开头
    "..",            # 纯点
    "../etc",        # 路径穿越形态
    "a/b",           # 含分隔符
    "a\\b",
    "a b",           # 含空格
    "a\nb",
    "a" * 65,        # 超长 (上限 64)
    "软件",           # 非 ASCII
    "-abc",          # 连字符开头
    "_abc",          # 下划线开头
])
def test_validate_code_rejects_illegal(code: str):
    """非法 code → InvalidPath (code 会变成目录名, 这是安全边界)."""
    with pytest.raises(ss.InvalidPath):
        ss.validate_code(code)


def test_validate_code_strips_surrounding_whitespace():
    """⚠️ 现状: validate_code **内部 strip 后校验**, 但返回的是**去空白**的值.

    注意 safe_rel_path 用的是**原始** code (见下面的用例) —— 两处口径不一致.
    """
    assert ss.validate_code("  abc  ") == "abc"
    assert ss.validate_code("abc\n") == "abc"


def test_validate_code_rejects_none():
    with pytest.raises(ss.InvalidPath):
        ss.validate_code(None)  # type: ignore[arg-type]


# ---------- validate_file_name ----------


@pytest.mark.parametrize("name", [
    "a",
    "a.zip",
    "A.zip",
    "a_b-c.zip",
    "a..b",
    "a.",
    "0.bin",
    "a" * 200,
])
def test_validate_file_name_accepts_legal(name: str):
    """合法文件名原样返回 (去首尾空白)."""
    assert ss.validate_file_name(name) == name


@pytest.mark.parametrize("name", [
    "",             # 空 → 单独的错误消息
    " ",
    ".hidden",      # 点开头 → 会变成隐藏文件
    "..",
    ".",
    "a b.zip",      # 空格
    "a(b).zip",     # 括号
    "a/b.zip",      # 分隔符
    "a\\b.zip",
    "软件.zip",      # 中文
    "a" * 201,      # 超长 (上限 200)
    "a\tb",
])
def test_validate_file_name_rejects_illegal(name: str):
    """非法文件名 → InvalidPath (文件名会落进磁盘路径, 也是下载时的显示名)."""
    with pytest.raises(ss.InvalidPath):
        ss.validate_file_name(name)


def test_validate_file_name_empty_has_its_own_message():
    """空文件名是"没给"而不是"不合规" —— 错误消息要能区分."""
    with pytest.raises(ss.InvalidPath) as ei:
        ss.validate_file_name("")
    assert "不能为空" in str(ei.value)


def test_validate_file_name_rejects_none():
    with pytest.raises(ss.InvalidPath):
        ss.validate_file_name(None)  # type: ignore[arg-type]


# ---------- sanitize_filename (兜底清洗) ----------


@pytest.mark.parametrize(("raw", "want"), [
    ("a.zip", "a.zip"),
    ("../../etc/passwd", "passwd"),          # 只取 basename
    ("..\\..\\etc\\passwd", "passwd"),       # 反斜杠也当分隔符
    ("/abs/path/f.bin", "f.bin"),
    ("a/b/c.zip", "c.zip"),
    ("a\\b\\c.zip", "c.zip"),
    (".hidden", "hidden"),                   # 去掉前导点
    ("..", "fb"),                            # 剥空 → 用 fallback
    ("", "fb"),
    ("a b.txt", "a_b.txt"),                  # 非法字符 → _
    ("a\x00b", "ab"),                        # NUL 直接去掉
])
def test_sanitize_filename(raw: str, want: str):
    """sanitize_filename 只做兜底: basename + 洗字符 + 限长."""
    assert ss.sanitize_filename(raw, "fb") == want


def test_sanitize_filename_keeps_chinese_but_validate_file_name_rejects_it():
    """⚠️ **已知不一致**: ``_UNSAFE_CHARS`` 用 ``\\w`` (unicode 模式含中文),
    所以 sanitize_filename **放行中文**; 而 validate_file_name 明确拒绝中文.

    即"兜底清洗"比"上架校验"宽松 —— 走兜底路径落盘的文件名仍可能是中文.
    这里把现状钉住, 便于将来决定要不要统一.
    """
    assert ss.sanitize_filename("软件.zip", "fb") == "软件.zip"
    with pytest.raises(ss.InvalidPath):
        ss.validate_file_name("软件.zip")


def test_sanitize_filename_truncates_to_max_len():
    """超长 → 截断到 MAX_FILE_NAME_LEN."""
    out = ss.sanitize_filename("x" * 300, "fb")
    assert len(out) == ss.MAX_FILE_NAME_LEN


def test_sanitize_filename_length_limit_is_characters_not_bytes():
    """⚠️ **已知不一致**: 常量注释写"字节不是字符", 但实现是**按字符**截断.

    ``name[:MAX_FILE_NAME_LEN]`` 切的是字符 —— 中文 200 字 = 600 字节,
    超过常见文件系统的 255 字节上限. 这里把现状钉住.
    """
    out = ss.sanitize_filename("中" * 300, "fb")
    assert len(out) == ss.MAX_FILE_NAME_LEN          # 200 个字符
    assert len(out.encode("utf-8")) > 255            # 但字节数超了


# ---------- code_from_file_name ----------


@pytest.mark.parametrize(("raw", "want"), [
    ("aitestx-v2.1.zip", "aitestx-v2.1"),
    ("Aitestx-V2.1.ZIP", "aitestx-v2.1"),
    ("dify-web-entrypoint.sh", "dify-web-entrypoint"),
    ("a.tar.gz", "a.tar"),          # 只去最后一段扩展名
    ("img_6659.png", "img_6659"),
    ("my tool.zip", "my-tool"),     # 非法字符 → -
    ("a  b.zip", "a-b"),            # 连续非法字符合并
    ("a_b.zip", "a_b"),
])
def test_code_from_file_name(raw: str, want: str):
    """文件名 → code: 去扩展名 / 转小写 / 洗字符 / 限 64 位."""
    assert ss.code_from_file_name(raw) == want


@pytest.mark.parametrize(("raw", "want"), [
    ("", "software"),               # 兜底名
    (None, "software"),
    ("a", "a0"),                    # 太短 → 补到 2 位
    ("1", "10"),
    ("-x.zip", "x0"),               # 剥掉前后 -._ 后只剩 1 位
])
def test_code_from_file_name_short_or_empty(raw, want: str):
    """⚠️ **已知与注释不符**: docstring 写"太短就补 ``-tool``",
    实际实现是 ``(base or "so")[:2].ljust(2, "0")`` → 补 **"0"** 而不是 "-tool".
    """
    assert ss.code_from_file_name(raw) == want


def test_code_from_file_name_never_exceeds_64():
    """超长文件名 → code 截到 64 位 (CODE_RE 的上限)."""
    assert len(ss.code_from_file_name("x" * 70 + ".zip")) == 64


def test_code_from_file_name_result_always_passes_validate_code():
    """派生出来的 code **必须**能过 validate_code —— 否则会被 api 层拒掉."""
    samples = [
        "aitestx-v2.1.zip", "a.tar.gz", "a", "1", "-x.zip", "..", "...",
        ".gitignore", "a_b.zip", "x" * 70 + ".zip", "A.ZIP", "a..b.zip",
    ]
    for raw in samples:
        code = ss.code_from_file_name(raw)
        assert ss.validate_code(code) == code, (raw, code)


def test_code_from_file_name_dotfile_collides_with_software():
    """⚠️ **可疑行为**: 纯点开头的文件名 → 扩展名被剥光 → code 变成 "software".

    ".gitignore" → rsplit('.', 1)[0] == "" → 兜底成 "software" ——
    于是**所有**点文件都撞到同一个 code (api 层只能靠加序号兜底).
    """
    assert ss.code_from_file_name(".gitignore") == "software"


def test_code_from_file_name_chinese_name_collapses_to_prefix():
    """⚠️ **可疑行为**: 中文名 → 非法字符合并成 "-" → 剥掉 → 只剩前缀.

    "SSD 日志医生.zip" → "ssd" —— 静默丢信息, 不同中文名极易撞车.
    """
    assert ss.code_from_file_name("SSD 日志医生.zip") == "ssd"


# ---------- alias_from_code / validate_alias ----------


@pytest.mark.parametrize(("code", "want"), [
    ("aitestx-v2.1", "aitestx"),      # -v2.1 → 剥
    ("tool-v2", "tool"),              # -v2 → 剥
    ("tool-2.1", "tool"),             # -2.1 → 剥
    ("tool-1.2.3", "tool"),
    ("tool_2.1", "tool"),
    ("abc-beta", "abc-beta"),         # 字母标签 → 不剥
    ("abc-final", "abc-final"),
    ("img_6659", "img_6659"),         # 纯数字段 → 不剥 (数字是名字的一部分)
    ("a.b.c", "a.b.c"),
])
def test_alias_from_code(code: str, want: str):
    """别名 = 剥掉版本号后缀的 code (固定下载链接里不该出现版本号)."""
    assert ss.alias_from_code(code) == want


def test_alias_from_code_falls_back_when_stripped_too_short():
    """剥完不足 2 位 (或剥空) → 退回用原 code."""
    assert ss.alias_from_code("v2") == "v2"
    assert ss.alias_from_code("") == "software"


def test_alias_from_code_lowercases():
    """⚠️ 现状: alias_from_code 内部 lower() —— code 本来就小写, 无害."""
    assert ss.alias_from_code("AITestx-V2.1") == "aitestx"


@pytest.mark.parametrize("alias", [
    "abc", "a1", "a-b", "a_b", "a.b", "a" * 64,
])
def test_validate_alias_accepts_legal(alias: str):
    assert ss.validate_alias(alias) == alias


@pytest.mark.parametrize("alias", [
    "", "a", "Ab", "ABC", "../x", "a/b", "a b", "a" * 65, ".x", "软件",
])
def test_validate_alias_rejects_illegal(alias: str):
    """别名会进 URL 路径段 → 跟 code 一样的安全边界."""
    with pytest.raises(ss.InvalidPath):
        ss.validate_alias(alias)


# ---------- resolve_under (读侧第二道闸) ----------


def test_resolve_under_resolves_legal_relative_path(store_root: Path):
    """合法相对路径 → root 下的绝对路径."""
    (store_root / "demo").mkdir()
    (store_root / "demo" / "a.zip").write_bytes(b"x")
    got = ss.resolve_under(store_root, "demo/a.zip")
    assert got == (store_root / "demo" / "a.zip").resolve()


@pytest.mark.parametrize("rel", [
    "",                        # 空
    "../outside/secret.txt",   # 往上一层
    "../../etc/passwd",
    "demo/../../etc/passwd",
    "/etc/passwd",             # 绝对路径 (pathlib: 绝对右操作数会顶掉 root)
    "demo/../../../etc/passwd",
])
def test_resolve_under_rejects_escapes(rel: str, store_root: Path, outside_dir: Path):
    """越界 → None (调用方当"没落盘"处理)."""
    assert ss.resolve_under(store_root, rel) is None, rel


def test_resolve_under_rejects_sibling_prefix_directory(
    store_root: Path, tmp_path: Path
):
    """⚠️ 经典前缀陷阱: ``/a/root`` 与 ``/a/root2`` —— 后者**不是**前者的子目录.

    relative_to 是**按路径段**比较的, 所以 "../root2/x.txt" 会被挡住
    (如果实现用的是字符串前缀 startswith, 这里就会漏).
    """
    sibling = tmp_path / "software2"
    sibling.mkdir()
    (sibling / "x.txt").write_text("x", encoding="utf-8")
    assert ss.resolve_under(store_root, "../software2/x.txt") is None


def test_resolve_under_blocks_symlink_escape(store_root: Path, outside_dir: Path):
    """符号链接指向 root 外面 → 挡掉 (resolve() 会把软链解析成真实路径)."""
    link = store_root / "link"
    try:
        os.symlink(outside_dir, link)
    except (OSError, NotImplementedError):  # pragma: no cover - 平台不支持软链
        pytest.skip("当前平台不支持创建符号链接")
    assert ss.resolve_under(store_root, "link/secret.txt") is None


def test_resolve_under_allows_inner_dotdot_that_stays_inside(store_root: Path):
    """⚠️ **与 git_sync.safe_rel_path 的行为差异**: 这里允许 ``a/../b`` ——
    只要**最终**仍落在 root 下就放行; git_sync 那份是"见到 .. 就拒".
    两边规则不同 (但各自自洽)."""
    (store_root / "demo").mkdir()
    got = ss.resolve_under(store_root, "demo/../demo/a.zip")
    assert got == (store_root / "demo" / "a.zip").resolve()


def test_resolve_under_nonexistent_path_is_still_resolved(store_root: Path):
    """⚠️ 现状: resolve_under **不检查文件是否存在** ——
    它只管"路径安不安全", 存在性由 locate_under / file_exists 判断."""
    got = ss.resolve_under(store_root, "not/exists.zip")
    assert got == (store_root / "not" / "exists.zip").resolve()
    assert not got.exists()


def test_resolve_under_windows_style_traversal_is_a_literal_name(store_root: Path):
    """⚠️ POSIX 下反斜杠**不是**分隔符 → "..\\\\..\\\\etc" 只是一个怪文件名, 落在 root 内.

    (Windows 上就不是这样了 —— 但这个项目跑在 Linux/macOS 上.)
    """
    got = ss.resolve_under(store_root, "..\\..\\etc")
    assert got is not None
    assert got.parent == store_root.resolve()


# ---------- safe_rel_path (software_store 自己那份) ----------


def test_safe_rel_path_builds_three_segment_relative_path():
    """正常路径 → "code/version/file_name"."""
    assert ss.safe_rel_path("demo-sw", "1.0.0", "a.zip") == "demo-sw/1.0.0/a.zip"


@pytest.mark.parametrize("version", ["", ".", "..", "a/b", "a\\b", "1.0/../.."])
def test_safe_rel_path_rejects_illegal_version(version: str):
    """版本号必须是单段."""
    with pytest.raises(ss.InvalidPath) as ei:
        ss.safe_rel_path("demo-sw", version, "a.zip")
    assert "版本号" in str(ei.value)


@pytest.mark.parametrize("file_name", ["", ".", "..", "a/b", "a\\b"])
def test_safe_rel_path_rejects_illegal_file_name(file_name: str):
    """文件名必须是单段."""
    with pytest.raises(ss.InvalidPath) as ei:
        ss.safe_rel_path("demo-sw", "1.0.0", file_name)
    assert "文件名" in str(ei.value)


def test_safe_rel_path_validates_code():
    """code 非法 → InvalidPath (validate_code 抛的)."""
    with pytest.raises(ss.InvalidPath):
        ss.safe_rel_path("../evil", "1.0.0", "a.zip")


def test_safe_rel_path_does_not_strip_whitespace_like_validate_code_does():
    """⚠️ **已知不一致**: validate_code 会 strip, 但 safe_rel_path 用的是**原始** code.

    safe_rel_path(' demo ', ...) → " demo /1.0.0/a.zip" (带空格!)
    —— 校验用的是 strip 后的值, 拼路径用的是没 strip 的值. 这里钉住现状.
    """
    assert ss.safe_rel_path(" demo ", "1.0.0", "a.zip") == " demo /1.0.0/a.zip"
    assert ss.safe_rel_path("demo", " 1.0.0 ", "a.zip") == "demo/ 1.0.0 /a.zip"


def test_safe_rel_path_allows_odd_but_single_segment_names():
    """⚠️ **已知**: safe_rel_path 只挡**分隔符**, 不校验名字的"长相".

    空格 / 中文 / "..." 都能过 (validate_file_name 才会拒) —— 因为它假定
    上层已经用 validate_file_name 验过了.
    """
    assert ss.safe_rel_path("demo", "1.0.0", "a b.zip") == "demo/1.0.0/a b.zip"
    assert ss.safe_rel_path("demo", "1.0.0", "软件.zip") == "demo/1.0.0/软件.zip"
    assert ss.safe_rel_path("demo", "1.0.0", "...") == "demo/1.0.0/..."


def test_safe_rel_path_is_a_different_implementation_from_git_sync_one():
    """⚠️ 两个同名函数**不是一回事** —— 别在重构时混用.

    · software_store.safe_rel_path(code, version, file_name) -> str  (抛 InvalidPath)
    · git_sync.safe_rel_path(rel_path)                       -> str | None (返回 None)
    """
    with pytest.raises(ss.InvalidPath):
        ss.safe_rel_path("demo", "1.0.0", "../x")
    assert git_sync.safe_rel_path("../x") is None
    assert git_sync.safe_rel_path("skills/dml-a") == "skills/dml-a"


# ---------- candidate_roots (多存储根) ----------


def test_candidate_roots_puts_current_root_first(store_root: Path, monkeypatch):
    """优先级: 当前根 → 历史根 → 环境变量根 → 默认根."""
    monkeypatch.delenv("SOFTWARE_STORAGE_PATH", raising=False)
    roots = ss.candidate_roots(store_root, [])
    assert roots[0] == store_root.resolve()


def test_candidate_roots_includes_history_roots_in_order(store_root: Path, tmp_path):
    """历史根按给定顺序接在当前根后面."""
    old1 = tmp_path / "old1"
    old2 = tmp_path / "old2"
    roots = ss.candidate_roots(store_root, [str(old1), str(old2)])
    assert roots[0] == store_root.resolve()
    assert roots[1] == old1.resolve()
    assert roots[2] == old2.resolve()


def test_candidate_roots_dedupes(store_root: Path):
    """同一个根出现多次 → 只留一份 (按解析后的绝对路径去重)."""
    roots = ss.candidate_roots(store_root, [str(store_root), str(store_root)])
    assert roots.count(store_root.resolve()) == 1


def test_candidate_roots_ignores_empty_values(store_root: Path):
    """空串 / None → 跳过 (不是"根目录"!)."""
    roots = ss.candidate_roots(store_root, ["", None])
    assert roots[0] == store_root.resolve()
    assert "" not in [str(r) for r in roots]


def test_candidate_roots_uses_env_var_as_fallback(store_root: Path, tmp_path, monkeypatch):
    """环境变量根也在候选里 (部署时固定的那份)."""
    env_root = tmp_path / "env-root"
    monkeypatch.setenv("SOFTWARE_STORAGE_PATH", str(env_root))
    roots = ss.candidate_roots(store_root, [])
    assert env_root.resolve() in roots


def test_candidate_roots_resolves_relative_paths_against_repo_root(
    store_root: Path, monkeypatch
):
    """⚠️ **已知口径**: 相对路径是相对**仓库根**解析的, 不是相对 cwd.

    candidate_roots 里的 push() 与 resolve_root() 口径一致 (都相对仓库根),
    换机器时相对路径仍然可解析. 这里钉住.
    """
    monkeypatch.delenv("SOFTWARE_STORAGE_PATH", raising=False)
    roots = ss.candidate_roots(None, ["data/legacy-software"])
    assert ss.repo_root() / "data" / "legacy-software" in roots


def test_candidate_roots_always_has_at_least_default_root(monkeypatch):
    """兜底: 至少有一个根 (默认根), 不会返回空列表."""
    monkeypatch.delenv("SOFTWARE_STORAGE_PATH", raising=False)
    roots = ss.candidate_roots(None, None)
    assert len(roots) >= 1
    assert roots[-1] == (ss.repo_root() / "data" / "software").resolve()


# ---------- locate_under (多根定位) ----------


def test_locate_under_finds_file_in_first_root(store_root: Path):
    """第一个根里有 → 返回它."""
    (store_root / "demo").mkdir()
    (store_root / "demo" / "a.zip").write_bytes(b"x")
    got = ss.locate_under([store_root], "demo/a.zip")
    assert got == (store_root / "demo" / "a.zip").resolve()


def test_locate_under_falls_back_to_second_root(store_root: Path, tmp_path: Path):
    """⚠️ 多根存在的意义: 第一个根没有 → 第二个根找到.

    (管理员改过 storage_path 之后, 老文件还躺在旧根里 —— 这就是这层的价值.)
    """
    old = tmp_path / "old"
    (old / "demo").mkdir(parents=True)
    (old / "demo" / "a.zip").write_bytes(b"x")
    got = ss.locate_under([store_root, old], "demo/a.zip")
    assert got == (old / "demo" / "a.zip").resolve()


def test_locate_under_returns_none_when_missing(store_root: Path):
    """找不到 → None."""
    assert ss.locate_under([store_root], "demo/a.zip") is None


def test_locate_under_returns_none_for_empty_rel(store_root: Path):
    """空相对路径 → None."""
    assert ss.locate_under([store_root], "") is None


def test_locate_under_never_escapes_root(store_root: Path, outside_dir: Path):
    """越界的 rel 在**每个**候选根下都被挡掉."""
    assert ss.locate_under([store_root], "../outside/secret.txt") is None
    assert ss.locate_under([store_root], "/etc/passwd") is None


def test_locate_under_requires_a_file_not_a_directory(store_root: Path):
    """⚠️ 现状: locate_under 要求 **is_file()** —— 目录不算命中."""
    (store_root / "demo").mkdir()
    assert ss.locate_under([store_root], "demo") is None


# ---------- file_exists / version_dir / locate_item_dir ----------


def test_file_exists_reflects_disk_and_refuses_escape(store_root: Path, outside_dir: Path):
    """file_exists = resolve_under + is_file (越界的一律 False)."""
    (store_root / "demo").mkdir()
    (store_root / "demo" / "a.zip").write_bytes(b"x")
    assert ss.file_exists(store_root, "demo/a.zip") is True
    assert ss.file_exists(store_root, "demo/nope.zip") is False
    assert ss.file_exists(store_root, "../outside/secret.txt") is False


def test_version_dir_rejects_illegal_version(store_root: Path):
    """版本目录也做越界防护."""
    assert ss.version_dir(store_root, "demo", "1.0.0") == (
        store_root / "demo" / "1.0.0"
    ).resolve()
    with pytest.raises(ss.InvalidPath):
        ss.version_dir(store_root, "demo", "..")


def test_locate_item_dir_returns_none_for_illegal_code(store_root: Path):
    """非法 code → None (不抛)."""
    assert ss.locate_item_dir([store_root], "BAD") is None
    assert ss.locate_item_dir([store_root], "no-such-code") is None


# ---------- 常量自洽 ----------


def test_constants_match_the_documented_limits():
    """常量与文档口径一致 (改了一处另一处必须跟着改)."""
    assert ss.MAX_FILE_NAME_LEN == 200
    assert ss.CODE_RE.pattern == r"^[a-z0-9][a-z0-9._-]{1,63}$"
    assert ss.FILE_NAME_RE.pattern == r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$"
    assert ss.ALIAS_RE.pattern == r"^[a-z0-9][a-z0-9._-]{1,63}$"


def test_tmp_dir_is_dot_tmp_under_root(store_root: Path):
    """临时目录固定在 root/.tmp."""
    assert ss.tmp_dir(store_root) == store_root / ".tmp"
