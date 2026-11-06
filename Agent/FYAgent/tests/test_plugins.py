"""插件系统测试：清单解析、扫描装载、隔离、注册表挂载、配置与开关。

真实 `plugins/` 目录里的示例插件不在测试路径上：所有用例都用 tmp_path 构造
插件目录，或者显式注入 PluginHub（conftest 已把 FY_PLUGINS 设为 off）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.config import AppConfig, ConfigStore, render_config_template
from core.factory import build_registry
from core.plugins import (
    ENV_PLUGINS,
    MANIFEST_FILENAME,
    PluginHub,
    default_plugin_roots,
    read_manifest,
    split_plugin_roots,
)
from core.tools.spec import ToolRegistry

# ------------------------------------------------------------------ 辅助


def make_plugin(
    root: Path,
    name: str,
    *,
    body: str | None = None,
    manifest: dict | None = None,
    entry: str = "tools.py",
) -> Path:
    """在 root/<name> 下建一个插件；body 为 None 时用最小可用实现。"""
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    data = {"name": name, "description": "插件 %s" % name, "entry": entry}
    if manifest is not None:
        data = manifest
    (directory / MANIFEST_FILENAME).write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    if body is None:
        body = (
            "def register(api):\n"
            "    api.add_tool(\n"
            "        '%s_tool', '说明', {'type': 'object', 'properties': {"
            "'x': {'type': 'string'}}, 'required': []},\n"
            "        lambda x='': {'ok': True, 'echo': x},\n"
            "    )\n"
            "    api.add_prompt('plugin %s ready')\n" % (name, name)
        )
    (directory / entry).write_text(body, encoding="utf-8")
    return directory


# ------------------------------------------------------------- 清单解析


def test_read_manifest_defaults(tmp_path: Path) -> None:
    directory = tmp_path / "a"
    directory.mkdir()
    path = directory / MANIFEST_FILENAME
    path.write_text(json.dumps({"name": "a"}), encoding="utf-8")
    manifest, reason = read_manifest(path)
    assert reason is None
    assert manifest is not None
    assert manifest.name == "a"
    assert manifest.entry == "tools.py"
    assert manifest.enabled is True
    assert manifest.source == "plugin:a"


@pytest.mark.parametrize(
    "payload, keyword",
    [
        ({}, "非空字符串"),
        ({"name": ""}, "非空字符串"),
        ({"name": "a/b"}, "不合法"),
        ({"name": ".."}, "不合法"),
        ({"name": {"x": 1}}, "非空字符串"),
    ],
)
def test_read_manifest_rejects_bad_names(tmp_path: Path, payload: dict, keyword: str) -> None:
    directory = tmp_path / "a"
    directory.mkdir()
    path = directory / MANIFEST_FILENAME
    path.write_text(json.dumps(payload), encoding="utf-8")
    manifest, reason = read_manifest(path)
    assert manifest is None
    assert keyword in (reason or "")


def test_read_manifest_bad_json_and_encoding(tmp_path: Path) -> None:
    directory = tmp_path / "a"
    directory.mkdir()
    path = directory / MANIFEST_FILENAME
    path.write_text("{not json", encoding="utf-8")
    manifest, reason = read_manifest(path)
    assert manifest is None and "JSON" in (reason or "")

    path.write_bytes(b"\xff\xfe invalid utf8")
    manifest, reason = read_manifest(path)
    assert manifest is None
    assert "UTF-8" in (reason or "")


def test_manifest_enabled_accepts_strings(tmp_path: Path) -> None:
    directory = tmp_path / "a"
    directory.mkdir()
    path = directory / MANIFEST_FILENAME
    for value, expected in (("false", False), ("0", False), ("off", False), ("yes", True)):
        path.write_text(json.dumps({"name": "a", "enabled": value}), encoding="utf-8")
        manifest, _ = read_manifest(path)
        assert manifest is not None
        assert manifest.enabled is expected, value


# --------------------------------------------------------------- 扫描


def test_discover_skips_missing_manifest_and_duplicates(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(root, "good")
    (root / "no-manifest").mkdir()
    (root / "broken").mkdir()
    (root / "broken" / MANIFEST_FILENAME).write_text("{bad", encoding="utf-8")

    hub = PluginHub(roots=[root])
    states = hub.discover()
    assert [state.name for state in states] == ["good"]
    reasons = " ".join(item["reason"] for item in hub.skipped)
    assert "缺少" in reasons and "JSON" in reasons

    # 同名插件在第二个根里：后扫到的被跳过
    other = tmp_path / "plugins2"
    make_plugin(other, "good")
    hub2 = PluginHub(roots=[root, other])
    states2 = hub2.discover()
    assert [state.name for state in states2] == ["good"]
    assert any("重复" in item["reason"] for item in hub2.skipped)


def test_discover_missing_root_is_skipped_not_fatal(tmp_path: Path) -> None:
    hub = PluginHub(roots=[tmp_path / "nope"])
    assert hub.discover() == []
    assert any("不存在" in item["reason"] for item in hub.skipped)


def test_disabled_list_blocks_plugin(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(root, "a")
    make_plugin(root, "b")
    hub = PluginHub(roots=[root], disabled=["A"])  # 大小写不敏感
    states = hub.load()
    by_name = {state.name: state for state in states}
    assert by_name["a"].enabled is False
    assert by_name["a"].loaded is False
    assert by_name["b"].loaded is True
    assert hub.register_into(ToolRegistry()) == ["b_tool"]


# --------------------------------------------------------------- 装载


def test_load_isolates_failing_plugins(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(root, "boom", body="raise RuntimeError('插件炸了')\n")
    # 清单指向不存在的入口文件
    directory = make_plugin(root, "missing_entry", body="def register(api): pass\n")
    (directory / MANIFEST_FILENAME).write_text(
        json.dumps({"name": "missing_entry", "entry": "gone.py"}), encoding="utf-8"
    )
    make_plugin(
        root, "no_register", body="x = 1\n", manifest={"name": "no_register"}
    )
    make_plugin(root, "ok")

    hub = PluginHub(roots=[root])
    states = hub.load()
    by_name = {state.name: state for state in states}
    assert "RuntimeError" in by_name["boom"].error
    assert "入口文件" in by_name["missing_entry"].error
    assert "register" in by_name["no_register"].error
    assert by_name["ok"].loaded is True
    assert hub.tool_names() == ["ok_tool"]


def test_register_can_defer_failure_until_execution(tmp_path: Path) -> None:
    """register() 里 add_tool 抛错 → 该插件失败，其余不受影响。"""
    root = tmp_path / "plugins"
    make_plugin(
        root,
        "badadd",
        body="def register(api):\n    api.add_tool('', 'x', {}, lambda: 1)\n",
    )
    make_plugin(root, "ok")
    hub = PluginHub(roots=[root])
    states = hub.load()
    by_name = {state.name: state for state in states}
    assert "不能为空" in by_name["badadd"].error
    assert by_name["ok"].loaded is True


def test_handler_errors_become_failed_outcomes(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(
        root,
        "throw",
        body=(
            "def register(api):\n"
            "    def boom():\n"
            "        raise ValueError('内部错误')\n"
            "    api.add_tool('boom', 'x', {}, boom)\n"
        ),
    )
    workspace = tmp_path / "ws"
    workspace.mkdir()
    registry = build_registry(workspace, plugins=PluginHub(roots=[root]))
    outcome = registry.execute("boom", "{}")
    assert outcome.ok is False
    assert "内部错误" in outcome.output


# ------------------------------------------------------------ 注册表挂载


def test_registry_order_and_builtin_protection(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(
        root,
        "shadow",
        body=(
            "def register(api):\n"
            "    api.add_tool('get_date', '抢内置', {}, lambda: 'nope')\n"
            "    api.add_tool('fresh', '新工具', {}, lambda: 'yes')\n"
        ),
    )
    hub = PluginHub(roots=[root])
    workspace = tmp_path / "ws"
    workspace.mkdir()
    registry = build_registry(workspace, plugins=hub)
    names = registry.names()
    # 内置工具优先，插件不能顶掉它；list_tools 永远最后
    assert names[0] == "get_date"
    assert names[-1] == "list_tools"
    assert "fresh" in names
    assert registry.get("get_date").description != "抢内置"
    assert registry.execute("fresh", "{}").output == "yes"


def test_plugin_prompt_fragments_and_system_prompt(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(root, "p1")
    hub = PluginHub(roots=[root])
    hub.load()
    blocks = hub.prompt_fragments()
    assert len(blocks) == 1
    assert blocks[0].startswith("[plugin:p1]")
    assert "plugin p1 ready" in blocks[0]


def test_register_into_is_idempotent_across_registries(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(root, "a")
    hub = PluginHub(roots=[root])
    hub.load()
    first = ToolRegistry()
    assert hub.register_into(first) == ["a_tool"]
    # 同一注册表重复挂载：不报错、不重复
    assert hub.register_into(first) == []
    second = ToolRegistry()
    assert hub.register_into(second) == ["a_tool"]


def test_load_is_cached_until_rediscover(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    make_plugin(root, "a")
    hub = PluginHub(roots=[root])
    hub.load()
    make_plugin(root, "b")
    hub.load()  # 已装载过：不重新扫描
    assert hub.tool_names() == ["a_tool"]
    hub.discover()
    hub.load()
    assert set(hub.tool_names()) == {"a_tool", "b_tool"}


# ---------------------------------------------------------------- 路径


def test_default_plugin_roots_uses_project_root(tmp_path: Path) -> None:
    roots = default_plugin_roots(tmp_path)
    assert roots == [tmp_path / "plugins"]


def test_default_plugin_roots_configured_relative_and_dedup(tmp_path: Path) -> None:
    extra = tmp_path / "team"
    extra.mkdir()
    roots = default_plugin_roots(tmp_path, ["team", str(extra), "team"])
    assert roots == [extra]


def test_split_plugin_roots_separators() -> None:
    assert split_plugin_roots("a;b") == ["a", "b"]
    assert split_plugin_roots("a, b\nc") == ["a", "b", "c"]
    assert split_plugin_roots("") == []


def test_env_kill_switch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_PLUGINS, "off")
    from core.factory import create_session

    root = tmp_path / "plugins"
    make_plugin(root, "a")
    session = create_session(
        AppConfig(base_url="http://x", api_key="k", model_name="m"),
        project_root=tmp_path,
        history_dir=tmp_path / "hist",
    )
    assert session.plugins is None
    assert "a_tool" not in session.registry.names()
    session.close()


def test_roots_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    extra = tmp_path / "envplugins"
    make_plugin(extra, "e")
    monkeypatch.setenv("FY_PLUGIN_DIRS", str(extra))
    # conftest 的 autouse fixture 默认 FY_PLUGINS=off，这里显式放开
    monkeypatch.delenv(ENV_PLUGINS, raising=False)
    from core.factory import create_session

    session = create_session(
        AppConfig(base_url="http://x", api_key="k", model_name="m"),
        project_root=tmp_path,
        history_dir=tmp_path / "hist",
    )
    assert session.plugins is not None
    assert any(state.name == "e" for state in session.plugins.status())
    assert "e_tool" in session.registry.names()
    session.close()


# ---------------------------------------------------------------- 配置


def test_config_plugins_section_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    path.write_text(render_config_template(), encoding="utf-8")
    text = path.read_text(encoding="utf-8")
    assert "[plugins]" in text and "enabled = true" in text

    config = ConfigStore(path).load()
    assert config.plugins_enabled is True
    assert config.plugin_roots == ()
    assert config.plugins_disabled == ()

    path.write_text(
        text.replace("enabled = true", "enabled = false")
        .replace("roots =", "roots = D:\\p1;D:\\p2")
        .replace("disabled =", "disabled = alpha;Beta"),
        encoding="utf-8",
    )
    config = ConfigStore(path).load()
    assert config.plugins_enabled is False
    assert config.plugin_roots == ("D:\\p1", "D:\\p2")
    assert config.plugins_disabled == ("alpha", "Beta")


def test_config_bad_plugins_enabled(tmp_path: Path) -> None:
    from core.errors import ConfigError

    path = tmp_path / "config.ini"
    path.write_text(
        render_config_template().replace("enabled = true", "enabled = maybe"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        ConfigStore(path).load()
