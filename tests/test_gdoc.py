import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from naver_blog import gdoc  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "doc_sample.json"


def test_parse_fixture():
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    post = gdoc.parse_tab(doc, gdoc.find_tab(doc, "샘플"))
    assert post.title == "샘플 제목｜부제"
    assert post.tags == ["원더바레", "바레"]
    kinds = [b.kind for b in post.blocks]
    assert kinds == ["paragraph", "image", "heading", "paragraph", "paragraph", "table", "link"]
    assert post.blocks[0].lines[0][0].bold is True
    assert post.blocks[4].note is True
    assert post.blocks[5].rows == [["항목", "내용"], ["가", "나"]]
    assert post.blocks[6].url == "https://www.wonderbarrelicense.kr"
