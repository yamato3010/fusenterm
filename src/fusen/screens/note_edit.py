"""付箋の本文と色の編集"""

from __future__ import annotations

from typing import Optional

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Select, TextArea

from ..clipboard import markdown_from_paste
from ..models import COLORS


class NoteTextArea(TextArea):
    """付箋の本文の入力欄 (リンク付きの文字列は markdown のリンクにして貼る)"""

    async def _on_paste(self, event: events.Paste) -> None:
        # TextArea 本来の貼り付け (届いたテキストをそのまま入れる) は止めて、ここで入れる
        event.prevent_default()
        if self.read_only:
            return
        text = await markdown_from_paste(event.text) or event.text
        result = self.replace(text, *self.selection)
        self.move_cursor(result.end_location)


class NoteEditScreen(ModalScreen[Optional[tuple[str, str]]]):
    """付箋の本文と色を編集する

    Enter は改行なので、閉じたときに自動保存する。変えていれば (本文, 色) を、
    何も変えていなければ None を返す。
    """

    BINDINGS = [
        Binding("escape", "save", "保存して閉じる"),
        Binding("ctrl+s", "save", "保存して閉じる"),
    ]

    def __init__(self, text: str, color: str, *, title: str = "付箋を編集") -> None:
        super().__init__()
        self._text = text
        self._color = color
        self._title = title

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-dialog") as dialog:
            dialog.border_title = self._title
            dialog.border_subtitle = "Tab 色へ移動   Esc 保存して閉じる"
            yield NoteTextArea(
                self._text,
                soft_wrap=True,
                show_line_numbers=False,
                id="edit-text",
            )
            yield Select(
                [(Text(f"■ {label}", style=value), value) for value, label in COLORS],
                value=self._color,
                allow_blank=False,
                compact=True,
                id="edit-color",
            )

    def on_mount(self) -> None:
        editor = self.query_one("#edit-text", TextArea)
        editor.focus()
        editor.move_cursor(editor.document.end)

    def action_save(self) -> None:
        text = self.query_one("#edit-text", TextArea).text.strip()
        color = self.query_one("#edit-color", Select).value
        if text == self._text.strip() and color == self._color:
            self.dismiss(None)
        else:
            self.dismiss((text, str(color)))
