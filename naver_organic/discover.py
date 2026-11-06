"""0단계: 씨앗 키워드 하나에 대해 자동완성·연관검색어·검색화면 블록·플레이스 순위를 모은다."""
from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .browser import BlockedError, Browser, Log
from .config import Config, as_list, normalize_name
from .dom import BLOCKS_JS, PLACES_JS


@dataclass
class Block:
    order: int
    title: str
    kind: str
    css_class: str
    is_ad: bool
    keywords: list[str] = field(default_factory=list)   # 블록 안 키워드 칩
    item_count: int = 0                                  # 블록 안 항목 수
    names: list[str] = field(default_factory=list)      # 항목 이름(업체명·블로거명 등, 상위 몇 개)


@dataclass
class PlaceItem:
    order: int            # 표시 순서(광고 포함)
    rank: int | None      # 광고 제외 순위
    name: str
    is_ad: bool
    source: str           # 검색화면 / 더보기
    link: str = ""


@dataclass
class KeywordResult:
    seed: str
    date: str
    autocomplete: list[str] = field(default_factory=list)
    autocomplete_source: str = ""        # 검색창 / API / (빈칸)
    related: list[str] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    places_serp: list[PlaceItem] = field(default_factory=list)
    places_more: list[PlaceItem] = field(default_factory=list)
    place_more_url: str = ""
    search_url: str = ""
    notes: list[str] = field(default_factory=list)

    def places(self) -> list[PlaceItem]:
        """집계에 쓸 목록: 더보기 목록이 있으면 그것, 없으면 검색화면 목록."""
        return self.places_more if self.places_more else self.places_serp

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clean(s: str) -> str:
    return " ".join(s.split()).strip()


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        k = normalize_name(it)
        if it and k and k not in seen:
            seen.add(k)
            out.append(it)
    return out


class Discoverer:
    def __init__(self, cfg: Config, br: Browser, log: Log, out_dir: Path, date: str):
        self.cfg = cfg
        self.br = br
        self.S = br.S
        self.log = log
        self.out_dir = out_dir
        self.date = date

    # ---------- 전체 ----------
    def run_keyword(self, kw: str) -> KeywordResult:
        r = KeywordResult(seed=kw, date=self.date)
        stem = re.sub(r"[\\/:*?\"<>|\s]+", "_", kw)
        self.log.write(f"▶ [{kw}]")

        # 1) 검색 결과 화면
        url = self.cfg.crawl["search_url"].format(query=urllib.parse.quote(kw))
        r.search_url = url
        self.br.goto(url)
        self.br.page.wait_for_timeout(int(self.cfg.crawl.get("render_wait_ms", 2500)))
        self.br.save_page(self.out_dir / "pages", stem)
        self.collect_related(kw, r)
        self.collect_blocks(kw, r)
        self.collect_places_serp(kw, r)

        # 2) 자동완성(API → 화면 레이어)
        try:
            self.collect_autocomplete(kw, r)
        except BlockedError:
            raise
        except Exception as e:
            r.notes.append(f"자동완성 실패: {e}")
            self.log.write(f"  ⚠ 자동완성 실패: {e}", stderr=True)

        # 3) 플레이스 더보기(목록 페이지)
        if self.cfg.crawl.get("place_more", True):
            self.br.sleep_between()
            try:
                self.collect_places_more(kw, r, stem)
            except BlockedError:
                raise
            except Exception as e:
                r.notes.append(f"플레이스 더보기 실패: {e}")
                self.log.write(f"  ⚠ 플레이스 더보기 실패: {e}", stderr=True)

        self.log.write(
            f"  자동완성 {len(r.autocomplete)}개({r.autocomplete_source or '없음'}), 연관 {len(r.related)}개, "
            f"블록 {len(r.blocks)}개, 플레이스 검색화면 {len(r.places_serp)}곳 / 더보기 {len(r.places_more)}곳"
        )
        raw_dir = self.out_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / f"{stem}.json").write_text(json.dumps(r.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return r

    # ---------- 자동완성 ----------
    def collect_autocomplete(self, kw: str, r: KeywordResult) -> None:
        api = self.cfg.crawl.get("autocomplete_api")
        if api:
            try:
                resp = self.br.ctx.request.get(api.format(query=urllib.parse.quote(kw)), timeout=10000,
                                               headers={"Referer": "https://m.search.naver.com/"})
                data = resp.json()
                texts: list[str] = []
                for group in data.get("items", []) or []:
                    for row in group:
                        if row and isinstance(row, list) and isinstance(row[0], str):
                            texts.append(row[0])
                for row in data.get("answer", []) or []:       # 정답형·의도형 제안이 있으면 같이
                    if isinstance(row, list) and row and isinstance(row[0], str):
                        texts.append(row[0])
                r.autocomplete = _dedupe(texts)
                if r.autocomplete:
                    r.autocomplete_source = "자동완성 API"
                    return
                self.log.write("  자동완성 API 응답에 항목이 없어 화면 레이어로 다시 시도")
            except Exception as e:
                self.log.write(f"  자동완성 API 실패({e}) → 화면 레이어로 다시 시도", stderr=True)
        # 화면 레이어: 지금 떠 있는 검색 결과 화면의 검색창에 입력한다(검색은 하지 않음)
        box = self.br.first("search_input", context=f"{kw}/자동완성")
        if box is None:
            return
        box.click()
        self.br.page.wait_for_timeout(500)
        box.press("Control+a")
        box.type(kw, delay=90)
        self.br.page.wait_for_timeout(1500)
        items = self.br.all("autocomplete_item", context=f"{kw}/자동완성")
        r.autocomplete = _dedupe([_clean(self.br.text(i)) for i in items])
        r.autocomplete_source = "검색창 레이어" if r.autocomplete else ""
        box.press("Escape")

    # ---------- 연관검색어 ----------
    def collect_related(self, kw: str, r: KeywordResult) -> None:
        items = self.br.all("related_keyword", context=f"{kw}/연관검색어")
        r.related = _dedupe([_clean(self.br.text(i)) for i in items])

    # ---------- 검색화면 블록 ----------
    def collect_blocks(self, kw: str, r: KeywordResult) -> None:
        res = self.br.page.evaluate(BLOCKS_JS, [
            as_list(self.S.get("result_container")), as_list(self.S.get("block_skip_tags")),
            self.S.get("block_rules") or [], as_list(self.S.get("block_ad_marker")), as_list(self.S.get("block_keyword_item")),
        ])
        if not res.get("root"):
            self.log.miss(f"{kw}/블록", "result_container")
            return
        for i, b in enumerate(res["blocks"], start=1):
            r.blocks.append(Block(i, b["title"], b["kind"], b["css"], b["is_ad"], _dedupe(b["keywords"]),
                                  b["item_count"], b["names"][:10]))
        if not r.blocks:
            self.log.miss(f"{kw}/블록", "block_rules")

    # ---------- 플레이스(검색 화면) ----------
    def _read_places(self, root_key: str, item_key: str, source: str, ctx: str, *, prefer_title: str = "",
                     limit: int | None = None) -> list[PlaceItem]:
        res = self.br.page.evaluate(PLACES_JS, [
            as_list(self.S.get(root_key)), self.S.get("place_title", ".place_section_header_title"),
            self.S.get(item_key, "li"), self.S.get("place_name_anchor", "a"), self.S.get("place_name_text", "span"),
            self.S.get("place_ad_text", "광고"), prefer_title,
        ])
        if not res.get("root"):
            self.log.miss(ctx, root_key)
            return []
        out: list[PlaceItem] = []
        seen: set[str] = set()
        rank = 0
        for it in res["items"]:
            key = normalize_name(it["name"])
            if not key or key in seen:
                continue
            seen.add(key)
            if not it["is_ad"]:
                rank += 1
            out.append(PlaceItem(len(out) + 1, None if it["is_ad"] else rank, it["name"], it["is_ad"], source, it["link"]))
            if limit and rank >= limit:
                break
        if not out:
            self.log.miss(ctx, item_key)
        return out

    def collect_places_serp(self, kw: str, r: KeywordResult) -> None:
        ctx = f"{kw}/플레이스"
        btn = self.br.first("place_expand_button", required=False)
        if btn is not None:
            try:
                btn.click()
                self.br.page.wait_for_timeout(1200)
            except Exception:
                pass
        r.places_serp = self._read_places("place_root", "place_item", "검색화면", ctx, prefer_title="플레이스")
        more = self.br.first("place_more_link", context=f"{kw}/플레이스 더보기", required=False)
        if more is not None:
            href = more.get_attribute("href") or ""
            if href and not href.startswith("javascript"):
                r.place_more_url = urllib.parse.urljoin(self.br.page.url, href)

    # ---------- 플레이스 더보기(목록 페이지) ----------
    def collect_places_more(self, kw: str, r: KeywordResult, stem: str) -> None:
        top_n = int(self.cfg.crawl.get("place_top_n", 10))
        url = r.place_more_url
        if not url:
            tmpl = self.cfg.crawl.get("place_list_url")
            if not tmpl:
                self.log.write("  플레이스 더보기 링크 없음 → 검색화면 목록만 사용")
                return
            url = tmpl.format(query=urllib.parse.quote(kw))
            r.place_more_url = url
            self.log.write("  더보기 링크를 못 찾아 기본 목록 URL 사용")
        self.br.goto(url)
        self.br.page.wait_for_timeout(int(self.cfg.crawl.get("render_wait_ms", 2500)))
        ctx = f"{kw}/플레이스 더보기"
        places = self._read_places("place_list_root", "place_list_item", "더보기", ctx, limit=top_n)
        tries = 0
        while len([p for p in places if not p.is_ad]) < top_n and tries < int(self.S.get("place_list_scroll_times", 4)):
            self.br.page.mouse.wheel(0, 3000)
            self.br.page.wait_for_timeout(1500)
            self.br.check_blocked()
            tries += 1
            more = self._read_places("place_list_root", "place_list_item", "더보기", ctx, limit=top_n)
            if len(more) <= len(places):
                break
            places = more
        self.br.save_page(self.out_dir / "pages", f"{stem}_place")
        if not places:
            r.notes.append("플레이스 목록 페이지에서 업체를 읽지 못해 검색화면 목록만 사용")
            self.log.write("  ⚠ 플레이스 목록 페이지에서 업체를 못 읽음 → 검색화면 목록만 사용 (pages/*_place.png 확인)", stderr=True)
        r.places_more = places


def keyword_candidates(results: list[KeywordResult], seeds: list[str]) -> list[dict[str, Any]]:
    """새 키워드 후보(중복 제거). 어떤 씨앗에서 / 어디서 나왔는지 함께."""
    seed_keys = {normalize_name(s) for s in seeds}
    found: dict[str, dict[str, Any]] = {}

    def add(kw: str, seed: str, where: str) -> None:
        k = normalize_name(kw)
        if not k or k in seed_keys:
            return
        d = found.setdefault(k, {"keyword": kw, "seeds": [], "sources": [], "count": 0})
        d["count"] += 1
        if seed not in d["seeds"]:
            d["seeds"].append(seed)
        if where not in d["sources"]:
            d["sources"].append(where)

    for r in results:
        for kw in r.autocomplete:
            add(kw, r.seed, "자동완성")
        for kw in r.related:
            add(kw, r.seed, "연관검색어")
        for b in r.blocks:
            if b.kind == "연관검색어":      # 위에서 연관검색어로 이미 넣었다
                continue
            where = b.kind if b.title in (b.kind, "파워링크") else f"{b.kind}:{b.title}"
            for kw in b.keywords:
                add(kw, r.seed, where)
    rows = sorted(found.values(), key=lambda d: (-len(d["seeds"]), -d["count"], d["keyword"]))
    return rows
