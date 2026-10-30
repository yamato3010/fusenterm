"""fusen - メインアプリケーション"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Union

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header

from . import storage
from .models import DEFAULT_COLOR, Note, color_label, next_color, note_title
from .screens.about import AboutScreen
from .screens.confirm import ConfirmDeleteScreen
from .screens.links import LinksScreen
from .screens.note_edit import NoteEditScreen
from .screens.overview import OverviewScreen
from .screens.settings import SettingsScreen
from .widgets.board import Board, NoteCard

log = logging.getLogger(__name__)

CSS_PATH = Path(__file__).parent / "styles" / "app.tcss"

# a キーで続けて足したときに、真上に重ならないようずらす量と周期
_CASCADE_STEP = (2, 1)
_CASCADE_COUNT = 6


class FusenApp(App):
    """fusen アプリケーション"""

    TITLE = "fusen"
    CSS_PATH = CSS_PATH
    BINDING_GROUP_TITLE = "全体"

    # 端末のANSIパレット (ユーザーのターミナル配色設定) をそのまま使うテーマ
    THEME = "ansi-dark"

    # 既定では先頭 (一番奥) の付箋が選ばれて手前に出てしまうので、選ぶのは on_mount に任せる
    AUTO_FOCUS = None

    # フッターに出すのは使用頻度の高いものだけ。show=False のキーも ? のヘルプには出る
    BINDINGS = [
        Binding("a", "add", "追加"),
        Binding("e,enter", "edit", "編集"),
        Binding("c", "cycle_color", "色"),
        Binding("d", "delete", "剥がす"),
        Binding("tab", "focus_next", "次の付箋"),
        Binding("z", "overview", "全体"),
        Binding("o", "links", "リンク"),
        Binding("x", "hold", "持つ"),
        Binding("p", "put", "ここに置く"),
        Binding("comma", "settings", "設定"),
        Binding("question_mark", "show_help_panel", "ヘルプ"),
        Binding("q", "quit", "終了"),
        Binding("shift+tab", "focus_previous", "前の付箋", show=False),
        Binding("u", "undo", "剥がした付箋を戻す", show=False),
        Binding("i", "about", "このアプリについて", show=False),
        Binding("escape", "hide_help_panel", "ヘルプを閉じる", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._notes = storage.load_notes()
        self._settings = storage.load_settings()
        self._deleted: Note | None = None  # u キーで戻せる、直前に剥がした付箋
        self._held: NoteCard | None = None  # x で持っている、p で今見ている所へ運ぶ付箋

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        board = Board(id="board")
        board.border_subtitle = "hjkl 選ぶ   m 移動モード   r サイズ変更モード   JK 本文スクロール   ドラッグ 移動   右下の角 大きさ"
        yield board
        # コマンドパレットの案内はフッターの幅を食うので出さない
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        self.theme = self.THEME
        board = self._board()
        self._apply_settings()
        board.mount_all(NoteCard(note) for note in self._notes)
        # 一番手前の付箋から始める
        if self._notes:
            self.call_after_refresh(lambda: board.cards()[-1].focus())
        self._update_title()

    # ── 参照 ────────────────────────────────

    def _board(self) -> Board:
        return self.query_one("#board", Board)

    def _current(self) -> NoteCard | None:
        """選んでいる付箋 (無ければ None)"""
        focused = self.focused
        return focused if isinstance(focused, NoteCard) else None

    # ── イベント ────────────────────────────

    def on_note_card_changed(self, event: NoteCard.Changed) -> None:
        self._save()

    def on_note_card_edit_requested(self, event: NoteCard.EditRequested) -> None:
        self._edit(event.card)

    def on_note_card_delete_requested(self, event: NoteCard.DeleteRequested) -> None:
        self._delete(event.card)

    def on_board_add_requested(self, event: Board.AddRequested) -> None:
        self._add_at(event.x, event.y)

    def on_settings_screen_changed(self, event: SettingsScreen.Changed) -> None:
        self._settings = event.settings
        self._apply_settings()
        try:
            storage.save_settings(self._settings)
        except OSError as e:
            log.warning("設定の保存に失敗しました: %s", e)
            self.notify(f"設定の保存に失敗しました: {e}", severity="error")

    # ── 操作 ────────────────────────────────

    def action_add(self) -> None:
        """今見ている範囲の中央付近に付箋を足す (続けて足すと少しずつずらす)"""
        board = self._board()
        sample = Note(text="")
        step = len(board.cards()) % _CASCADE_COUNT
        camera_x, camera_y = board.camera
        width, height = board.view_size()
        x = camera_x + (width - sample.width) // 2 + _CASCADE_STEP[0] * step
        y = camera_y + (height - sample.height) // 2 + _CASCADE_STEP[1] * step
        self._add_at(x, y)

    def _add_at(self, x: int, y: int) -> None:
        """位置を決めて新しい付箋の編集を開く (本文を書かずに閉じたら足さない)"""

        def on_result(result: Optional[tuple[str, str]]) -> None:
            if result is None or not result[0]:
                return
            text, color = result
            self._attach(NoteCard(Note(text=text, x=x, y=y, color=color)))

        self.push_screen(NoteEditScreen("", DEFAULT_COLOR, title="付箋を追加"), on_result)

    def _attach(self, card: NoteCard) -> None:
        """付箋を一番手前に貼って選ぶ"""
        self._board().mount(card)
        self.call_after_refresh(card.focus)
        self._save()

    def action_edit(self) -> None:
        card = self._current()
        if card is not None:
            self._edit(card)

    def _edit(self, card: NoteCard) -> None:
        note = card.note

        def on_result(result: Optional[tuple[str, str]]) -> None:
            if result is None:
                return
            note.text, note.color = result
            card.sync()
            self._save()

        self.push_screen(NoteEditScreen(note.text, note.color), on_result)

    def action_cycle_color(self) -> None:
        card = self._current()
        if card is None:
            return
        card.note.color = next_color(card.note.color)
        card.sync()
        self.notify(f"色: {color_label(card.note.color)}", timeout=1)
        self._save()

    def action_delete(self) -> None:
        card = self._current()
        if card is not None:
            self._delete(card)

    def _delete(self, card: NoteCard) -> None:
        """確認してから付箋を剥がす (u で戻せるよう覚えておく)"""

        def on_result(confirmed: Optional[bool]) -> None:
            if not confirmed:
                return
            self._deleted = card.note
            if card is self._held:
                self._set_held(None)
            card.remove()
            self._save(exclude=card)
            self.notify("剥がしました (u で元に戻す)", timeout=3)
            # 残りのうち一番手前の付箋を選び直す
            rest = [c for c in self._board().cards() if c is not card]
            if rest:
                rest[-1].focus()

        self.push_screen(ConfirmDeleteScreen(card.note.text), on_result)

    def action_hold(self) -> None:
        """選んでいる付箋を持つ (持っている付箋でもう一度押すとやめる)

        持つだけでボードからは外さない (持ったまま終了しても付箋を失わないように)。
        """
        card = self._current()
        if card is None:
            return
        if card is self._held:
            self._set_held(None)
            self.notify("持つのをやめました", timeout=2)
            return
        self._set_held(card)
        self.notify("持ちました。運びたい所で p (やめるならもう一度 x)", timeout=3)

    def action_put(self) -> None:
        """持っている付箋を、今見ている範囲の真ん中に置く"""
        card = self._held
        if card is None:
            return
        board = self._board()
        camera_x, camera_y = board.camera
        width, height = board.view_size()
        note = card.note
        note.x = camera_x + (width - note.width) // 2
        note.y = camera_y + (height - note.height) // 2
        card.sync()
        self._set_held(None)
        board.raise_card(card)
        card.focus()
        self._save()

    def _set_held(self, card: NoteCard | None) -> None:
        """持っている付箋を変える (印と、ボードの題と、p キーの表示を揃える)"""
        if self._held is not None:
            self._held.remove_class("-held")
        self._held = card
        if card is not None:
            card.add_class("-held")
        self._update_title()
        self.refresh_bindings()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # 何も持っていないときは p を出さない
        if action == "put":
            return self._held is not None
        return True

    def action_overview(self) -> None:
        """縮小表示でボード全体を見て、選んだ付箋か場所へ飛ぶ"""
        board = self._board()

        def on_result(result: Optional[Union[str, tuple[int, int]]]) -> None:
            if result is None:
                return
            if isinstance(result, tuple):
                board.move_camera(*result)
                return
            card = next((c for c in board.cards() if c.note.id == result), None)
            if card is None:
                return
            note = card.note
            board.center_camera(note.x + note.width // 2, note.y + note.height // 2)
            # 画面より大きい付箋は左上を見せる (選び直さない場合もあるのでここで呼ぶ)
            board.reveal(card)
            card.focus()

        notes = [c.note for c in board.cards()]
        self.push_screen(OverviewScreen(notes, board.camera, board.view_size()), on_result)

    def action_links(self) -> None:
        """選んでいる付箋に書かれたリンクを一覧で見せる"""
        card = self._current()
        if card is not None:
            self.push_screen(LinksScreen(card.note.text))

    def action_settings(self) -> None:
        self.push_screen(SettingsScreen(self._settings))

    def action_about(self) -> None:
        self.push_screen(AboutScreen())

    def _apply_settings(self) -> None:
        """設定をボードの見た目に反映する"""
        board = self._board()
        board.set_shadow(self._settings.shadow)
        board.set_background(self._settings.background)

    def action_undo(self) -> None:
        """直前に剥がした付箋を、元の位置の一番手前に戻す"""
        if self._deleted is None:
            self.notify("戻せる付箋はありません", timeout=2)
            return
        note, self._deleted = self._deleted, None
        self._attach(NoteCard(note))

    # ── 保存 ────────────────────────────────

    def _save(self, *, exclude: NoteCard | None = None) -> None:
        """ボードの並び (奥から手前) のまま保存する

        ``exclude`` は削除処理中でまだボードに残っている付箋。
        """
        self._notes = [c.note for c in self._board().cards() if c is not exclude]
        self._update_title()
        try:
            storage.save_notes(self._notes)
        except OSError as e:
            log.warning("付箋の保存に失敗しました: %s", e)
            self.notify(f"保存に失敗しました: {e}", severity="error")

    def _update_title(self) -> None:
        title = f"ホワイトボード  {len(self._notes)}枚"
        # 持っている付箋が画面の外にあっても分かるように題にも出す
        if self._held is not None:
            title += f"  持っている: {note_title(self._held.note.text)}"
        self._board().border_title = title
