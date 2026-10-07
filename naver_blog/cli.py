"""명령줄 진입점. `python -m naver_blog <명령>`

  tabs                      원고 문서의 탭 목록
  fetch-doc                 구글 문서 JSON을 workspace/doc.json 에 저장(구글 API 인증 필요)
  build --tab 1주차         원고 → post.json / post.txt / preview.html (사진 자리 채우기 포함)
  photos list|pull          드라이브 사진 목록 / 내려받기(구글 API)
  crop --tab 1주차          raw 사진 → 5:4 가공 + review.jpg
  preview --tab 1주차       미리보기 다시 만들기
  login                     네이버 로그인(브라우저가 열림, 한 번만)
  post --tab 1주차          스마트에디터에 입력하고 임시저장 (--publish 로 발행까지)
  run --tab 1주차           build → crop → preview 한 번에
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

from . import gdoc, naver_format
from .model import Post

ROOT = Path(__file__).resolve().parent.parent


def load_settings(path: str | None) -> dict[str, Any]:
    p = Path(path) if path else ROOT / "config" / "settings.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def slugify(tab: str) -> str:
    return re.sub(r"[\\/:*?\"<>|\s]+", "_", tab.strip()) or "post"


def post_dir(settings: dict[str, Any], tab: str, create: bool = True) -> Path:
    """글 폴더. workspace/<탭> 이 기본. 없고 drafts/<탭>(저장소에 넣어 둔 완성본)이 있으면 그것을 쓴다."""
    d = ROOT / settings["paths"]["workspace"] / slugify(tab)
    alt = ROOT / "drafts" / slugify(tab)
    if not d.exists() and alt.exists():
        return alt
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def resolve_photo_paths(post: Post, pdir: Path) -> None:
    """post.json 의 사진 경로는 글 폴더 기준 상대 경로. 실행 시 절대 경로로 바꾼다."""
    for b in post.image_blocks():
        if b.path and not Path(b.path).is_absolute():
            b.path = str((pdir / b.path).resolve())


def doc_path(settings: dict[str, Any]) -> Path:
    return ROOT / settings["paths"]["workspace"] / "doc.json"


def format_options(settings: dict[str, Any], title: str) -> naver_format.FormatOptions:
    f = settings["format"]
    academy = any(k in title for k in f.get("academy_keywords", []))
    links = f.get("footer_links_academy" if academy else "footer_links", [])
    return naver_format.FormatOptions(
        max_line=f.get("max_line", 30),
        min_line=f.get("min_line", 16),
        wrap=f.get("wrap", True),
        hr_before_heading=f.get("hr_before_heading", True),
        max_tags=f.get("max_tags", 15),
        min_tags=f.get("min_tags", 10),
        footer_links=list(links),
        closing_lines=list(f.get("closing_lines", []) or []),
        extra_tags=list(f.get("extra_tags", []) or []),
    )


# ---------- 사진 자리 채우기 ----------
def load_photo_config(pdir: Path) -> dict[str, Any]:
    p = pdir / "photos.yaml"
    if p.exists():
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {}


def assign_photos(post: Post, pdir: Path, settings: dict[str, Any]) -> list[str]:
    """photos/out 의 가공 사진을 사진 자리에 순서대로 넣는다. photos.yaml 의 order 가 있으면 그 순서."""
    from .photos import local_images

    out_dir = pdir / "photos" / "out"
    files = local_images(out_dir)
    cfg = load_photo_config(pdir)
    order = cfg.get("order") or []
    if order:
        by_stem = {p.stem: p for p in files}
        ordered = [by_stem[Path(n).stem] for n in order if Path(n).stem in by_stem]
        ordered += [p for p in files if p not in ordered]
        files = ordered
    notes = []
    slots = post.image_blocks()
    want = settings["photos"].get("per_post") or len(slots)
    # 자리보다 사진이 많고 per_post 가 더 크면 마지막 사진 자리 뒤에 추가
    if want > len(slots) and len(files) > len(slots):
        from .model import Block

        last = max((i for i, b in enumerate(post.blocks) if b.kind == "image"), default=len(post.blocks) - 1)
        for k in range(len(slots), min(want, len(files))):
            post.blocks.insert(last + 1 + (k - len(slots)), Block(kind="image", slot=k))
        slots = post.image_blocks()
    for b, f in zip(slots, files):
        b.path = str(f.relative_to(pdir)).replace("\\", "/")  # 글 폴더 기준 상대 경로(폴더째 옮겨도 됨)
    if len(files) < len(slots):
        notes.append(f"사진 {len(slots)}장 필요, {len(files)}장 있음 → photos/raw 에 더 넣고 crop 을 다시 실행")
    return notes


# ---------- 명령 ----------
def cmd_tabs(a, s):
    doc = gdoc.load_doc_json(doc_path(s))
    for name, tid in gdoc.list_tabs(doc):
        print(f"{name}\t{tid}")


def cmd_fetch_doc(a, s):
    from .google_auth import fetch_document, get_credentials

    creds = get_credentials(ROOT / s["paths"]["secrets"])
    doc = fetch_document(a.doc_id or s["source"]["doc_id"], creds)
    p = doc_path(s)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    print(f"저장: {p} (탭 {len(list(gdoc.iter_tabs(doc)))}개)")


def cmd_google_login(a, s):
    from .google_auth import get_credentials

    get_credentials(ROOT / s["paths"]["secrets"])
    print("구글 인증 완료")


def _build(a, s) -> tuple[Post, Path, list[str]]:
    pdir = post_dir(s, a.tab)
    doc = gdoc.load_doc_json(doc_path(s))
    post = gdoc.parse_tab(doc, gdoc.find_tab(doc, a.tab))
    opts = format_options(s, post.title)
    if getattr(a, "no_wrap", False):
        opts.wrap = False
    post = naver_format.apply(post, opts)
    notes = assign_photos(post, pdir, s)
    issues = naver_format.lint(post, opts) + notes
    post.save(pdir / "post.json")
    (pdir / "post.txt").write_text(post.plain_text(), encoding="utf-8")
    from .render_html import render

    render(post, pdir / "preview.html", issues, base_dir=pdir)
    return post, pdir, issues


def cmd_build(a, s):
    post, pdir, issues = _build(a, s)
    print(f"제목: {post.title}")
    print(f"태그 {len(post.tags)}개, 사진 자리 {len(post.image_blocks())}곳, 블록 {len(post.blocks)}개")
    print(f"→ {pdir / 'post.json'}\n→ {pdir / 'post.txt'}\n→ {pdir / 'preview.html'}")
    if issues:
        print("확인할 점:")
        for i in issues:
            print("  -", i)


def cmd_photos(a, s):
    from . import photos as ph

    pdir = post_dir(s, a.tab) if a.tab else None
    index_path = ROOT / s["paths"]["workspace"] / "drive_index.json"
    if a.action == "list":
        from .google_auth import drive_service, get_credentials

        drive = drive_service(get_credentials(ROOT / s["paths"]["secrets"]))
        files = ph.list_folder(drive, s["source"]["drive_folder_id"])
        ph.save_index(files, index_path)
        for f in files:
            print(f"{f.folder or '-'}\t{f.name}\t{f.width}x{f.height}\t{f.size // 1024}KB\t{f.id}")
        print(f"{len(files)}개 → {index_path}")
    elif a.action == "pull":
        if pdir is None:
            sys.exit("--tab 이 필요합니다")
        from .google_auth import drive_service, get_credentials

        drive = drive_service(get_credentials(ROOT / s["paths"]["secrets"]))
        files = ph.load_index(index_path) if index_path.exists() else ph.list_folder(drive, s["source"]["drive_folder_id"])
        ph.save_index(files, index_path)
        ledger = ph.Ledger(ROOT / s["paths"]["workspace"] / "used_photos.json")
        cfg = load_photo_config(pdir)
        if cfg.get("order"):
            by_name = {f.name: f for f in files}
            chosen = [by_name[n] for n in cfg["order"] if n in by_name]
            missing = [n for n in cfg["order"] if n not in by_name]
            if missing:
                print("드라이브에 없는 파일명:", missing, file=sys.stderr)
        else:
            doc = gdoc.load_doc_json(doc_path(s))
            n = a.n or s["photos"].get("per_post") or len(gdoc.parse_tab(doc, gdoc.find_tab(doc, a.tab)).image_blocks())
            chosen = ph.pick(files, n, ledger, s["photos"].get("prefer_folders", []), s["photos"].get("exclude_folders", []))
        raw = pdir / "photos" / "raw"
        for f in chosen:
            dest = raw / f.name
            if dest.exists():
                print("있음:", dest.name)
                continue
            ph.download(drive, f.id, dest)
            print("내려받음:", dest.name, f"({f.size // 1024}KB)")
        ledger.mark([f.id for f in chosen] + [f.name for f in chosen], slugify(a.tab))
        print(f"{len(chosen)}장 → {raw}")


def cmd_crop(a, s):
    from . import crop
    from .photos import local_images

    pdir = post_dir(s, a.tab)
    raw = pdir / "photos" / "raw"
    files = local_images(raw)
    if not files:
        sys.exit(f"사진이 없습니다: {raw}  (photos pull 또는 직접 복사)")
    cfg = load_photo_config(pdir)
    ovs = cfg.get("overrides") or {}
    out = pdir / "photos" / "out"
    if a.clean and out.exists():
        shutil.rmtree(out)
    plans = []
    for f in files:
        o = ovs.get(f.name) or ovs.get(f.stem) or {}
        ov = crop.Override(
            top=o.get("top"), focus_y=o.get("focus_y"), anchor=o.get("anchor") or s["photos"].get("anchor", "third"),
            protect=o.get("protect", []), skip_crop=o.get("skip_crop", False), rotate=o.get("rotate", 0),
        )
        plan = crop.process_photo(f, out, ov, max_width=s["photos"].get("max_width", 1600), quality=s["photos"].get("jpeg_quality", 90))
        plans.append(plan)
        flag = " ⚠ 확인" if plan.needs_review else ""
        print(f"{f.name}: {plan.width}x{plan.height} → {plan.method}{flag} {'; '.join(plan.notes)}")
    crop.save_plans(plans, pdir / "photos" / "plans.json")
    sheet = crop.review_sheet(plans, pdir / "photos" / "review.jpg")
    print(f"확인용 이미지: {sheet}")


def cmd_preview(a, s):
    post, pdir, issues = _build(a, s)
    print(f"→ {pdir / 'preview.html'}")
    for i in issues:
        print("  -", i)


def _poster(a, s, headless: bool):
    from . import poster

    sel = poster.load_selectors(ROOT / "config" / "selectors.yaml")
    f = s["format"]
    opts = poster.PostOptions(heading_size=f.get("heading_size", "fs19"), body_size=f.get("body_size", "fs15"),
                              note_size=f.get("note_size", "fs13"), note_color=f.get("note_color", "#777777"))
    return poster.Poster(s["blog"]["id"], sel, ROOT / s["paths"]["browser_profile"], headless=headless, options=opts,
                         editor_url=getattr(a, "editor_url", None), slow_mo=getattr(a, "slow_mo", 0))


def cmd_login(a, s):
    with _poster(a, s, headless=False) as p:
        p.login()


def cmd_post(a, s):
    from . import poster

    pdir = post_dir(s, a.tab)
    pj = pdir / "post.json"
    if not pj.exists():
        sys.exit(f"{pj} 가 없습니다. 먼저 build 를 실행하세요.")
    post = Post.load(pj)
    resolve_photo_paths(post, pdir)
    missing = [b for b in post.image_blocks() if not b.path or not Path(b.path).exists()]
    if missing and not a.allow_missing_photos:
        sys.exit(f"사진 자리 {len(missing)}곳에 파일이 없습니다. crop → build 를 먼저 하거나 --allow-missing-photos 를 주세요.")
    if a.dry_run:
        for i, step in enumerate(poster.dry_run_plan(post), 1):
            print(f"{i:3d}. {step}")
        return
    with _poster(a, s, headless=a.headless) as p:
        if not a.editor_url and not p.is_logged_in():
            sys.exit("네이버 로그인이 필요합니다: python -m naver_blog login")
        p.open_editor()
        p.write_title(post.title)
        p.write_body(post)
        if a.publish:
            ok = p.publish(post.tags, s["blog"].get("category", ""), s["blog"].get("public", True))
            print("발행", "완료" if ok else "실패")
        else:
            ok = p.save_draft()
            print("임시저장", "클릭 완료" if ok else "실패")
        shot = p.screenshot(pdir / "editor_result.png")
        print("화면 캡처:", shot)
        if p.report.warnings:
            print("주의:")
            for w in p.report.warnings:
                print("  -", w)
        print("발행할 때 넣을 태그:", " ".join("#" + t for t in post.tags))
        if a.keep_open:
            input("브라우저를 닫으려면 Enter...")


def cmd_run(a, s):
    pdir = post_dir(s, a.tab)
    if list((pdir / "photos" / "raw").glob("*")) if (pdir / "photos" / "raw").exists() else []:
        a.clean = False
        cmd_crop(a, s)
    else:
        print(f"사진이 없어 크롭을 건너뜁니다: {pdir / 'photos' / 'raw'}")
    cmd_build(a, s)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="naver_blog", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--settings", help="설정 파일(기본 config/settings.yaml)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("tabs").set_defaults(fn=cmd_tabs)
    sp = sub.add_parser("fetch-doc"); sp.add_argument("--doc-id"); sp.set_defaults(fn=cmd_fetch_doc)
    sub.add_parser("google-login").set_defaults(fn=cmd_google_login)

    sp = sub.add_parser("build"); sp.add_argument("--tab", required=True); sp.add_argument("--no-wrap", action="store_true"); sp.set_defaults(fn=cmd_build)
    sp = sub.add_parser("preview"); sp.add_argument("--tab", required=True); sp.add_argument("--no-wrap", action="store_true"); sp.set_defaults(fn=cmd_preview)

    sp = sub.add_parser("photos"); sp.add_argument("action", choices=["list", "pull"]); sp.add_argument("--tab"); sp.add_argument("--n", type=int); sp.set_defaults(fn=cmd_photos)
    sp = sub.add_parser("crop"); sp.add_argument("--tab", required=True); sp.add_argument("--clean", action="store_true"); sp.set_defaults(fn=cmd_crop)

    sp = sub.add_parser("login"); sp.set_defaults(fn=cmd_login)
    sp = sub.add_parser("post"); sp.add_argument("--tab", required=True)
    sp.add_argument("--publish", action="store_true", help="임시저장 대신 발행까지(확인 후에만)")
    sp.add_argument("--dry-run", action="store_true"); sp.add_argument("--headless", action="store_true")
    sp.add_argument("--allow-missing-photos", action="store_true"); sp.add_argument("--keep-open", action="store_true")
    sp.add_argument("--editor-url", help="테스트용 에디터 주소(모의 에디터)"); sp.add_argument("--slow-mo", type=int, default=0)
    sp.set_defaults(fn=cmd_post)

    sp = sub.add_parser("run"); sp.add_argument("--tab", required=True); sp.add_argument("--no-wrap", action="store_true"); sp.add_argument("--clean", action="store_true"); sp.set_defaults(fn=cmd_run)

    a = ap.parse_args(argv)
    s = load_settings(a.settings)
    a.fn(a, s)


if __name__ == "__main__":
    main()
