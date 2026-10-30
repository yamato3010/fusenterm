"""付箋に書かれたリンクの一覧 (選んだリンクをブラウザで開く)"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from ..markdown import extract_links


class LinksScreen(ModalScreen[None]):
    """付箋の本文にあるリンクを並べて見せる (文字付きのリンクは文字と URL の両方)

    Enter かクリックで選んだリンクをブラウザで開く。続けて開けるよう一覧は閉じない。
    """

    # App 側で AUTO_FOCUS を切っているので、一覧に直接フォーカスを置く
    AUTO_FOCUS = "#links-list"

    BINDINGS = [
        Binding("j", "cursor(1)", "下へ", show=False),
        Binding("k", "cursor(-1)", "上へ", show=False),
        Binding("escape,o", "close", "閉じる"),
    ]

    def __init__(self, text: str) -> None:
        super().__init__()
        self._links = extract_links(text)

    def compose(self) -> ComposeResult:
        with Vertical(id="links-dialog") as dialog:
            dialog.border_title = f"リンク  {len(self._links)}件"
            if not self._links:
                dialog.border_subtitle = "Esc / o 閉じる"
                yield Static(Text("この付箋にリンクはありません", style="dim"))
                return
            dialog.border_subtitle = "jk 選ぶ   Enter / クリック 開く   Esc / o 閉じる"
            yield OptionList(
                *(self._option(n, label, url) for n, (label, url) in enumerate(self._links, 1)),
                id="links-list",
            )

    @staticmethod
    def _option(number: int, label: str, url: str) -> Option:
        head = f"{number}. "
        prompt = Text(head)
        if label:
            prompt.append(label, style="bold")
            # URL は文字の下に、番号の分だけ字下げして書く
            prompt.append("\n" + " " * len(head))
        prompt.append(url, style="underline")
        return Option(prompt)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        _, url = self._links[event.option_index]
        self.app.open_url(url)
        self.notify(f"開きました: {url}", timeout=2)

    def action_cursor(self, step: int) -> None:
        for option_list in self.query(OptionList):
            if step > 0:
                option_list.action_cursor_down()
            else:
                option_list.action_cursor_up()

    def action_close(self) -> None:
        self.dismiss(None)
