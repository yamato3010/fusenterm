"""付箋のデータモデル"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

# 付箋の色 (値, 表示名)
# 端末のANSI色だけを使い、ターミナルの配色設定に追従させる。c キーはこの順に切り替える
COLORS: list[tuple[str, str]] = [
    ("yellow", "黄"),
    ("magenta", "桃"),
    ("cyan", "水"),
    ("green", "緑"),
    ("blue", "青"),
    ("red", "赤"),
    ("white", "白"),
]

_COLOR_LABELS = dict(COLORS)
_COLOR_ORDER = [value for value, _ in COLORS]

DEFAULT_COLOR = "yellow"

# ボードの背景 (値, 表示名)。設定画面はこの順に並べる
BACKGROUNDS: list[tuple[str, str]] = [
    ("plain", "無地"),
    ("dots", "ドット"),
    ("grid", "方眼"),
    ("cork", "コルク (粒だけ)"),
    ("cork-filled", "コルク (塗りつぶし)"),
]

DEFAULT_BACKGROUND = "plain"

# 付箋の大きさ (桁・行。枠を含む)
DEFAULT_WIDTH = 24
DEFAULT_HEIGHT = 7
# 枠の内側に1桁×1行は残す
MIN_WIDTH = 8
MIN_HEIGHT = 3


def color_label(color: str) -> str:
    """色の表示名"""
    return _COLOR_LABELS.get(color, color)


def valid_color(color: object) -> str:
    """未知の色は既定色に落とす"""
    return color if isinstance(color, str) and color in _COLOR_LABELS else DEFAULT_COLOR


def next_color(color: str) -> str:
    """次の色 (COLORS の順に一周する)"""
    if color not in _COLOR_ORDER:
        return DEFAULT_COLOR
    return _COLOR_ORDER[(_COLOR_ORDER.index(color) + 1) % len(_COLOR_ORDER)]


def clamp_size(width: int, height: int) -> tuple[int, int]:
    """付箋の大きさを最小値以上に揃える"""
    return max(MIN_WIDTH, width), max(MIN_HEIGHT, height)


# 行頭の markdown の記号 (見出し・箇条書き・引用・チェックボックス)。題名からは外す
_MARKS = re.compile(r"^\s*(?:#+|[-*+]|\d+\.|>)\s+(?:\[[ xX]\]\s+)?")


def note_title(text: str) -> str:
    """付箋の題名 (空でない最初の行から markdown の記号を外したもの)"""
    for line in text.splitlines():
        if line.strip():
            return _MARKS.sub("", line).strip()
    return "(空)"


def _int_of(raw: object, default: int) -> int:
    """保存された数値を取り出す (壊れていれば既定値)"""
    return raw if isinstance(raw, int) and not isinstance(raw, bool) else default


@dataclass
class Note:
    """1枚の付箋

    位置・大きさはボード全体での桁・行で持つ (ボードは無限なので位置はマイナスもある)。
    重なり順は保存時のリストの順 (後ろほど手前) で表すため、付箋自身は持たない。
    """

    text: str
    x: int = 0
    y: int = 0
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    color: str = DEFAULT_COLOR
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict:
        """保存用の辞書にする"""
        return {
            "id": self.id,
            "text": self.text,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "color": self.color,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Note:
        """保存された辞書から復元する

        本文が文字列でない場合だけ ValueError を投げ (呼び出し側でその1枚を
        飛ばす)、位置・大きさ・色は壊れていれば既定値に落とす。
        """
        text = data.get("text")
        if not isinstance(text, str):
            raise ValueError("text が文字列ではありません")
        width, height = clamp_size(
            _int_of(data.get("width"), DEFAULT_WIDTH),
            _int_of(data.get("height"), DEFAULT_HEIGHT),
        )
        return cls(
            text=text,
            x=_int_of(data.get("x"), 0),
            y=_int_of(data.get("y"), 0),
            width=width,
            height=height,
            color=valid_color(data.get("color")),
            id=str(data.get("id") or uuid.uuid4().hex),
        )


@dataclass
class Settings:
    """アプリの設定"""

    shadow: bool = True
    background: str = DEFAULT_BACKGROUND

    def to_dict(self) -> dict:
        """保存用の辞書にする"""
        return {"shadow": self.shadow, "background": self.background}

    @classmethod
    def from_dict(cls, data: dict) -> Settings:
        """保存された辞書から復元する (無い・壊れている項目は既定値に落とす)"""
        shadow = data.get("shadow")
        background = data.get("background")
        if background not in dict(BACKGROUNDS):
            background = DEFAULT_BACKGROUND
        return cls(
            shadow=shadow if isinstance(shadow, bool) else True,
            background=background,
        )
