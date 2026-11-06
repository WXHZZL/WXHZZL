"""FYAgent TUI 新特性测试：插件/主题命令、三段边栏、界面快捷键与偏好。

沿用现有无头测试驱动方式（run_test + FakeBackend），不碰网络。
"""

from __future__ import annotations

import json
from pathlib import Path

from core.config import ConfigStore
from core.plugins import PluginHub
from core.skills import SkillLibrary
from support import FakeBackend
from tui.app import FYAgentApp
from tui.commands import COMMANDS, find
from tui.i18n import HELP_TEXT
from tui.widgets.chat_input import ChatInput
from tui.widgets.chat_log import ChatLog, ToolCard
from tui.widgets.sidebar import McpSidebar

from test_plugins import make_plugin  # 复用插件构造辅助


def make_app(session, tmp_path, **kwargs) -> FYAgentApp:
    return FYAgentApp(
        session=session, store=ConfigStore(tmp_path / "config.ini"), **kwargs
    )


def _system_texts(app: FYAgentApp) -> list[str]:
    texts = []
    for child in app._chat.children:
        if child.has_class("system"):
            texts.append(str(child.render()))
    return texts


def build_session_with_plugins(make_session, tmp_path, names=("alpha",)):
    """给会话注入一个真实装载了插件的 PluginHub（tmp_path 下构造）。"""
    root = tmp_path / "plugins"
    for name in names:
        make_plugin(root, name)
    hub = PluginHub(roots=[root])
    hub.load()
    session = make_session(FakeBackend())
    session._plugins = hub
    hub.register_into(session.registry)
    return session, hub


# ---------------------------------------------------------------- 命令清单


def test_plugins_and_theme_commands_registered() -> None:
    assert find("/plugins") is not None
    assert find("/theme") is not None
    assert find("/undo") is not None
    assert find("/retry") is not None
    assert find("/copy") is not None
    assert [spec.name for spec in COMMANDS] == [
        "/help", "/new", "/resume", "/save", "/sessions", "/export",
        "/clear", "/copy", "/reset", "/undo", "/retry", "/compact", "/status",
        "/tools", "/model", "/workspace", "/skills", "/mcp", "/plugins",
        "/theme", "/config", "/quit", "/exit",
    ]
    assert "/plugins" in HELP_TEXT and "/theme" in HELP_TEXT
    assert "/undo" in HELP_TEXT and "/retry" in HELP_TEXT and "/copy" in HELP_TEXT
    assert "Ctrl+T" in HELP_TEXT and "Ctrl+K" in HELP_TEXT and "Ctrl+B" in HELP_TEXT


def test_parser_accepts_repeated_plugins_dir() -> None:
    from tui.__main__ import build_parser

    parser = build_parser()
    assert parser.parse_args([]).plugin_dirs is None
    args = parser.parse_args(["--plugins-dir", "a", "--plugins-dir", "b"])
    assert args.plugin_dirs == ["a", "b"]


# ---------------------------------------------------------------- /plugins


async def test_plugins_command_lists_states_and_tools(
    make_session, tmp_path
) -> None:
    session, _ = build_session_with_plugins(make_session, tmp_path, ("alpha",))
    app = make_app(session, tmp_path)

    async with app.run_test() as pilot:
        app.query_one("#prompt", ChatInput).load_text("/plugins")
        await pilot.press("enter")
        await pilot.pause()

        joined = "\n".join(_system_texts(app))
        assert "插件根目录" in joined
        assert "alpha" in joined and "alpha_tool" in joined
        assert str(tmp_path / "plugins") in joined


async def test_plugins_command_reports_broken_plugin(make_session, tmp_path) -> None:
    root = tmp_path / "plugins"
    make_plugin(root, "ok")
    make_plugin(root, "boom", body="raise RuntimeError('炸了')\n")
    hub = PluginHub(roots=[root])
    hub.load()
    session = make_session(FakeBackend())
    session._plugins = hub
    app = make_app(session, tmp_path)

    async with app.run_test() as pilot:
        app.query_one("#prompt", ChatInput).load_text("/plugins")
        await pilot.press("enter")
        await pilot.pause()

        joined = "\n".join(_system_texts(app))
        assert "装载失败" in joined and "炸了" in joined
        assert "ok" in joined


async def test_plugins_command_when_hub_missing(make_session, tmp_path) -> None:
    """插件总开关关闭时 hub 为 None，命令给出明确说明而不是报错。"""
    session = make_session(FakeBackend())
    session._plugins = None
    app = make_app(session, tmp_path)

    async with app.run_test() as pilot:
        app.query_one("#prompt", ChatInput).load_text("/plugins")
        await pilot.press("enter")
        await pilot.pause()
        assert any("总开关" in text for text in _system_texts(app))


# ---------------------------------------------------------------- 边栏三段


async def test_sidebar_shows_three_sections(make_session, tmp_path) -> None:
    session, _ = build_session_with_plugins(make_session, tmp_path, ("alpha",))
    app = make_app(session, tmp_path)

    async with app.run_test() as pilot:
        await pilot.pause()
        sidebar = app.query_one("#sidebar", McpSidebar)
        assert sidebar.query_one("#mcp-sidebar-body") is not None
        assert sidebar.query_one("#plugin-sidebar-body") is not None
        assert sidebar.query_one("#skill-sidebar-body") is not None
        plugin_text = str(sidebar.query_one("#plugin-sidebar-body").render())
        assert "alpha" in plugin_text and "alpha_tool" in plugin_text


async def test_sidebar_shows_skills_section(make_session, tmp_path, workspace) -> None:
    project = tmp_path / "project"
    skill = project / ".agents" / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: demo\ndescription: 演示\n---\n正文\n", encoding="utf-8"
    )
    session = make_session(FakeBackend())
    session._skills = SkillLibrary(project)
    app = make_app(session, tmp_path)

    async with app.run_test() as pilot:
        app._refresh_sidebar()
        await pilot.pause()
        body = str(app.query_one("#sidebar", McpSidebar).query_one(
            "#skill-sidebar-body"
        ).render())
        assert "demo" in body


# ---------------------------------------------------------------- 主题


async def test_theme_command_switches_and_persists(make_session, tmp_path) -> None:
    app = make_app(make_session(FakeBackend()), tmp_path)

    async with app.run_test() as pilot:
        app.query_one("#prompt", ChatInput).load_text("/theme nord")
        await pilot.press("enter")
        await pilot.pause()

        assert app.theme == "nord"
        assert app._ui_theme == "nord"
        text = (tmp_path / "config.ini").read_text(encoding="utf-8")
        assert "[ui]" in text and "theme = nord" in text
        assert any("nord" in item for item in _system_texts(app))


async def test_theme_command_rejects_unknown(make_session, tmp_path) -> None:
    app = make_app(make_session(FakeBackend()), tmp_path)

    async with app.run_test() as pilot:
        app.query_one("#prompt", ChatInput).load_text("/theme 不存在的主题")
        await pilot.press("enter")
        await pilot.pause()

        assert any("未知主题" in text for text in _system_texts(app))
        assert not (tmp_path / "config.ini").exists()


async def test_ctrl_t_cycles_theme(make_session, tmp_path) -> None:
    app = make_app(make_session(FakeBackend()), tmp_path)

    async with app.run_test() as pilot:
        await pilot.press("ctrl+t")
        await pilot.pause()
        first = app.theme
        await pilot.press("ctrl+t")
        await pilot.pause()
        assert app.theme != first
        assert app._ui_theme == app.theme


# ---------------------------------------------------------- Ctrl+K / Ctrl+B


async def test_ctrl_k_toggles_tool_collapse(make_session, tmp_path) -> None:
    from support import text_chunks, tool_script

    backend = FakeBackend(
        [tool_script("c1", "isLeapyear", '{"year": 2048}'), text_chunks("是闰年")]
    )
    app = make_app(make_session(backend), tmp_path)

    async with app.run_test() as pilot:
        app.query_one("#prompt", ChatInput).load_text("2048 是闰年吗")
        await pilot.press("enter")
        # 等一轮结束
        while app._turn_busy:
            await pilot.pause(0.01)
        await pilot.pause(0.1)

        cards = list(app._chat.query(ToolCard))
        assert cards and cards[0]._body.display  # 默认展开

        await pilot.press("ctrl+k")
        await pilot.pause()
        assert not cards[0]._body.display  # 折叠

        await pilot.press("ctrl+k")
        await pilot.pause()
        assert cards[0]._body.display


async def test_collapse_pref_from_config_applies_to_new_cards(
    make_session, tmp_path
) -> None:
    from core.config import ConfigStore
    from support import text_chunks, tool_script

    store_path = tmp_path / "config.ini"
    # 手工写一份带 [ui] collapse_tools = true 的最小配置
    store = ConfigStore(store_path)
    store.save("http://x/v1", "k", "m")
    text = store_path.read_text(encoding="utf-8")
    store_path.write_text(text + "\n[ui]\ncollapse_tools = true\n", encoding="utf-8")

    backend = FakeBackend(
        [tool_script("c1", "isLeapyear", '{"year": 2048}'), text_chunks("是闰年")]
    )
    # 注入会话时，界面偏好以会话配置为准（真实启动路径由 config.ini 装载而来）
    app = FYAgentApp(
        session=make_session(backend, config=store.load()),
        store=ConfigStore(store_path),
    )
    async with app.run_test() as pilot:
        app.query_one("#prompt", ChatInput).load_text("2048 是闰年吗")
        await pilot.press("enter")
        while app._turn_busy:
            await pilot.pause(0.01)
        await pilot.pause(0.1)

        cards = list(app._chat.query(ToolCard))
        assert cards and not cards[0]._body.display  # 新卡片默认折叠


async def test_ctrl_b_toggles_sidebar(make_session, tmp_path) -> None:
    app = make_app(make_session(FakeBackend()), tmp_path)

    async with app.run_test() as pilot:
        sidebar = app.query_one("#sidebar", McpSidebar)
        assert sidebar.display
        await pilot.press("ctrl+b")
        await pilot.pause()
        assert not sidebar.display
        assert app._ui_sidebar is False
        await pilot.press("ctrl+b")
        await pilot.pause()
        assert sidebar.display


# ------------------------------------------------------------- 时间戳


async def test_timestamps_pref_shows_clock(make_session, tmp_path) -> None:
    from core.config import ConfigStore
    from support import text_chunks

    store_path = tmp_path / "config.ini"
    store = ConfigStore(store_path)
    store.save("http://x/v1", "k", "m")
    text = store_path.read_text(encoding="utf-8")
    store_path.write_text(text + "\n[ui]\ntimestamps = true\n", encoding="utf-8")

    app = FYAgentApp(
        session=make_session(FakeBackend([text_chunks("好")]), config=store.load()),
        store=ConfigStore(store_path),
    )
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._chat.show_timestamps is True

        app.query_one("#prompt", ChatInput).load_text("hi")
        await pilot.press("enter")
        while app._turn_busy:
            await pilot.pause(0.01)
        await pilot.pause(0.1)

        roles = [str(item.render()) for item in app._chat.query(".role")]
        assert any("你 ·" in role for role in roles)
        assert any("AI ·" in role for role in roles)


# ------------------------------------------------------------ /status 插件行


async def test_status_shows_plugin_and_theme_rows(make_session, tmp_path) -> None:
    session, _ = build_session_with_plugins(make_session, tmp_path, ("alpha",))
    app = make_app(session, tmp_path)

    async with app.run_test() as pilot:
        app.query_one("#prompt", ChatInput).load_text("/status")
        await pilot.press("enter")
        await pilot.pause()

        joined = "\n".join(_system_texts(app))
        assert "插件" in joined and "1/1" in joined
        assert "主题" in joined
