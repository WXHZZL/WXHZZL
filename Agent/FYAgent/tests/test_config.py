"""config.ini 读写测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.config import ConfigStore, render_config_template
from core.constants import (
    HISTORY_TURNS,
    MAX_TOOL_ROUNDS,
    UI_DEFAULT_CLOCK,
    UI_DEFAULT_COLLAPSE_TOOLS,
    UI_DEFAULT_SIDEBAR,
    UI_DEFAULT_THEME,
    UI_DEFAULT_TIMESTAMPS,
)
from core.errors import ConfigError, ErrorCode


def test_load_missing_file_raises(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "absent.ini")
    assert store.exists() is False
    with pytest.raises(ConfigError) as excinfo:
        store.load()
    assert excinfo.value.code is ErrorCode.CONFIG_MISSING


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    store = ConfigStore(path)
    saved = store.save(" http://example.test/v1 ", " secret ", " model ")

    assert saved.base_url == "http://example.test/v1"
    assert saved.api_key == "secret"
    assert saved.model_name == "model"
    assert store.exists() is True
    assert store.load() == saved

    text = path.read_text(encoding="utf-8")
    assert "[llm]" in text
    assert "base_url = http://example.test/v1" in text


def test_save_rejects_blank_values(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.ini")
    with pytest.raises(ConfigError) as excinfo:
        store.save("http://example.test/v1", "  ", "model")
    assert excinfo.value.code is ErrorCode.CONFIG_INVALID
    assert "API 密钥" in excinfo.value.detail


def test_load_rejects_missing_section(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    path.write_text("[other]\nkey = value\n", encoding="utf-8")
    store = ConfigStore(path)
    assert store.exists() is False
    with pytest.raises(ConfigError) as excinfo:
        store.load()
    assert excinfo.value.code is ErrorCode.CONFIG_INVALID


def test_load_rejects_empty_required_key(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    path.write_text(
        "[llm]\nbase_url = http://x\napi_key =\nmodel_name = m\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError) as excinfo:
        ConfigStore(path).load()
    assert "API 密钥" in excinfo.value.detail


def test_load_reads_optional_search_section(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    path.write_text(
        "[llm]\nbase_url = http://x\napi_key = k\nmodel_name = m\n"
        "[search]\nbaidu_qianfan_api_key = bce-key\n"
        "endpoint = https://example.test/search\n",
        encoding="utf-8",
    )

    config = ConfigStore(path).load()

    assert config.search_api_key == "bce-key"
    assert config.search_endpoint == "https://example.test/search"


def test_load_without_search_section_uses_default_endpoint(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    path.write_text(
        "[llm]\nbase_url = http://x\napi_key = k\nmodel_name = m\n", encoding="utf-8"
    )

    config = ConfigStore(path).load()

    assert config.search_api_key == ""
    assert config.search_endpoint.startswith("https://qianfan.baidubce.com/")


def test_load_reads_optional_tool_rounds(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    path.write_text(
        "[llm]\nbase_url = http://x\napi_key = k\nmodel_name = m\n"
        "max_tool_rounds = 7\nhistory_turns = 4\n",
        encoding="utf-8",
    )

    config = ConfigStore(path).load()

    assert config.max_tool_rounds == 7
    assert config.history_turns == 4


def test_load_defaults_tool_rounds_when_absent(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    path.write_text(
        "[llm]\nbase_url = http://x\napi_key = k\nmodel_name = m\n", encoding="utf-8"
    )

    config = ConfigStore(path).load()

    assert config.max_tool_rounds == MAX_TOOL_ROUNDS
    assert config.history_turns == HISTORY_TURNS


def test_save_preserves_optional_tool_rounds(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    path.write_text(
        "[llm]\nbase_url = http://old\napi_key = old\nmodel_name = old\n"
        "max_tool_rounds = 9\n",
        encoding="utf-8",
    )
    store = ConfigStore(path)

    saved = store.save("http://example.test/v1", "secret", "model")

    assert saved.max_tool_rounds == 9
    assert store.load().max_tool_rounds == 9


def test_load_rejects_non_numeric_tool_rounds(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    path.write_text(
        "[llm]\nbase_url = http://x\napi_key = k\nmodel_name = m\n"
        "max_tool_rounds = many\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as excinfo:
        ConfigStore(path).load()
    assert "max_tool_rounds" in excinfo.value.detail


def test_save_preserves_search_section(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    path.write_text(
        "[llm]\nbase_url = http://old\napi_key = old\nmodel_name = old\n"
        "[search]\nbaidu_qianfan_api_key = keep-me\n",
        encoding="utf-8",
    )
    store = ConfigStore(path)

    saved = store.save("http://example.test/v1", "secret", "model")

    assert saved.search_api_key == "keep-me"
    reloaded = store.load()
    assert reloaded.search_api_key == "keep-me"
    assert reloaded.base_url == "http://example.test/v1"


def test_load_reads_skill_roots(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    path.write_text(
        "[llm]\nbase_url = http://x\napi_key = k\nmodel_name = m\n"
        "[skills]\n"
        "; 分号分隔多个根，%TEMP% 这类写法不能被当成插值\n"
        "roots = D:\\skills ; %TEMP%\\skills\n",
        encoding="utf-8",
    )

    config = ConfigStore(path).load()

    assert config.skill_roots == ("D:\\skills", "%TEMP%\\skills")


def test_save_preserves_skill_roots(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    path.write_text(
        "[llm]\nbase_url = http://old\napi_key = old\nmodel_name = old\n"
        "[skills]\nroots = relative/skills\n",
        encoding="utf-8",
    )
    store = ConfigStore(path)

    saved = store.save("http://example.test/v1", "secret", "model")

    assert saved.skill_roots == ("relative/skills",)
    text = path.read_text(encoding="utf-8")
    assert "[skills]" in text
    assert "relative/skills" in text
    assert store.load().skill_roots == ("relative/skills",)


def test_config_without_skills_section_has_no_roots(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    path.write_text(
        "[llm]\nbase_url = http://x\napi_key = k\nmodel_name = m\n",
        encoding="utf-8",
    )
    assert ConfigStore(path).load().skill_roots == ()


# ---------------------------------------------------------------- [ui] 段


def test_ui_defaults_follow_constants(tmp_path: Path) -> None:
    """老配置文件没有 [ui] 段时全部走默认值，不需要迁移。"""
    path = tmp_path / "config.ini"
    path.write_text(
        "[llm]\nbase_url = http://x\napi_key = k\nmodel_name = m\n",
        encoding="utf-8",
    )
    config = ConfigStore(path).load()
    assert config.ui_theme == UI_DEFAULT_THEME
    assert config.ui_sidebar is UI_DEFAULT_SIDEBAR
    assert config.ui_collapse_tools is UI_DEFAULT_COLLAPSE_TOOLS
    assert config.ui_clock is UI_DEFAULT_CLOCK
    assert config.ui_timestamps is UI_DEFAULT_TIMESTAMPS


def test_ui_section_reads_every_key(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    path.write_text(
        "[llm]\nbase_url = http://x\napi_key = k\nmodel_name = m\n"
        "[ui]\n"
        "theme = nord\n"
        "sidebar = false\n"
        "collapse_tools = yes\n"
        "clock = 0\n"
        "timestamps = on\n",
        encoding="utf-8",
    )
    config = ConfigStore(path).load()
    assert config.ui_theme == "nord"
    assert config.ui_sidebar is False
    assert config.ui_collapse_tools is True
    assert config.ui_clock is False
    assert config.ui_timestamps is True


def test_ui_bad_bool_reports_key_name(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    path.write_text(
        "[llm]\nbase_url = http://x\napi_key = k\nmodel_name = m\n"
        "[ui]\nclock = maybe\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as excinfo:
        ConfigStore(path).load()
    assert "clock" in excinfo.value.detail


def test_template_lists_ui_and_plugins_sections(tmp_path: Path) -> None:
    """模板必须列出新段落：首次运行的用户靠它发现这些开关。"""
    text = render_config_template()
    for section in ("[llm]", "[context]", "[session]", "[tools]", "[search]",
                    "[mcp]", "[skills]", "[plugins]", "[ui]"):
        assert section in text
    for key in ("theme =", "sidebar =", "collapse_tools =", "clock =",
                "timestamps =", "enabled =", "roots =", "disabled ="):
        assert key in text
    # 模板自己必须能被解析
    path = tmp_path / "config.ini"
    path.write_text(text, encoding="utf-8")
    config = ConfigStore(path).load()
    assert config.ui_theme == UI_DEFAULT_THEME
    assert config.plugins_enabled is True


# ------------------------------------------------- save_ui_theme 保注释


def _comments(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip().startswith("#")]


def test_save_ui_theme_keeps_every_comment(tmp_path: Path) -> None:
    """/theme 只该动那一行：切主题是高频动作，不该顺手毁掉整份配置文件。"""
    path = tmp_path / "config.ini"
    path.write_text(render_config_template(), encoding="utf-8")
    store = ConfigStore(path)
    before = path.read_text(encoding="utf-8")

    config = store.save_ui_theme("nord")

    assert config.ui_theme == "nord"
    after = path.read_text(encoding="utf-8")
    assert _comments(after) == _comments(before)
    assert "theme = nord" in after
    for section in ("[llm]", "[context]", "[session]", "[tools]", "[search]",
                    "[mcp]", "[skills]", "[plugins]"):
        assert section in after
    # 其余值原样保留，包括用户自己的接口地址
    assert "base_url = https://api.example.com/v1" in after


def test_save_ui_theme_appends_missing_section(tmp_path: Path) -> None:
    """老文件没有 [ui] 段时补一段，而不是报错或整体重写。"""
    path = tmp_path / "config.ini"
    path.write_text(
        "[llm]\nbase_url = http://x\napi_key = k\nmodel_name = m\n"
        "# 用户自己的备注\n",
        encoding="utf-8",
    )
    store = ConfigStore(path)

    config = store.save_ui_theme("gruvbox")

    assert config.ui_theme == "gruvbox"
    text = path.read_text(encoding="utf-8")
    assert "[ui]" in text and "theme = gruvbox" in text
    assert "# 用户自己的备注" in text
    assert "base_url = http://x" in text


def test_save_ui_theme_inserts_key_into_existing_section(tmp_path: Path) -> None:
    """有 [ui] 段但没有 theme 键：插进段内，不能插到下一个段后面。"""
    path = tmp_path / "config.ini"
    path.write_text(
        "[llm]\nbase_url = http://x\napi_key = k\nmodel_name = m\n"
        "[ui]\nsidebar = true\n"
        "[plugins]\nenabled = true\n",
        encoding="utf-8",
    )

    ConfigStore(path).save_ui_theme("nord")

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines.index("theme = nord") < lines.index("[plugins]")
    assert "sidebar = true" in text


def test_save_ui_theme_repeated_switch_does_not_stack_keys(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    path.write_text(render_config_template(), encoding="utf-8")
    store = ConfigStore(path)

    for name in ("nord", "dracula", "gruvbox"):
        assert store.save_ui_theme(name).ui_theme == name

    text = path.read_text(encoding="utf-8")
    assert text.count("theme = ") == 1
    assert "theme = gruvbox" in text


def test_save_ui_theme_rejects_blank(tmp_path: Path) -> None:
    path = tmp_path / "config.ini"
    path.write_text(render_config_template(), encoding="utf-8")
    with pytest.raises(ConfigError):
        ConfigStore(path).save_ui_theme("   ")


def test_save_ui_theme_creates_template_when_file_absent(tmp_path: Path) -> None:
    """完全没有配置文件时，先把完整模板落盘再改那一行。"""
    path = tmp_path / "sub" / "config.ini"
    config = ConfigStore(path).save_ui_theme("nord")

    assert path.is_file()
    assert config.ui_theme == "nord"
    text = path.read_text(encoding="utf-8")
    assert "[llm]" in text and _comments(text)