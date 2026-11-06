"""Playwright 브라우저 세션(모바일, 비로그인, 위치 권한 없음) + 차단 감지 + 셀렉터 후보 탐색."""
from __future__ import annotations

import os
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import as_list


class BlockedError(RuntimeError):
    """캡챠·차단 화면. 즉시 멈춘다."""


@dataclass
class Log:
    path: Path | None = None
    lines: list[str] = field(default_factory=list)
    missing: list[tuple[str, str]] = field(default_factory=list)   # (키워드/문맥, 셀렉터 키)

    def write(self, msg: str, *, stderr: bool = False) -> None:
        stamp = time.strftime("%H:%M:%S")
        line = f"[{stamp}] {msg}"
        self.lines.append(line)
        print(line, file=sys.stderr if stderr else sys.stdout, flush=True)
        if self.path:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")

    def miss(self, context: str, key: str) -> None:
        self.missing.append((context, key))
        self.write(f"  ⚠ 셀렉터 없음: {key}  ({context}) → 빈칸", stderr=True)


class Browser:
    def __init__(self, crawl: dict[str, Any], selectors: dict[str, Any], log: Log, *, headless: bool | None = None):
        self.crawl = crawl
        self.S = selectors
        self.log = log
        self.headless = crawl.get("headless", False) if headless is None else headless
        self._pw = None
        self.browser = None
        self.ctx = None
        self.page = None

    # ---------- 수명 ----------
    def __enter__(self) -> "Browser":
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        exe = os.environ.get("NAVER_ORGANIC_CHROME") or os.environ.get("NAVER_BLOG_CHROME")
        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")   # 회사망·클라우드 프록시가 있을 때만
        self.browser = self._pw.chromium.launch(
            headless=self.headless,
            executable_path=exe or None,
            proxy={"server": proxy} if proxy else None,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self.new_context()
        return self

    def __exit__(self, *exc) -> None:
        try:
            if self.browser:
                self.browser.close()
        finally:
            if self._pw:
                self._pw.stop()

    def new_context(self) -> None:
        """쿠키·저장소가 빈 새 컨텍스트. 위치 권한은 주지 않는다(permissions=[])."""
        if self.ctx:
            self.ctx.close()
        dev = self._pw.devices.get(self.crawl.get("device") or "", {})
        opts: dict[str, Any] = {
            "viewport": dev.get("viewport") or self.crawl.get("viewport") or {"width": 412, "height": 915},
            "user_agent": dev.get("user_agent") or self.crawl.get("user_agent"),
            "device_scale_factor": dev.get("device_scale_factor", 2),
            "is_mobile": dev.get("is_mobile", True),
            "has_touch": dev.get("has_touch", True),
            "locale": self.crawl.get("locale", "ko-KR"),
            "timezone_id": self.crawl.get("timezone", "Asia/Seoul"),
            "permissions": [],
            "geolocation": None,
        }
        self.ctx = self.browser.new_context(**opts)
        self.ctx.set_default_timeout(int(self.crawl.get("page_timeout_ms", 30000)))
        self.page = self.ctx.new_page()

    # ---------- 이동·대기 ----------
    def sleep_between(self) -> None:
        lo = float(self.crawl.get("wait_min_sec", 3))
        hi = float(self.crawl.get("wait_max_sec", 5))
        t = random.uniform(lo, hi)
        self.log.write(f"  … {t:.1f}초 대기")
        time.sleep(t)

    def goto(self, url: str) -> None:
        self.page.goto(url, wait_until="domcontentloaded")
        try:
            self.page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        self.check_blocked()

    def check_blocked(self) -> None:
        b = self.S.get("blocked", {}) or {}
        url = (self.page.url or "").lower()
        for frag in as_list(b.get("url_contains")):
            if frag.lower() in url:
                raise BlockedError(f"차단/캡챠로 보이는 URL: {self.page.url}")
        try:
            text = self.page.inner_text("body", timeout=3000)
        except Exception:
            return
        head = text[:4000]
        for frag in as_list(b.get("text_contains")):
            if frag.lower() in head.lower():
                raise BlockedError(f"차단/캡챠 문구 발견: '{frag}' (URL {self.page.url})")

    # ---------- 셀렉터 후보 탐색 ----------
    def first(self, key: str, *, root=None, context: str = "", required: bool = True):
        """후보 중 요소가 하나라도 있는 첫 셀렉터의 locator(첫 요소). 없으면 None(+로그)."""
        root = root if root is not None else self.page
        for sel in as_list(self.S.get(key)):
            try:
                loc = root.locator(sel)
                if loc.count() > 0:
                    return loc.first
            except Exception:
                continue
        if required:
            self.log.miss(context, key)
        return None

    def all(self, key: str, *, root=None, context: str = "", required: bool = True) -> list:
        """후보 중 요소가 있는 첫 셀렉터의 모든 요소. 없으면 [](+로그)."""
        root = root if root is not None else self.page
        for sel in as_list(self.S.get(key)):
            try:
                loc = root.locator(sel)
                n = loc.count()
                if n > 0:
                    return [loc.nth(i) for i in range(n)]
            except Exception:
                continue
        if required:
            self.log.miss(context, key)
        return []

    @staticmethod
    def text(loc, default: str = "") -> str:
        if loc is None:
            return default
        try:
            return " ".join(loc.inner_text(timeout=1500).split())
        except Exception:
            return default

    def save_page(self, out_dir: Path, stem: str) -> None:
        if not self.crawl.get("save_html", True):
            return
        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            (out_dir / f"{stem}.html").write_text(self.page.content(), encoding="utf-8")
            self.page.screenshot(path=str(out_dir / f"{stem}.png"), full_page=True)
        except Exception as e:  # 저장 실패는 치명적이지 않다
            self.log.write(f"  (화면 저장 실패: {e})", stderr=True)
