"""設定 (付箋の影・ボードの背景)"""

from __future__ import annotations

from dataclasses import replace

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Label, RadioButton, RadioSet, Switch

from ..models import BACKGROUNDS, Settings


class SettingsScreen(ModalScreen[None]):
    """設定を変える

    変えるたびに Changed を送り、ボードへの反映と保存はアプリ側に任せる
    (後ろのボードで見た目を確かめながら選べるように)。
    """

    # App 側で AUTO_FOCUS を切っているので、最初の項目に直接フォーカスを置く
    AUTO_FOCUS = "#settings-shadow"

    BINDINGS = [
        Binding("escape,s", "close", "閉じる"),
    ]

    class Changed(Message):
        """設定が変わった"""

        def __init__(self, settings: Settings) -> None:
            super().__init__()
            self.settings = settings

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = replace(settings)

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-dialog") as dialog:
            dialog.border_title = "設定"
            dialog.border_subtitle = "Tab 移る   Enter 切り替え   Esc / s 閉じる"
            with Horizontal(classes="settings-row"):
                yield Label("付箋の影", classes="settings-label")
                yield Switch(self._settings.shadow, id="settings-shadow")
            yield Label("ボードの背景", id="settings-background-label", classes="settings-label")
            with RadioSet(id="settings-background"):
                for value, label in BACKGROUNDS:
                    yield RadioButton(label, value=value == self._settings.background, name=value)

    def on_switch_changed(self, event: Switch.Changed) -> None:
        self._settings.shadow = event.value
        self.post_message(self.Changed(replace(self._settings)))

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        self._settings.background = event.pressed.name or self._settings.background
        self.post_message(self.Changed(replace(self._settings)))

    def action_close(self) -> None:
        self.dismiss(None)
