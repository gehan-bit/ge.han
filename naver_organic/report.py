"""결과 → 엑셀(시트: 키워드 후보 / 검색화면 구조 / 플레이스 순위 / 경쟁사 집계 / 실행 로그)."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .config import Config, normalize_name
from .discover import KeywordResult, keyword_candidates

HEADER_FILL = PatternFill("solid", fgColor="DDEBF7")
OURS_FILL = PatternFill("solid", fgColor="FFF2CC")
COMP_FILL = PatternFill("solid", fgColor="FCE4D6")


def _sheet(wb: Workbook, title: str, header: list[str], rows: list[list[Any]], widths: list[int] | None = None,
           fills: list[PatternFill | None] | None = None):
    ws = wb.create_sheet(title)
    ws.append(header)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = HEADER_FILL
        c.alignment = Alignment(vertical="center", wrap_text=True)
    for i, row in enumerate(rows):
        ws.append(row)
        if fills and fills[i] is not None:
            for c in ws[ws.max_row]:
                c.fill = fills[i]
    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(header))}{len(rows) + 1}"
    for i, w in enumerate(widths or [], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    return ws


def competitor_summary(cfg: Config, results: list[KeywordResult]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(업체 집계 행, 우리 지점 키워드별 순위 행)"""
    agg: dict[str, dict[str, Any]] = {}
    for r in results:
        for p in r.places():
            k = normalize_name(p.name)
            d = agg.setdefault(k, {"name": p.name, "ranks": {}, "ad_keywords": [], "orders": {}})
            if p.is_ad:
                if r.seed not in d["ad_keywords"]:
                    d["ad_keywords"].append(r.seed)
                continue
            # 같은 키워드에 두 번 나오면 더 좋은 순위만
            if r.seed not in d["ranks"] or (p.rank or 999) < d["ranks"][r.seed]:
                d["ranks"][r.seed] = p.rank
    rows: list[dict[str, Any]] = []
    for d in agg.values():
        ranks = [v for v in d["ranks"].values() if v]
        kind, matched = cfg.classify(d["name"])
        rows.append({
            "name": d["name"],
            "kind": kind,
            "matched": matched,
            "n_keywords": len(ranks),
            "top3": sum(1 for v in ranks if v <= 3),
            "best": min(ranks) if ranks else None,
            "avg": round(sum(ranks) / len(ranks), 1) if ranks else None,
            "by_keyword": ", ".join(f"{k} {v}위" for k, v in d["ranks"].items() if v),
            "ad_keywords": ", ".join(d["ad_keywords"]),
        })
    rows.sort(key=lambda d: (-d["n_keywords"], -d["top3"], d["avg"] if d["avg"] is not None else 999, d["name"]))

    # 네이버에 한 번도 안 뜬 후보도 표에 넣어 대조할 수 있게
    seen = {d["matched"] for d in rows if d["matched"]}
    for r in results:                     # 더보기엔 없고 검색화면에만 뜬 업체도 "등장"으로 본다
        for p in r.places_serp + r.places_more:
            seen.add(cfg.classify(p.name)[1])
    for c in cfg.competitors:
        if c.name not in seen:
            rows.append({"name": c.name, "kind": "경쟁사 후보", "matched": c.name, "n_keywords": 0, "top3": 0,
                         "best": None, "avg": None, "by_keyword": "", "ad_keywords": "", "unseen": True})

    ours: list[dict[str, Any]] = []
    for r in results:
        pl = r.places()
        hit = [p for p in pl if cfg.brand.matches(p.name)]
        if hit:
            p = hit[0]
            ours.append({"seed": r.seed, "rank": "광고" if p.is_ad else p.rank, "name": p.name, "source": p.source,
                         "total": len([q for q in pl if not q.is_ad])})
        else:
            ours.append({"seed": r.seed, "rank": "미노출", "name": "", "source": pl[0].source if pl else "",
                         "total": len([q for q in pl if not q.is_ad])})
    return rows, ours


def write_excel(cfg: Config, results: list[KeywordResult], path: Path, log_lines: list[str],
                missing: list[tuple[str, str]]) -> Path:
    wb = Workbook()
    wb.remove(wb.active)
    date = results[0].date if results else ""

    # 1) 키워드 후보
    cands = keyword_candidates(results, cfg.seed_keywords + cfg.test_keywords)
    rows = [[date, c["keyword"], len(c["seeds"]), ", ".join(c["seeds"]), ", ".join(c["sources"]), c["count"]]
            for c in cands]
    _sheet(wb, "키워드 후보", ["수집일", "키워드 후보", "씨앗 수", "어떤 씨앗에서", "어디서", "등장 횟수"],
           rows, [12, 28, 8, 40, 36, 10])

    # 2) 검색화면 구조
    rows = []
    for r in results:
        for b in r.blocks:
            rows.append([date, r.seed, b.order, b.kind, b.title, "광고" if b.is_ad else "", b.item_count,
                         " | ".join(b.names), ", ".join(b.keywords), b.css_class])
    _sheet(wb, "검색화면 구조", ["수집일", "씨앗 키워드", "순서", "블록 종류", "블록 제목", "광고", "항목 수",
                            "항목(업체·블로거 등, 상위)", "블록 안 키워드", "id/class(디버그)"],
           rows, [12, 16, 6, 20, 24, 6, 8, 60, 30, 40])

    # 3) 플레이스 순위
    rows, fills = [], []
    for r in results:
        for p in r.places_more + r.places_serp:
            kind, matched = cfg.classify(p.name)
            rows.append([date, r.seed, p.source, p.order, "광고" if p.is_ad else p.rank, p.name, kind, matched])
            fills.append(OURS_FILL if kind == "우리 지점" else COMP_FILL if kind == "경쟁사 후보" else None)
    _sheet(wb, "플레이스 순위", ["수집일", "씨앗 키워드", "출처", "표시 순서", "순위(광고 제외)", "업체명", "구분",
                            "일치한 후보"], rows, [12, 16, 10, 8, 12, 34, 12, 24], fills)

    # 4) 경쟁사 집계
    comp_rows, ours = competitor_summary(cfg, results)
    ws = wb.create_sheet("경쟁사 집계")
    ws.append([f"{cfg.brand.name} 플레이스 순위 (수집일 {date})"])
    ws["A1"].font = Font(bold=True, size=12)
    ws.append(["씨앗 키워드", "순위(광고 제외)", "노출 업체명", "출처", "목록 업체 수"])
    for c in ws[2]:
        c.font = Font(bold=True)
        c.fill = HEADER_FILL
    for o in ours:
        ws.append([o["seed"], o["rank"], o["name"], o["source"], o["total"]])
    ws.append([])
    ws.append(["업체별 집계 (여러 키워드에서 상위에 반복 등장한 순)"])
    ws.cell(ws.max_row, 1).font = Font(bold=True, size=12)
    header = ["업체명", "구분", "일치한 후보", "등장 키워드 수", "3위 안 횟수", "최고 순위", "평균 순위",
              "키워드별 순위", "광고로 뜬 키워드", "비고"]
    ws.append(header)
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
        c.fill = HEADER_FILL
    for d in comp_rows:
        ws.append([d["name"], d["kind"], d["matched"], d["n_keywords"], d["top3"], d["best"], d["avg"],
                   d["by_keyword"], d["ad_keywords"], "네이버 미등장" if d.get("unseen") else ""])
        fill = OURS_FILL if d["kind"] == "우리 지점" else COMP_FILL if d["kind"] == "경쟁사 후보" else None
        if fill:
            for c in ws[ws.max_row]:
                c.fill = fill
    for i, w in enumerate([30, 12, 24, 12, 10, 10, 10, 50, 24, 14], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # 5) 실행 로그
    rows = [["셀렉터 없음", ctx, key] for ctx, key in missing]
    rows += [["", "", line] for line in log_lines]
    _sheet(wb, "실행 로그", ["종류", "문맥", "내용"], rows, [12, 30, 100])

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
