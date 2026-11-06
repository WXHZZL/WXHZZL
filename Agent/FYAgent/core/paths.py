"""项目内固定路径。

统一从本文件推算，避免各模块各自用 ``__file__`` 拼路径时算错层级。

FYAgent 的路径口径（第一性原理：程序行为不应依赖“从哪里启动”）：

- ``PACKAGE_ROOT``  : ``Agent/FYAgent/``，配置文件与代码同目录；
- ``PROJECT_ROOT``  : 仓库根 ``D:\\work``，技能、会话、归档、插件都以它为锚点；
- 不再使用 ``Path.cwd()`` 推导项目根——无论从哪个目录启动 ``main.py``，
  ``.agents/``、``plugins/`` 的位置都固定不变。
"""

from __future__ import annotations

from pathlib import Path

from .constants import CONTEXT_ARCHIVE_DIR, PLUGINS_DIR_NAME

# Agent/FYAgent/
PACKAGE_ROOT = Path(__file__).resolve().parent.parent

# 仓库根目录：PACKAGE_ROOT 的上上级（Agent/FYAgent → Agent → 仓库根）
PROJECT_ROOT = PACKAGE_ROOT.parent.parent

DEFAULT_CONFIG_PATH = PACKAGE_ROOT / "config.ini"
DEFAULT_HISTORY_DIR = PACKAGE_ROOT / "chat_history"
# 文件工具的沙箱根：默认整个工程目录，可由 --workspace 覆盖
DEFAULT_WORKSPACE_ROOT = PACKAGE_ROOT
# 插件目录：固定在仓库根下，与代码同级，方便单独增删
DEFAULT_PLUGIN_ROOT = PROJECT_ROOT / PLUGINS_DIR_NAME


def context_archive_dir(project_root: Path | str | None = None) -> Path:
    """上下文归档目录：默认 `<仓库根>/.agents/context/`。"""
    base = PROJECT_ROOT if project_root is None else Path(project_root)
    return base / CONTEXT_ARCHIVE_DIR
