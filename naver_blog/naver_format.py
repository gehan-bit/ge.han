"""네이버 작성 원칙 적용.

원칙 문서(원더바레 행사 블로그 작성 원칙｜네이버)에서 서식에 해당하는 부분만 자동화한다.
  - 가운데 정렬, 한 줄 약 25~30자, 문단 2~3줄   → 긴 줄만 뜻이 나뉘는 곳에서 다시 줄바꿈
  - 소제목 앞 구분선, 소제목은 큰 글씨 굵게      → heading 앞에 hr 블록 삽입
  - ※ 문구는 작은 회색 글씨                      → note 블록 그대로
  - 맨 아래 공식 채널 링크(미리보기 카드)         → settings의 footer 링크 추가
  - 태그 10~15개                                  → 15개 초과분 제거
글의 단어는 바꾸지 않는다. 줄바꿈과 블록 구조만 손본다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from .model import Block, Line, Post, Run, line_text

# 줄바꿈 우선순위: 문장 끝 > 쉼표/가운뎃점 뒤 > 띄어쓰기
SENTENCE_END = set(".?!。」』”’)]…")
CLAUSE_END = set(",、·:;")
WRAP_TOLERANCE = 4
NO_WRAP_PREFIXES = ("http://", "https://", "□", "✔", "☑", "①", "②", "③", "④", "⑤", "→", "예:", "예 :")


@dataclass
class FormatOptions:
    max_line: int = 30          # 한 줄 최대 글자 수(공백 포함)
    min_line: int = 16          # 이보다 짧게는 자르지 않음
    wrap: bool = True           # False면 원고 줄바꿈 그대로
    hr_before_heading: bool = True
    max_tags: int = 15
    min_tags: int = 10
    footer_links: list[str] = field(default_factory=list)   # 맨 아래 링크 카드 URL들
    closing_lines: list[str] = field(default_factory=list)  # 공감·댓글 청하는 한 줄 등(비우면 생략)
    extra_tags: list[str] = field(default_factory=list)     # 태그가 10개 미만일 때 채울 후보


# ---------- 줄바꿈 ----------
def _flatten(line: Line) -> list[tuple[str, bool, str | None]]:
    out = []
    for r in line:
        for ch in r.text:
            out.append((ch, r.bold, r.link))
    return out


def _rebuild(chars: list[tuple[str, bool, str | None]]) -> Line:
    line: Line = []
    for ch, bold, link in chars:
        if line and line[-1].bold == bold and line[-1].link == link:
            line[-1] = Run(line[-1].text + ch, bold, link)
        else:
            line.append(Run(ch, bold, link))
    # 앞뒤 공백 정리
    if line:
        line[0] = Run(line[0].text.lstrip(), line[0].bold, line[0].link)
        line[-1] = Run(line[-1].text.rstrip(), line[-1].bold, line[-1].link)
    return [r for r in line if r.text]


OPEN_Q = {"‘": "’", "“": "”", "(": ")", "「": "」", "『": "』", "[": "]", "《": "》"}
CLOSE_Q = set(OPEN_Q.values())


def _depths(text: str) -> list[int]:
    """각 위치에서 열린 따옴표/괄호 깊이. 따옴표 안에서는 줄을 바꾸지 않기 위해 쓴다."""
    depth = 0
    out = []
    for ch in text:
        if ch in OPEN_Q:
            depth += 1
            out.append(depth)
        elif ch in CLOSE_Q:
            out.append(depth)
            depth = max(0, depth - 1)
        else:
            out.append(depth)
    return out


def _best_break(text: str, lo: int, hi: int) -> int | None:
    """text 안에서 가장 좋은 줄바꿈 위치(그 위치 앞까지가 첫 줄)를 고른다.

    후보: 띄어쓰기 자리(깊이 0, 따옴표·괄호 밖). 첫 줄 길이는 lo 이상 hi 이하, 뒷부분도 8자 이상.
    점수: 문장 끝 3 > 쉼표 뒤 2 > 띄어쓰기 1, 여기에 앞뒤 균형 가산.
    """
    n = len(text)
    depths = _depths(text)
    best: tuple[float, int] | None = None
    for allow_depth in (False, True):
        for pos in range(lo, min(hi, n - 1) + 1):
            if text[pos] != " ":
                continue
            if not allow_depth and depths[pos] > 0:
                continue
            rest = len(text[pos:].strip())
            if rest < 8:
                continue
            prev = text[pos - 1]
            score = 3.0 if prev in SENTENCE_END else 2.0 if prev in CLAUSE_END else 1.0
            imbalance = abs(pos - (n - pos)) / n  # 0(균형)~1
            score -= imbalance * 2.5
            if best is None or score > best[0]:
                best = (score, pos)
        if best is not None:
            break
    return best[1] if best else None


def wrap_line(line: Line, max_line: int, min_line: int) -> list[Line]:
    text = line_text(line)
    # 기준은 약 25~30자. 조금 넘는 줄(최대 +4자)은 억지로 자르지 않는다.
    if len(text) <= max_line + WRAP_TOLERANCE or text.startswith(NO_WRAP_PREFIXES):
        return [line]
    chars = _flatten(line)
    pos = _best_break(text, min_line, max_line)
    if pos is None:
        # 띄어쓰기가 없는 긴 줄은 그대로 둔다
        return [line]
    first = _rebuild(chars[:pos])
    rest = _rebuild(chars[pos:])
    return [first] + wrap_line(rest, max_line, min_line)


def wrap_block(block: Block, opts: FormatOptions) -> Block:
    if block.kind not in ("paragraph", "quote") or not opts.wrap:
        return block
    new_lines: list[Line] = []
    for line in block.lines:
        new_lines.extend(wrap_line(line, opts.max_line, opts.min_line))
    block.lines = new_lines
    return block


# ---------- 태그 ----------
def normalize_tags(tags: Iterable[str], opts: FormatOptions) -> list[str]:
    seen: list[str] = []
    for t in tags:
        t = re.sub(r"\s+", "", t.strip().lstrip("#"))
        if t and t not in seen:
            seen.append(t)
    for t in opts.extra_tags:
        if len(seen) >= opts.min_tags:
            break
        t = t.strip().lstrip("#")
        if t and t not in seen:
            seen.append(t)
    return seen[: opts.max_tags]


# ---------- 전체 ----------
def apply(post: Post, opts: FormatOptions) -> Post:
    blocks: list[Block] = []
    for b in post.blocks:
        if b.kind == "heading" and opts.hr_before_heading:
            if not blocks or blocks[-1].kind != "hr":
                blocks.append(Block(kind="hr"))
        blocks.append(wrap_block(b, opts))

    # 마무리 줄(공감·댓글 청하는 한 줄 등): 마지막 link 블록들 앞에 넣는다
    if opts.closing_lines:
        idx = len(blocks)
        while idx > 0 and blocks[idx - 1].kind in ("link", "hr"):
            idx -= 1
        closing = Block(kind="paragraph", lines=[[Run(t)] for t in opts.closing_lines])
        blocks.insert(idx, closing)

    existing = {b.url.rstrip("/") for b in blocks if b.kind == "link"}
    for url in opts.footer_links:
        if url.rstrip("/") not in existing:
            blocks.append(Block(kind="link", url=url))

    post.blocks = blocks
    post.tags = normalize_tags(post.tags, opts)
    return post


def lint(post: Post, opts: FormatOptions) -> list[str]:
    """발행 전 체크리스트 중 기계로 확인할 수 있는 항목."""
    issues: list[str] = []
    if not (opts.min_tags <= len(post.tags) <= opts.max_tags):
        issues.append(f"태그 {len(post.tags)}개 (기준 {opts.min_tags}~{opts.max_tags}개)")
    long_lines = [t for b in post.blocks if b.kind in ("paragraph", "quote") for t in b.plain_lines() if len(t) > opts.max_line + 4 and not t.startswith(NO_WRAP_PREFIXES)]
    if long_lines:
        issues.append(f"{opts.max_line}자를 크게 넘는 줄 {len(long_lines)}개: " + " / ".join(l[:20] + "…" for l in long_lines[:3]))
    n_img = len(post.image_blocks())
    missing = [b for b in post.image_blocks() if not b.path]
    if missing:
        issues.append(f"사진 자리 {n_img}곳 중 {len(missing)}곳에 파일이 없음")
    headings = [b for b in post.blocks if b.kind == "heading"]
    for h in headings:
        emojis = re.findall(r"[\U0001F300-\U0001FAFF☀-➿]", h.text)
        if len(emojis) > 1:
            issues.append(f"소제목 이모지 2개 이상: {h.text[:20]}")
    emoji_lines = [t for b in post.blocks if b.kind == "paragraph" and not b.note for t in b.plain_lines() if re.search(r"[\U0001F300-\U0001FAFF]", t)]
    if emoji_lines:
        issues.append(f"본문에 이모지 {len(emoji_lines)}줄(원칙: 소제목에만). 원고 그대로 두려면 무시: " + " / ".join(t[:18] + "…" for t in emoji_lines[:2]))
    if not any(b.kind == "link" for b in post.blocks):
        issues.append("맨 아래 공식 채널 링크 없음")
    return issues
