import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from naver_blog import crop  # noqa: E402


def test_landscape_untouched():
    p = crop.plan_crop(4000, 3000, [])
    assert p.crop is None and p.method == "original"


def test_portrait_face_on_upper_third():
    W, H = 4000, 5000
    face = crop.Box(1700, 1600, 600, 700)
    p = crop.plan_crop(W, H, [face])
    l, t, r, b = p.crop
    assert (r - l) * 4 == (b - t) * 5
    assert p.method == "face-third"
    third = t + (b - t) / 3
    assert abs(face.cy - third) < 2


def test_face_near_top_is_clamped():
    W, H = 4000, 5000
    face = crop.Box(1700, 100, 600, 700)
    p = crop.plan_crop(W, H, [face])
    l, t, r, b = p.crop
    assert t == 0
    assert p.method in ("face-fit", "face-third", "face-center")


def test_protect_box_kept_when_possible():
    W, H = 4000, 5000
    face = crop.Box(1700, 2200, 600, 700)        # 얼굴 가운데쯤
    logo = crop.Box(100, 4300, 800, 300)         # 아래쪽 로고
    p = crop.plan_crop(W, H, [face], [logo])
    l, t, r, b = p.crop
    assert b >= logo.y2 and t <= face.y


def test_no_face_center_flagged():
    p = crop.plan_crop(3000, 4000, [])
    assert p.crop is not None and p.needs_review


def test_manual_top():
    p = crop.plan_crop(3000, 4000, [], manual_top=0.1)
    assert p.method == "manual" and p.crop[1] == 400
