"""FYAgent 启动入口。

保留 ``python main.py`` 的习惯用法，真正的实现都在 core / tui 两个包内。

本文件额外做一件事（FYAgent 路径修复）：把「FYAgent 包目录」插到 ``sys.path``
最前面，因此无论从哪个目录用绝对路径启动

    python D:\\work\\Agent\\FYAgent\\main.py

都能稳定 import core / tui。项目锚点（``.agents/``、``plugins/``、config.ini）
全部由 ``core.paths`` 从包目录反推成绝对路径，与进程工作目录无关——
所以这里**不改 cwd**，避免影响 ``/workspace`` 等按当前目录解析的相对路径。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 包目录 = 本文件所在目录：插到 sys.path 前面保证 import 成功
_PACKAGE_ROOT = Path(__file__).resolve().parent
if str(_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_ROOT))

from tui.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
