"""FYAgent 第二批界面/会话增强测试。

覆盖：/undo 与 /retry 的上下文回滚、↑↓ 历史翻阅、/copy 复制、
配置页「测试连接」，以及 core 侧的会话日志回滚与连通性探测。
"""

from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path

import pytest
from textual.widgets import Button, Input, Static

from core.config import ConfigStore
from core.probe import PROBE_MAX_TOKENS, probe_connection
from core.sessions import SessionStore
from core.skills import SkillLibrary
from support import FakeBackend, RaisingBackend, text_chunks, tool_script
from tui.app import FYAgentApp
from tui.screens.config_screen import ConfigScreen
from tui.widgets.chat_input import ChatInput


def make_app(session, tmp_path, **kwargs) -> FYAgentApp:
    return FYAgentApp(
        session=session, store=ConfigStore(tmp_path / "config.ini"), **kwargs
    )


async def submit(app: FYAgentApp, pilot, text: str) -> None:
    app.query_one("#prompt", ChatInput).load_text(text)
    await pilot.press("enter")
    await pilot.pause()


async def wait_idle(app: FYAgentApp, pilot, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while app._turn_busy and time.monotonic() < deadline:
        await pilot.pause(0.01)
    assert not app._turn_busy, "本轮问答没有在超时前结束"
    await pilot.pause(0.1)


def _system_texts(app: FYAgentApp) -> list[str]:
    return [str(child.render()) for child in app._chat.children if child.has_class("system")]


# ---------------------------------------------------------------- /undo


async def test_undo_rolls_back_history_and_context(make_session, tmp_path) -> None:
    backend = FakeBackend([text_chunks("第一答"), text_chunks("第二答")])
    session = make_session(backend)
    app = make_app(session, tmp_path)

    async with app.run_test() as pilot:
        await submit(app, pilot, "第一问")
        await wait_idle(app, pilot)
        await submit(app, pilot, "第二问")
        await wait_idle(app, pilot)
        assert len(session.history) == 4

        await submit(app, pilot, "/undo")
        await pilot.pause(0.1)

        assert len(session.history) == 2
        assert session.history[0]["content"] == "第一问"
        assert session.history[-1]["content"] == "第一答"
        assert any("已撤销" in text for text in _system_texts(app))
        # 聊天区也跟着只剩一轮
        users = [child for child in app._chat.children if child.has_class("user")]
        assert len(users) == 1


async def test_undo_clears_compact_pause(make_session, tmp_path, config) -> None:
    """撤销后占用变小，「等待 /compact」的暂停状态要一并解除。"""
    session = make_session(FakeBackend([text_chunks("答")]))
    session._compact_required = True
    app = make_app(session, tmp_path)

    async with app.run_test() as pilot:
        await submit(app, pilot, "第一问")
        await wait_idle(app, pilot)
        await submit(app, pilot, "/undo")
        await pilot.pause(0.1)
        assert session.compact_required is False


async def test_undo_without_history_says_so(make_session, tmp_path) -> None:
    app = make_app(make_session(FakeBackend()), tmp_path)

    async with app.run_test() as pilot:
        await submit(app, pilot, "/undo")
        await pilot.pause()
        assert any("没有可撤销" in text for text in _system_texts(app))


async def test_undo_also_rewrites_session_log(make_session, tmp_path) -> None:
    store = SessionStore(tmp_path / "sessions", "test-model")
    session = make_session(FakeBackend([text_chunks("一答"), text_chunks("二答")]), sessions=store)
    app = make_app(session, tmp_path)

    async with app.run_test() as pilot:
        await submit(app, pilot, "一问")
        await wait_idle(app, pilot)
        await submit(app, pilot, "二问")
        await wait_idle(app, pilot)
        session_id = store.session_id
        assert store.messages(session_id) and len(store.messages(session_id)) == 4

        await submit(app, pilot, "/undo")
        await pilot.pause(0.1)

        left = store.messages(session_id)
        assert [item["content"] for item in left] == ["一问", "一答"]
        assert store.message_count == 2


def test_drop_last_turn_core_semantics(tmp_path: Path) -> None:
    """无界面直测：AGENTS.md 注入与压缩摘要都不会被 /undo 抹掉。"""
    store = SessionStore(tmp_path / "sessions", "m")
    store.start()
    store.append_message("system", "项目约定", kind="agents_md")
    store.append_message("user", "一问")
    store.append_message("assistant", "一答")
    store.append_tool("RunCli", "{}", "ok", True)
    store.append_message("user", "二问")
    store.append_message("assistant", "二答")

    assert store.drop_last_turn() == 2
    contents = [item["content"] for item in store.messages(store.session_id)]
    assert contents == ["一问", "一答"]
    # AGENTS.md 那条 system 事件仍在文件里（messages() 会过滤掉它）
    raw = json.dumps(store.load(store.session_id), ensure_ascii=False)
    assert "项目约定" in raw

    # 只剩一轮时还能撤销；再撤销就没有可撤的了
    assert store.drop_last_turn() == 2
    assert store.messages(store.session_id) == []
    assert store.drop_last_turn() == 0


def test_drop_last_turn_refuses_when_compact_follows(tmp_path: Path) -> None:
    """压缩记录若落在截断点之后，回滚会连摘要与归档指针一起抹掉 → 拒绝。"""
    store = SessionStore(tmp_path / "sessions", "m")
    store.start()
    store.append_message("user", "一问")
    store.append_message("assistant", "一答")
    # 压缩发生在「二问」之前：compact 事件之后又有了新的问答
    store.append_compact("20261106-000000", "这是摘要")
    store.append_message("user", "二问")
    store.append_message("assistant", "二答")
    # 最后一个 user 在 compact 之后，截断点不会丢 compact → 允许撤销
    assert store.drop_last_turn() == 2
    assert len(store.messages(store.session_id)) == 2  # 摘要 + 一问一答里压缩后的部分

    # 构造拒绝场景：截断点后面还留着 compact 事件
    store.append_message("user", "三问")
    store.append_message("assistant", "三答")
    store.append_compact("20261106-000001", "第二次摘要")
    refused = store.drop_last_turn()
    assert refused == 0
    assert store.path is not None and store.path.is_file()


def test_drop_last_turn_disabled_store(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "sessions", "m", enabled=False)
    assert store.drop_last_turn() == 0


# ---------------------------------------------------------------- /retry


async def test_retry_asks_the_last_question_again(make_session, tmp_path) -> None:
    backend = FakeBackend([text_chunks("第一次"), text_chunks("第二次")])
    session = make_session(backend)
    app = make_app(session, tmp_path)

    async with app.run_test() as pilot:
        await submit(app, pilot, "今天几号")
        await wait_idle(app, pilot)
        await submit(app, pilot, "/retry")
        await wait_idle(app, pilot)

        asked = [request.messages[-1]["content"] for request in backend.requests]
        assert asked == ["今天几号", "今天几号"]
        assert session.history[-1]["content"] == "第二次"


async def test_retry_without_history_says_so(make_session, tmp_path) -> None:
    app = make_app(make_session(FakeBackend()), tmp_path)

    async with app.run_test() as pilot:
        await submit(app, pilot, "/retry")
        await pilot.pause()
        assert any("还没有提问" in text for text in _system_texts(app))


# ------------------------------------------------------------ ↑↓ 翻阅


async def test_arrows_recall_previous_inputs(make_session, tmp_path) -> None:
    backend = FakeBackend([text_chunks("一"), text_chunks("二")])
    app = make_app(make_session(backend), tmp_path)

    async with app.run_test() as pilot:
        prompt = app.query_one("#prompt", ChatInput)
        await submit(app, pilot, "第一个问题")
        await wait_idle(app, pilot)
        await submit(app, pilot, "第二个问题")
        await wait_idle(app, pilot)

        # 光标在空的输入框里按 ↑：拿到上一条
        await pilot.press("up")
        await pilot.pause()
        assert prompt.text == "第二个问题"

        await pilot.press("up")
        await pilot.pause()
        assert prompt.text == "第一个问题"

        # 按 ↓ 回到更新的一条，再按回到最初那份草稿（空）
        await pilot.press("down")
        await pilot.pause()
        assert prompt.text == "第二个问题"
        await pilot.press("down")
        await pilot.pause()
        assert prompt.text == ""


async def test_recall_does_not_duplicate_consecutive_inputs(make_session, tmp_path) -> None:
    backend = FakeBackend([text_chunks("一"), text_chunks("二"), text_chunks("三")])
    app = make_app(make_session(backend), tmp_path)

    async with app.run_test() as pilot:
        await submit(app, pilot, "重复的问题")
        await wait_idle(app, pilot)
        await submit(app, pilot, "重复的问题")
        await wait_idle(app, pilot)

        prompt = app.query_one("#prompt", ChatInput)
        await pilot.press("up")
        await pilot.pause()
        assert prompt.text == "重复的问题"
        # 连续同条只记一份，所以只有一条可翻；再按 ↑ 停在最早一条（不越界）
        await pilot.press("up")
        await pilot.pause()
        assert prompt.text == "重复的问题"


async def test_recall_keeps_draft_of_unsent_text(make_session, tmp_path) -> None:
    app = make_app(make_session(FakeBackend([text_chunks("答")])), tmp_path)

    async with app.run_test() as pilot:
        await submit(app, pilot, "已发送")
        await wait_idle(app, pilot)

        prompt = app.query_one("#prompt", ChatInput)
        prompt.load_text("还没发的草稿")
        prompt.move_cursor(prompt.document.end)
        await pilot.pause()

        await pilot.press("up")
        await pilot.pause()
        assert prompt.text == "已发送"
        await pilot.press("down")
        await pilot.pause()
        assert prompt.text == "还没发的草稿"


async def test_multiline_input_keeps_arrow_cursor_semantics(make_session, tmp_path) -> None:
    """多行编辑时 ↑ 不该抢去做翻阅——那是用户调光标的手感。"""
    app = make_app(make_session(FakeBackend([text_chunks("答")])), tmp_path)

    async with app.run_test() as pilot:
        await submit(app, pilot, "上一轮")
        await wait_idle(app, pilot)

        prompt = app.query_one("#prompt", ChatInput)
        prompt.load_text("第一行\n第二行")
        prompt.move_cursor((1, 0))
        await pilot.pause()

        await pilot.press("up")
        await pilot.pause()
        # 内容没有被历史覆盖
        assert prompt.text == "第一行\n第二行"


async def test_commands_are_recallable_too(make_session, tmp_path) -> None:
    app = make_app(make_session(FakeBackend()), tmp_path)

    async with app.run_test() as pilot:
        await submit(app, pilot, "/status")
        await pilot.pause()
        prompt = app.query_one("#prompt", ChatInput)
        await pilot.press("up")
        await pilot.pause()
        assert prompt.text == "/status"


# ---------------------------------------------------------------- /copy


async def test_copy_puts_last_reply_into_clipboard(make_session, tmp_path) -> None:
    backend = FakeBackend([text_chunks("这段要能被复制")])
    app = make_app(make_session(backend), tmp_path)

    async with app.run_test() as pilot:
        await submit(app, pilot, "说一句")
        await wait_idle(app, pilot)
        await submit(app, pilot, "/copy")
        await pilot.pause()

        assert app.clipboard == "这段要能被复制"
        assert any("已复制" in text for text in _system_texts(app))


async def test_copy_without_reply_warns(make_session, tmp_path) -> None:
    app = make_app(make_session(FakeBackend()), tmp_path)

    async with app.run_test() as pilot:
        await submit(app, pilot, "/copy")
        await pilot.pause()
        assert any("没有 AI 回复" in text for text in _system_texts(app))
        assert app.clipboard == ""


class _FakeCompletions:
    """记录参数并返回一条固定正文的假 completions。"""

    def __init__(self, content: str = "可用") -> None:
        self.content = content
        self.seen: dict = {}

    def create(self, **kwargs):
        self.seen = kwargs
        message = type("Msg", (), {"content": self.content})
        choice = type("Choice", (), {"message": message})()
        return type("Res", (), {"choices": [choice]})()


class _FakeClient:
    """假 OpenAI 客户端：只暴露 chat.completions.create。"""

    def __init__(self, content: str = "可用") -> None:
        self.chat = type("Chat", (), {"completions": _FakeCompletions(content)})()


class _Error(Exception):
    """带 status_code 的假 SDK 异常（core.probe._explain 会读类名与状态码）。"""

    def __init__(self, name: str, status=None, detail: str = "原始错误文本") -> None:
        self.__class__ = type(name, (_Error,), {})
        self.status_code = status
        super().__init__(detail)


def test_probe_rejects_missing_fields() -> None:
    ok, message = probe_connection("", "k", "m")
    assert ok is False and "接口地址" in message
    ok, message = probe_connection("http://x", "", "m")
    assert ok is False and "API 密钥" in message
    ok, message = probe_connection("http://x", "k", "")
    assert ok is False and "模型名称" in message


def test_probe_uses_injected_client() -> None:
    client = _FakeClient("可用")
    ok, message = probe_connection(
        "https://api.deepseek.com/v1", "sk-x", "deepseek-chat", client=client
    )
    assert ok is True, message
    assert "可用" in message
    seen = client.chat.completions.seen
    assert seen["model"] == "deepseek-chat"
    assert seen["max_tokens"] == PROBE_MAX_TOKENS
    assert seen["stream"] is False


@pytest.mark.parametrize(
    "name, status, keyword",
    [
        ("AuthenticationError", 401, "密钥"),
        ("NotFoundError", 404, "不存在"),
        ("RateLimitError", 429, "额度"),
        ("APIConnectionError", None, "连不上"),
        ("BadRequestError", 400, "拒绝"),
        ("InternalServerError", 503, "服务端"),
    ],
)
def test_probe_translates_sdk_errors(name: str, status, keyword: str) -> None:
    class Failing:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    raise _Error(name, status)

    ok, message = probe_connection("https://x/v1", "sk-x", "m", client=Failing())
    assert ok is False
    assert keyword in message, message


def test_probe_reports_unreadable_payload_as_success() -> None:
    class Weird:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    class Res:
                        choices = []

                    return Res()

    ok, message = probe_connection("https://x/v1", "sk-x", "m", client=Weird())
    assert ok is True  # 有响应就算连通，只是读不出正文


def test_probe_survives_client_level_boom() -> None:
    class Boom:
        @property
        def chat(self):
            raise RuntimeError("客户端坏了")

    ok, message = probe_connection("https://x/v1", "sk-x", "m", client=Boom())
    assert ok is False
    assert "Boom" not in message and message  # 给出中文说明，不是裸 traceback

# ------------------------------------------------- 配置页「测试连接」
#
# 不子类化 FYAgentApp：Textual 会按「定义类的模块」解析 CSS_PATH，
# 测试文件里的子类会去找 tests/styles.tcss 而报错。改成正常建 App
# （注入会话，on_mount 直接返回，不联网），再由测试把对话框 push 上去。


async def _open_config_screen(app: FYAgentApp, pilot, probe) -> None:
    app.push_screen(
        ConfigScreen(
            app._store,
            base_url="https://api.deepseek.com/v1",
            api_key="sk-x",
            model_name="deepseek-chat",
            probe=probe,
        )
    )
    await pilot.pause()


async def test_config_screen_probe_shows_result(make_session, tmp_path) -> None:
    calls: list[tuple[str, str, str]] = []

    def fake_probe(base_url: str, api_key: str, model: str):
        calls.append((base_url, api_key, model))
        return (True, "连接正常：可用")

    app = make_app(make_session(FakeBackend()), tmp_path)
    async with app.run_test() as pilot:
        await _open_config_screen(app, pilot, fake_probe)
        screen = app.screen
        await pilot.click("#probe")

        deadline = time.monotonic() + 5.0
        error = screen.query_one("#form-error", Static)
        while time.monotonic() < deadline and "连接正常" not in str(error.render()):
            await pilot.pause(0.05)

        assert calls and calls[0] == (
            "https://api.deepseek.com/v1",
            "sk-x",
            "deepseek-chat",
        )
        assert "连接正常" in str(error.render())
        assert error.has_class("ok")


async def test_config_screen_probe_failure_is_red(make_session, tmp_path) -> None:
    def fake_probe(base_url: str, api_key: str, model: str):
        return (False, "API 密钥无效或被拒（401）")

    app = make_app(make_session(FakeBackend()), tmp_path)
    async with app.run_test() as pilot:
        await _open_config_screen(app, pilot, fake_probe)
        screen = app.screen
        # 改掉预填值，确认探测用的是界面上的当前内容
        screen.query_one("#api-key", Input).value = "sk-bad"
        await pilot.click("#probe")

        error = screen.query_one("#form-error", Static)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and "401" not in str(error.render()):
            await pilot.pause(0.05)

        assert "密钥无效" in str(error.render())
        assert not error.has_class("ok")


async def test_config_screen_probe_reads_current_field_values(make_session, tmp_path) -> None:
    seen: list[tuple[str, str, str]] = []

    app = make_app(make_session(FakeBackend()), tmp_path)
    async with app.run_test() as pilot:
        await _open_config_screen(app, pilot, lambda *a: (seen.append(a), (True, "ok"))[1])
        screen = app.screen
        screen.query_one("#model-name", Input).value = "deepseek-reasoner"
        await pilot.click("#probe")
        deadline = time.monotonic() + 5.0
        while not seen and time.monotonic() < deadline:
            await pilot.pause(0.05)
        assert seen and seen[0][2] == "deepseek-reasoner"


async def test_config_screen_save_still_works(make_session, tmp_path) -> None:
    """测试连接是附加能力，不能影响原来的保存路径。"""
    app = make_app(make_session(FakeBackend()), tmp_path)
    async with app.run_test() as pilot:
        await _open_config_screen(app, pilot, lambda *a: (True, "ok"))
        screen = app.screen
        screen.query_one("#base-url", Input).value = "https://api.deepseek.com/v1"
        screen.query_one("#api-key", Input).value = "sk-x"
        screen.query_one("#model-name", Input).value = "deepseek-chat"
        await pilot.click("#save")
        await pilot.pause()

        config = app._store.load()
        assert config.model_name == "deepseek-chat"
        assert config.api_key == "sk-x"
