"""付箋の本文を markdown として描く

付箋は背景に色が付いているため、Rich や Textual の Markdown が使う文字色だと
背景に埋もれて読めない組み合わせが出る。そこで markdown-it でパースした結果を、
色を使わず太字・下線・反転などの装飾だけで Rich の Text にする。
"""

from __future__ import annotations

import re

from markdown_it import MarkdownIt
from markdown_it.token import Token
from rich.cells import cell_len
from rich.text import Text

# 見出しの装飾 (h3 以降は太字だけ)
_HEADING_STYLES = {"h1": "bold underline", "h2": "bold"}

# 行内の装飾 (markdown-it のトークン名 → Rich のスタイル)
_INLINE_STYLES = {"strong": "bold", "em": "italic", "s": "strike", "link": "underline"}

# 箇条書きの先頭の「[ ] 」「[x] 」(チェックボックス)
_TASK = re.compile(r"^\[([ xX])\]\s+")

# 本文にそのまま書かれた URL (markdown のリンクになっていないもの)。
# 「https://example.comです」のように日本語が続いても切れるよう、URL に使える文字だけ拾う。
# 文末の句読点は URL に含めない
_BARE_URL = re.compile(r"https?://[A-Za-z0-9\-._~:/?#@!$&'*+,;=%]*[A-Za-z0-9\-_~/#=%]")


def _parser() -> MarkdownIt:
    """付箋用の markdown パーサ

    HTML は解釈しない (html=False)。`<確認>` のような書き方をタグと見なして
    消してしまうと、書いたはずの本文が読めなくなるため。
    """
    return MarkdownIt("commonmark", {"html": False}).enable("strikethrough")


_PARSER = _parser()


def render_markdown(text: str, width: int) -> Text:
    """本文を markdown として描いた Text を返す (``width`` は区切り線の長さ)"""
    return _Renderer(text, width).render(_PARSER.parse(text))


def split_heading(text: str) -> tuple[str | None, str]:
    """本文が h1 の見出しで始まっていれば (見出しの文字, 残りの本文) に分ける

    付箋の枠の題に見出しを出すため。見出しが無い・空なら (None, 本文) を返す。
    見出しの中の装飾は落として文字だけにする。
    """
    tokens = _PARSER.parse(text)
    if len(tokens) < 2 or tokens[0].type != "heading_open" or tokens[0].tag != "h1":
        return None, text
    title = "".join(
        child.content
        for child in tokens[1].children or []
        if child.type in ("text", "code_inline", "image")
    ).strip()
    if not title or not tokens[0].map:
        return None, text
    # 見出しの行 (「===」で書く見出しなら下線の行まで) を抜いた残り
    rest = text.split("\n")[tokens[0].map[1]:]
    return title, "\n".join(rest)


def extract_links(text: str) -> list[tuple[str, str]]:
    """本文に書かれたリンクを書かれた順に (文字, URL) で返す

    URL をそのまま書いたものや、文字が URL と同じリンクは文字を空にする。
    コードの中の URL はリンクと見なさない。
    """
    links: list[tuple[str, str]] = []
    for token in _PARSER.parse(text):
        if token.type != "inline":
            continue
        href: str | None = None  # リンクの中にいる間はその URL
        label = ""
        for child in token.children or []:
            if child.type == "link_open":
                href = str(child.attrGet("href") or "")
                label = ""
            elif child.type == "link_close" and href is not None:
                label = label.strip()
                links.append(("" if label == href else label, href))
                href = None
            elif href is not None:
                if child.type in ("text", "code_inline", "image"):
                    label += child.content
                elif child.type in ("softbreak", "hardbreak"):
                    label += " "
            elif child.type == "text":
                links.extend(("", url) for url in _BARE_URL.findall(child.content))
    return links


class _Renderer:
    """markdown-it のトークン列を Rich の Text に書き出す

    markdown 本来の規則では単独の改行はつながってしまうが、付箋は短く改行して
    書くものなので、改行はそのまま改行として描く。ブロック同士の間は、元の本文に
    空行があったときだけ空ける (狭い付箋で行を無駄にしないため)。
    """

    def __init__(self, source: str, width: int) -> None:
        self.source_lines = source.split("\n")
        self.out = Text()
        self.width = max(1, width)
        self.quote = 0  # 引用の深さ
        self.indent = ""  # 箇条書きの2行目以降の字下げ
        self.indents: list[str] = []  # 入れ子の箇条書きを抜けたときに戻す字下げ
        self.marker: str | None = None  # 次の行頭に付ける箇条書きの記号 (付けたら消す)
        self.blank = False  # 次の行の前に空行を入れるか

    def render(self, tokens: list[Token]) -> Text:
        heading = ""
        for token in tokens:
            if token.level == 0 and token.nesting != -1 and token.map:
                self._separate(token.map)

            kind = token.type
            if kind == "heading_open":
                heading = _HEADING_STYLES.get(token.tag, "bold")
            elif kind == "heading_close":
                heading = ""
            elif kind == "inline":
                self._inline(token, heading)
            elif kind == "list_item_open":
                # 番号付きなら info に番号、markup に「.」か「)」が入っている
                mark = f"{token.info}{token.markup} " if token.info else "• "
                self.marker = self.indent + mark
                self.indents.append(self.indent)
                self.indent = " " * cell_len(self.marker)
            elif kind == "list_item_close":
                self.indent = self.indents.pop()
                self.marker = None
            elif kind == "blockquote_open":
                self.quote += 1
            elif kind == "blockquote_close":
                self.quote -= 1
            elif kind in ("fence", "code_block"):
                for line in token.content.rstrip("\n").split("\n"):
                    self._new_line()
                    self.out.append(line, style="reverse")
            elif kind == "hr":
                self._new_line()
                self.out.append("─" * max(1, self.width - cell_len(self.indent)), style="dim")
        return self.out

    def _separate(self, lines: list[int]) -> None:
        """元の本文で空行を挟んでいたブロックの前には空行を入れる

        markdown-it の行範囲は箇条書きの後ろの空行まで含むことがあるため、
        範囲同士ではなく、ブロックの直前の行が空かどうかで見る。
        """
        start = lines[0]
        if start > 0 and not self.source_lines[start - 1].strip():
            self.blank = True

    def _new_line(self, marker: str | None = None) -> None:
        """改行して、引用の印と箇条書きの記号 (または字下げ) を書く"""
        if self.out.plain and not self.out.plain.endswith("\n"):
            self.out.append("\n")
        if self.blank and self.out.plain:
            self.out.append("\n")
        self.blank = False
        if self.quote:
            self.out.append("▎ " * self.quote, style="dim")
        if marker is None:
            marker, self.marker = self.marker, None
        self.out.append(marker if marker is not None else self.indent)

    def _inline(self, token: Token, base_style: str) -> None:
        children = list(token.children or [])
        styles = [base_style] if base_style else []

        # 「• [ ] やること」はチェックボックスにする (済んだものは薄くして消し線)
        marker, self.marker = self.marker, None
        if marker and marker.endswith("• ") and children and children[0].type == "text":
            match = _TASK.match(children[0].content)
            if match:
                done = match.group(1) != " "
                marker = marker[: -len("• ")] + ("☑ " if done else "☐ ")
                children[0] = Token("text", "", 0, content=children[0].content[match.end():])
                if done:
                    styles.append("dim strike")
        self._new_line(marker)

        for child in children:
            kind = child.type
            style = " ".join(styles)
            if kind == "text":
                self.out.append(child.content, style=style)
            elif kind in ("softbreak", "hardbreak"):
                self._new_line()
            elif kind == "code_inline":
                self.out.append(child.content, style=f"{style} reverse")
            elif kind == "image":
                # 端末では画像を出せないので代替テキストだけ書く
                self.out.append(child.content or "画像", style=f"{style} underline")
            elif kind.endswith("_open") and kind[:-5] in _INLINE_STYLES:
                styles.append(_INLINE_STYLES[kind[:-5]])
            elif kind.endswith("_close") and kind[:-6] in _INLINE_STYLES:
                styles.pop()
