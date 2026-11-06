"""多行聊天输入框："Enter 发送、Ctrl+J 换行"。

Enter 是最顺手的发送键；换行用 Ctrl+J（Windows 控制台里唯一可靠、
能被程序区分出来的换行组合），部分支持增强键盘协议的终端里
Ctrl+Enter / Shift+Enter 也能换行。注意 Windows 控制台会丢掉 Ctrl 修饰，
Ctrl+Enter 会退化成普通 Enter（也就是发送），所以文案里把 Ctrl+J 作为
主要换行方式。

输入以 `/` 开头时，把候选命令交给 :class:`CommandMenu` 显示：↑↓ 选择、
Tab 补全（带参数的命令补出空格）、Enter 直接执行、Esc 收起。

FYAgent 新增「历史翻阅」：菜单收起且输入框只有一行时，↑ / ↓ 在本轮运行
提交过的内容之间来回翻（像 bash / Python REPL）。多行编辑时 ↑↓ 仍然移动
光标，不抢走原有语义；发送成功后翻阅位置自动归零。
"""

from __future__ import annotations

from textual import events
from textual.message import Message
from textual.widgets import TextArea

from .command_menu import CommandMenu

#: 这些按键插入换行；Ctrl+J 是 Windows 控制台上唯一可靠的组合
NEWLINE_KEYS = frozenset({"ctrl+j", "ctrl+enter", "shift+enter", "alt+enter"})

#: 这些按键把内容交给上层发送
SUBMIT_KEYS = frozenset({"enter"})

#: 菜单展开时由输入框截走的按键
MENU_KEYS = frozenset({"up", "down", "tab", "escape", "enter"})

#: `/` 后面最多允许这么多字符再判定“不再像命令名”
MAX_PREFIX_LENGTH = 32

#: 翻阅时最多记住多少条历史提问（够长，也不会吃内存）
HISTORY_LIMIT = 50


class ChatInput(TextArea):
    """支持多行的聊天输入框。"""

    class Submitted(Message):
        """用户按下发送键：请求把文本作为一条消息发送。"""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def __init__(
        self,
        *,
        placeholder: str = "",
        id: str | None = None,
        menu: CommandMenu | None = None,
    ) -> None:
        super().__init__(
            "",
            soft_wrap=True,
            tab_behavior="focus",
            show_line_numbers=False,
            compact=True,
            highlight_cursor_line=False,
            placeholder=placeholder,
            id=id,
        )
        self.menu = menu
        # 本次运行提交过的内容，供 ↑ / ↓ 翻阅；None 表示当前不在翻阅状态
        self._history: list[str] = []
        self._recall: int | None = None
        self._draft = ""

    def submit(self) -> None:
        """把当前文本作为消息发送出去。"""
        self.post_message(self.Submitted(self.text))

    def reset(self) -> None:
        """清空输入并回到行首，供发送后调用。"""
        self.load_text("")
        self._recall = None
        self._draft = ""
        self.sync_menu()

    # ------------------------------------------------------------ 历史翻阅

    def remember(self, text: str) -> None:
        """记录一条真正被接受提交的输入（提问或命令），供 ↑↓ 翻阅。

        与 shell 一致的取舍：连续重复的同一条只留一份，翻阅位置回到最新，
        这样反复按 ↑ 不会在同一条上原地打转。
        """
        cleaned = (text or "").strip()
        if not cleaned:
            return
        if not (self._history and self._history[-1] == cleaned):
            self._history.append(cleaned)
            if len(self._history) > HISTORY_LIMIT:
                del self._history[: -HISTORY_LIMIT]
        self._recall = None
        self._draft = ""

    def _recall_history(self, delta: int) -> bool:
        """↑（-1）/ ↓（+1）翻阅历史；没有可翻阅的东西时返回 False。

        只在「菜单收起 + 输入框是单行」时接管方向键，多行编辑时 ↑↓ 仍然
        移动光标，不抢走原有语义。行为与 bash 一致：↑ 从最新往最早走，
        走过最早一条再按 ↓ 回到最初开始翻阅前那份没发出去的草稿。
        """
        if self.read_only or not self._history or "\n" in self.text:
            return False
        if self.menu is not None and self.menu.is_open:
            return False
        index = self._recall
        if index is None:
            if delta > 0:
                return False  # 还没开始翻阅，往下没有方向可去
            self._draft = self.text
            index = len(self._history)
        target = index + delta
        if target < 0:
            return True  # 已经到最早一条，↑ 继续按就停在最早一条（不越界）
        if target >= len(self._history):
            # 走过最新一条：回到开始翻阅前的草稿，退出翻阅状态
            self._recall = None
            self.load_text(self._draft)
            self.move_cursor(self.document.end)
            return True
        self._recall = target
        self.load_text(self._history[target])
        self.move_cursor(self.document.end)
        return True

    # ------------------------------------------------------------ 命令补全

    def sync_menu(self) -> None:
        """按当前输入刷新命令候选；不像命令时收起菜单。"""
        menu = self.menu
        if menu is None:
            return
        prefix = self._command_prefix()
        if prefix is None:
            menu.close()
        else:
            menu.open_for(prefix)

    def _command_prefix(self) -> str | None:
        """返回需要补全的命令前缀；当前输入不是半截命令时返回 None。"""
        if self.read_only:
            return None
        text = self.text
        if not text.startswith("/") or len(text) > MAX_PREFIX_LENGTH:
            return None
        if any(ch in text for ch in (" ", "\t", "\n", "\r")):
            return None
        row, column = self.cursor_location
        if row != 0 or column != len(text):
            return None
        return text

    def _handle_menu_key(self, event: events.Key) -> bool:
        """菜单展开时处理 ↑↓ / Tab / Enter / Esc；返回是否已消费该按键。"""
        menu = self.menu
        if menu is None or not menu.is_open:
            return False
        key = event.key
        if key in ("up", "down"):
            menu.move(-1 if key == "up" else 1)
        elif key == "tab":
            spec = menu.selected
            if spec is None:
                return False
            self.load_text(spec.name + (" " if spec.accepts_argument else ""))
            self.move_cursor(self.document.end)
            menu.close()
        elif key == "enter":
            spec = menu.selected
            if spec is None:
                return False
            self.load_text(spec.name)
            self.move_cursor(self.document.end)
            menu.close()
            event.stop()
            event.prevent_default()
            self.submit()
            return True
        elif key == "escape":
            menu.close()
        else:
            return False
        event.stop()
        event.prevent_default()
        return True

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """自身内容变化（键入、粘贴、程序回填）后同步候选。

        消息先投给发送者自己再冒泡，因此这里不依赖 App 再转一次；
        `load_text` 这类不经过按键的改动也能照顾到。
        """
        if event.text_area is self:
            self.sync_menu()

    async def _on_key(self, event: events.Key) -> None:
        if not self.read_only and self._handle_menu_key(event):
            return
        if not self.read_only:
            key = event.key
            if key in SUBMIT_KEYS:
                event.stop()
                event.prevent_default()
                self.submit()
                return
            if key in NEWLINE_KEYS:
                event.stop()
                event.prevent_default()
                self.insert("\n")
                self.sync_menu()
                return
            if key in ("up", "down") and self._recall_history(-1 if key == "up" else 1):
                event.stop()
                event.prevent_default()
                self.sync_menu()
                return
        await super()._on_key(event)
        self.sync_menu()
