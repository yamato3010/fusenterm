"""縮小表示 (ボード全体を1画面に縮めて見渡し、行きたい所へ飛ぶ)"""

from __future__ import annotations

from typing import Optional, Union

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static

from ..models import COLORS, Note, note_title

# hjkl 1回で枠を動かす量 (縮小した画面での桁, 行)
_FRAME_STEP = (2, 1)

# 縮小した付箋の最小の幅 (題名の頭の数文字は読めるように)
_MIN_CARD_WIDTH = 6


class MiniCard(Static, can_focus=True):
    """縮小表示の付箋 (題名だけを描く)"""

    def __init__(self, note: Note) -> None:
        super().__init__(Text(note_title(note.text)))
        self.note = note
        for value, _ in COLORS:
            self.set_class(note.color == value, f"-{value}")


class OverviewScreen(ModalScreen[Optional[Union[str, tuple[int, int]]]]):
    """ボード全体を縮めて見せる

    付箋を選んで飛ぶなら付箋の id を、枠を動かして飛ぶならカメラの位置を、
    何もせずに戻るなら None を返す。
    """

    BINDINGS = [
        Binding("left,h", "move_frame(-1, 0)", "枠を左へ", show=False),
        Binding("right,l", "move_frame(1, 0)", "枠を右へ", show=False),
        Binding("up,k", "move_frame(0, -1)", "枠を上へ", show=False),
        Binding("down,j", "move_frame(0, 1)", "枠を下へ", show=False),
        Binding("enter", "jump", "飛ぶ"),
        Binding("escape,z", "cancel", "戻る"),
    ]

    def __init__(
        self, notes: list[Note], camera: tuple[int, int], view_size: tuple[int, int]
    ) -> None:
        super().__init__()
        self._notes = notes
        self._camera = camera
        self._view_size = view_size
        # 縮小の倍率と、縮小した画面の左上に当たるボード全体での位置 (_fit で決める)
        self._scale = 1.0
        self._origin = (0.0, 0.0)

    def compose(self) -> ComposeResult:
        with Container(id="overview") as box:
            box.border_title = f"縮小表示  {len(self._notes)}枚"
            box.border_subtitle = (
                "hjkl 枠を動かす   Tab 付箋を選ぶ   Enter / クリック 飛ぶ   Esc 戻る"
            )
            # 枠は付箋の奥に置く (枠の内側が付箋を隠さないように)
            yield Static(id="overview-frame")
            for note in self._notes:
                yield MiniCard(note)

    def on_mount(self) -> None:
        self.call_after_refresh(self._fit)

    def on_resize(self, event: events.Resize) -> None:
        self.call_after_refresh(self._fit)

    # ── 縮小 ────────────────────────────────

    def _area(self) -> tuple[int, int]:
        size = self.query_one("#overview").content_size
        return max(1, size.width), max(1, size.height)

    def _fit(self) -> None:
        """付箋と今見ている範囲が全部収まるよう、倍率を決めて並べ直す

        周りに画面半分ずつの余白を足して、付箋の無い所へも枠を動かせるようにする。
        """
        view_w, view_h = self._view_size
        rects = [(n.x, n.y, n.width, n.height) for n in self._notes]
        rects.append((*self._camera, view_w, view_h))
        left = min(x for x, _, _, _ in rects) - view_w / 2
        top = min(y for _, y, _, _ in rects) - view_h / 2
        right = max(x + w for x, _, w, _ in rects) + view_w / 2
        bottom = max(y + h for _, y, _, h in rects) + view_h / 2

        area_w, area_h = self._area()
        # 桁と行で同じ倍率にする (付箋の形を崩さない)
        scale = max((right - left) / area_w, (bottom - top) / area_h, 1.0)
        self._scale = scale
        # 余った分は両側に振り分けて真ん中に寄せる
        self._origin = (
            left - (area_w * scale - (right - left)) / 2,
            top - (area_h * scale - (bottom - top)) / 2,
        )

        for card in self.query(MiniCard):
            note = card.note
            card.styles.offset = self._to_map(note.x, note.y)
            card.styles.width = max(_MIN_CARD_WIDTH, round(note.width / scale))
            card.styles.height = max(1, round(note.height / scale))
        frame = self.query_one("#overview-frame")
        frame.styles.width = max(2, round(view_w / scale))
        frame.styles.height = max(2, round(view_h / scale))
        self._sync_frame()

    def _to_map(self, x: float, y: float) -> tuple[int, int]:
        """ボード全体での位置 → 縮小した画面での位置"""
        origin_x, origin_y = self._origin
        return round((x - origin_x) / self._scale), round((y - origin_y) / self._scale)

    def _from_map(self, x: int, y: int) -> tuple[int, int]:
        """縮小した画面での位置 → ボード全体での位置"""
        origin_x, origin_y = self._origin
        return round(origin_x + x * self._scale), round(origin_y + y * self._scale)

    def _sync_frame(self) -> None:
        self.query_one("#overview-frame").styles.offset = self._to_map(*self._camera)

    # ── 操作 ────────────────────────────────

    def action_move_frame(self, dx: int, dy: int) -> None:
        """今見ている範囲の枠を動かす (縮小した画面からははみ出さない)"""
        # 枠を動かしたら、Enter は付箋ではなく枠の位置へ飛ぶ
        self.set_focus(None)
        area_w, area_h = self._area()
        view_w, view_h = self._view_size
        origin_x, origin_y = self._origin
        camera_x = self._camera[0] + round(dx * _FRAME_STEP[0] * self._scale)
        camera_y = self._camera[1] + round(dy * _FRAME_STEP[1] * self._scale)
        camera_x = max(origin_x, min(camera_x, origin_x + area_w * self._scale - view_w))
        camera_y = max(origin_y, min(camera_y, origin_y + area_h * self._scale - view_h))
        self._camera = (round(camera_x), round(camera_y))
        self._sync_frame()

    def action_jump(self) -> None:
        focused = self.focused
        if isinstance(focused, MiniCard):
            self.dismiss(focused.note.id)
        else:
            self.dismiss(self._camera)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_click(self, event: events.Click) -> None:
        """付箋をクリックしたらその付箋へ、空いている所ならそこを真ん中にして飛ぶ"""
        if isinstance(event.widget, MiniCard):
            self.dismiss(event.widget.note.id)
            return
        offset = event.get_content_offset(self.query_one("#overview"))
        if offset is None:
            return
        x, y = self._from_map(offset.x, offset.y)
        view_w, view_h = self._view_size
        self.dismiss((x - view_w // 2, y - view_h // 2))
