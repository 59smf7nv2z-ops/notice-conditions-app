"""조례 ↔ 시군구코드 매핑 점검 리포트.

사용법 (저장소 루트):
  python scripts/check_ordinance_mapping.py

출력
1. 매칭 실패(이름 없음 / 폐지 코드만 맞음) → mapping_overrides.csv에 사람이 넣는다
2. 같은 코드에 조례가 둘 이상(충돌)
3. 1:N 매핑(일반구가 있는 시, 세종·제주)
4. 행정구역 개편 지역(인천 제물포·영종·검단·서해구, 전남광주통합특별시): 자동 매핑 결과를 사람이 확인
5. 조례가 없는 시군구
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import ordinances, regions  # noqa: E402

REORG_INCHEON = ("제물포구", "영종구", "검단구", "서해구")
REORG_SIDO = "전남광주통합특별시"


def table(headers: list[str], rows: list[list[object]]) -> str:
    if not rows:
        return "(없음)\n"
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join("" if v is None else str(v) for v in r) + " |" for r in rows]
    return "\n".join(lines) + "\n"


def main() -> None:
    m = ordinances.load_all()
    print(f"# 조례 매핑 점검 ({ordinances.source_file().name})\n")
    print(f"- 점검대상 조례 {len(m.ordinances)}건, 매핑된 시군구코드 {len(m.by_code)}개")
    print(f"- 법정동코드 파일: {regions._ref_file().name}\n")

    print("## 1. 매칭 실패 / 폐지 코드만 매칭")
    print(table(["지자체", "결과", "폐지 코드"], [[f["지자체"], f["kind"], ", ".join(f["abolished"])] for f in m.failures]))

    print("## 2. 같은 코드에 조례 둘 이상")
    print(table(["sigunguCd", "이름", "조례"], [[c, regions.name_of(c), ", ".join(v)] for c, v in sorted(m.conflicts.items())]))

    print("## 3. 1:N 매핑 (조례 1개 : 시군구코드 N개)")
    multi = [o for o in m.ordinances if len(o.sigungu_codes) > 1]
    print(table(["지자체", "코드", "이름"], [[o.name, ", ".join(o.sigungu_codes), ", ".join(regions.name_of(c) or "?" for c in o.sigungu_codes)] for o in multi]))

    print("## 4. 행정구역 개편 지역 — 사람 확인 필요 (자동 추정 아님: 현재 '존재' 코드와 이름이 정확히 같을 때만 연결)")
    reorg = [
        o
        for o in m.ordinances
        if o.sido == REORG_SIDO or (o.sido == "인천광역시" and o.sigungu in REORG_INCHEON)
    ]
    print(
        table(
            ["지자체", "연결된 코드", "조례명", "시행일"],
            [[o.name, ", ".join(o.sigungu_codes) or "(없음)", o.ordinance_name, o.effective_date] for o in reorg],
        )
    )
    print("참고: 인천 중구·동구·서구, 광주광역시(29)·전라남도(46) 코드는 법정동코드상 모두 '폐지'.")
    print("건축물대장 API가 새 코드(12xxx, 28125 등)로 조회되는지는 단계 3에서 실제 호출로 확인한다.\n")

    print("## 5. 조례가 없는 시군구")
    missing = []
    for sido in regions.list_sido():
        for code, name in regions.list_sigungu(sido):
            if code not in m.by_code and code not in m.conflicts:
                missing.append([code, f"{sido} {name}" if name != sido else sido])
    print(table(["sigunguCd", "이름"], missing))
    print(f"→ {len(missing)}곳. 이 지역은 공고가 없으면 '법정 기준(30년)만 적용'으로 판정한다.\n")

    review = [o for o in m.ordinances if o.review_needed]
    print(f"## 참고: 분류 검토필요 조례 {len(review)}건 (data/ordinances/ordinance_conditions_draft.csv review_needed=Y)")


if __name__ == "__main__":
    main()
