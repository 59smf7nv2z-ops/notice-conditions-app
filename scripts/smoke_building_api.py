"""건축물대장 표제부 실조회 smoke 테스트 + 판정 엔진 연결 확인.

사용법 (저장소 루트, .env에 BUILDING_API_KEY 필요):
  python scripts/smoke_building_api.py
  python scripts/smoke_building_api.py "서울특별시 종로구 청운동"

출력은 건수·호출 수·소요시간·상태별 건수만. 주소는 출력하지 않는다. 결과를 파일로 저장하지 않는다.
"""

from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import building_api, normalize, ordinances, regions  # noqa: E402
from core.conditions import BusinessType, NoticeConditions  # noqa: E402
from core.evaluator import evaluate, status_counts  # noqa: E402

LEGACY_TOTAL = 359  # legacy 검증 이력: 청운동 번지 없이 일괄 조회 359건
LEGACY_COUNTS = {"후보": 65, "확인필요": 36, "제외": 258}

# legacy 검증 때 쓴 광주 동구 점검 조건(40년·3층 이하·200㎡ 미만). 원본 조건 파일은 미수령이라 수치만 옮김.
GWANGJU_DONGGU_TEST = NoticeConditions(
    notice_id="gwangju-donggu-test",
    program_name="광주 동구 조건(시험 적용)",
    business_type=BusinessType.APPLY_INSPECTION,
    min_years=40,
    max_floors=3,
    floors_bound="LE",
    max_area=200,
    area_bound="LT",
)


def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else "서울특별시 종로구 청운동"
    code = regions.find_code(target)
    if not code:
        sys.exit(f"법정동코드를 찾지 못했습니다: {target}")
    sgg, bjd = code[:5], code[5:]
    print(f"# 건축물대장 실조회: {target} (sigunguCd={sgg}, bjdongCd={bjd})")

    r = building_api.fetch_dong(sgg, bjd, progress=lambda d, t: print(f"  진행 {d}/{t} 페이지"))
    print(f"- 총건수(totalCount) {r.total_count}, 받은 건수 {len(r.df)}, API 호출 {r.api_calls}회, {r.seconds:.2f}초")
    print(f"- 응답에 없는 필드: {r.missing_fields or '없음'}")
    for w in r.warnings:
        print(f"- 경고: {w}")
    if target == "서울특별시 종로구 청운동":
        diff = len(r.df) - LEGACY_TOTAL
        print(f"- legacy {LEGACY_TOTAL}건과 비교: {'같음' if diff == 0 else f'{diff:+d}건'} (대장 갱신으로 달라질 수 있음)")

    n = normalize.normalize_df(r.df)
    print(f"- 구조 미매핑: {dict(n.unmapped_structures) or '없음'}")
    print(f"- 용도 미매핑: {dict(n.unmapped_uses) or '없음'}")

    o = ordinances.get_ordinance(sgg)
    print(f"\n# 판정 연결 (판정 기준일 {date.today().isoformat()})")
    print(f"- 조례: {o.name + ' / ' + o.scale_rule_type if o else '없음'}")
    t = time.perf_counter()
    res = evaluate(n.df, GWANGJU_DONGGU_TEST, o, date.today())
    print(f"- 광주 동구 조건 시험 적용: {status_counts(res)} ({time.perf_counter() - t:.3f}초)")
    reasons = res.loc[res.status == "NEEDS_CHECK", "check_reasons"].explode().value_counts().to_dict()
    print(f"- 확인필요 사유: {reasons}")
    if target == "서울특별시 종로구 청운동":
        print(f"- legacy 결과(기준일 미상): {LEGACY_COUNTS}  ※ legacy 제외 = v2 NOT_ELIGIBLE + ORDINANCE_ONLY")
    res_o = evaluate(n.df, None, o, date.today())
    print(f"- 공고 없이 조례 기준: {status_counts(res_o)}")


if __name__ == "__main__":
    main()
