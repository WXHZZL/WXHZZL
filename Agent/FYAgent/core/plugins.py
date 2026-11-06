"""FYAgent 插件机制：仓库根目录下的 `plugins/` 是本机可扩展的能力插槽。

设计出发点（与 MCP、Skill 两条扩展路径同构，第一性原理：Agent 的能力边界
应当由「注册表」决定，而不是由代码决定）：

- 发现：扫描 ``<仓库根>/plugins/<插件名>/FYPLUGIN.json``，缺清单的目录直接跳过；
- 装载：按清单的 ``entry``（默认 ``tools.py``）导入模块，调用它的 ``register(api)``；
- 隔离：单个插件报错只影响它自己，其余插件与内置工具照常可用（同 MCP 的策略）；
- 可关：``config.ini`` 的 ``[plugins] disabled = a;b`` 或清单里 ``enabled = false``
  都能停用插件，不需要删文件；``[plugins] enabled = false`` 或环境变量
  ``FY_PLUGINS=off`` 整体关闭。

插件可以贡献两类东西：

1. **工具**：``api.add_tool(name, description, parameters, handler)``，
   与内置工具进同一张注册表，模型看到的就是普通 Function Calling；
2. **提示片段**：``api.add_prompt(text)``，追加到 System Prompt 末尾，
   用来告诉模型「本插件已就绪，什么时候该用它」。

插件代码在本进程内执行，信任等级与用户自己写的脚本一致：FYAgent 不做沙箱，
只把导入与执行异常收敛成该插件自身的失败状态。装载是同步的——插件不调网络、
不起子进程，没有 MCP 那种异步连接的必要。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .tools.spec import ToolRegistry, ToolSpec

#: 插件清单文件名（放在 plugins/<名字>/ 下）
MANIFEST_FILENAME = "FYPLUGIN.json"
#: 清单没写 entry 时默认找的实现文件
DEFAULT_ENTRY_FILENAME = "tools.py"
#: 插件目录默认位置：仓库根下的 plugins/
DEFAULT_PLUGIN_DIR_NAME = "plugins"
#: 环境变量覆盖：设为 off 整体关闭插件装载（测试与排错用）
ENV_PLUGINS = "FY_PLUGINS"
#: 环境变量：分号分隔的额外插件根目录
ENV_PLUGIN_DIRS = "FY_PLUGIN_DIRS"
#: 注入 System Prompt 的插件清单标题（模型据此知道插件工具已就绪）
PLUGINS_PROMPT_HEADER = (
    "Local FYAgent plugins are loaded; the tools they register are available "
    "to you like any other tool:"
)
#: 插件贡献工具的统一前缀标记（/tools 与边栏据此区分来源）
PLUGIN_SOURCE_PREFIX = "plugin:"

#: 单个插件贡献的提示片段最大长度（防止一个插件把 System Prompt 挤爆）
MAX_PROMPT_FRAGMENT_CHARS = 4000


@dataclass(frozen=True, slots=True)
class PluginManifest:
    """FYPLUGIN.json 的解析结果。"""

    name: str
    directory: Path
    description: str = ""
    version: str = "0.0.0"
    entry: str = DEFAULT_ENTRY_FILENAME
    enabled: bool = True
    author: str = ""

    @property
    def source(self) -> str:
        return PLUGIN_SOURCE_PREFIX + self.name


def read_manifest(path: Path) -> tuple[PluginManifest | None, str | None]:
    """读一个清单文件；返回 ``(manifest, 跳过原因)``，二者恰有一个为 None。"""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, "清单读取失败：%s" % exc
    except UnicodeDecodeError:
        return None, "清单不是 UTF-8 文本"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, "清单不是合法 JSON：%s" % exc
    if not isinstance(data, dict):
        return None, "清单顶层必须是 JSON 对象"

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        return None, "清单的 name 必须是非空字符串"
    name = name.strip()
    if any(sep in name for sep in ("/", "\\", "..")):
        return None, "插件名不合法：%s" % name

    enabled = data.get("enabled", True)
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() not in ("false", "0", "no", "off", "")

    return (
        PluginManifest(
            name=name,
            directory=path.parent,
            description=str(data.get("description") or "").strip(),
            version=str(data.get("version") or "0.0.0").strip(),
            entry=str(data.get("entry") or DEFAULT_ENTRY_FILENAME).strip(),
            enabled=bool(enabled),
            author=str(data.get("author") or "").strip(),
        ),
        None,
    )


class PluginApi:
    """交给插件 ``register(api)`` 的登记门面：插件只能往这里挂东西。"""

    def __init__(self, manifest: PluginManifest) -> None:
        self._manifest = manifest
        self._tools: list[ToolSpec] = []
        self._prompts: list[str] = []

    @property
    def name(self) -> str:
        return self._manifest.name

    @property
    def description(self) -> str:
        return self._manifest.description

    @property
    def tools(self) -> list[ToolSpec]:
        return list(self._tools)

    @property
    def prompts(self) -> list[str]:
        return list(self._prompts)

    def add_tool(
        self,
        name: str,
        description: str,
        parameters: Mapping[str, Any],
        handler: Callable[..., Any],
    ) -> None:
        """登记一个工具；重名在挂载阶段由注册表统一裁决。"""
        tool_name = str(name or "").strip()
        if not tool_name:
            raise ValueError("工具名不能为空")
        if not callable(handler):
            raise ValueError("工具 %s 的 handler 必须可调用" % tool_name)
        schema = dict(parameters or {})
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})
        schema.setdefault("required", [])
        self._tools.append(
            ToolSpec(
                name=tool_name,
                description=str(description or "").strip() or tool_name,
                parameters=schema,
                handler=handler,
            )
        )

    def add_prompt(self, text: str) -> None:
        """追加一段 System Prompt（例如说明插件何时该用）。"""
        cleaned = str(text or "").strip()
        if cleaned:
            self._prompts.append(cleaned[:MAX_PROMPT_FRAGMENT_CHARS])


@dataclass(slots=True)
class PluginState:
    """一个插件在本次运行中的完整状态，供 /plugins 与边栏展示。"""

    name: str
    directory: Path
    description: str = ""
    version: str = "0.0.0"
    enabled: bool = True
    loaded: bool = False
    error: str = ""
    tools: tuple[str, ...] = ()
    prompts: int = 0

    @property
    def status(self) -> str:
        if not self.enabled:
            return "已停用"
        if self.error:
            return "装载失败"
        if self.loaded:
            return "已装载"
        return "未装载"


class PluginHub:
    """扫描、装载插件，并把结果挂进工具注册表。

    ``discover()`` 只读清单不执行代码（可安全地给用户看目录结构）；
    ``load()`` 才真正 import 并调用 ``register(api)``。装载失败只标记该插件，
    其余插件与内置工具不受影响——与 MCP「单个 Server 挂了不影响别人」一致。
    """

    def __init__(
        self,
        roots: Sequence[Path | str] | None = None,
        disabled: Sequence[str] = (),
    ) -> None:
        self.roots = [Path(root).expanduser() for root in (roots or ())]
        self.disabled = tuple(disabled)
        self._states: list[PluginState] = []
        self._apis: dict[str, PluginApi] = {}
        self._skipped: list[dict[str, str]] = []
        self._loaded = False

    # ------------------------------------------------------------ 发现与装载

    def discover(self) -> list[PluginState]:
        """扫描全部根目录的清单，不执行插件代码；返回状态列表。"""
        states: list[PluginState] = []
        seen: set[str] = set()
        skipped: list[dict[str, str]] = []
        blocked = {item.lower() for item in self.disabled}
        for root in self.roots:
            if not root.is_dir():
                skipped.append({"directory": str(root), "reason": "插件根目录不存在"})
                continue
            for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
                if not child.is_dir():
                    continue
                manifest_path = child / MANIFEST_FILENAME
                if not manifest_path.is_file():
                    skipped.append(
                        {"directory": str(child), "reason": "缺少 %s" % MANIFEST_FILENAME}
                    )
                    continue
                manifest, reason = read_manifest(manifest_path)
                if manifest is None:
                    skipped.append(
                        {"directory": str(child), "reason": reason or "清单无效"}
                    )
                    continue
                if manifest.name in seen:
                    skipped.append(
                        {"directory": str(child), "reason": "插件名重复：%s" % manifest.name}
                    )
                    continue
                seen.add(manifest.name)
                states.append(
                    PluginState(
                        name=manifest.name,
                        directory=child,
                        description=manifest.description,
                        version=manifest.version,
                        enabled=manifest.enabled
                        and manifest.name.lower() not in blocked,
                    )
                )
        self._states = states
        self._skipped = skipped
        self._loaded = False
        return self.status()

    def load(self) -> list[PluginState]:
        """导入并调用每个启用插件的 register(api)；失败只标记该插件。"""
        if not self._loaded:
            self._loaded = True
            if not self._states:
                self.discover()
            self._apis = {}
            for state in self._states:
                if not state.enabled:
                    continue
                manifest = self._manifest_for(state)
                if manifest is None:
                    state.error = "清单已失效或不可读"
                    continue
                api = PluginApi(manifest)
                try:
                    module = _import_module(manifest)
                    register = getattr(module, "register", None)
                    if not callable(register):
                        state.error = "%s 里没有可调用的 register(api)" % manifest.entry
                        continue
                    register(api)
                except Exception as exc:  # 插件代码的任何异常都不外溢
                    state.error = "%s: %s" % (type(exc).__name__, exc)
                    continue
                state.loaded = True
                state.tools = tuple(tool.name for tool in api.tools)
                state.prompts = len(api.prompts)
                self._apis[state.name] = api
        return self.status()

    # ------------------------------------------------------------ 展示与挂载

    def status(self) -> list[PluginState]:
        """状态快照（深拷贝一份，界面拿到的不会被后续装载改动）。"""
        copies: list[PluginState] = []
        for state in self._states:
            copies.append(
                PluginState(
                    name=state.name,
                    directory=state.directory,
                    description=state.description,
                    version=state.version,
                    enabled=state.enabled,
                    loaded=state.loaded,
                    error=state.error,
                    tools=state.tools,
                    prompts=state.prompts,
                )
            )
        return copies

    @property
    def skipped(self) -> list[dict[str, str]]:
        return [dict(item) for item in self._skipped]

    def prompt_fragments(self) -> list[str]:
        """每个已装载插件的提示片段（一个插件一段，带来源标记）。"""
        blocks: list[str] = []
        for state in self._states:
            api = self._apis.get(state.name)
            if api is None or not api.prompts:
                continue
            blocks.append(
                "[%s%s]\n%s" % (PLUGIN_SOURCE_PREFIX, state.name, "\n".join(api.prompts))
            )
        return blocks

    def register_into(self, registry: ToolRegistry) -> list[str]:
        """把插件工具挂进注册表，返回本次实际注册成功的工具名。

        未装载时先装载（``build_registry`` 可以拿到一个「新鲜」的 hub）。
        与已有工具（内置 / MCP / 别的插件）重名时跳过——先注册者优先，
        插件不能顶掉内置工具。重复调用是安全的（切换工作区会重建注册表）。
        """
        if not self._loaded:
            self.load()
        names: list[str] = []
        taken = set(registry.names())
        for state in self._states:
            api = self._apis.get(state.name)
            if api is None:
                continue
            for tool in api.tools:
                if tool.name in taken:
                    continue
                try:
                    registry.register(tool)
                except ValueError as exc:
                    state.error = str(exc)
                    continue
                taken.add(tool.name)
                names.append(tool.name)
        return names

    def tool_names(self) -> list[str]:
        """全部插件贡献的工具名（不含挂载结果，用于展示）。"""
        names: list[str] = []
        for state in self._states:
            api = self._apis.get(state.name)
            if api is not None:
                names.extend(tool.name for tool in api.tools)
        return names

    # ------------------------------------------------------------------ 内部

    def _manifest_for(self, state: PluginState) -> PluginManifest | None:
        manifest_path = state.directory / MANIFEST_FILENAME
        if not manifest_path.is_file():
            return None
        manifest, _ = read_manifest(manifest_path)
        if manifest is None:
            return None
        return manifest


def _import_module(manifest: PluginManifest) -> Any:
    """按文件路径导入插件入口；模块名带上插件名，避免与 sys.modules 冲突。"""
    entry = manifest.directory / manifest.entry
    if not entry.is_file():
        raise FileNotFoundError("找不到入口文件：%s" % entry)
    module_name = "fyagent_plugin_%s" % _safe_module_part(manifest.name)
    spec = importlib.util.spec_from_file_location(module_name, entry)
    if spec is None or spec.loader is None:
        raise ImportError("无法构造导入规格：%s" % entry)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module


def _safe_module_part(name: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in name)


def split_plugin_roots(raw: str) -> list[str]:
    """把 ``roots = a;b`` 拆成路径列表（`;`、`,` 或换行分隔）。"""
    import re

    return [piece.strip() for piece in re.split(r"[;,\n]+", raw or "") if piece.strip()]


def default_plugin_roots(
    project_root: Path | str,
    configured: Sequence[str] = (),
    env_value: str = "",
) -> list[Path]:
    """解析插件根：显式配置优先，为空时用 ``<仓库根>/plugins``。

    支持 ``~``、``%环境变量%`` 与相对路径（相对仓库根解析），重复项去重。
    """
    import os

    base = Path(project_root).expanduser()
    pieces: list[str] = []
    for raw in configured:
        pieces.extend(split_plugin_roots(str(raw)))
    pieces.extend(split_plugin_roots(env_value))
    if not pieces:
        return [base / DEFAULT_PLUGIN_DIR_NAME]

    roots: list[Path] = []
    seen: set[Path] = set()
    for piece in pieces:
        path = Path(os.path.expandvars(piece)).expanduser()
        if not path.is_absolute():
            path = base / path
        resolved = path.resolve() if path.exists() else path
        if resolved in seen:
            continue
        seen.add(resolved)
        roots.append(resolved)
    return roots
