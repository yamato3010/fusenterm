"""「このアプリについて」モーダル画面"""

from __future__ import annotations

from pathlib import Path

from rich.cells import cell_len
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static

from .. import __version__
from ..storage import notes_path, settings_path

APP_NAME = "fusenterm"
APP_DESCRIPTION = "ターミナルのホワイトボードに付箋を貼るアプリ"

# ラベルと値 (値は右側で桁を揃えて表示する)
ENTRIES: list[tuple[str, str]] = [
    ("バージョン", __version__),
    ("作者", "Yamato3010"),
    ("ライセンス", "MIT"),
]

# 値を揃える位置 (全角ラベルを含むためセル幅で計算する)
LABEL_WIDTH = 12


def _short(path: Path) -> str:
    """ホーム以下のパスは ~ 付きの短い表記にする (枠内に収まるように)"""
    try:
        return f"~/{path.relative_to(Path.home())}"
    except ValueError:
        return str(path)


def build_about_text() -> Text:
    """モーダルに表示する本文を組み立てる"""
    text = Text()
    text.append(f"▤ {APP_NAME}\n", style="bold")
    text.append(f"{APP_DESCRIPTION}\n\n", style="dim")

    for label, value in ENTRIES:
        padding = " " * max(1, LABEL_WIDTH - cell_len(label))
        text.append(f"{label}{padding}", style="dim")
        text.append(f"{value}\n")

    # 画面からは辿れないため、データの置き場所もここに出す
    text.append("\n保存先\n", style="dim")
    text.append(f"  {_short(notes_path())}\n")
    text.append(f"  {_short(settings_path())}")

    return text


class AboutScreen(ModalScreen[None]):
    """アプリ名・バージョン・作者などを表示するモーダル"""

    BINDINGS = [
        Binding("escape,i", "dismiss", "閉じる"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="about-dialog") as dialog:
            dialog.border_title = "このアプリについて"
            dialog.border_subtitle = "Esc / i 閉じる"
            yield Static(build_about_text(), id="about-body")
