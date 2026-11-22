"""조례 조건표 로더 (OrdinanceConditions).

원본: data/ordinances/ 의 분류 CSV.
- 사람이 검토를 마친 ordinance_conditions.csv 가 있으면 그것을, 없으면 ordinance_conditions_draft.csv 를 쓴다.
- row_role == '점검대상' 행만 쓴다(지원조문·개편 전 조례 제외).

scale_rule_type
- NUMERIC: 수치 그대로
- DISCRETION(단체장 재량), NONE(점검대상 조문 없음): 규모 필터 없음. 조례 평가는 경과연수만, note '조례에 규모 수치 없음'
- STRUCTURE_RULE_REF, CONSTRUCTION_ACT_REF: 외부 기준 참조. 수치를 추측하지 않는다.
  manual_override(담당자 입력 수치)가 있으면 그 값을, 없으면 규모 조건 UNKNOWN(ORD_SCALE_EXTERNAL_REF)
- USE_STRUCTURE: 용도·구조 필터

지역 매핑: 시도+시군구 이름 → sigunguCd 목록(1:N). 실패·폐지 코드만 맞는 경우는 추측하지 않고
scripts/check_ordinance_mapping.py 리포트로 사람에게 넘긴다. 수동 매핑은 mapping_overrides.csv.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from core import regions

ORD_DIR = Path(__file__).resolve().parents[1] / "data" / "ordinances"

ScaleRuleType = Literal[
    "NUMERIC", "DISCRETION", "NONE", "STRUCTURE_RULE_REF", "CONSTRUCTION_ACT_REF", "USE_STRUCTURE"
]
EXTERNAL_REF_TYPES = ("STRUCTURE_RULE_REF", "CONSTRUCTION_ACT_REF")
# 화면·내보내기용 이름(코드값을 그대로 보이지 않는다)
SCALE_RULE_LABEL = {
    "NUMERIC": "층수·연면적 수치",
    "DISCRETION": "규모 수치 없음(단체장 재량)",
    "NONE": "점검대상 조문 없음",
    "STRUCTURE_RULE_REF": "구조기준규칙의 소규모건축물 기준 참조",
    "CONSTRUCTION_ACT_REF": "건설산업기본법 제41조 기준 참조",
    "USE_STRUCTURE": "용도·구조 기준",
}
LEGAL_MIN_YEARS = 30  # 건축물관리법 제15조제1항제1호: 사용승인 후 30년 이상


class OrdinanceConditions(BaseModel):
    sido: str
    sigungu: str
    sigungu_codes: list[str] = Field(default_factory=list)
    ordinance_name: str
    effective_date: date | None = None
    source_article: str | None = None
    scale_rule_type: ScaleRuleType

    min_years: int | None = LEGAL_MIN_YEARS  # None: 조례가 연수를 따로 정함(예: 매년 고시)
    max_floors: int | None = None
    floors_bound: Literal["LE", "LT"] = "LE"
    min_floors: int | None = None
    min_floors_bound: Literal["GE", "GT"] = "GE"
    max_area: float | None = None
    area_bound: Literal["LE", "LT"] = "LE"
    use_filter: list[str] = Field(default_factory=list)  # 원문 토큰(core.normalize.use_tokens로 해석)
    structure_filter: list[str] = Field(default_factory=list)

    private_only: bool = False  # 민간건축물 한정 → 대장으로 확인 불가, 현장확인 항목
    exclusions: list[str] = Field(default_factory=list)
    collective_excluded: bool = False
    multi_housing_excluded: Literal["ALL", "MANDATORY_MGMT"] | None = None
    committee_required: bool = False
    approver: str | None = None

    manual_override: dict | None = None  # 담당자가 넣은 외부 기준 수치
    note: str | None = None
    review_needed: bool = False
    evidence_definition: str | None = None

    @property
    def name(self) -> str:
        return f"{self.sido} {self.sigungu}".strip()

    def effective_scale(self) -> dict:
        """판정에 쓸 규모 수치. 외부 참조형은 manual_override가 있을 때만 수치가 생긴다."""
        base = {
            "max_floors": self.max_floors,
            "floors_bound": self.floors_bound,
            "min_floors": self.min_floors,
            "min_floors_bound": self.min_floors_bound,
            "max_area": self.max_area,
            "area_bound": self.area_bound,
        }
        if self.manual_override:
            base.update({k: v for k, v in self.manual_override.items() if k in base and v not in (None, "")})
        return base

    def has_scale_numbers(self) -> bool:
        """ORDINANCE_ONLY 판정 조건: 조례에 규모 수치가 있는가."""
        s = self.effective_scale()
        if self.scale_rule_type in ("DISCRETION", "NONE"):
            return False
        return s["max_floors"] is not None or s["max_area"] is not None


# ---------------------------------------------------------------- CSV 읽기


def source_file() -> Path:
    reviewed = ORD_DIR / "ordinance_conditions.csv"
    return reviewed if reviewed.exists() else ORD_DIR / "ordinance_conditions_draft.csv"


def _int(v: str) -> int | None:
    v = (v or "").strip()
    return int(float(v)) if v else None


def _float(v: str) -> float | None:
    v = (v or "").strip()
    return float(v) if v else None


def _date(v: str) -> date | None:
    v = (v or "").strip()
    return datetime.strptime(v, "%Y%m%d").date() if len(v) == 8 and v.isdigit() else None


def _overrides() -> dict[str, dict]:
    """scale_overrides.csv: 외부 참조형 조례에 담당자가 넣은 수치."""
    path = ORD_DIR / "scale_overrides.csv"
    if not path.exists():
        return {}
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            name = r.get("지자체", "").strip()
            if not name:
                continue
            out[name] = {
                "max_floors": _int(r.get("max_floors", "")),
                "floors_bound": (r.get("floors_bound") or "LE").strip(),
                "max_area": _float(r.get("max_area", "")),
                "area_bound": (r.get("area_bound") or "LE").strip(),
                "entered_by": r.get("entered_by", "").strip(),
                "note": r.get("note", "").strip(),
            }
    return out


def mapping_overrides() -> dict[str, list[str]]:
    """mapping_overrides.csv: 지자체 이름 → sigunguCd 목록(; 구분). 사람이 확인해 넣는다."""
    path = ORD_DIR / "mapping_overrides.csv"
    if not path.exists():
        return {}
    out = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            name = r.get("지자체", "").strip()
            codes = [c.strip() for c in r.get("sigungu_codes", "").split(";") if c.strip()]
            if name and codes:
                out[name] = codes
    return out


def _from_row(r: dict, overrides: dict[str, dict]) -> OrdinanceConditions:
    split = lambda s: [x.strip() for x in (s or "").split("|") if x.strip()]  # noqa: E731
    return OrdinanceConditions(
        sido=r["sido"].strip(),
        sigungu=r["sigungu"].strip(),
        ordinance_name=r["ordinance_name"].strip(),
        effective_date=_date(r["effective_date"]),
        source_article=r.get("source_article") or None,
        scale_rule_type=r["scale_rule_type"].strip() or "NONE",
        min_years=_int(r["min_years"]),
        max_floors=_int(r["max_floors"]),
        floors_bound=r["floors_bound"] or "LE",
        min_floors=_int(r.get("min_floors", "")),
        min_floors_bound=r.get("min_floors_bound") or "GE",
        max_area=_float(r["max_area"]),
        area_bound=r["area_bound"] or "LE",
        use_filter=split(r["use_filter"]),
        structure_filter=split(r["structure_filter"]),
        private_only=r["private_only"] == "Y",
        exclusions=split(r["exclusions"]),
        collective_excluded=r["excl_collective"] == "Y",
        multi_housing_excluded=r["excl_multi_housing"] or None,
        committee_required=r["committee_required"] == "Y",
        approver=r["approver"] or None,
        manual_override=overrides.get(r["지자체"].strip()),
        note=r["note"] or None,
        review_needed=r["review_needed"] == "Y",
        evidence_definition=r["evidence_definition"] or None,
    )


@dataclass
class MappingResult:
    by_code: dict[str, OrdinanceConditions] = field(default_factory=dict)
    ordinances: list[OrdinanceConditions] = field(default_factory=list)
    failures: list[dict] = field(default_factory=list)  # 매칭 실패·폐지 코드만 매칭
    conflicts: dict[str, list[str]] = field(default_factory=dict)  # 같은 코드에 조례 2개 이상


@lru_cache(maxsize=1)
def load_all() -> MappingResult:
    overrides = _overrides()
    manual_map = mapping_overrides()
    result = MappingResult()
    claims: dict[str, list[OrdinanceConditions]] = {}
    with open(source_file(), encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if r["row_role"] != "점검대상":
                continue
            o = _from_row(r, overrides)
            if o.name in manual_map:
                o.sigungu_codes = manual_map[o.name]
                kind = "manual"
            else:
                m = regions.match_sigungu(o.sido, o.sigungu)
                o.sigungu_codes = m["codes"]
                kind = m["kind"]
                if not m["codes"]:
                    result.failures.append({"지자체": o.name, "kind": kind, "abolished": m["abolished"]})
            result.ordinances.append(o)
            for c in o.sigungu_codes:
                claims.setdefault(c, []).append(o)
    for code, owners in claims.items():
        if len(owners) == 1:
            result.by_code[code] = owners[0]
        else:
            result.conflicts[code] = [o.name for o in owners]
    return result


def get_ordinance(sigungu_cd: str) -> OrdinanceConditions | None:
    """sigunguCd(5자리) → 조례 조건. 없거나 매핑이 충돌하면 None."""
    return load_all().by_code.get(sigungu_cd)
