"""조례 조문 → 점검 대상 규모 조건 분류 초안 (규칙 기반).

사람이 검토하기 위한 초안을 만든다. 확정값이 아니다.
- 확실히 읽히는 수치·표현만 채우고, 애매하면 비우고 '검토필요'에 사유를 남긴다.
- 수치를 추측하지 않는다(외부 기준 참조형은 수치 칸을 비운다).

사용법 (저장소 루트에서):
  python scripts/classify_ordinances.py
  python scripts/classify_ordinances.py <조례 CSV> <출력 CSV>

기본 입력:  data/ordinances/ordinances_raw.csv  (컬럼: 지자체, 조례명, 시행일, 조문)
기본 출력:  data/ordinances/ordinance_conditions_draft.csv

출력은 '초안'이다. review_needed=Y 행은 사람이 원문을 확인해야 한다.
사람이 확정한 값은 아래 MANUAL에 넣고 confirmed=True로 표시한다.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SRC = ROOT / "data" / "ordinances" / "ordinances_raw.csv"
DEFAULT_DST = ROOT / "data" / "ordinances" / "ordinance_conditions_draft.csv"

# ---------------------------------------------------------------- 공통 도구

KOR_DIGIT = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}


def parse_area(raw: str) -> float | None:
    """'5백', '1천', '1천500', '1,000', '660' → 숫자. 해석 못 하면 None."""
    s = raw.replace(",", "").replace(" ", "")
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return float(s)
    m = re.fullmatch(r"(\d*)천(\d*)", s)
    if m:
        return float((int(m.group(1) or 1)) * 1000 + int(m.group(2) or 0))
    m = re.fullmatch(r"(\d*)백(\d*)", s)
    if m:
        return float((int(m.group(1) or 1)) * 100 + int(m.group(2) or 0))
    return None


def clean(text: str) -> str:
    text = re.sub(r"<[^>]*>", " ", text)  # <개정 2023.12.26.>
    text = re.sub(r"\[[^\]]*\]", " ", text)  # [본조신설 ...]
    return re.sub(r"\s+", " ", text).strip()


def split_sido(name: str) -> tuple[str, str]:
    parts = name.split(maxsplit=1)
    return (parts[0], parts[1] if len(parts) > 1 else "")


def list_items(block: str) -> list[str]:
    """'1. … 2. …' 형식 목록을 항목 리스트로."""
    items = re.split(r"(?:(?<=\s)|^)(\d{1,2})\.\s*(?![\d])", block)
    out = []
    # re.split 결과: [앞부분, 번호, 내용, 번호, 내용, ...]
    for i in range(1, len(items) - 1, 2):
        body = items[i + 1].strip(" ,.")
        if body:
            out.append(body)
    return out


# ---------------------------------------------------------------- 조문 해석

DEF_RE = re.compile(
    r"조례\s*로\s*정하는\s*(?:규모의\s*)?건축물[”\"’']?\s*(?:이란|은|과[^이]*이란)\s*(?P<def>.*?)(?:을|를)?\s*말(?:한다|하며)"
)
# '구조적 균열'의 '조적'을 조적조로 읽지 않도록 '구' 뒤의 '조적'은 제외
MASONRY_RE = re.compile(r"(?<!구)조적|벽돌|블[럭록]|연와")


def first_paragraph(text: str) -> str:
    """① 항(없으면 본문 전체)에서 ② 앞까지."""
    cut = text.find("②")
    return text[: cut] if cut > 0 else text


def classify(row: dict) -> dict:
    jur = row["지자체"].strip()
    name = row["조례명"].strip()
    raw = row["조문"]
    m = re.match(r"^(\d{6})Y", raw)
    art_code = m.group(1) if m else ""
    art_no = ""
    if art_code:
        main, sub = int(art_code[:4]), int(art_code[4:])
        art_no = f"제{main}조" + (f"의{sub}" if sub else "")
    text = clean(raw[7:] if m else raw)
    para1 = first_paragraph(text)
    sido, sigungu = split_sido(jur)

    out = {
        "지자체": jur,
        "sido": sido,
        "sigungu": sigungu,
        "ordinance_name": name,
        "effective_date": row["시행일"].strip(),
        "source_article": art_no,
        "row_role": "점검대상",
        "scale_rule_type": "",
        "min_years": "30",
        "max_floors": "",
        "floors_bound": "",
        "min_floors": "",
        "min_floors_bound": "",
        "max_area": "",
        "area_bound": "",
        "use_filter": "",
        "structure_filter": "",
        "private_only": "",
        "exclusions": "",
        "excl_collective": "",
        "excl_multi_housing": "",
        "committee_required": "",
        "approver": "",
        "evidence_definition": "",
        "evidence_exclusion": "",
        "note": "",
        "review_needed": "",
        "review_reason": "",
    }
    reasons: list[str] = []

    # --- 행 구분: 지원 조문 / 개편 전 조례 -------------------------------
    title = text[:40]
    if ("지원" in title or "재정지원" in title) and "점검" not in title.split("제")[0]:
        out["row_role"] = "지원조문(점검대상 아님)"
        out["scale_rule_type"] = ""
        out["min_years"] = ""
        return out
    base = sigungu.split()[-1] if sigungu else ""
    if base and base not in name and sido not in ("세종특별자치시", "제주특별자치도"):
        # 예: 지자체=인천 제물포구, 조례명=인천광역시 동구 조례 → 개편 전 조례
        short = re.sub(r"(특별자치)?(시|군|구)$", "", base)
        if short not in name:
            out["row_role"] = "개편전조례(대체됨)"
            reasons.append(f"지자체({jur})와 조례명({name})이 다름: 개편 전 조례로 보임")

    # --- 정의 구절 -------------------------------------------------------
    dm = DEF_RE.search(para1)
    definition = dm.group("def").strip() if dm else ""
    list_form = False
    if not definition or re.search(r"다음 각 호(?:에|의 어느 하나에) 해당하는 (?:건축물|경우)$", definition):
        # 정의가 목록형(다음 각 호에 해당하는 …)이거나 정의 문장이 없는 '점검의 실시'형
        list_form = True
        definition = definition or para1[:400]
    out["evidence_definition"] = definition[:500]

    # 목록형이면 목록 본문까지 수치 탐색 범위로 쓴다
    scope = para1 if list_form else definition

    # --- 경과연수 --------------------------------------------------------
    if "매년 정" in para1:
        out["min_years"] = ""
        reasons.append("경과연수를 '매년 정한다'고 함 → 해당 연도 공고·고시로 확인")
    yrs = sorted({int(y) for y in re.findall(r"(\d+)\s*년\s*이상", scope)})
    if yrs and yrs != [30]:
        out["min_years"] = "/".join(str(y) for y in yrs)
        reasons.append(f"점검 대상 정의에 30년이 아닌 경과연수({out['min_years']}년) 등장")

    # --- 층수 ------------------------------------------------------------
    fl_max = re.findall(r"(\d+)\s*층\s*이하", scope)
    fl_lt = re.findall(r"(\d+)\s*층\s*미만", scope)
    fl_min = re.findall(r"(\d+)\s*층\s*이상", scope)
    if fl_max and not fl_lt:
        out["max_floors"], out["floors_bound"] = fl_max[0], "LE"
    elif fl_lt and not fl_max:
        out["max_floors"], out["floors_bound"] = fl_lt[0], "LT"
    if len(set(fl_max + fl_lt)) > 1:
        reasons.append(f"층수 상한이 여러 개({fl_max + fl_lt})")
    if fl_min:
        out["min_floors"], out["min_floors_bound"] = fl_min[0], "GE"
        reasons.append(f"'{fl_min[0]}층 이상' 하한이 있음(min_floors, GE=이상)")

    # --- 연면적 ----------------------------------------------------------
    areas = re.findall(
        r"연면적\s*(?:이|의\s*합계가)?\s*([0-9,]*\s*[천백]?\s*[0-9,]*)\s*제곱미터\s*(이하|미만)", scope
    )
    parsed = [(parse_area(a), b) for a, b in areas if a.strip()]
    if parsed:
        val, bound = parsed[0]
        if val is None:
            reasons.append(f"연면적 숫자 해석 실패: {areas[0][0]}")
        else:
            out["max_area"] = f"{val:g}"
            out["area_bound"] = "LE" if bound == "이하" else "LT"
        if len({p for p in parsed}) > 1:
            reasons.append(f"연면적 조건이 여러 개({areas})")

    # --- 용도·구조 -------------------------------------------------------
    uses = []
    if "단독주택" in scope:
        uses.append("단독주택(다가구주택 제외)" if "다가구주택은 제외" in scope or "다가구주택 제외" in scope else "단독주택")
    if "지역아동센터" in scope:
        uses.append("지역아동센터")
    out["use_filter"] = "|".join(uses)
    if MASONRY_RE.search(scope):
        out["structure_filter"] = "조적조"
    out["private_only"] = "Y" if re.search(
        r"민간\s*건축물|공공건축물을 제외|공공건축물이 아닌|국가ㆍ지방자치단체.{0,30}소유", para1
    ) else ""

    # --- 인정 주체·위원회 --------------------------------------------------
    out["committee_required"] = "Y" if re.search(r"위원", definition) else "N"
    for who in ("지역건축안전센터", "건축안전센터", "안전진단기관", "건축물관리점검기관", "구청장", "군수", "시장"):
        if who in definition:
            out["approver"] = who
            break

    # --- 제외 대상 -------------------------------------------------------
    excl_block = ""
    em = re.search(r"다만[,，]?\s*(.*)$", para1)
    if em and "제외" in em.group(1)[:200]:
        excl_block = em.group(1)
    elif re.search(r"다음 각 호.{0,60}(?:건축물을|경우를)?\s*제외한", definition) or "해당되지 않으며" in definition:
        excl_block = para1[dm.end():] if dm else ""
    items: list[str] = []
    if excl_block:
        head = excl_block[: excl_block.find("제외") + 2]
        if em and "다음 각 호" not in head:
            # "다만, A, B, C 등 … 건축물은 제외한다." 처럼 문장 안에 바로 나열한 경우
            sentence = re.sub(r"\s*(?:은|는)\s*제외$", "", head.strip())
            items = [p.strip() for p in re.split(r",\s*(?=[「법영])", sentence) if p.strip()]
            out["evidence_exclusion"] = head
        else:
            items = list_items(excl_block) or [excl_block.strip()[:200]]
            out["evidence_exclusion"] = excl_block[:600]
    # 정의 문장 안에 직접 쓴 제외: "…, …, … 등 의무관리대상 건축물을 제외한 민간건축물"
    inline = re.search(r"^(.*?)(?:을|를)\s*제외한", definition)
    if inline and "다음 각 호" not in inline.group(1):
        phrase = re.split(r"중\s", inline.group(1))[-1]  # "30년 이상 지난 건축물중 공공건축물" → "공공건축물"
        items += [p.strip() for p in re.split(r",\s*(?=[「법영])", phrase) if p.strip()]
        out["evidence_exclusion"] = (out["evidence_exclusion"] + " " + phrase).strip()[:600]
    out["exclusions"] = " | ".join(i[:120] for i in items)
    joined = " ".join(items)
    out["excl_collective"] = "Y" if "집합건" in joined else ""
    if re.search(r"주택법.{0,15}공동주택", joined):
        out["excl_multi_housing"] = "ALL"  # 주택법상 공동주택 전체
    elif "의무관리대상 공동주택" in joined:
        out["excl_multi_housing"] = "MANDATORY_MGMT"  # 공동주택관리법 의무관리대상만
    else:
        out["excl_multi_housing"] = ""

    # --- 유형 결정 -------------------------------------------------------
    has_num = bool(out["max_floors"] or out["max_area"])
    struct_ref = "구조기준" in scope
    constr_ref = "건설산업" in scope
    discretion_word = re.search(r"(구청장|군수|시장)[이가]?\s*(?:점검이\s*)?필요하다고\s*인정", scope)

    if list_form and re.search(r"그 밖에|어느 하나|다음 각 호에 해당", para1) and (discretion_word or "위원회" in para1):
        out["scale_rule_type"] = "DISCRETION"
        ref = []
        if out["max_floors"]:
            ref.append(f"{out['max_floors']}층 {'이하' if out['floors_bound'] == 'LE' else '미만'}")
        if out["max_area"]:
            ref.append(f"연면적 {out['max_area']}㎡ {'이하' if out['area_bound'] == 'LE' else '미만'}")
        if out["structure_filter"]:
            ref.append(out["structure_filter"])
        out["note"] = ("참고 수치(OR 조건 중 하나): " + ", ".join(ref)) if ref else ""
        out["max_floors"] = out["floors_bound"] = out["max_area"] = out["area_bound"] = out["structure_filter"] = ""
        reasons.append("목록형 'OR' 정의: 수치 기준 외에 단체장·위원회 인정으로도 대상이 됨 → 규모 필터 없음(DISCRETION), 수치는 note에 참고로만")
    elif constr_ref:
        out["scale_rule_type"] = "CONSTRUCTION_ACT_REF"
        if re.search(r"시공하여야\s*하는", scope):
            out["note"] = "시공자 조건 표현: '시공하여야 하는 건축물 이외'(법적 의무 기준)"
        elif re.search(r"시공한", scope):
            out["note"] = "시공자 조건 표현: '시공한 건축물 이외'(실제 시공 사실 기준)"
        if has_num:
            reasons.append("건설산업기본법 참조와 층수 수치가 함께 있음")
    elif has_num:
        out["scale_rule_type"] = "NUMERIC"
        if struct_ref:
            reasons.append("구조기준규칙을 인용하면서 수치도 명시: 명시된 수치를 사용")
    elif struct_ref:
        out["scale_rule_type"] = "STRUCTURE_RULE_REF"
    elif out["use_filter"] or out["structure_filter"]:
        out["scale_rule_type"] = "USE_STRUCTURE"
    elif discretion_word or out["private_only"]:
        out["scale_rule_type"] = "DISCRETION"
    else:
        out["scale_rule_type"] = ""
        reasons.append("유형을 자동으로 정하지 못함")

    if out["scale_rule_type"] == "NUMERIC" and (out["use_filter"] or out["structure_filter"]):
        reasons.append("수치 + 용도/구조 조건이 함께 있음(둘 다 적용)")
    if not dm:
        reasons.append("'조례로 정하는 규모의 건축물이란 … 말한다' 정의 문장이 없음(점검의 실시형 등)")
    if out["max_floors"] and not out["max_area"] and out["scale_rule_type"] == "NUMERIC":
        reasons.append("층수만 있고 연면적 없음")
    if " 또는 " in definition and out["committee_required"] == "Y":
        reasons.append("인정 주체가 '또는'으로 둘 이상")

    # --- 규칙으로 못 잡는 조례: 조문을 직접 읽고 정한 값 -----------------------
    manual = MANUAL.get(jur)
    if manual and out["row_role"] == "점검대상":
        out.update(manual["set"])
        if manual.get("confirmed"):
            # 사람이 원문을 확인해 확정한 행: 자동 사유는 지우고 확정 근거만 남긴다
            out["review_needed"] = ""
            out["review_reason"] = "검토 확정: " + manual["why"]
            return out
        reasons.append("수동 판단: " + manual["why"])

    out["review_needed"] = "Y" if reasons else ""
    out["review_reason"] = " / ".join(reasons)
    return out


# 조문 전문을 읽고 정한 값. 사람 검토 대상(review_needed=Y)으로 남긴다.
MANUAL: dict[str, dict] = {
    "서울특별시 동작구": {
        "set": {
            "scale_rule_type": "DISCRETION",
            "min_years": "30",
            "structure_filter": "",
            "note": "1호: 사용승인 50년 이상이면 규모 무관 대상 / 2호: 30년 이상 + 균열·축대 침하 등 구청장 인정",
        },
        "why": "50년 이상 무조건 대상과 30년+구청장 인정의 OR 구조. 규모 수치 없음",
    },
    "충청남도 당진시": {
        "set": {
            "scale_rule_type": "CONSTRUCTION_ACT_REF",
            "min_floors": "3",
            "min_floors_bound": "GE",
            "max_floors": "",
            "floors_bound": "",
            "note": "AND 조건: 3층 이상(>=3) + 건설사업자가 '시공한' 건축물 이외. "
            "층수 미달이면 조례 불충족, 층수 충족 시 시공자 여부는 대장으로 확정 불가 → 확인필요"
            "(사유: 건설산업기본법 제41조 건설사업자 시공 여부 확인 필요)",
        },
        "why": "'3층 이상'은 오기가 아니라 의도된 하한(2026-11-15 담당자 검토)",
        "confirmed": True,
    },
    "충청남도 아산시": {
        "set": {
            "scale_rule_type": "CONSTRUCTION_ACT_REF",
            "note": "AND 조건: 3층 이하(<=3) + 건설사업자가 '시공한' 건축물 이외. "
            "층수 초과면 조례 불충족, 층수 충족 시 시공자 여부는 대장으로 확정 불가 → 확인필요",
        },
        "why": "당진과 같은 구조(층수 조건 + 시공자 조건 AND)로 처리. 층수 방향만 반대(이하)",
        "confirmed": False,
    },
}


def classify_file(src: Path) -> list[dict]:
    with open(src, encoding="utf-8-sig", newline="") as f:
        return [classify(r) for r in csv.DictReader(f)]


def main(src: Path, dst: Path) -> None:
    results = classify_file(src)
    with open(dst, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)
    inspect = [r for r in results if r["row_role"] == "점검대상"]
    review = sum(r["review_needed"] == "Y" for r in inspect)
    print(f"{len(results)}행 → {dst}")
    print(f"점검대상 {len(inspect)}곳, 검토필요 {review}곳")


if __name__ == "__main__":
    if len(sys.argv) == 3:
        main(Path(sys.argv[1]), Path(sys.argv[2]))
    else:
        main(DEFAULT_SRC, DEFAULT_DST)
