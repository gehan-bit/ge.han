"""확인용 미리보기 HTML. 네이버 모바일 글 느낌(가운데 정렬, 소제목 큰 글씨, ※ 회색)으로 그린다."""
from __future__ import annotations

import html
from pathlib import Path

from .model import Block, Line, Post

CSS = """
:root{--fg:#222;--muted:#8c8c8c;--line:#e5e5e5;--bg:#fff;--accent:#03c75a}
*{box-sizing:border-box}
body{margin:0;background:#f3f4f6;color:var(--fg);font-family:-apple-system,"Apple SD Gothic Neo","Malgun Gothic","Noto Sans KR",sans-serif}
.phone{max-width:430px;margin:24px auto;background:var(--bg);border-radius:18px;box-shadow:0 6px 30px rgba(0,0,0,.08);padding:28px 20px 40px}
h1{font-size:22px;line-height:1.35;margin:0 0 6px;text-align:left;word-break:keep-all}
.meta{color:var(--muted);font-size:12px;margin-bottom:22px}
.body{text-align:center;font-size:15px;line-height:1.75;word-break:keep-all}
.body p{margin:0 0 20px}
.body p.note{font-size:12.5px;color:var(--muted);line-height:1.6}
.body h2{font-size:19px;margin:30px 0 14px;line-height:1.4}
.body hr{border:0;border-top:1px solid var(--line);margin:28px 40px}
.body figure{margin:0 0 22px}
.body figure img{width:100%;border-radius:6px;display:block}
.body figure .ph{width:100%;aspect-ratio:5/4;background:repeating-linear-gradient(45deg,#f3f3f3,#f3f3f3 10px,#e9e9e9 10px,#e9e9e9 20px);border-radius:6px;display:flex;align-items:center;justify-content:center;color:#888;font-size:13px}
.body figcaption{font-size:11.5px;color:var(--muted);margin-top:6px}
.body table{margin:0 auto 22px;border-collapse:collapse;font-size:13px;text-align:left}
.body td,.body th{border:1px solid var(--line);padding:6px 8px;vertical-align:top}
.body th{background:#fafafa}
.body blockquote{margin:0 0 22px;padding:14px 16px;border-left:3px solid var(--accent);background:#fafafa;text-align:left;border-radius:4px}
.card{display:block;border:1px solid var(--line);border-radius:10px;padding:14px;margin:0 0 14px;text-decoration:none;color:inherit;text-align:left;font-size:13px}
.card .u{color:var(--muted);font-size:11.5px;word-break:break-all}
.tags{margin-top:26px;text-align:left;font-size:13px;line-height:2}
.tags span{display:inline-block;background:#f1f3f5;border-radius:14px;padding:0 10px;margin:0 6px 4px 0;color:#444}
.lint{max-width:430px;margin:0 auto 20px;background:#fff8e6;border:1px solid #f1d58a;border-radius:10px;padding:12px 16px;font-size:13px}
.lint h3{margin:0 0 6px;font-size:13px}
.lint ul{margin:0;padding-left:18px}
"""


def _runs_html(line: Line) -> str:
    out = []
    for r in line:
        t = html.escape(r.text)
        if r.bold:
            t = f"<b>{t}</b>"
        if r.link:
            t = f'<a href="{html.escape(r.link)}">{t}</a>'
        out.append(t)
    return "".join(out)


def _block_html(b: Block, img_rel: dict[str, str]) -> str:
    if b.kind == "paragraph":
        cls = ' class="note"' if b.note else ""
        return f"<p{cls}>" + "<br>".join(_runs_html(l) for l in b.lines) + "</p>"
    if b.kind == "quote":
        return "<blockquote>" + "<br>".join(_runs_html(l) for l in b.lines) + "</blockquote>"
    if b.kind == "heading":
        return f"<h2>{html.escape(b.text)}</h2>"
    if b.kind == "hr":
        return "<hr>"
    if b.kind == "image":
        cap = f"<figcaption>{html.escape(b.caption)}</figcaption>" if b.caption else ""
        if b.path and b.path in img_rel:
            return f'<figure><img src="{html.escape(img_rel[b.path])}" alt="">{cap}</figure>'
        return f'<figure><div class="ph">사진 {(b.slot or 0) + 1} 자리</div>{cap}</figure>'
    if b.kind == "table":
        rows = []
        for i, row in enumerate(b.rows):
            tag = "th" if i == 0 else "td"
            rows.append("<tr>" + "".join(f"<{tag}>{html.escape(c)}</{tag}>" for c in row) + "</tr>")
        return "<table>" + "".join(rows) + "</table>"
    if b.kind == "link":
        return f'<a class="card" href="{html.escape(b.url)}">링크 미리보기 카드<div class="u">{html.escape(b.url)}</div></a>'
    return ""


def render(post: Post, out_path: Path | str, lint_issues: list[str] | None = None, base_dir: Path | str | None = None) -> Path:
    out_path = Path(out_path)
    base = Path(base_dir) if base_dir else out_path.parent
    img_rel: dict[str, str] = {}
    for b in post.image_blocks():
        if b.path:
            p = Path(b.path)
            if not p.is_absolute():
                p = base / p
            try:
                img_rel[b.path] = str(p.resolve().relative_to(out_path.parent.resolve()))
            except ValueError:
                img_rel[b.path] = p.resolve().as_uri()
    body = "\n".join(_block_html(b, img_rel) for b in post.blocks)
    tags = "".join(f"<span>#{html.escape(t)}</span>" for t in post.tags)
    lint_html = ""
    if lint_issues:
        lint_html = '<div class="lint"><h3>확인할 점</h3><ul>' + "".join(f"<li>{html.escape(i)}</li>" for i in lint_issues) + "</ul></div>"
    src = post.source
    meta = f"{html.escape(src.get('doc_title', ''))} · {html.escape(src.get('tab_title', ''))} · 사진 {len(post.image_blocks())}장 · 태그 {len(post.tags)}개"
    doc = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(post.title)}</title><style>{CSS}</style></head><body>
{lint_html}
<div class="phone"><h1>{html.escape(post.title)}</h1><div class="meta">{meta}</div>
<div class="body">{body}</div>
<div class="tags">{tags}</div></div></body></html>"""
    out_path.write_text(doc, encoding="utf-8")
    return out_path
