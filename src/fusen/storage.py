"""付箋の保存・読み込み

付箋は JSON で ``~/.local/share/fusen/notes.json`` に保存する
(``XDG_DATA_HOME`` があればそれに従う)。リストの順が重なり順 (後ろほど手前)。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from .models import Note

log = logging.getLogger(__name__)

APP_DIR_NAME = "fusen"


def data_dir() -> Path:
    """データディレクトリ"""
    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / APP_DIR_NAME


def notes_path() -> Path:
    """付箋ファイルのパス"""
    return data_dir() / "notes.json"


def load_notes() -> list[Note]:
    """付箋を読み込む

    ファイルが無ければ空のリストを返す。読めない・形式が違う場合は
    ``notes.json.broken`` に退避してから空で始める (保存で上書きして失うのを防ぐ)。
    """
    path = notes_path()
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as e:
        log.warning("付箋ファイルを読めないため退避します (%s): %s", path, e)
        _quarantine(path)
        return []

    if not isinstance(data, list):
        log.warning("付箋ファイルの形式が不正なため退避します: %s", path)
        _quarantine(path)
        return []

    notes: list[Note] = []
    for item in data:
        try:
            notes.append(Note.from_dict(item))
        except (AttributeError, TypeError, ValueError) as e:
            log.warning("読み込めない付箋を飛ばします (%r): %s", item, e)
    return notes


def save_notes(notes: list[Note]) -> None:
    """付箋を保存する

    書き込み中に落ちてもファイルが壊れないよう、一時ファイルに書いてから
    置き換える。失敗した場合は OSError を送出する。
    """
    path = notes_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump([n.to_dict() for n in notes], f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def _quarantine(path: Path) -> None:
    """壊れたファイルを退避する (失敗しても起動は続ける)"""
    try:
        path.replace(path.parent / (path.name + ".broken"))
    except OSError as e:
        log.warning("退避に失敗しました: %s", e)
