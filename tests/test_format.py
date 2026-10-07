import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from naver_blog import naver_format as nf  # noqa: E402
from naver_blog.model import Block, Post, Run  # noqa: E402


def text_of(lines):
    return ["".join(r.text for r in l) for l in lines]


def test_short_lines_untouched():
    line = [Run("쉬는 날에도 센터 연락이 끊이지 않는다면")]
    assert text_of(nf.wrap_line(line, 30, 16)) == ["쉬는 날에도 센터 연락이 끊이지 않는다면"]


def test_slightly_long_line_untouched():
    t = "※ 강사님이라면 일하는 센터의 원장님을 떠올리며 골라보세요."  # 33자
    assert text_of(nf.wrap_line([Run(t)], 30, 16)) == [t]


def test_long_line_breaks_balanced_at_space():
    t = "쉬는 날 오는 연락, 떠올려 보면 대부분 이런 질문이지 않나요?"
    out = text_of(nf.wrap_line([Run(t)], 30, 16))
    assert out == ["쉬는 날 오는 연락, 떠올려 보면", "대부분 이런 질문이지 않나요?"]
    assert all(len(l) <= 30 for l in out)


def test_no_break_inside_quotes_or_parens():
    t = "회원 관계·매출에 영향을 주는 일 (예: 환불·연기, 컴플레인)"
    out = text_of(nf.wrap_line([Run(t)], 30, 16))
    assert out == ["회원 관계·매출에 영향을 주는 일", "(예: 환불·연기, 컴플레인)"]


def test_bold_runs_survive_wrap():
    line = [Run("굵은 제목 부분입니다 ", bold=True), Run("그리고 뒤에는 보통 글씨가 길게 이어집니다 정말로")]
    out = nf.wrap_line(line, 30, 16)
    assert len(out) == 2
    assert out[0][0].bold is True
    assert "".join(r.text for l in out for r in l).replace(" ", "") == "".join(r.text for r in line).replace(" ", "")


def test_apply_adds_hr_and_footer_and_caps_tags():
    post = Post(
        title="테스트",
        tags=[f"태그{i}" for i in range(20)],
        blocks=[Block(kind="paragraph", lines=[[Run("안녕하세요")]]), Block(kind="heading", text="1. 소제목"), Block(kind="link", url="https://www.wonderbarrelicense.kr")],
    )
    opts = nf.FormatOptions(footer_links=["https://www.instagram.com/wonder_barre/", "https://www.wonderbarrelicense.kr/"], closing_lines=["공감 부탁드려요."])
    post = nf.apply(post, opts)
    kinds = [b.kind for b in post.blocks]
    assert kinds == ["paragraph", "hr", "heading", "paragraph", "link", "link"]
    assert len(post.tags) == 15
    urls = [b.url for b in post.blocks if b.kind == "link"]
    assert urls == ["https://www.wonderbarrelicense.kr", "https://www.instagram.com/wonder_barre/"]


def test_min_tags_filled_from_extra():
    post = Post(title="t", tags=["원더바레"], blocks=[])
    opts = nf.FormatOptions(extra_tags=["바레", "요가", "필라테스"], min_tags=3)
    post = nf.apply(post, opts)
    assert post.tags == ["원더바레", "바레", "요가"]
