"""글 한 편을 표현하는 데이터 모델. 문서 파서(gdoc)와 포맷터(naver_format), 렌더러, 포스터가 공유한다."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class Run:
    """한 줄 안의 서식 단위. 굵게/링크만 다룬다."""

    text: str
    bold: bool = False
    link: str | None = None

    def plain(self) -> str:
        return self.text


Line = list[Run]


def line_text(line: Line) -> str:
    return "".join(r.text for r in line)


@dataclass
class Block:
    """본문 블록.

    kind:
      paragraph  lines(여러 줄, Shift+Enter로 이어지는 한 문단). note=True면 ※ 회색 작은 글씨
      heading    text (소제목. 앞에 구분선)
      image      slot(0부터), path(가공된 사진 파일), caption
      table      rows(list[list[str]])
      hr         구분선
      link       url (링크 카드)
      quote      lines (인용구 블록)
    """

    kind: str
    lines: list[Line] = field(default_factory=list)
    text: str = ""
    note: bool = False
    slot: int | None = None
    path: str | None = None
    caption: str = ""
    rows: list[list[str]] = field(default_factory=list)
    url: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def plain_lines(self) -> list[str]:
        return [line_text(l) for l in self.lines]


@dataclass
class Post:
    title: str
    tags: list[str]
    blocks: list[Block]
    source: dict[str, Any] = field(default_factory=dict)
    category: str = ""

    # ---- 직렬화 ----
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: Path | str) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Post":
        blocks = []
        for b in d["blocks"]:
            lines = [[Run(**r) for r in line] for line in b.get("lines", [])]
            blocks.append(
                Block(
                    kind=b["kind"],
                    lines=lines,
                    text=b.get("text", ""),
                    note=b.get("note", False),
                    slot=b.get("slot"),
                    path=b.get("path"),
                    caption=b.get("caption", ""),
                    rows=b.get("rows", []),
                    url=b.get("url", ""),
                    meta=b.get("meta", {}),
                )
            )
        return cls(
            title=d["title"],
            tags=list(d.get("tags", [])),
            blocks=blocks,
            source=d.get("source", {}),
            category=d.get("category", ""),
        )

    @classmethod
    def load(cls, path: Path | str) -> "Post":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    # ---- 편의 ----
    def image_blocks(self) -> list[Block]:
        return [b for b in self.blocks if b.kind == "image"]

    def plain_text(self) -> str:
        """사람이 읽거나 수동으로 붙여넣을 때 쓰는 평문."""
        out: list[str] = [self.title, ""]
        for b in self.blocks:
            if b.kind == "heading":
                out += [b.text, ""]
            elif b.kind == "paragraph" or b.kind == "quote":
                prefix = "" if not b.note else ""
                out += [prefix + t for t in b.plain_lines()] + [""]
            elif b.kind == "image":
                out += [f"[사진 {(b.slot or 0) + 1}: {Path(b.path).name if b.path else '미정'}]", ""]
            elif b.kind == "table":
                for row in b.rows:
                    out.append(" | ".join(row))
                out.append("")
            elif b.kind == "hr":
                out += ["─" * 12, ""]
            elif b.kind == "link":
                out += [b.url, ""]
        out += ["", "태그: " + " ".join("#" + t for t in self.tags)]
        return "\n".join(out).rstrip() + "\n"
