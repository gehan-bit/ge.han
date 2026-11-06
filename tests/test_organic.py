"""naver_organic: 업체명 분류, 키워드 후보 집계, 엑셀 생성."""
from pathlib import Path

from naver_organic.config import Business, Config, load_config, load_selectors, normalize_name
from naver_organic.discover import Block, KeywordResult, PlaceItem, keyword_candidates
from naver_organic.report import competitor_summary, write_excel


def _cfg() -> Config:
    return Config(
        brand=Business("어반필드 역삼점", ["어반필드"]),
        seed_keywords=["역삼 헬스장", "강남역 PT"], test_keywords=[],
        competitors=[Business("소울업짐 역삼점", ["소울업짐"]), Business("Exxl 피트니스", ["exxl"]),
                     Business("알파짐 강남역PT", ["알파짐"])],
        crawl={}, output={}, raw={},
    )


def test_normalize_and_classify():
    assert normalize_name("EXXL 피트니스 (강남점)") == "exxl피트니스"
    cfg = _cfg()
    assert cfg.classify("어반필드 역삼점 헬스장")[0] == "우리 지점"
    assert cfg.classify("소울업짐 역삼")[1] == "소울업짐 역삼점"
    assert cfg.classify("Exxl Fitness")[1] == "Exxl 피트니스"   # 별칭(영문)으로도 맞춘다
    assert cfg.classify("바디스페이스")[0] == "기타"


def test_real_config_loads():
    cfg = load_config()
    assert cfg.brand.name and cfg.seed_keywords and cfg.test_keywords
    S = load_selectors()
    for key in ["search_input", "autocomplete_item", "related_keyword", "result_container", "block_rules",
                "place_root", "place_item", "place_name_anchor", "place_list_root", "place_list_item", "blocked"]:
        assert key in S, key
    assert any(r.get("self") == "#place-app-root" for r in S["block_rules"])


def _results():
    r1 = KeywordResult("역삼 헬스장", "2026-11-06",
                       autocomplete=["역삼 헬스장 추천", "역삼 PT"], related=["역삼역 헬스장", "역삼 PT"],
                       blocks=[Block(1, "연관검색어", "연관검색어", "sp_keyword", False, ["역삼 PT"]),
                               Block(2, "역삼 헬스장 추천", "스마트블록", "sp_intent", False, ["강남 헬스장 가격"])],
                       places_more=[PlaceItem(1, None, "광고헬스", True, "더보기"),
                                    PlaceItem(2, 1, "소울업짐 역삼점", False, "더보기"),
                                    PlaceItem(3, 2, "어반필드 역삼점", False, "더보기")])
    r2 = KeywordResult("강남역 PT", "2026-11-06", autocomplete=["강남역 PT 가격"],
                       places_serp=[PlaceItem(1, 1, "알파짐 강남역PT", False, "검색화면"),
                                    PlaceItem(2, 2, "소울업짐 역삼점", False, "검색화면")])
    return [r1, r2]


def test_keyword_candidates():
    rows = keyword_candidates(_results(), ["역삼 헬스장", "강남역 PT"])
    by = {r["keyword"]: r for r in rows}
    assert "역삼 헬스장" not in by                          # 씨앗은 제외
    assert by["역삼 PT"]["sources"] == ["자동완성", "연관검색어"]  # 연관검색어 블록 칩은 중복 집계 안 함
    assert by["강남 헬스장 가격"]["sources"] == ["스마트블록:역삼 헬스장 추천"]
    assert by["역삼역 헬스장"]["seeds"] == ["역삼 헬스장"]


def test_competitor_summary_and_excel(tmp_path: Path):
    cfg = _cfg()
    rows, ours = competitor_summary(cfg, _results())
    top = rows[0]
    assert top["name"] == "소울업짐 역삼점" and top["n_keywords"] == 2 and top["best"] == 1
    assert ours[0]["rank"] == 2 and ours[1]["rank"] == "미노출"
    unseen = {d["name"] for d in rows if d.get("unseen")}
    assert unseen == {"Exxl 피트니스"}                       # 알파짐은 검색화면에 떴으니 미등장이 아니다
    ad = next(d for d in rows if d["name"] == "광고헬스")
    assert ad["n_keywords"] == 0 and ad["ad_keywords"] == "역삼 헬스장"

    out = write_excel(cfg, _results(), tmp_path / "x.xlsx", ["log"], [("역삼 헬스장/플레이스", "place_item")])
    from openpyxl import load_workbook
    wb = load_workbook(out)
    assert wb.sheetnames == ["키워드 후보", "검색화면 구조", "플레이스 순위", "경쟁사 집계", "실행 로그"]
    assert wb["플레이스 순위"].max_row == 6
