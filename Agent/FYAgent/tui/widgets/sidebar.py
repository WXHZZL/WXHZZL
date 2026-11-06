"""右侧边栏（FYAgent 重排）：MCP 服务、插件、技能三段常驻在同一面板里。

三段共用一个可滚动容器，每段一个小标题 + 一段正文：

- MCP：异步连接，先显示“连接中”，连上后原地刷新（同旧版）；
- 插件：装载是同步的，直接展示状态、工具数与失败原因；
- 技能：启动时扫描一次，列出名字与跳过原因。

边栏只显示已经确定的信息，不触发任何加载动作；数据都来自 core 的
``McpHub`` / ``PluginHub`` / ``SkillLibrary``，界面层不参与业务。
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from core.mcp.hub import McpHub
from core.plugins import PluginHub
from core.skills import SkillLibrary

from ..i18n import (
    MCP_SIDEBAR_LOADING,
    MCP_SIDEBAR_NONE,
    MCP_SIDEBAR_SERVER_DISABLED,
    MCP_SIDEBAR_SERVER_FAILED,
    MCP_SIDEBAR_SERVER_OK,
    MCP_SIDEBAR_TITLE,
    MCP_SIDEBAR_TOOL,
    PLUGINS_SIDEBAR_EMPTY,
    PLUGINS_SIDEBAR_ITEM,
    PLUGINS_SIDEBAR_ITEM_DISABLED,
    PLUGINS_SIDEBAR_ITEM_FAILED,
    PLUGINS_SIDEBAR_TITLE,
    PLUGINS_SIDEBAR_TOOL,
    SIDEBAR_TITLE,
    SKILLS_SIDEBAR_EMPTY,
    SKILLS_SIDEBAR_ITEM,
    SKILLS_SIDEBAR_SKIPPED,
    SKILLS_SIDEBAR_TITLE,
)

#: 单个服务最多列出的工具条数，避免边栏被超长工具清单挤爆
MAX_TOOLS_PER_SERVER = 60
#: 插件、技能段各自最多列几行
MAX_PLUGIN_ROWS = 12
MAX_SKILL_ROWS = 24


class McpSidebar(VerticalScroll):
    """MCP / 插件 / 技能三段清单；数据由 App 在合适时机推进来。"""

    def compose(self) -> ComposeResult:
        yield Static(SIDEBAR_TITLE, id="sidebar-title")
        yield Static(MCP_SIDEBAR_TITLE, classes="sidebar-section-title")
        yield Static(MCP_SIDEBAR_LOADING, id="mcp-sidebar-body", markup=False)
        yield Static(PLUGINS_SIDEBAR_TITLE, classes="sidebar-section-title")
        yield Static(PLUGINS_SIDEBAR_EMPTY, id="plugin-sidebar-body", markup=False)
        yield Static(SKILLS_SIDEBAR_TITLE, classes="sidebar-section-title")
        yield Static(SKILLS_SIDEBAR_EMPTY, id="skill-sidebar-body", markup=False)

    # ------------------------------------------------------------------ MCP

    def show_loading(self) -> None:
        self._write("#mcp-sidebar-body", MCP_SIDEBAR_LOADING)

    def show_unavailable(self) -> None:
        self._write("#mcp-sidebar-body", MCP_SIDEBAR_NONE)

    def show_hub(self, hub: McpHub | None) -> None:
        """按当前连接状态刷新：先服务，再每个服务下的工具名。"""
        if hub is None or not hub.config.configured:
            self.show_unavailable()
            return
        if hub.loading:
            self.show_loading()
            return
        rows = hub.status()
        if not rows:
            self.show_unavailable()
            return
        tools_by_server: dict[str, list[str]] = {}
        for info in hub.tools:
            tools_by_server.setdefault(info.server, []).append(info.exposed)
        lines: list[str] = []
        for row in rows:
            if not row.enabled:
                lines.append(MCP_SIDEBAR_SERVER_DISABLED % row.name)
                continue
            if not row.connected:
                lines.append(MCP_SIDEBAR_SERVER_FAILED % row.name)
                continue
            lines.append(MCP_SIDEBAR_SERVER_OK % (row.name, row.tool_count))
            names = tools_by_server.get(row.name, [])
            for name in names[:MAX_TOOLS_PER_SERVER]:
                lines.append(MCP_SIDEBAR_TOOL % name)
            if len(names) > MAX_TOOLS_PER_SERVER:
                lines.append(
                    MCP_SIDEBAR_TOOL % ("… 其余 %d 个" % (len(names) - MAX_TOOLS_PER_SERVER))
                )
        self._write("#mcp-sidebar-body", "\n".join(lines))

    # ----------------------------------------------------------------- 插件

    def show_plugins(self, hub: PluginHub | None) -> None:
        if hub is None:
            self._write("#plugin-sidebar-body", PLUGINS_SIDEBAR_EMPTY)
            return
        states = hub.status()
        if not states:
            self._write("#plugin-sidebar-body", PLUGINS_SIDEBAR_EMPTY)
            return
        lines: list[str] = []
        for index, state in enumerate(states[:MAX_PLUGIN_ROWS]):
            if not state.enabled:
                lines.append(PLUGINS_SIDEBAR_ITEM_DISABLED % state.name)
                continue
            if state.error:
                lines.append(PLUGINS_SIDEBAR_ITEM_FAILED % (state.name, state.error))
                continue
            lines.append(PLUGINS_SIDEBAR_ITEM % (state.name, len(state.tools)))
            for tool in state.tools:
                lines.append(PLUGINS_SIDEBAR_TOOL % tool)
        if len(states) > MAX_PLUGIN_ROWS:
            lines.append(PLUGINS_SIDEBAR_TOOL % "… 其余 %d 个" % (len(states) - MAX_PLUGIN_ROWS))
        self._write("#plugin-sidebar-body", "\n".join(lines))

    # ----------------------------------------------------------------- 技能

    def show_skills(self, library: SkillLibrary | None) -> None:
        if library is None or not library.skills:
            self._write("#skill-sidebar-body", SKILLS_SIDEBAR_EMPTY)
            return
        lines = [
            SKILLS_SIDEBAR_ITEM % (info.name,)
            for info in library.skills[:MAX_SKILL_ROWS]
        ]
        skipped = len(library.skipped)
        if skipped:
            lines.append(SKILLS_SIDEBAR_SKIPPED % skipped)
        self._write("#skill-sidebar-body", "\n".join(lines))

    # ------------------------------------------------------------------ 内部

    def _write(self, selector: str, text: str) -> None:
        try:
            self.query_one(selector, Static).update(text)
        except Exception:
            return
