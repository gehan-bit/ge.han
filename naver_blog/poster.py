"""네이버 스마트에디터 ONE 자동 입력(Playwright).

흐름: 로그인(한 번, 사람이 직접) → 글쓰기 화면 → 제목·본문·사진 입력 → 임시저장 → 화면 캡처.
발행은 --publish 를 명시했을 때만 한다(원칙: 임시저장 후 확인받고 발행).

셀렉터는 config/selectors.yaml 에 있다. 네이버가 화면을 바꾸면 그 파일만 고친다.
"""
from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

from .model import Block, Line, Post


def _as_list(v: Any) -> list[str]:
    if v is None:
        return []
    return [v] if isinstance(v, str) else list(v)


@dataclass
class PostOptions:
    heading_size: str = "fs19"
    body_size: str = "fs15"
    note_size: str = "fs13"
    note_color: str = "#777777"
    type_delay_ms: int = 0
    step_pause_ms: int = 150          # 동작 사이 잠깐 대기(에디터가 따라오게)
    upload_timeout_ms: int = 60000
    blank_line_between_paragraphs: bool = True


@dataclass
class Report:
    ok: bool = True
    warnings: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    screenshot: str | None = None

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        print(f"  ⚠ {msg}", file=sys.stderr)

    def log(self, msg: str) -> None:
        self.actions.append(msg)


class Poster:
    def __init__(self, blog_id: str, selectors: dict[str, Any], profile_dir: Path | str, *, headless: bool = False,
                 options: PostOptions | None = None, editor_url: str | None = None, slow_mo: int = 0):
        self.blog_id = blog_id
        self.S = selectors
        self.profile_dir = Path(profile_dir)
        self.headless = headless
        self.opt = options or PostOptions()
        self.editor_url = editor_url or selectors["editor_url"].format(blog_id=blog_id)
        self.slow_mo = slow_mo
        self.report = Report()
        self._pw = None
        self.ctx = None
        self.page = None
        self.ed = None  # 에디터가 들어 있는 page 또는 frame

    # ---------- 브라우저 ----------
    def __enter__(self) -> "Poster":
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        exe = os.environ.get("NAVER_BLOG_CHROME")  # 시스템 크롬/크로미움을 쓰고 싶을 때
        self.ctx = self._pw.chromium.launch_persistent_context(
            str(self.profile_dir),
            headless=self.headless,
            executable_path=exe or None,
            channel=None if exe else os.environ.get("NAVER_BLOG_CHANNEL") or None,
            slow_mo=self.slow_mo,
            viewport={"width": 1400, "height": 950},
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            args=["--disable-blink-features=AutomationControlled"],
        )
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        return self

    def __exit__(self, *exc) -> None:
        try:
            if self.ctx:
                self.ctx.close()
        finally:
            if self._pw:
                self._pw.stop()

    def is_logged_in(self) -> bool:
        names = {c["name"] for c in self.ctx.cookies("https://www.naver.com")}
        return self.S.get("login_cookie", "NID_AUT") in names

    def login(self, wait_minutes: int = 5) -> bool:
        """로그인 창을 띄우고 사람이 로그인할 때까지 기다린다(헤드리스 불가)."""
        if self.is_logged_in():
            print("이미 로그인되어 있습니다.")
            return True
        self.page.goto(self.S["login_url"])
        print("브라우저에서 네이버에 로그인해 주세요. (2단계 인증·기기 등록까지 마치면 자동으로 이어집니다)")
        deadline = time.time() + wait_minutes * 60
        while time.time() < deadline:
            if self.is_logged_in():
                print("로그인 확인. 이 폴더에 세션이 저장되어 다음부터는 바로 글을 쓸 수 있습니다:", self.profile_dir)
                return True
            time.sleep(2)
        print("로그인 대기 시간이 지났습니다.", file=sys.stderr)
        return False

    # ---------- 공통 ----------
    def _pause(self, ms: int | None = None) -> None:
        self.page.wait_for_timeout(ms if ms is not None else self.opt.step_pause_ms)

    def _find(self, key: str, *, root=None, timeout: int = 2000, fmt: dict[str, str] | None = None):
        """후보 셀렉터를 차례로 시도해 보이는 첫 요소를 돌려준다. 없으면 None."""
        root = root or self.ed or self.page
        for sel in _as_list(self.S.get(key)):
            if fmt:
                sel = sel.format(**fmt)
            loc = root.locator(sel).first
            try:
                loc.wait_for(state="visible", timeout=timeout)
                return loc
            except Exception:
                continue
        return None

    def _click(self, key: str, *, timeout: int = 2000, fmt: dict[str, str] | None = None, required: bool = False) -> bool:
        loc = self._find(key, timeout=timeout, fmt=fmt)
        if loc is None:
            msg = f"요소를 찾지 못함: {key} ({', '.join(_as_list(self.S.get(key)))})"
            if required:
                raise RuntimeError(msg)
            self.report.warn(msg)
            return False
        loc.click()
        self._pause()
        return True

    def _dismiss_popups(self) -> None:
        for _ in range(3):
            clicked = False
            for sel in _as_list(self.S.get("popup_dismiss")):
                loc = self.page.locator(sel).first
                try:
                    if loc.is_visible(timeout=600):
                        loc.click()
                        clicked = True
                        self.report.log(f"팝업 닫음: {sel}")
                        self._pause(400)
                except Exception:
                    pass
            if not clicked:
                break

    def _locate_editor(self, timeout_ms: int = 30000):
        deadline = time.time() + timeout_ms / 1000
        roots = _as_list(self.S.get("editor_root"))
        while time.time() < deadline:
            for frame in [self.page] + list(self.page.frames):
                for sel in roots:
                    try:
                        if frame.locator(sel).first.is_visible(timeout=300):
                            return frame
                    except Exception:
                        continue
            self._dismiss_popups()
            time.sleep(0.5)
        raise RuntimeError("에디터를 찾지 못했습니다. 로그인 상태와 editor_url 을 확인하세요.")

    def open_editor(self) -> None:
        self.page.goto(self.editor_url, wait_until="domcontentloaded")
        self.ed = self._locate_editor()
        self._dismiss_popups()
        self.report.log("에디터 열림")

    # ---------- 입력 도우미 ----------
    def _type(self, text: str) -> None:
        if not text:
            return
        if self.opt.type_delay_ms:
            self.page.keyboard.type(text, delay=self.opt.type_delay_ms)
        else:
            self.page.keyboard.insert_text(text)

    def _bold(self, on: bool) -> None:
        self.page.keyboard.press("Control+b")

    def _type_line(self, line: Line) -> None:
        bold_on = False
        for run in line:
            if run.bold != bold_on:
                self._bold(run.bold)
                bold_on = run.bold
            self._type(run.text)
        if bold_on:
            self._bold(False)

    def _set_size(self, size: str) -> bool:
        if not self._click("font_size_button"):
            return False
        sel = self.S.get("font_size_option", "").format(size=size)
        loc = (self.ed or self.page).locator(sel).first
        try:
            loc.click(timeout=2000)
            self._pause()
            self._refocus()
            return True
        except Exception:
            self.report.warn(f"글자 크기 옵션을 찾지 못함: {sel}")
            self.page.keyboard.press("Escape")
            self._refocus()
            return False

    def _set_color(self, color: str | None) -> bool:
        if not color:
            return False
        if not self._click("font_color_button", timeout=1200):
            return False
        sel = self.S.get("font_color_option", "").format(color=color)
        loc = (self.ed or self.page).locator(sel).first
        try:
            loc.click(timeout=1500)
            self._pause()
            self._refocus()
            return True
        except Exception:
            self.report.warn(f"글자 색 옵션을 찾지 못함: {sel}")
            self.page.keyboard.press("Escape")
            self._refocus()
            return False

    def _align_center(self) -> None:
        if self._click("align_button", timeout=1500):
            if not self._click("align_center_option", timeout=1500):
                self.page.keyboard.press("Escape")
            self._refocus()

    def _new_paragraph(self, blank: bool | None = None) -> None:
        self.page.keyboard.press("Enter")
        if blank if blank is not None else self.opt.blank_line_between_paragraphs:
            self.page.keyboard.press("Enter")

    def _focus_last_paragraph(self) -> None:
        """마지막 본문 문단을 클릭하고 캐럿을 문서 끝으로 옮긴다(순서대로 이어 쓰는 흐름 전제)."""
        loc = None
        for sel in _as_list(self.S.get("body_paragraph")):
            cand = (self.ed or self.page).locator(sel)
            if cand.count():
                loc = cand.last
                break
        if loc is None:
            raise RuntimeError("본문 문단을 찾지 못했습니다.")
        loc.click()
        self.page.keyboard.press("Control+End")
        self._pause()

    def _refocus(self) -> None:
        """툴바 버튼을 누른 뒤 포커스가 에디터 밖으로 나갔으면 되돌린다."""
        try:
            active = self.page.evaluate("() => (document.activeElement && document.activeElement.isContentEditable) ? 1 : 0")
        except Exception:
            active = 0
        if not active:
            self._focus_last_paragraph()

    # ---------- 블록 입력 ----------
    def write_title(self, title: str) -> None:
        loc = self._find("title", timeout=10000)
        if loc is None:
            raise RuntimeError("제목 입력란을 찾지 못했습니다.")
        loc.click()
        self._type(title)
        self.report.log("제목 입력")

    def write_body(self, post: Post) -> None:
        self._focus_last_paragraph()
        self._align_center()
        for i, b in enumerate(post.blocks):
            try:
                self._write_block(b)
            except Exception as e:  # 한 블록 실패해도 나머지는 계속
                self.report.ok = False
                self.report.warn(f"블록 {i} ({b.kind}) 입력 실패: {e}")
                try:
                    self._focus_last_paragraph()
                except Exception:
                    pass

    def _write_block(self, b: Block) -> None:
        if b.kind in ("paragraph", "quote"):
            if b.note:
                self._set_size(self.opt.note_size)
                self._set_color(self.opt.note_color)
            for j, line in enumerate(b.lines):
                if j:
                    self.page.keyboard.press("Shift+Enter")
                self._type_line(line)
            self._new_paragraph()
            if b.note:
                self._set_size(self.opt.body_size)
                self._set_color("#000000")
            self.report.log(f"문단 {len(b.lines)}줄")
        elif b.kind == "heading":
            self._set_size(self.opt.heading_size)
            self._bold(True)
            self._type(b.text)
            self._bold(False)
            self._new_paragraph()
            self._set_size(self.opt.body_size)
            self.report.log(f"소제목: {b.text[:20]}")
        elif b.kind == "hr":
            if self._click("hr_button", timeout=1500):
                if not self._click("hr_option", timeout=1500):
                    self.page.keyboard.press("Escape")
                self._pause(400)
                self._focus_last_paragraph()
                self._align_center()
                self.report.log("구분선")
        elif b.kind == "image":
            if not b.path or not Path(b.path).exists():
                self.report.warn(f"사진 파일 없음(자리 {b.slot}): {b.path}")
                return
            self._insert_image(Path(b.path))
        elif b.kind == "table":
            for row in b.rows:
                self._type(" | ".join(row))
                self.page.keyboard.press("Shift+Enter")
            self._new_paragraph()
            self.report.log(f"표 → 글줄 {len(b.rows)}행")
        elif b.kind == "link":
            self._type(b.url)
            self.page.keyboard.press("Enter")
            self._pause(2500)  # 링크 미리보기 카드가 만들어질 시간
            self._focus_last_paragraph()
            self._align_center()
            self.page.keyboard.press("Enter")
            self.report.log(f"링크 카드: {b.url}")

    def _insert_image(self, path: Path) -> None:
        root = self.ed or self.page
        before = root.locator(self.S["image_component"]).count()
        btn = self._find("image_button", timeout=3000)
        if btn is None:
            raise RuntimeError("사진 버튼을 찾지 못함")
        with self.page.expect_file_chooser(timeout=10000) as fc:
            btn.click()
        fc.value.set_files(str(path))
        deadline = time.time() + self.opt.upload_timeout_ms / 1000
        while time.time() < deadline:
            if root.locator(self.S["image_component"]).count() > before:
                break
            time.sleep(0.3)
        else:
            raise RuntimeError(f"사진 업로드 확인 실패: {path.name}")
        self._pause(1200)
        self._dismiss_popups()
        self._focus_last_paragraph()
        self._align_center()
        self.report.log(f"사진: {path.name}")

    # ---------- 저장/발행 ----------
    def save_draft(self) -> bool:
        ok = self._click("save_button", timeout=5000)
        if ok:
            self._pause(2500)
            self.report.log("임시저장 클릭")
        else:
            self.report.ok = False
        return ok

    def publish(self, tags: Iterable[str], category: str = "", public: bool = True) -> bool:
        if not self._click("publish_button", timeout=5000):
            self.report.ok = False
            return False
        self._pause(1200)
        tag_input = self._find("tag_input", timeout=5000)
        if tag_input is None:
            self.report.warn("태그 입력란을 찾지 못함. 태그를 직접 넣어 주세요.")
        else:
            for t in tags:
                tag_input.click()
                self._type(t)
                self.page.keyboard.press("Enter")
                self._pause(150)
            self.report.log("태그 입력")
        if category:
            if self._click("category_button", timeout=2000):
                sel = self.S.get("category_option", "").format(name=category)
                try:
                    self.page.locator(sel).first.click(timeout=2000)
                except Exception:
                    self.report.warn(f"카테고리를 찾지 못함: {category}")
        if public:
            try:
                self.page.locator(self.S.get("public_radio", "")).first.click(timeout=1500)
            except Exception:
                pass
        ok = self._click("publish_confirm", timeout=5000)
        if ok:
            self._pause(4000)
            self.report.log("발행 클릭")
        return ok

    def screenshot(self, path: Path | str) -> str:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=str(p), full_page=True)
        self.report.screenshot = str(p)
        return str(p)


def load_selectors(path: Path | str) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def dry_run_plan(post: Post) -> list[str]:
    """브라우저 없이 어떤 동작을 할지 목록으로 보여준다."""
    steps = [f"제목 입력: {post.title}", "가운데 정렬"]
    for b in post.blocks:
        if b.kind in ("paragraph", "quote"):
            steps.append(("※회색 작은 글씨 " if b.note else "") + f"문단 {len(b.lines)}줄: {b.plain_lines()[0][:30]}")
        elif b.kind == "heading":
            steps.append(f"소제목(큰 글씨·굵게): {b.text}")
        elif b.kind == "hr":
            steps.append("구분선")
        elif b.kind == "image":
            steps.append(f"사진 업로드: {b.path or '(파일 없음)'}")
        elif b.kind == "table":
            steps.append(f"표 {len(b.rows)}행을 글줄로")
        elif b.kind == "link":
            steps.append(f"링크 카드: {b.url}")
    steps.append("임시저장")
    steps.append("태그(발행 때 입력): " + " ".join("#" + t for t in post.tags))
    return steps
