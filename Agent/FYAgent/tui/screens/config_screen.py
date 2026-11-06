"""首次运行或 /config 时使用的配置对话框。

FYAgent 新增「测试连接」：保存前先发一次极小请求，确认这套接口 / 密钥 /
模型真的能用。探测逻辑在 `core/probe.py`（core 不依赖界面技术），这里只
负责把结果画出来，所以无头测试可以注入假探测函数。
"""

from __future__ import annotations

from typing import Callable

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from core.config import AppConfig, ConfigStore
from core.errors import ConfigError
from core.probe import probe_connection

#: 测试连接：(base_url, api_key, model_name) -> (可用?, 说明)
Probe = Callable[[str, str, str], "tuple[bool, str]"]


class ConfigScreen(ModalScreen[AppConfig | None]):
    """填写三项配置；保存成功返回 :class:`AppConfig`，取消返回 ``None``。"""

    BINDINGS = [Binding("escape", "cancel", "取消")]

    def __init__(
        self,
        store: ConfigStore,
        *,
        base_url: str = "",
        api_key: str = "",
        model_name: str = "",
        probe: Probe | None = None,
    ) -> None:
        super().__init__()
        self._store = store
        self._base_url = base_url
        self._api_key = api_key
        self._model_name = model_name
        # 允许测试注入假探测；默认走真实接口
        self._probe = probe or probe_connection
        self._probing = False

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static("模型设置", classes="title")
            yield Static(
                "首次使用请先填写下面三项，保存后写入 config.ini。",
                classes="hint",
                markup=False,
            )
            yield Static("接口地址", classes="label")
            yield Input(
                value=self._base_url,
                placeholder="例如：https://api.example.com/v1",
                id="base-url",
            )
            yield Static("API 密钥", classes="label")
            yield Input(
                value=self._api_key,
                password=True,
                placeholder="粘贴你的 API 密钥",
                id="api-key",
            )
            yield Static("模型名称", classes="label")
            yield Input(
                value=self._model_name,
                placeholder="例如：deepseek-chat",
                id="model-name",
            )
            yield Static("", id="form-error", markup=False)
            with Horizontal(classes="buttons"):
                # FYAgent 新增：先验证再保存，省得配完才发现连不上
                yield Button("测试连接", id="probe", variant="default")
                yield Button("保存", variant="primary", id="save")
                yield Button("取消", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#base-url", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self._save()
        elif event.button.id == "probe":
            self._start_probe()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    # ------------------------------------------------------------ 测试连接

    def _values(self) -> tuple[str, str, str]:
        return (
            self.query_one("#base-url", Input).value.strip(),
            self.query_one("#api-key", Input).value.strip(),
            self.query_one("#model-name", Input).value.strip(),
        )

    def _start_probe(self) -> None:
        if self._probing:
            return
        error = self.query_one("#form-error", Static)
        button = self.query_one("#probe", Button)
        self._probing = True
        button.disabled = True
        error.set_class(False, "ok")
        error.update("正在测试连接…（发一次极小请求，最多等 20 秒）")
        self._run_probe(*self._values())

    @work(thread=True, exclusive=True, group="probe", exit_on_error=False)
    def _run_probe(self, base_url: str, api_key: str, model_name: str) -> None:
        try:
            result = self._probe(base_url, api_key, model_name)
        except Exception as exc:  # 探测本身炸了也不该关掉对话框
            result = (False, "探测异常：%s" % exc)
        # call_from_thread 挂在 App 上（screen 没有这个方法）
        self.app.call_from_thread(self._finish_probe, result)

    def _finish_probe(self, result: "tuple[bool, str]") -> None:
        self._probing = False
        try:
            error = self.query_one("#form-error", Static)
            button = self.query_one("#probe", Button)
        except Exception:
            return  # 对话框已经关闭
        ok, message = result
        button.disabled = False
        error.update(("✓ " if ok else "✗ ") + message)
        error.set_class(ok, "ok")

    def _save(self) -> None:
        try:
            config = self._store.save(*self._values())
        except ConfigError as exc:
            error = self.query_one("#form-error", Static)
            error.set_class(False, "ok")
            error.update(exc.detail or str(exc))
            return
        self.dismiss(config)