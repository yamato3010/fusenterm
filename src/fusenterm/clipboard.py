"""リンク付きの文字列を貼り付けたときに markdown のリンクにする

端末の貼り付け (ペースト) で届くのはプレーンテキストだけなので、Teams やブラウザから
コピーしたリンク付きの文字列は URL か文字だけになってしまう。クリップボードには
同じ内容の HTML も入っているので、それを読んで ``[文字](URL)`` の形に直す。

クリップボードを直接読めるのは macOS だけ (osascript)。他の環境や、読めなかった
場合は端末から届いたテキストをそのまま貼る。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from html.parser import HTMLParser

log = logging.getLogger(__name__)

# クリップボードのプレーンテキストと HTML を JSON で返す (無い方は null)
_READ_CLIPBOARD = """
ObjC.import("AppKit");
const pb = $.NSPasteboard.generalPasteboard;
const read = (type) => { const s = pb.stringForType(type); return s.isNil() ? null : s.js; };
JSON.stringify({text: read("public.utf8-plain-text"), html: read("public.html")});
"""

# クリップボードの読み取りを待つ上限 (秒)。超えたら届いたテキストをそのまま貼る
_TIMEOUT = 2

# 改行として扱う (前後で行が変わる) タグ
_BLOCK_TAGS = {
    "p", "div", "li", "tr", "ul", "ol", "table", "pre", "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6",
}

# 中身を本文として扱わないタグ
_SKIP_TAGS = {"script", "style", "head", "title"}


async def markdown_from_paste(pasted: str) -> str | None:
    """貼り付けたテキストをリンク入りの markdown にしたもの (できなければ None)

    クリップボードのプレーンテキストが ``pasted`` と一致するときだけ HTML を使う
    (別の経路で貼られたテキストに、たまたま残っていた HTML を混ぜないため)。
    """
    clip = await _read_clipboard()
    if clip is None:
        return None
    text, html = clip
    if not html or text is None or _normalize(text) != _normalize(pasted):
        return None
    return html_to_markdown(html)


def html_to_markdown(html: str) -> str | None:
    """HTML のリンクを ``[文字](URL)`` にしたテキスト (リンクが無ければ None)

    リンク以外の装飾は落とし、段落・改行・箇条書きだけ残す。
    """
    parser = _HtmlToMarkdown()
    parser.feed(html)
    parser.close()
    if not parser.has_link:
        return None
    text = "".join(parser.out)
    # 行頭・行末の空白を落とし、続いた空行は1つにまとめる
    text = "\n".join(line.strip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _normalize(text: str) -> str:
    """改行コードと前後の空白の違いを無視して比べるための形"""
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _link(text: str, href: str) -> str:
    """markdown のリンク (文字が無いか URL そのものなら URL だけ)"""
    text = " ".join(text.split())
    if not text or text == href:
        return href
    text = text.replace("[", r"\[").replace("]", r"\]")
    href = href.replace(" ", "%20").replace("(", "%28").replace(")", "%29")
    return f"[{text}]({href})"


class _HtmlToMarkdown(HTMLParser):
    """HTML を読みながら、リンクを markdown にしたテキストを out に貯める"""

    def __init__(self) -> None:
        super().__init__()
        self.out: list[str] = []
        self.has_link = False
        self._skip = 0  # script などの中にいる深さ
        self._pre = 0  # pre の中 (空白をそのまま残す) にいる深さ
        self._href: str | None = None  # 開いているリンクの URL
        self._link_text: list[str] = []  # 開いているリンクの文字

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag == "a":
            href = dict(attrs).get("href")
            if href and not href.startswith("#"):
                self._href = href.strip()
                self._link_text = []
        elif tag == "br":
            self._write("\n")
        elif tag in _BLOCK_TAGS:
            if tag == "pre":
                self._pre += 1
            self._write("\n- " if tag == "li" else "\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag == "a" and self._href is not None:
            href, self._href = self._href, None
            self.out.append(_link("".join(self._link_text), href))
            self.has_link = True
        elif tag in _BLOCK_TAGS:
            if tag == "pre":
                self._pre = max(0, self._pre - 1)
            # 項目の区切りは次の li の「- 」の前の改行で足りる (空行を挟まない)
            if tag != "li":
                self._write("\n")

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        # HTML では改行やタブも1つの空白として扱われる (pre の中は除く)
        self._write(data if self._pre else re.sub(r"\s+", " ", data))

    def _write(self, text: str) -> None:
        if self._href is not None:
            self._link_text.append(text)
        else:
            self.out.append(text)


async def _read_clipboard() -> tuple[str | None, str | None] | None:
    """クリップボードの (プレーンテキスト, HTML)。読めなければ None"""
    if sys.platform != "darwin":
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-l", "JavaScript", "-e", _READ_CLIPBOARD,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError as e:
        log.warning("クリップボードを読めません: %s", e)
        return None
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), _TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        log.warning("クリップボードの読み取りが時間切れになりました")
        return None
    try:
        data = json.loads(out)
    except ValueError as e:
        log.warning("クリップボードの内容を解釈できません: %s", e)
        return None
    return data.get("text"), data.get("html")
