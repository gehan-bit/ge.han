"""구글 문서(Docs API JSON) → Post.

원고 문서의 규칙(1~12주차 탭 기준):
  - 첫 줄 "[제목] ..."  → 제목
  - 둘째 줄 "[태그] #a #b" → 태그
  - HEADING_* 문단 → 소제목
  - 인라인 이미지 → 사진 자리(slot)
  - 빈 줄로 나뉜 연속 문단 → paragraph 블록 한 개(여러 줄)
  - "※"로 시작하거나 9pt 회색 글씨 문단 → note(회색 작은 글씨)
  - 표 → table 블록
JSON은 Docs API `documents.get`(includeTabsContent) 결과와 같은 형태다. 클로드 커넥터 read_doc 결과도 같다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterator

from .model import Block, Line, Post, Run

TITLE_RE = re.compile(r"^\s*\[제목\]\s*(.+?)\s*$")
TAGS_RE = re.compile(r"^\s*\[태그\]\s*(.+?)\s*$")


# ---------- 탭 찾기 ----------
def iter_tabs(doc: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """모든 탭을 깊이 우선으로 순회한다(하위 탭 포함)."""
    for tab in doc.get("tabs", []):
        yield tab
        for child in tab.get("childTabs", []) or []:
            yield child
            for grand in child.get("childTabs", []) or []:
                yield grand


def tab_title(tab: dict[str, Any]) -> str:
    return tab.get("tabProperties", {}).get("title", "")


def tab_id(tab: dict[str, Any]) -> str:
    return tab.get("tabProperties", {}).get("tabId", "")


def find_tab(doc: dict[str, Any], key: str) -> dict[str, Any]:
    """탭 제목(정확히 또는 부분 일치) 또는 tabId로 탭을 찾는다."""
    tabs = list(iter_tabs(doc))
    for t in tabs:
        if tab_id(t) == key or tab_title(t) == key:
            return t
    for t in tabs:
        if key in tab_title(t):
            return t
    names = ", ".join(tab_title(t) for t in tabs)
    raise KeyError(f"탭을 찾지 못했습니다: {key!r}. 있는 탭: {names}")


def list_tabs(doc: dict[str, Any]) -> list[tuple[str, str]]:
    return [(tab_title(t), tab_id(t)) for t in iter_tabs(doc)]


# ---------- 문단 해석 ----------
def _is_grey(ts: dict[str, Any]) -> bool:
    rgb = ts.get("foregroundColor", {}).get("color", {}).get("rgbColor")
    if not rgb:
        return False
    r, g, b = rgb.get("red", 0), rgb.get("green", 0), rgb.get("blue", 0)
    return abs(r - g) < 0.05 and abs(g - b) < 0.05 and 0.3 < r < 0.8


def _font_pt(ts: dict[str, Any]) -> float | None:
    fs = ts.get("fontSize")
    return fs.get("magnitude") if fs else None


def _runs_of(paragraph: dict[str, Any]) -> tuple[Line, list[str], bool]:
    """문단의 elements → (runs, inline_object_ids, looks_like_note)."""
    runs: Line = []
    images: list[str] = []
    small_grey = False
    for el in paragraph.get("elements", []):
        if "inlineObjectElement" in el:
            images.append(el["inlineObjectElement"]["inlineObjectId"])
            continue
        tr = el.get("textRun")
        if not tr:
            continue
        text = tr.get("content", "")
        ts = tr.get("textStyle", {}) or {}
        if text.strip():
            pt = _font_pt(ts)
            if _is_grey(ts) and pt is not None and pt <= 9.5:
                small_grey = True
        link = (ts.get("link") or {}).get("url")
        runs.append(Run(text=text, bold=bool(ts.get("bold")), link=link))
    return runs, images, small_grey


def _merge_runs(runs: Line) -> Line:
    merged: Line = []
    for r in runs:
        if merged and merged[-1].bold == r.bold and merged[-1].link == r.link:
            merged[-1] = Run(merged[-1].text + r.text, r.bold, r.link)
        else:
            merged.append(Run(r.text, r.bold, r.link))
    return merged


def _strip_line(runs: Line) -> Line:
    """줄 끝 개행 제거, 공백만 남은 run 정리. 시작/끝 공백은 보존하지 않는다."""
    out: Line = []
    for r in runs:
        out.append(Run(r.text.replace("\n", ""), r.bold, r.link))
    # 앞뒤 공백 제거(첫 run 앞, 마지막 run 뒤)
    if out:
        out[0] = Run(out[0].text.lstrip(), out[0].bold, out[0].link)
        out[-1] = Run(out[-1].text.rstrip(), out[-1].bold, out[-1].link)
    return [r for r in _merge_runs(out) if r.text != ""]


def _table_rows(table: dict[str, Any]) -> list[list[str]]:
    rows: list[list[str]] = []
    for tr in table.get("tableRows", []):
        cells: list[str] = []
        for tc in tr.get("tableCells", []):
            texts: list[str] = []
            for c in tc.get("content", []):
                p = c.get("paragraph")
                if not p:
                    continue
                texts.append("".join(e.get("textRun", {}).get("content", "") for e in p.get("elements", [])))
            cells.append(" ".join(t.strip() for t in texts if t.strip()).strip())
        rows.append(cells)
    return rows


# ---------- 메인 ----------
def parse_tab(doc: dict[str, Any], tab: dict[str, Any]) -> Post:
    dt = tab.get("documentTab", {})
    body = dt.get("body", {}).get("content", [])
    inline_objects = dt.get("inlineObjects", {}) or {}

    title = ""
    tags: list[str] = []
    blocks: list[Block] = []
    current: list[Line] = []
    current_note = False
    slot = 0

    def flush() -> None:
        nonlocal current, current_note
        if current:
            blocks.append(Block(kind="paragraph", lines=current, note=current_note))
        current = []
        current_note = False

    for el in body:
        if "table" in el:
            flush()
            blocks.append(Block(kind="table", rows=_table_rows(el["table"])))
            continue
        if "sectionBreak" in el:
            continue
        p = el.get("paragraph")
        if not p:
            continue
        style = (p.get("paragraphStyle") or {}).get("namedStyleType", "NORMAL_TEXT")
        runs, images, small_grey = _runs_of(p)
        text = "".join(r.text for r in runs).strip()

        if not title and (m := TITLE_RE.match(text)):
            title = m.group(1)
            continue
        if not tags and (m := TAGS_RE.match(text)):
            tags = [t.lstrip("#") for t in m.group(1).split() if t.strip("#")]
            continue

        if images:
            flush()
            for oid in images:
                emb = inline_objects.get(oid, {}).get("inlineObjectProperties", {}).get("embeddedObject", {})
                size = emb.get("size", {})
                blocks.append(
                    Block(
                        kind="image",
                        slot=slot,
                        meta={
                            "doc_object_id": oid,
                            "doc_uri": emb.get("imageProperties", {}).get("contentUri"),
                            "doc_size": [size.get("width", {}).get("magnitude"), size.get("height", {}).get("magnitude")],
                        },
                    )
                )
                slot += 1
            if text:
                # 이미지와 같은 문단에 글이 있으면 이어서 처리
                pass
            else:
                continue

        if style.startswith("HEADING") or style == "TITLE":
            flush()
            if text:
                blocks.append(Block(kind="heading", text=text))
            continue

        if not text:
            flush()
            continue

        line = _strip_line(runs)
        is_note = text.startswith("※") or small_grey
        # 링크만 있는 줄 → link 블록
        if len(line) == 1 and line[0].link and re.match(r"^https?://\S+$", text):
            flush()
            blocks.append(Block(kind="link", url=line[0].link))
            continue
        if current and is_note != current_note:
            flush()
        current.append(line)
        current_note = current_note or is_note
    flush()

    if not title:
        title = tab_title(tab)
    return Post(
        title=title,
        tags=tags,
        blocks=blocks,
        source={"doc_id": doc.get("documentId"), "doc_title": doc.get("title"), "tab_id": tab_id(tab), "tab_title": tab_title(tab)},
    )


def load_doc_json(path: Path | str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    # 커넥터 결과 파일은 {"content": {...}} 로 감싸져 있을 수 있다
    if "tabs" not in data and "content" in data and isinstance(data["content"], dict):
        data = data["content"]
    return data


def parse_doc_file(path: Path | str, tab_key: str) -> Post:
    doc = load_doc_json(path)
    return parse_tab(doc, find_tab(doc, tab_key))
