"""example-tools 插件：演示 FYAgent 插件的两件事——加工具、加提示片段。

约定只有一个：模块里暴露 ``register(api)``，在装载时被调用一次。
``api.add_tool`` 挂 Function Calling 工具，``api.add_prompt`` 追加 System Prompt。
"""

from __future__ import annotations

import os
import platform
import sys
from datetime import datetime
from pathlib import Path


def env_probe() -> dict:
    """返回 Python / 平台 / 当前目录等运行环境信息。"""
    root = Path(sys.executable)
    return {
        "ok": True,
        "python": platform.python_version(),
        "executable": str(root),
        "platform": "%s %s" % (platform.system(), platform.release()),
        "cwd": os.getcwd(),
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def ping() -> dict:
    """返回 pong，用于验证「模型能不能调到插件工具」。"""
    return {"ok": True, "pong": datetime.now().strftime("%H:%M:%S")}


def register(api) -> None:
    api.add_tool(
        name="envProbe",
        description="查看当前运行环境：Python 版本、解释器路径、操作系统、工作目录",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=env_probe,
    )
    api.add_tool(
        name="ping",
        description="插件自检：返回 pong 与当前时刻，用于确认插件工具可用",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=ping,
    )
    api.add_prompt(
        "The example-tools plugin is loaded: envProbe reports the Python/runtime "
        "environment, ping confirms plugin tools are callable."
    )
