"""安装目录的跨平台家目录解析 —— split_home_path.

前端安装通道要"自动找到家目录的位置", 但浏览器不暴露家目录绝对路径,
只能靠**目录句柄**逐级派生. 后端负责把设置里的路径翻译成
"是否在家目录下 + 家目录下的相对路径段".

各平台常见写法都要认:
    ~/xxx                 三平台通用 (推荐)
    %USERPROFILE%\\xxx     Windows 原生
    $HOME/xxx             shell 习惯
    C:\\Users\\张三\\xxx    Windows 绝对家目录
    /Users/zhangsan/xxx   macOS 绝对家目录
"""
from __future__ import annotations

from app.api.marketplace import split_home_path


def test_tilde_is_the_cross_platform_form():
    """~/... 是推荐写法 —— 三平台都认."""
    assert split_home_path("~/.qoder-cn/skills") == (True, [".qoder-cn", "skills"])
    assert split_home_path("~/qoder-cn/skills") == (True, ["qoder-cn", "skills"])


def test_tilde_alone_means_home_itself():
    assert split_home_path("~") == (True, [])


def test_windows_userprofile_prefix():
    assert split_home_path(r"%USERPROFILE%\.qoder-cn\skills") == (
        True, [".qoder-cn", "skills"],
    )
    assert split_home_path(r"%HOMEPATH%\.qoder-cn") == (True, [".qoder-cn"])


def test_shell_home_variable():
    assert split_home_path("$HOME/qoder-cn/skills") == (True, ["qoder-cn", "skills"])
    assert split_home_path("${HOME}/qoder-cn") == (True, ["qoder-cn"])


def test_windows_absolute_home_path():
    """Windows 用户直接填绝对家目录路径也要能自动定位."""
    assert split_home_path(r"C:\Users\张三\.qoder-cn\skills") == (
        True, [".qoder-cn", "skills"],
    )
    assert split_home_path("C:/Users/zhangsan/.qoder-cn") == (True, [".qoder-cn"])


def test_macos_absolute_home_path():
    assert split_home_path("/Users/zhangsan/.qoder-cn/skills") == (
        True, [".qoder-cn", "skills"],
    )


def test_absolute_path_outside_home_is_not_auto_locatable():
    """不在家目录下 → 前端没法自动定位, 只能让用户手动选."""
    assert split_home_path("/opt/skills") == (False, [])
    assert split_home_path("/srv/data/qoder-cn") == (False, [])
    assert split_home_path("D:\\qoder-cn\\skills") == (False, [])


def test_empty_is_not_auto_locatable():
    assert split_home_path("") == (False, [])
    assert split_home_path("   ") == (False, [])


def test_redundant_slashes_and_dots_are_normalized():
    assert split_home_path("~/.qoder-cn//skills/") == (True, [".qoder-cn", "skills"])
    assert split_home_path("~/./qoder-cn") == (True, ["qoder-cn"])


def test_backslash_is_normalized_to_slash():
    """反斜杠要先换成正斜杠再拆, 否则会拆错."""
    assert split_home_path(r"~\qoder-cn\skills") == (True, ["qoder-cn", "skills"])
