"""명령줄 진입점. `python -m naver_organic <명령>`

  discover            씨앗 키워드로 자동완성·연관검색어·검색화면 블록·플레이스 순위 수집 → 엑셀
      --test          config 의 test_keywords(처음 확인용 2개)만
      --keywords ...  씨앗을 직접 지정
      --headless      브라우저 화면 없이(기본은 화면이 보임)
      --no-place-more 플레이스 '더보기' 목록 페이지는 가지 않음
  show-config         설정 요약 출력
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .browser import BlockedError, Browser, Log
from .config import ROOT, load_config, load_selectors
from .discover import Discoverer
from .report import write_excel


def cmd_show_config(a) -> int:
    cfg = load_config(a.config)
    print("우리 지점:", cfg.brand.name, cfg.brand.aliases)
    print("씨앗 키워드:", cfg.seed_keywords)
    print("테스트 키워드:", cfg.test_keywords)
    print("경쟁사 후보:", [c.name for c in cfg.competitors])
    print("대기:", cfg.crawl.get("wait_min_sec"), "~", cfg.crawl.get("wait_max_sec"), "초")
    return 0


def cmd_discover(a) -> int:
    cfg = load_config(a.config)
    S = load_selectors(a.selectors)
    if a.search_url:
        cfg.crawl["search_url"] = a.search_url
    if a.place_list_url:
        cfg.crawl["place_list_url"] = a.place_list_url
    if a.no_place_more:
        cfg.crawl["place_more"] = False
    if a.ac_ui:
        cfg.crawl["autocomplete_api"] = None       # 화면 레이어 경로만 시험
    if a.fast:
        cfg.crawl["wait_min_sec"] = cfg.crawl["wait_max_sec"] = 0.2

    keywords = a.keywords or (cfg.test_keywords if a.test else cfg.seed_keywords)
    if not keywords:
        print("키워드가 없습니다. config/organic.yaml 의 seed_keywords 를 채워 주세요.", file=sys.stderr)
        return 2

    date = time.strftime("%Y-%m-%d")
    out_root = Path(a.out) if a.out else ROOT / cfg.output.get("dir", "output/organic")
    out_dir = out_root / date
    out_dir.mkdir(parents=True, exist_ok=True)
    log = Log(out_dir / "log.txt")
    log.write(f"=== 0단계 발굴 시작: {len(keywords)}개 키워드 {keywords} (headless={a.headless or cfg.crawl.get('headless')})")

    results = []
    blocked = None
    try:
        with Browser(cfg.crawl, S, log, headless=True if a.headless else None) as br:
            d = Discoverer(cfg, br, log, out_dir, date)
            for i, kw in enumerate(keywords):
                if i:
                    br.sleep_between()
                try:
                    results.append(d.run_keyword(kw))
                except BlockedError as e:
                    blocked = str(e)
                    br.save_page(out_dir / "pages", "BLOCKED")
                    break
    except KeyboardInterrupt:
        log.write("사용자가 중단했습니다.", stderr=True)

    if blocked:
        log.write(f"🛑 차단/캡챠 감지로 즉시 중단했습니다: {blocked}", stderr=True)
        log.write("   → 브라우저를 닫고 몇 시간 뒤(또는 다른 네트워크에서) 다시 시도하세요. "
                  "화면은 output/.../pages/BLOCKED.png 에 저장했습니다.", stderr=True)

    if not results:
        log.write("수집된 결과가 없어 엑셀을 만들지 않습니다.", stderr=True)
        return 3 if blocked else 1

    (out_dir / "results.json").write_text(
        json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2), encoding="utf-8")
    name = cfg.output.get("excel_name", "organic_discovery_{date}.xlsx").format(date=date.replace("-", ""))
    xlsx = write_excel(cfg, results, out_dir / name, log.lines, log.missing)
    log.write(f"✅ 엑셀 저장: {xlsx}")
    if log.missing:
        keys = sorted({k for _, k in log.missing})
        log.write(f"   못 찾은 셀렉터 {len(log.missing)}건 (키: {', '.join(keys)}) → config/organic_selectors.yaml 확인")
    return 3 if blocked else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m naver_organic", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", help="config/organic.yaml 대신 쓸 파일")
    ap.add_argument("--selectors", help="config/organic_selectors.yaml 대신 쓸 파일")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("discover", help="0단계: 키워드 후보 + 경쟁사 발굴")
    p.add_argument("--test", action="store_true", help="test_keywords 만")
    p.add_argument("--keywords", nargs="+")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--no-place-more", action="store_true")
    p.add_argument("--out", help="출력 폴더(기본 output/organic)")
    p.add_argument("--search-url", help=argparse.SUPPRESS)        # 테스트용(모의 화면)
    p.add_argument("--place-list-url", help=argparse.SUPPRESS)
    p.add_argument("--fast", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--ac-ui", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(fn=cmd_discover)

    p = sub.add_parser("show-config")
    p.set_defaults(fn=cmd_show_config)

    a = ap.parse_args(argv)
    return a.fn(a)
