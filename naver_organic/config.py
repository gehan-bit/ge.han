"""config/organic.yaml, config/organic_selectors.yaml 읽기."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "organic.yaml"
SELECTORS_PATH = ROOT / "config" / "organic_selectors.yaml"


def normalize_name(s: str) -> str:
    """업체명 비교용 정규화: 소문자, 공백·기호 제거."""
    s = s.lower()
    s = re.sub(r"\(.*?\)", " ", s)          # 괄호 안(지점 설명)은 비교에서 뺀다
    s = re.sub(r"[\s\-_·.,/&'\"!?~]+", "", s)
    return s


@dataclass
class Business:
    name: str
    aliases: list[str] = field(default_factory=list)

    def keys(self) -> list[str]:
        return [normalize_name(a) for a in [self.name, *self.aliases] if a.strip()]

    def matches(self, place_name: str) -> bool:
        n = normalize_name(place_name)
        return any(k and k in n for k in self.keys())


@dataclass
class Config:
    brand: Business
    seed_keywords: list[str]
    test_keywords: list[str]
    competitors: list[Business]
    crawl: dict[str, Any]
    output: dict[str, Any]
    raw: dict[str, Any]

    def classify(self, place_name: str) -> tuple[str, str]:
        """(구분, 일치한 후보 이름). 구분: 우리 지점 / 경쟁사 후보 / 기타"""
        if self.brand.matches(place_name):
            return "우리 지점", self.brand.name
        for c in self.competitors:
            if c.matches(place_name):
                return "경쟁사 후보", c.name
        return "기타", ""


def load_config(path: Path | str | None = None) -> Config:
    p = Path(path) if path else CONFIG_PATH
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    b = raw.get("brand", {})
    comps = []
    for c in raw.get("competitor_candidates", []) or []:
        if isinstance(c, str):
            comps.append(Business(c, []))
        else:
            comps.append(Business(c["name"], list(c.get("aliases") or [])))
    return Config(
        brand=Business(b.get("name", ""), list(b.get("aliases") or [])),
        seed_keywords=list(raw.get("seed_keywords") or []),
        test_keywords=list(raw.get("test_keywords") or []),
        competitors=comps,
        crawl=dict(raw.get("crawl") or {}),
        output=dict(raw.get("output") or {}),
        raw=raw,
    )


def load_selectors(path: Path | str | None = None) -> dict[str, Any]:
    p = Path(path) if path else SELECTORS_PATH
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def as_list(v: Any) -> list[str]:
    if v is None:
        return []
    return [v] if isinstance(v, str) else list(v)
