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


@dataclass
class Block:
    order: int
    title: str
    kind: str
    css_class: str
    is_ad: bool
    keywords: list[str] = field(default_factory=list)   # 블록 안 키워드 칩
    item_count: int = 0                                  # 블록 안 링크 수(참고)


@dataclass
class PlaceItem:
    order: int            # 표시 순서(광고 포함)
    rank: int | None      # 광고 제외 순위
    name: str
    is_ad: bool
    source: str           # 검색화면 / 더보기


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

        # 1) 자동완성(검색창 입력)
        try:
            self.collect_autocomplete(kw, r)
        except BlockedError:
            raise
        except Exception as e:
            r.notes.append(f"자동완성 실패: {e}")
            self.log.write(f"  ⚠ 자동완성 실패: {e}", stderr=True)
        self.br.sleep_between()

        # 2) 검색 결과 화면
        url = self.cfg.crawl["search_url"].format(query=urllib.parse.quote(kw))
        r.search_url = url
        self.br.goto(url)
        self.br.save_page(self.out_dir / "pages", stem)
        self.collect_related(kw, r)
        self.collect_blocks(kw, r)
        self.collect_places_serp(kw, r)

        # 3) 플레이스 더보기
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
        home = self.cfg.crawl.get("home_url")
        if home:
            self.br.goto(home)
            box = self.br.first("search_input", context=f"{kw}/자동완성")
            if box is not None:
                box.click()
                box.fill("")
                box.type(kw, delay=80)
                self.br.page.wait_for_timeout(1200)
                items = self.br.all("autocomplete_item", context=f"{kw}/자동완성", required=False)
                texts = _dedupe([_clean(self.br.text(i)) for i in items])
                if texts:
                    r.autocomplete = texts
                    r.autocomplete_source = "검색창"
                    return
                self.log.write("  자동완성 목록을 화면에서 못 읽어 API로 다시 시도")
        api = self.cfg.crawl.get("autocomplete_api")
        if not api:
            self.log.miss(f"{kw}/자동완성", "autocomplete_item")
            return
        try:
            resp = self.br.ctx.request.get(api.format(query=urllib.parse.quote(kw)), timeout=10000)
            data = resp.json()
            texts: list[str] = []
            for group in data.get("items", []):
                for row in group:
                    if row and isinstance(row, list) and isinstance(row[0], str):
                        texts.append(row[0])
            r.autocomplete = _dedupe(texts)
            r.autocomplete_source = "API" if r.autocomplete else ""
            if not r.autocomplete:
                self.log.miss(f"{kw}/자동완성", "autocomplete_api")
        except Exception as e:
            self.log.miss(f"{kw}/자동완성", "autocomplete_item")
            r.notes.append(f"자동완성 API 실패: {e}")

    # ---------- 연관검색어 ----------
    def collect_related(self, kw: str, r: KeywordResult) -> None:
        items = self.br.all("related_keyword", context=f"{kw}/연관검색어")
        r.related = _dedupe([_clean(self.br.text(i)) for i in items])

    # ---------- 검색화면 블록 ----------
    def _kind_of(self, css: str, title: str) -> str:
        for frag, kind in self.S.get("block_type_by_class", []) or []:
            if frag in css:
                return kind
        for frag, kind in self.S.get("block_type_by_title", []) or []:
            if frag in title:
                return kind
        return "기타"

    def collect_blocks(self, kw: str, r: KeywordResult) -> None:
        secs = self.br.all("block", context=f"{kw}/블록")
        order = 0
        for sec in secs:
            try:
                if not sec.is_visible():
                    continue
            except Exception:
                continue
            css = (sec.get_attribute("class") or "").strip()
            title = _clean(self.br.text(self.br.first("block_title", root=sec, required=False)))
            if not title and not css:
                continue
            is_ad = self.br.first("block_ad_marker", root=sec, required=False) is not None
            kind = self._kind_of(css, title)
            if is_ad and "광고" not in kind:
                kind = f"광고({kind})" if kind != "기타" else "광고"
            chips = self.br.all("block_keyword_item", root=sec, required=False)
            kws = _dedupe([_clean(self.br.text(c)) for c in chips])
            try:
                n_links = sec.locator("a").count()
            except Exception:
                n_links = 0
            order += 1
            r.blocks.append(Block(order, title or "(제목 없음)", kind, css[:120], is_ad, kws, n_links))
        if secs and not r.blocks:
            self.log.miss(f"{kw}/블록", "block_title")

    # ---------- 플레이스(검색 화면) ----------
    def _read_place_items(self, root, item_key: str, name_key: str, ad_key: str, source: str, ctx: str,
                          limit: int | None = None) -> list[PlaceItem]:
        items = self.br.all(item_key, root=root, context=ctx)
        out: list[PlaceItem] = []
        seen: set[str] = set()
        rank = 0
        for it in items:
            try:
                if not it.is_visible():
                    continue
            except Exception:
                continue
            name = _clean(self.br.text(self.br.first(name_key, root=it, required=False)))
            if not name:
                continue
            key = normalize_name(name)
            if key in seen:
                continue
            seen.add(key)
            is_ad = self.br.first(ad_key, root=it, required=False) is not None
            if not is_ad:
                rank += 1
            out.append(PlaceItem(len(out) + 1, None if is_ad else rank, name, is_ad, source))
            if limit and rank >= limit:
                break
        if items and not out:
            self.log.miss(ctx, name_key)
        return out

    def collect_places_serp(self, kw: str, r: KeywordResult) -> None:
        sec = self.br.first("place_section", context=f"{kw}/플레이스", required=False)
        if sec is None:
            # 블록 목록에서 플레이스 종류를 찾아 본다
            secs = self.br.all("block", required=False)
            for s in secs:
                css = s.get_attribute("class") or ""
                title = _clean(self.br.text(self.br.first("block_title", root=s, required=False)))
                if self._kind_of(css, title) == "플레이스":
                    sec = s
                    break
        if sec is None:
            self.log.miss(f"{kw}/플레이스", "place_section")
            return
        r.places_serp = self._read_place_items(sec, "place_item", "place_item_name", "place_item_ad",
                                               "검색화면", f"{kw}/플레이스")
        more = self.br.first("place_more_link", root=sec, context=f"{kw}/플레이스 더보기", required=False)
        if more is not None:
            href = more.get_attribute("href") or ""
            if href and not href.startswith("javascript"):
                r.place_more_url = urllib.parse.urljoin(self.br.page.url, href)

    # ---------- 플레이스 더보기 ----------
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
        self.br.save_page(self.out_dir / "pages", f"{stem}_place")
        ctx = f"{kw}/플레이스 더보기"
        places = self._read_place_items(self.br.page, "place_list_item", "place_list_name", "place_list_ad",
                                        "더보기", ctx, limit=top_n)
        tries = 0
        while len([p for p in places if not p.is_ad]) < top_n and tries < 3:
            btn = self.br.first("place_list_more_button", required=False)
            if btn is None:
                break
            try:
                btn.click()
                self.br.page.wait_for_timeout(1500)
                self.br.check_blocked()
            except Exception:
                break
            tries += 1
            places = self._read_place_items(self.br.page, "place_list_item", "place_list_name", "place_list_ad",
                                            "더보기", ctx, limit=top_n)
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
            for kw in b.keywords:
                add(kw, r.seed, f"스마트블록:{b.title}")
    rows = sorted(found.values(), key=lambda d: (-len(d["seeds"]), -d["count"], d["keyword"]))
    return rows
