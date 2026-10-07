"""사진 가공: 세로 사진을 5:4로 자르되 얼굴·로고가 잘리지 않게.

규칙(작성 원칙 + 요청):
  - 가로 사진은 원본 비율 그대로(크기만 줄임)
  - 세로 사진은 가로:세로 = 5:4로 자른다. 폭은 그대로 두고 높이만 자른다(확대 금지)
  - 얼굴이 자른 사진의 가운데 또는 위에서 1/3 지점에 오게 한다(기본 1/3, 안 되면 가운데)
  - 얼굴(머리카락 여유 포함)과 보호 영역(로고 등)은 잘리지 않게 한다
  - 자동으로 못 정하면 needs_review 표시 → review.jpg에서 눈으로 확인하고 overrides로 고친다

얼굴 검출: OpenCV YuNet(models/face_detection_yunet_2023mar.onnx, Apache-2.0).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "face_detection_yunet_2023mar.onnx"
RATIO_W, RATIO_H = 5, 4


@dataclass
class Box:
    x: int
    y: int
    w: int
    h: int
    kind: str = "face"      # face | logo | protect
    conf: float = 1.0

    @property
    def x2(self) -> int:
        return self.x + self.w

    @property
    def y2(self) -> int:
        return self.y + self.h

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    def padded(self, top: float, side: float, bottom: float) -> "Box":
        return Box(
            int(self.x - self.w * side),
            int(self.y - self.h * top),
            int(self.w * (1 + 2 * side)),
            int(self.h * (1 + top + bottom)),
            self.kind,
            self.conf,
        )


@dataclass
class CropPlan:
    src: str
    width: int
    height: int
    crop: tuple[int, int, int, int] | None   # (left, top, right, bottom) / None이면 자르지 않음
    method: str                               # original | face-third | face-center | face-fit | center | manual
    faces: list[dict[str, Any]] = field(default_factory=list)
    protects: list[dict[str, Any]] = field(default_factory=list)
    needs_review: bool = False
    notes: list[str] = field(default_factory=list)
    out: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Override:
    """photos.yaml 의 overrides 항목. 모두 0~1 비율(이미지 높이/폭 기준) 또는 픽셀."""

    top: float | None = None            # 자를 위치를 직접 지정(위쪽 y, 비율)
    focus_y: float | None = None        # 이 지점을 얼굴 기준점으로 사용(비율)
    anchor: str | None = None           # third | center
    protect: list[list[float]] = field(default_factory=list)  # [[x,y,w,h], ...] 비율
    skip_crop: bool = False             # 세로여도 자르지 않음
    rotate: int = 0                     # 90/180/270 추가 회전


# ---------- 로드 ----------
def load_image(path: Path | str) -> Image.Image:
    im = Image.open(path)
    im = ImageOps.exif_transpose(im)
    return im.convert("RGB")


_detector = None


def _get_detector():
    global _detector
    if _detector is None:
        import cv2  # 지연 import: 크롭 안 쓰는 명령은 cv2 없이도 돌게

        if not MODEL_PATH.exists():
            raise FileNotFoundError(f"얼굴 검출 모델이 없습니다: {MODEL_PATH}")
        _detector = cv2.FaceDetectorYN.create(str(MODEL_PATH), "", (320, 320), 0.7, 0.3, 5000)
    return _detector


def detect_faces(im: Image.Image, min_conf: float = 0.7, long_side: int = 1280) -> list[Box]:
    import cv2

    det = _get_detector()
    W, H = im.size
    scale = min(1.0, long_side / max(W, H))
    small = im.resize((max(1, int(W * scale)), max(1, int(H * scale))))
    arr = cv2.cvtColor(np.array(small), cv2.COLOR_RGB2BGR)
    det.setInputSize((arr.shape[1], arr.shape[0]))
    det.setScoreThreshold(min_conf)
    _, faces = det.detect(arr)
    boxes: list[Box] = []
    if faces is not None:
        for f in faces:
            x, y, w, h = (float(v) / scale for v in f[:4])
            boxes.append(Box(int(x), int(y), int(w), int(h), "face", float(f[-1])))
    # 큰 얼굴부터(주인공 우선)
    boxes.sort(key=lambda b: -b.w * b.h)
    return boxes


# ---------- 크롭 계산 ----------
def target_crop_h(W: int) -> int:
    return int(round(W * RATIO_H / RATIO_W))


def needs_crop(W: int, H: int) -> bool:
    """세로 사진(폭 < 높이)만 자른다. 가로·정사각형은 원본 비율."""
    return W < H


def _feasible_range(H: int, crop_h: int, boxes: Iterable[Box]) -> tuple[int, int] | None:
    lo, hi = 0, H - crop_h
    for b in boxes:
        lo = max(lo, b.y2 - crop_h)
        hi = min(hi, b.y)
    return (lo, hi) if lo <= hi else None


def _clamp(v: float, lo: int, hi: int) -> int:
    return int(max(lo, min(hi, round(v))))


def plan_crop(
    W: int,
    H: int,
    faces: list[Box],
    protects: list[Box] | None = None,
    anchor: str = "third",
    focus_y: float | None = None,
    manual_top: float | None = None,
    src: str = "",
) -> CropPlan:
    protects = protects or []
    plan = CropPlan(src=src, width=W, height=H, crop=None, method="original",
                    faces=[asdict(b) for b in faces], protects=[asdict(b) for b in protects])
    if not needs_crop(W, H):
        plan.notes.append("가로 사진: 원본 비율 유지")
        return plan

    crop_w = W - (W % RATIO_W)          # 폭을 5의 배수로(최대 4px 잘라냄) → 정확한 5:4
    left = (W - crop_w) // 2
    crop_h = target_crop_h(crop_w)
    if crop_h >= H:
        plan.notes.append("이미 5:4보다 낮음: 원본 유지")
        return plan
    max_top = H - crop_h

    if manual_top is not None:
        top = _clamp(manual_top * H if manual_top <= 1 else manual_top, 0, max_top)
        plan.crop = (left, top, left + crop_w, top + crop_h)
        plan.method = "manual"
        return plan

    # 보호 영역 후보를 여유(패딩)가 큰 것부터 작은 것 순서로 준비한다.
    # 1) 얼굴(머리카락 여유 넉넉히) + 지정 보호 영역  2) 얼굴(여유 조금) + 보호 영역
    # 3) 얼굴 그대로 + 보호 영역  4) 얼굴만  5) 주인공 얼굴만
    def face_sets(top_pad: float, side_pad: float, bottom_pad: float) -> list[Box]:
        out: list[Box] = []
        if faces:
            out.append(faces[0].padded(top_pad, side_pad, bottom_pad))
            for f in faces[1:]:
                if f.conf >= 0.8 and f.w * f.h >= 0.25 * faces[0].w * faces[0].h:
                    out.append(f.padded(top_pad * 0.5, side_pad * 0.5, bottom_pad * 0.5))
        return out

    candidates: list[tuple[str, list[Box]]] = [
        ("full", face_sets(0.8, 0.3, 0.3) + protects),
        ("tight", face_sets(0.4, 0.2, 0.1) + protects),
        ("bare", face_sets(0.0, 0.0, 0.0) + protects),
        ("faces-only", face_sets(0.4, 0.2, 0.1)),
        ("main-face", face_sets(0.0, 0.0, 0.0)[:1]),
    ]

    # 기준점: 주인공 얼굴 중심(또는 focus_y)
    fy: float | None
    if focus_y is not None:
        fy = focus_y * H if focus_y <= 1 else focus_y
    elif faces:
        fy = faces[0].cy
    else:
        fy = None

    if fy is None:
        # 얼굴도 기준점도 없음: 가운데보다 살짝 위(사람 사진은 위쪽에 중요한 게 많다)
        rng = _feasible_range(H, crop_h, protects)
        top = _clamp(max_top * 0.4, 0, max_top)
        if rng:
            top = _clamp(top, rng[0], rng[1])
        else:
            plan.notes.append("보호 영역을 모두 담을 수 없음")
        plan.crop = (left, top, left + crop_w, top + crop_h)
        plan.method = "center"
        plan.needs_review = True
        plan.notes.append("얼굴 미검출: 가운데 기준 자동 크롭 → 확인 필요")
        return plan

    rng = None
    for level, boxes in candidates:
        rng = _feasible_range(H, crop_h, boxes)
        if rng is not None:
            if level != "full":
                plan.notes.append(f"보호 영역 여유를 줄여 맞춤({level})")
            if level in ("faces-only", "main-face") and protects:
                plan.needs_review = True
                plan.notes.append("지정 보호 영역을 다 담을 수 없음")
            break
    if rng is None:
        rng = (0, max_top)
        plan.needs_review = True
        plan.notes.append("얼굴을 온전히 담을 수 없음")

    order = [anchor, "center" if anchor == "third" else "third"]
    chosen = None
    for a in order:
        want = fy - crop_h / 3 if a == "third" else fy - crop_h / 2
        top = _clamp(want, rng[0], rng[1])
        # 원했던 위치에서 많이 밀렸으면 다음 후보 시도
        if abs(top - want) <= crop_h * 0.08:
            chosen = (a, top)
            break
        if chosen is None:
            chosen = (a, top)  # 임시
    a, top = chosen
    want = fy - crop_h / 3 if a == "third" else fy - crop_h / 2
    if abs(top - want) > crop_h * 0.08:
        plan.method = "face-fit"
        plan.notes.append("얼굴·보호 영역을 담느라 기준점에서 벗어남")
    else:
        plan.method = f"face-{a}"
    plan.crop = (left, top, left + crop_w, top + crop_h)
    if faces and faces[0].conf < 0.8:
        plan.needs_review = True
        plan.notes.append(f"얼굴 확신도 낮음({faces[0].conf:.2f})")
    return plan


# ---------- 실행 ----------
def process_photo(
    src: Path | str,
    out_dir: Path | str,
    override: Override | None = None,
    max_width: int = 1600,
    quality: int = 90,
) -> CropPlan:
    src = Path(src)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ov = override or Override()
    im = load_image(src)
    if ov.rotate:
        im = im.rotate(-ov.rotate, expand=True)
    W, H = im.size

    faces = detect_faces(im)
    protects = [Box(int(x * W), int(y * H), int(w * W), int(h * H), "protect") for x, y, w, h in ov.protect]

    if ov.skip_crop:
        plan = CropPlan(src=str(src), width=W, height=H, crop=None, method="original",
                        faces=[asdict(b) for b in faces], protects=[asdict(b) for b in protects], notes=["skip_crop"])
    else:
        plan = plan_crop(W, H, faces, protects, anchor=ov.anchor or "third", focus_y=ov.focus_y,
                         manual_top=ov.top, src=str(src))

    out_im = im.crop(plan.crop) if plan.crop else im
    if out_im.width > max_width:
        if plan.crop:
            new_size = (max_width, max_width * RATIO_H // RATIO_W)
        else:
            new_size = (max_width, max(1, round(out_im.height * max_width / out_im.width)))
        out_im = out_im.resize(new_size, Image.LANCZOS)
    out_path = out_dir / (src.stem + ".jpg")
    out_im.save(out_path, "JPEG", quality=quality, optimize=True)  # EXIF 제거(위치정보 등)
    plan.out = str(out_path)
    return plan


def _font(size: int):
    for name in ("/System/Library/Fonts/AppleSDGothicNeo.ttc", "C:/Windows/Fonts/malgun.ttf",
                 "/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                 "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()


def review_sheet(plans: list[CropPlan], out_path: Path | str, thumb_h: int = 420) -> Path:
    """원본(크롭 박스·얼굴 표시) + 결과물을 나란히 놓은 확인용 이미지."""
    out_path = Path(out_path)
    cells: list[Image.Image] = []
    font = _font(16)
    for p in plans:
        im = load_image(p.src)
        s = thumb_h / im.height
        orig = im.resize((max(1, int(im.width * s)), thumb_h))
        d = ImageDraw.Draw(orig)
        for f in p.faces:
            d.rectangle([f["x"] * s, f["y"] * s, (f["x"] + f["w"]) * s, (f["y"] + f["h"]) * s], outline=(0, 200, 90), width=3)
        for f in p.protects:
            d.rectangle([f["x"] * s, f["y"] * s, (f["x"] + f["w"]) * s, (f["y"] + f["h"]) * s], outline=(60, 120, 255), width=3)
        if p.crop:
            l, t, r, b = p.crop
            d.rectangle([l * s, t * s, r * s - 1, b * s - 1], outline=(255, 60, 60), width=4)
            # 1/3 선
            d.line([l * s, (t + (b - t) / 3) * s, r * s, (t + (b - t) / 3) * s], fill=(255, 60, 60), width=1)
        res = load_image(p.out) if p.out else im
        rs = (thumb_h * 0.8) / res.height if res.height > res.width else (thumb_h * 0.8) / res.height
        res = res.resize((max(1, int(res.width * rs)), max(1, int(res.height * rs))))
        label_h = 48
        cell = Image.new("RGB", (orig.width + res.width + 30, thumb_h + label_h), (250, 250, 250))
        cell.paste(orig, (10, label_h))
        cell.paste(res, (orig.width + 20, label_h + (thumb_h - res.height) // 2))
        dl = ImageDraw.Draw(cell)
        flag = "  ⚠ 확인 필요" if p.needs_review else ""
        dl.text((10, 6), f"{Path(p.src).name}  [{p.method}]{flag}", fill=(20, 20, 20), font=font)
        if p.notes:
            dl.text((10, 26), " / ".join(p.notes)[:90], fill=(120, 120, 120), font=_font(13))
        cells.append(cell)
    if not cells:
        raise ValueError("표시할 사진이 없습니다")
    width = max(c.width for c in cells)
    sheet = Image.new("RGB", (width, sum(c.height for c in cells) + 10 * len(cells)), (235, 235, 235))
    y = 0
    for c in cells:
        sheet.paste(c, (0, y))
        y += c.height + 10
    sheet.save(out_path, quality=85)
    return out_path


def save_plans(plans: list[CropPlan], path: Path | str) -> None:
    Path(path).write_text(json.dumps([p.to_dict() for p in plans], ensure_ascii=False, indent=2), encoding="utf-8")
