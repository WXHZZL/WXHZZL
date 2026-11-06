"""主题辅助：FYAgent 的 `/theme` 命令与 Ctrl+T 快捷键共用这套逻辑。

core 不依赖 textual，因此主题合法性只能在这里判断：把校验放在 tui，
配置文件里 `[ui] theme` 只存字符串。
"""

from __future__ import annotations

from typing import Iterable

from textual.app import App

#: 明显不适合终端的内置主题不展示（ansi 主题在部分 Windows 终端会糊）
_HIDDEN = ("ansi-dark", "ansi-light")


def theme_names(app: App) -> list[str]:
    """当前可选主题名清单（内置 + 注册过的），保持稳定顺序。"""
    try:
        themes = app.available_themes
    except Exception:  # 版本差异兜底：拿不到清单就退回默认主题
        return []
    names: list[str] = []
    for item in _iter_names(themes):
        if item in _HIDDEN:
            continue
        if item not in names:
            names.append(item)
    return names


def _iter_names(themes: object) -> Iterable[str]:
    if isinstance(themes, dict):
        return [str(key) for key in themes]
    result: list[str] = []
    try:
        for item in themes:  # type: ignore[union-attr]
            result.append(str(getattr(item, "name", item)))
    except TypeError:
        return []
    return result


def is_valid(app: App, name: str) -> bool:
    return name in theme_names(app)


def next_theme(app: App, current: str) -> str:
    """按清单顺序取下一个主题；清单为空时返回 current。"""
    names = theme_names(app)
    if not names:
        return current
    try:
        index = names.index(current)
    except ValueError:
        return names[0]
    return names[(index + 1) % len(names)]
