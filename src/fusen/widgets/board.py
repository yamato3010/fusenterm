"""ホワイトボードと、そこに貼る付箋のウィジェット

ボードは無限に広く、画面にはカメラ (ボードの左上に映す位置) から見える範囲だけを
映す。付箋はボードの中に ``position: absolute`` で置き、offset には付箋の位置から
カメラの位置を引いた値を入れる。重なり順はボードの子の並び順 (後ろほど手前) で、
選んだ付箋は最後尾に移して手前に出す。
"""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.containers import Container
from textual.message import Message
from textual.widgets import Static

from ..markdown import render_markdown
from ..models import COLORS, Note, clamp_size

# 右下の角のつまみ (ここをドラッグすると大きさが変わる)
_GRIP = "◢"

# 枠と左右の余白で使う桁数 (本文に使える幅を出すため。app.tcss の NoteCard と揃える)
_FRAME_WIDTH = 4

# ホイール1回でカメラを動かす量 (桁, 行)
_WHEEL_STEP = (4, 2)


class NoteCard(Static, can_focus=True):
    """ボードに貼られた1枚の付箋

    矢印キー / hjkl で移動、Shift+矢印 / HJKL で大きさを変える。
    マウスでは本体をドラッグで移動、右下の角をドラッグで大きさを変える。
    位置や大きさを変えたら Changed を送り、保存はアプリ側に任せる。
    キーボードで選んだり動かしたりしたら、見えるところまでカメラを動かす。
    """

    BINDING_GROUP_TITLE = "付箋"

    # ドラッグで動かすと本文が範囲選択されてしまうので、選択はさせない
    ALLOW_SELECT = False

    BINDINGS = [
        Binding("left,h", "move(-1, 0)", "左へ", show=False),
        Binding("right,l", "move(1, 0)", "右へ", show=False),
        Binding("up,k", "move(0, -1)", "上へ", show=False),
        Binding("down,j", "move(0, 1)", "下へ", show=False),
        Binding("shift+left,H", "resize(-1, 0)", "幅を縮める", show=False),
        Binding("shift+right,L", "resize(1, 0)", "幅を広げる", show=False),
        Binding("shift+up,K", "resize(0, -1)", "高さを縮める", show=False),
        Binding("shift+down,J", "resize(0, 1)", "高さを広げる", show=False),
    ]

    class Changed(Message):
        """付箋の位置・大きさが変わった (保存のきっかけ)"""

        def __init__(self, card: NoteCard) -> None:
            super().__init__()
            self.card = card

    class EditRequested(Message):
        """付箋をダブルクリックした (本文の編集を開く)"""

        def __init__(self, card: NoteCard) -> None:
            super().__init__()
            self.card = card

    def __init__(self, note: Note) -> None:
        super().__init__()
        self.note = note
        # ドラッグ中の状態: (押した画面上の位置, 押したときの x, y, 幅, 高さ, 大きさを変えるか)
        self._drag: tuple[int, int, int, int, int, int, bool] | None = None
        self.border_subtitle = _GRIP
        self.sync()

    def sync(self) -> None:
        """付箋のデータを見た目 (位置・大きさ・色・本文) に反映する"""
        note = self.note
        self.sync_offset()
        self.styles.width = note.width
        self.styles.height = note.height
        for value, _ in COLORS:
            self.set_class(note.color == value, f"-{value}")
        if note.text:
            self.update(render_markdown(note.text, note.width - _FRAME_WIDTH))
        else:
            self.update(Text("(空の付箋)", style="dim"))

    def sync_offset(self) -> None:
        """付箋の位置とカメラから、画面上の位置を決め直す"""
        camera_x, camera_y = self.parent.camera if isinstance(self.parent, Board) else (0, 0)
        self.styles.offset = (self.note.x - camera_x, self.note.y - camera_y)

    def on_mount(self) -> None:
        # 作った時点ではボードに付いておらずカメラが分からないので、付いてから決め直す
        self.sync_offset()

    def on_focus(self) -> None:
        """選んだ付箋を一番手前に出す (Tab でもクリックでもここに来る)"""
        if not isinstance(self.parent, Board):
            return
        if self.parent.raise_card(self):
            # 重なり順も保存するので、変わったことを知らせる
            self.post_message(self.Changed(self))
        # マウスで掴んだときは、付箋がマウスの下から逃げないようカメラを動かさない
        if self._drag is None:
            self.parent.reveal(self)

    # ── 位置・大きさ ────────────────────────

    def _place(self, x: int, y: int, width: int, height: int) -> None:
        """大きさを最小値以上に揃えてから位置・大きさを変える"""
        note = self.note
        note.width, note.height = clamp_size(width, height)
        note.x, note.y = x, y
        self.sync()

    def action_move(self, dx: int, dy: int) -> None:
        note = self.note
        self._place(note.x + dx, note.y + dy, note.width, note.height)
        self._reveal()
        self.post_message(self.Changed(self))

    def action_resize(self, dw: int, dh: int) -> None:
        note = self.note
        self._place(note.x, note.y, note.width + dw, note.height + dh)
        self._reveal()
        self.post_message(self.Changed(self))

    def _reveal(self) -> None:
        if isinstance(self.parent, Board):
            self.parent.reveal(self)

    # ── マウス ──────────────────────────────

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button != 1:
            return
        event.stop()
        self.focus()
        note = self.note
        # 右下の角 (つまみの辺り) を掴んだら大きさを変える
        resize = event.y >= note.height - 1 and event.x >= note.width - 3
        self._drag = (
            event.screen_x, event.screen_y, note.x, note.y, note.width, note.height, resize
        )
        self.capture_mouse()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._drag is None:
            return
        start_x, start_y, x, y, width, height, resize = self._drag
        dx, dy = event.screen_x - start_x, event.screen_y - start_y
        if resize:
            self._place(x, y, width + dx, height + dy)
        else:
            self._place(x + dx, y + dy, width, height)

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._drag is None:
            return
        self._drag = None
        self.release_mouse()
        self.post_message(self.Changed(self))

    def on_click(self, event: events.Click) -> None:
        # ボードのダブルクリック (付箋の追加) まで届かないように止める
        event.stop()
        if event.chain == 2:
            self.post_message(self.EditRequested(self))


class Board(Container):
    """付箋を貼るホワイトボード (無限に広い)

    空いている所をドラッグするとカメラが動く (ホイールでも動く。Shift+ホイールで左右)。
    空いている所をダブルクリックすると、その位置への追加を AddRequested で知らせる。
    """

    class AddRequested(Message):
        """ボードの空いている所をダブルクリックした (その位置に付箋を足す)"""

        def __init__(self, x: int, y: int) -> None:
            super().__init__()
            self.x = x
            self.y = y

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        # カメラ: 画面の左上に映す、ボード全体での位置
        self.camera: tuple[int, int] = (0, 0)
        # ドラッグ中の状態: (押した画面上の位置, 押したときのカメラの位置)
        self._drag: tuple[int, int, int, int] | None = None

    def on_click(self, event: events.Click) -> None:
        if event.chain == 2:
            offset = event.get_content_offset(self)
            if offset is not None:
                camera_x, camera_y = self.camera
                self.post_message(self.AddRequested(offset.x + camera_x, offset.y + camera_y))

    # ── カメラ ──────────────────────────────

    def view_size(self) -> tuple[int, int]:
        """画面に映っている範囲の大きさ"""
        size = self.content_size
        return size.width, size.height

    def move_camera(self, x: int, y: int) -> None:
        """カメラを (x, y) に動かす"""
        if (x, y) == self.camera:
            return
        self.camera = (x, y)
        for card in self.cards():
            card.sync_offset()

    def center_camera(self, x: int, y: int) -> None:
        """ボード全体での (x, y) が画面の真ん中に来るようカメラを動かす"""
        width, height = self.view_size()
        self.move_camera(x - width // 2, y - height // 2)

    def reveal(self, card: NoteCard) -> None:
        """付箋が画面に収まるよう、必要な分だけカメラを動かす

        付箋のほうが画面より大きい場合は左上を見せる。
        """
        note = card.note
        width, height = self.view_size()
        camera_x, camera_y = self.camera
        camera_x = min(max(camera_x, note.x + note.width - width), note.x)
        camera_y = min(max(camera_y, note.y + note.height - height), note.y)
        self.move_camera(camera_x, camera_y)

    # ── マウス (付箋の上の操作は付箋側で止めるので、ここに来るのは空いている所) ──

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button != 1:
            return
        self._drag = (event.screen_x, event.screen_y, *self.camera)
        self.capture_mouse()

    def on_mouse_move(self, event: events.MouseMove) -> None:
        if self._drag is None:
            return
        start_x, start_y, camera_x, camera_y = self._drag
        # 掴んだボードが手に付いてくるよう、マウスと逆向きにカメラを動かす
        self.move_camera(
            camera_x - (event.screen_x - start_x), camera_y - (event.screen_y - start_y)
        )

    def on_mouse_up(self, event: events.MouseUp) -> None:
        if self._drag is None:
            return
        self._drag = None
        self.release_mouse()

    def _scroll(self, event: events.MouseEvent, dx: int, dy: int) -> None:
        # 外側へ伝わって二重に動かないよう止める
        event.stop()
        camera_x, camera_y = self.camera
        self.move_camera(camera_x + dx * _WHEEL_STEP[0], camera_y + dy * _WHEEL_STEP[1])

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        if event.shift:
            self._scroll(event, 1, 0)
        else:
            self._scroll(event, 0, 1)

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        if event.shift:
            self._scroll(event, -1, 0)
        else:
            self._scroll(event, 0, -1)

    def on_mouse_scroll_right(self, event: events.MouseScrollRight) -> None:
        self._scroll(event, 1, 0)

    def on_mouse_scroll_left(self, event: events.MouseScrollLeft) -> None:
        self._scroll(event, -1, 0)

    def cards(self) -> list[NoteCard]:
        """貼られている付箋 (奥から手前の順)"""
        return list(self.query_children(NoteCard))

    def raise_card(self, card: NoteCard) -> bool:
        """付箋を一番手前に出す (重なり順が変わったら True)"""
        cards = self.cards()
        if not cards or cards[-1] is card:
            return False
        self.move_child(card, after=cards[-1])
        return True
