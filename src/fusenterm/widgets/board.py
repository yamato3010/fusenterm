"""ホワイトボードと、そこに貼る付箋のウィジェット

ボードは無限に広く、画面にはカメラ (ボードの左上に映す位置) から見える範囲だけを
映す。付箋はボードの中に ``position: absolute`` で置き、offset には付箋の位置から
カメラの位置を引いた値を入れる。重なり順はボードの子の並び順 (後ろほど手前) で、
選んだ付箋は最後尾に移して手前に出す。
"""

from __future__ import annotations

from itertools import groupby

from rich.console import Console
from rich.segment import Segment
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.containers import Container
from textual.geometry import Region
from textual.message import Message
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Static

from ..markdown import render_markdown, split_heading
from ..models import COLORS, Note, clamp_size

# 右下の角のつまみ (ここをドラッグすると大きさが変わる)
_GRIP = "◢"

# 選んでいる付箋の右上の角に出す、剥がすボタン
_CLOSE = "×"

# 移動モード・サイズ変更モードのとき枠の題に出す名前
_MODE_LABELS = {"move": "移動", "resize": "サイズ変更"}

# 影を付箋からどれだけずらすか (桁, 行)
_SHADOW_OFFSET = (1, 1)

# 枠と左右の余白で使う桁数 (本文に使える幅を出すため。app.tcss の NoteCard と揃える)
_FRAME_WIDTH = 4

# 枠の上下で使う行数 (本文に使える高さを出すため。app.tcss の NoteCard と揃える)
_FRAME_HEIGHT = 2

# 本文を付箋の幅で折り返すのに使う (折り返しにしか使わないので画面とは別でよい)
_WRAP_CONSOLE = Console()

# ホイール1回でカメラを動かす量 (桁, 行)
_WHEEL_STEP = (4, 2)

# 端末の1文字は縦長 (高さが幅のおよそ2倍) なので、見た目の距離を測るときは行数をこの倍にする
_ROW_ASPECT = 2

# 背景の模様の間隔 (桁, 行)。端末の1文字は縦長なので、桁を行の倍にすると正方形に見える
_DOT_STEP = (4, 2)
_GRID_STEP = (8, 4)

# コルクの粒に使う文字と、粒を置く割合 (256 マスにつきこの数)
_CORK_SPECKS = "·.,'`"
_CORK_DENSITY = 40

# 隣の付箋を探すとき、向きからのずれをどれだけ重く見るか (大きいほど真っ直ぐ先を選ぶ)
_OFF_AXIS_WEIGHT = 2


class CardShadow(Widget):
    """付箋の影 (右下にずらして付箋のすぐ奥に置き、はみ出た所だけが見える)"""


class NoteCard(Static, can_focus=True):
    """ボードに貼られた1枚の付箋

    矢印キー / hjkl でその向きの隣の付箋を選ぶ。m で移動モード、r でサイズ変更モードにすると、
    矢印キー / hjkl で付箋を動かす / 大きさを変える (同じキーか Esc で終わる)。
    マウスでは本体をドラッグで移動、右下の角をドラッグで大きさを変える。
    選んでいる付箋は右上の角が × になり、クリックすると DeleteRequested を送る。
    本文が h1 の見出しで始まっていれば、見出しは本文ではなく枠の題に出す。
    本文が収まらないときは Shift+↑↓ / K J かホイールで本文をスクロールする
    (スクロール位置は保存しない)。
    位置や大きさを変えたら Changed を送り、保存はアプリ側に任せる。
    キーボードで選んだり動かしたりしたら、見えるところまでカメラを動かす。
    """

    BINDING_GROUP_TITLE = "付箋"

    # ドラッグで動かすと本文が範囲選択されてしまうので、選択はさせない
    ALLOW_SELECT = False

    BINDINGS = [
        Binding("left,h", "step(-1, 0)", "左の付箋へ (モード中は左へ動かす / 幅を縮める)", show=False),
        Binding("right,l", "step(1, 0)", "右の付箋へ (モード中は右へ動かす / 幅を広げる)", show=False),
        Binding("up,k", "step(0, -1)", "上の付箋へ (モード中は上へ動かす / 高さを縮める)", show=False),
        Binding("down,j", "step(0, 1)", "下の付箋へ (モード中は下へ動かす / 高さを広げる)", show=False),
        Binding("m", "toggle_mode('move')", "移動モード"),
        Binding("r", "toggle_mode('resize')", "サイズ変更モード"),
        Binding("escape", "end_mode", "モードを終える"),
        Binding("shift+up,K", "scroll_text(-1)", "本文を上へスクロール", show=False),
        Binding("shift+down,J", "scroll_text(1)", "本文を下へスクロール", show=False),
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

    class DeleteRequested(Message):
        """右上の × をクリックした (剥がす確認を開く)"""

        def __init__(self, card: NoteCard) -> None:
            super().__init__()
            self.card = card

    def __init__(self, note: Note) -> None:
        super().__init__()
        self.note = note
        # ドラッグ中の状態: (押した画面上の位置, 押したときの x, y, 幅, 高さ, 大きさを変えるか)
        self._drag: tuple[int, int, int, int, int, int, bool] | None = None
        # 矢印キー / hjkl の使い道: "move" (付箋を動かす), "resize" (大きさを変える),
        # None (隣の付箋を選ぶ)
        self.mode: str | None = None
        # 本文を何行目から見せているか (収まらない本文をスクロールした分)
        self._scroll = 0
        # 枠の題に出している本文の見出し (無ければ None)
        self._heading: str | None = None
        # マウスを押す前から選んでいたか (× が出ていたか)
        self._focused_before_press = False
        # 影はボードの子として、この付箋のすぐ奥に置く (重なり順を付箋と揃えるため)
        self.shadow = CardShadow()
        self.sync()

    def sync(self) -> None:
        """付箋のデータを見た目 (位置・大きさ・色・本文) に反映する"""
        note = self.note
        self.sync_offset()
        self.styles.width = note.width
        self.styles.height = note.height
        self.shadow.styles.width = note.width
        self.shadow.styles.height = note.height
        for value, _ in COLORS:
            self.set_class(note.color == value, f"-{value}")
        self._heading, body = split_heading(note.text)
        self._update_title()
        if not note.text:
            self._scroll = 0
            self.border_subtitle = None
            self.update(Text("(空の付箋)", style="dim"))
            return
        width = note.width - _FRAME_WIDTH
        height = note.height - _FRAME_HEIGHT
        lines = render_markdown(body, width).wrap(_WRAP_CONSOLE, width)
        # 本文や大きさが変わって行き過ぎていたら、最後の行が下端に来る所まで戻す
        self._scroll = max(0, min(self._scroll, len(lines) - height))
        # 上下に隠れている本文があることを下の枠に出す
        above = "▲" if self._scroll > 0 else ""
        below = "▼" if self._scroll + height < len(lines) else ""
        self.border_subtitle = (above + below) or None
        self.update(Text("\n").join(lines[self._scroll : self._scroll + height]))

    def _scroll_text(self, lines: int) -> bool:
        """本文を lines 行スクロールする (動かせる余地が無ければ False)"""
        before = self._scroll
        self._scroll = max(0, self._scroll + lines)
        self.sync()
        return self._scroll != before

    def action_scroll_text(self, lines: int) -> None:
        self._scroll_text(lines)

    def _update_title(self) -> None:
        """枠の題に、モード中ならモードの名前と、本文の見出しを並べて出す"""
        parts = [_MODE_LABELS.get(self.mode or ""), self._heading]
        title = " · ".join(part for part in parts if part)
        # 見出しの文字が markup と見なされないよう Text で渡す
        self.border_title = Text(title) if title else None

    def render_lines(self, crop: Region) -> list[Strip]:
        """枠の右下の角をつまみに、選んでいるときは右上の角を × に置き換える

        枠の題・副題だと角から離れて描かれるため、角の文字を直接書き換える。
        """
        strips = super().render_lines(crop)
        width, height = self.outer_size
        _replace_cell(strips, crop, width - 1, height - 1, _GRIP)
        if self.has_focus:
            _replace_cell(strips, crop, width - 1, 0, _CLOSE)
        return strips

    def sync_offset(self) -> None:
        """付箋の位置とカメラから、画面上の位置を決め直す"""
        camera_x, camera_y = self.parent.camera if isinstance(self.parent, Board) else (0, 0)
        x, y = self.note.x - camera_x, self.note.y - camera_y
        self.styles.offset = (x, y)
        self.shadow.styles.offset = (x + _SHADOW_OFFSET[0], y + _SHADOW_OFFSET[1])

    def on_mount(self) -> None:
        # 作った時点ではボードに付いておらずカメラが分からないので、付いてから決め直す
        self.sync_offset()
        self.parent.mount(self.shadow, before=self)

    def on_unmount(self) -> None:
        # 剥がしたら影も消す
        self.shadow.remove()

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

    def on_blur(self) -> None:
        # ほかの付箋を選んだらモードは終わり
        self._set_mode(None)

    # ── 移動モード・サイズ変更モード ──────────

    def _set_mode(self, mode: str | None) -> None:
        self.mode = mode
        self.set_class(mode == "move", "-moving")
        self.set_class(mode == "resize", "-resizing")
        self._update_title()
        # フッターの Esc の表示を切り替える
        self.refresh_bindings()

    def action_toggle_mode(self, mode: str) -> None:
        # 別のモードのキーを押したら、そちらのモードに切り替える
        self._set_mode(None if self.mode == mode else mode)

    def action_end_mode(self) -> None:
        self._set_mode(None)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # モード中でないときの Esc は付箋では使わない (アプリの Esc に回す)
        if action == "end_mode":
            return self.mode is not None
        return True

    def action_step(self, dx: int, dy: int) -> None:
        """モードに応じて、付箋を動かす・大きさを変える・その向きの隣の付箋を選ぶ"""
        if self.mode == "move":
            self._move(dx, dy)
        elif self.mode == "resize":
            self._resize(dx, dy)
        elif isinstance(self.parent, Board):
            neighbor = self.parent.neighbor(self, dx, dy)
            if neighbor is not None:
                neighbor.focus()

    # ── 位置・大きさ ────────────────────────

    def _place(self, x: int, y: int, width: int, height: int) -> None:
        """大きさを最小値以上に揃えてから位置・大きさを変える"""
        note = self.note
        note.width, note.height = clamp_size(width, height)
        note.x, note.y = x, y
        self.sync()

    def _move(self, dx: int, dy: int) -> None:
        note = self.note
        self._place(note.x + dx, note.y + dy, note.width, note.height)
        self._reveal()
        self.post_message(self.Changed(self))

    def _resize(self, dw: int, dh: int) -> None:
        note = self.note
        self._place(note.x, note.y, note.width + dw, note.height + dh)
        self._reveal()
        self.post_message(self.Changed(self))

    def _reveal(self) -> None:
        if isinstance(self.parent, Board):
            self.parent.reveal(self)

    # ── マウス ──────────────────────────────

    def focus_on_click(self) -> bool:
        # マウスを押すと on_mouse_down より先に選ばれてしまうので、その前の状態を覚えておく
        self._focused_before_press = self.has_focus
        return super().focus_on_click()

    def on_mouse_down(self, event: events.MouseDown) -> None:
        if event.button != 1:
            return
        event.stop()
        # 右上の × (選んでいるときだけ出ている) を押したら剥がす
        if self._focused_before_press and event.y == 0 and event.x >= self.outer_size.width - 2:
            self.post_message(self.DeleteRequested(self))
            return
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

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        # 本文をスクロールできないとき (Shift 付き・下端まで見えている) はボードを動かす
        if not event.shift and self._scroll_text(1):
            event.stop()

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        if not event.shift and self._scroll_text(-1):
            event.stop()

    def on_click(self, event: events.Click) -> None:
        # ボードのダブルクリック (付箋の追加) まで届かないように止める
        event.stop()
        if event.chain == 2:
            self.post_message(self.EditRequested(self))


def _replace_cell(strips: list[Strip], crop: Region, x: int, y: int, char: str) -> None:
    """描いた行の (x, y) の1文字を、元の文字の色のまま char に置き換える"""
    if not crop.contains(x, y):
        return
    row = y - crop.y
    x -= crop.x
    strip = strips[row]
    cell = strip.crop(x, x + 1)
    style = next((segment.style for segment in cell if segment.text), None)
    strips[row] = Strip.join([strip.crop(0, x), Strip([Segment(char, style)], 1), strip.crop(x + 1)])


def _cell_hash(x: int, y: int) -> int:
    """ボード上の位置ごとに決まった 32 ビットの値 (スクロールしても模様が同じ所に出るように)"""
    h = (x * 374761393 + y * 668265263) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return h ^ (h >> 16)


def _pattern_cell(background: str, x: int, y: int) -> tuple[str, str | None]:
    """背景の模様の、ボード上の (x, y) の文字と色の種類 (app.tcss の board--* の名前)"""
    if background == "dots":
        if x % _DOT_STEP[0] == 0 and y % _DOT_STEP[1] == 0:
            return "·", "board--pattern"
    elif background == "grid":
        on_column = x % _GRID_STEP[0] == 0
        on_row = y % _GRID_STEP[1] == 0
        if on_column and on_row:
            return "┼", "board--pattern"
        if on_row:
            return "─", "board--pattern"
        if on_column:
            return "│", "board--pattern"
    elif background in ("cork", "cork-filled"):
        h = _cell_hash(x, y)
        if h & 0xFF < _CORK_DENSITY:
            char = _CORK_SPECKS[(h >> 8) % len(_CORK_SPECKS)]
            return char, "board--speck-alt" if h & 0x10000 else "board--speck"
    return " ", None


class Board(Container):
    """付箋を貼るホワイトボード (無限に広い)

    空いている所をドラッグするとカメラが動く (ホイールでも動く。Shift+ホイールで左右)。
    空いている所をダブルクリックすると、その位置への追加を AddRequested で知らせる。
    背景の模様はボード上の位置に描くので、カメラと一緒に動く。
    """

    # 背景の模様の色 (app.tcss で決める)
    COMPONENT_CLASSES = {"board--pattern", "board--speck", "board--speck-alt"}

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
        # 背景の模様 (models.BACKGROUNDS の値)
        self._background = "plain"

    # ── 見た目の設定 ────────────────────────

    def set_background(self, background: str) -> None:
        """背景の模様を変える (塗りつぶしの色は app.tcss の -bg-* のクラスで付ける)"""
        self.remove_class(f"-bg-{self._background}")
        self._background = background
        self.add_class(f"-bg-{background}")
        self.refresh()

    def set_shadow(self, shadow: bool) -> None:
        """付箋の影を出すかどうか"""
        self.set_class(not shadow, "-no-shadow")

    def render_line(self, y: int) -> Strip:
        """背景の模様を、カメラの位置に合わせて1行ずつ描く"""
        if self._background == "plain":
            return super().render_line(y)
        width = self.content_size.width
        camera_x, camera_y = self.camera
        cells = [_pattern_cell(self._background, camera_x + x, camera_y + y) for x in range(width)]
        base = self.rich_style
        # 同じ色の文字が続く所はまとめて1つの Segment にする
        segments = []
        for kind, run in groupby(cells, key=lambda cell: cell[1]):
            style = base if kind is None else base + self.get_component_rich_style(kind, partial=True)
            segments.append(Segment("".join(char for char, _ in run), style))
        return Strip(segments, width)

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
        # 背景の模様もカメラと一緒に動かす
        if self._background != "plain":
            self.refresh()

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

    def neighbor(self, card: NoteCard, dx: int, dy: int) -> NoteCard | None:
        """付箋から見て (dx, dy) の向きにある一番近い付箋 (無ければ None)

        付箋の中心どうしで比べる。向きに沿って先にあるものだけを候補にし、
        向きからのずれは重く見る (斜め遠くより、真っ直ぐ先を選びやすくする)。
        """

        def center(c: NoteCard) -> tuple[float, float]:
            note = c.note
            return note.x + note.width / 2, (note.y + note.height / 2) * _ROW_ASPECT

        from_x, from_y = center(card)
        best: NoteCard | None = None
        best_score = 0.0
        for other in self.cards():
            if other is card:
                continue
            to_x, to_y = center(other)
            along = (to_x - from_x) * dx + (to_y - from_y) * dy
            if along <= 0:
                continue
            off_axis = abs((to_x - from_x) * dy) + abs((to_y - from_y) * dx)
            score = along + off_axis * _OFF_AXIS_WEIGHT
            if best is None or score < best_score:
                best, best_score = other, score
        return best

    def cards(self) -> list[NoteCard]:
        """貼られている付箋 (奥から手前の順)"""
        return list(self.query_children(NoteCard))

    def raise_card(self, card: NoteCard) -> bool:
        """付箋を一番手前に出す (重なり順が変わったら True)"""
        cards = self.cards()
        if not cards or cards[-1] is card:
            return False
        self.move_child(card, after=cards[-1])
        self.move_child(card.shadow, before=card)
        return True
