"""지역 일괄 대조: 법정동 여러 개 조회 → 메모리에서 바로 판정.

- raw_cache(dict)에 이미 있는 동은 다시 조회하지 않는다. 조건만 바뀌면 재판정만 한다.
- 동 하나가 실패해도 나머지는 계속하고 failed_dongs에 남긴다.
- 일일 허용량 초과(BuildingApiQuotaError)면 즉시 멈추고, 그때까지 받은 동으로 부분 결과를 낸다.
- raw_cache·results_cache는 호출 측(st.session_state)이 들고 있는다. 여기서는 파일에 쓰지 않는다.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

import pandas as pd

from core import building_api, normalize
from core.conditions import NoticeConditions
from core.evaluator import EvalOptions, evaluate, status_counts
from core.notices import condition_hash
from core.ordinances import OrdinanceConditions

ProgressFn = Callable[[float, str], None]  # (0~1, 안내 문구)
FetchFn = Callable[..., "building_api.DongResult"]


@dataclass
class RegionResult:
    df: pd.DataFrame
    stats: dict[str, int]
    unmapped_structures: Counter = field(default_factory=Counter)
    unmapped_uses: Counter = field(default_factory=Counter)
    api_calls: int = 0
    warnings: list[str] = field(default_factory=list)
    failed_dongs: dict[str, str] = field(default_factory=dict)  # bjdongCd → 사유
    quota_stopped: bool = False
    condition_hash: str = ""
    test_mode: bool = False


def run_region(
    sigungu_cd: str,
    bjdong_cds: list[str],
    notice: NoticeConditions | None,
    ordinance: OrdinanceConditions | None,
    eval_date: date,
    raw_cache: dict,
    progress: ProgressFn | None = None,
    *,
    results_cache: dict | None = None,
    options: EvalOptions | None = None,
    test_mode: bool = False,
    fetch: FetchFn | None = None,
) -> RegionResult:
    fetch = fetch or building_api.fetch_dong
    options = options or EvalOptions()
    chash = condition_hash(notice, ordinance, options, eval_date, test_mode)
    result = RegionResult(df=pd.DataFrame(), stats={}, condition_hash=chash, test_mode=test_mode)

    todo = [b for b in bjdong_cds if (sigungu_cd, b) not in raw_cache]
    for i, b in enumerate(todo):
        if progress:
            progress(
                i / max(1, len(todo)),
                f"대장 조회 {i + 1}/{len(todo)}개 동 · 응답이 늦거나 일시 오류면 자동으로 다시 시도합니다(최대 약 25초)",
            )
        try:
            r = fetch(sigungu_cd, b)
        except building_api.BuildingApiQuotaError as e:
            result.quota_stopped = True
            result.failed_dongs[b] = str(e)
            for rest in todo[i + 1 :]:
                result.failed_dongs[rest] = "일일 허용량 초과로 조회하지 않음"
            result.warnings.append("일일 허용 호출량을 초과해 조회를 멈췄습니다. 지금까지 받은 동만 판정합니다.")
            break
        except building_api.BuildingApiAuthError:
            raise  # 키 문제는 모든 동이 실패하므로 바로 알린다
        except Exception as e:  # noqa: BLE001 - 동 하나 실패는 기록하고 계속
            result.failed_dongs[b] = str(e)
            continue
        raw_cache[(sigungu_cd, b)] = r.df
        result.api_calls += r.api_calls
        result.warnings += [f"{b}: {w}" for w in r.warnings]
        if r.missing_fields:
            result.warnings.append(f"{b}: 응답에 없는 필드 {r.missing_fields}")

    frames = []
    available = [b for b in bjdong_cds if (sigungu_cd, b) in raw_cache]
    for j, b in enumerate(available):
        if progress:
            progress(0.9 + 0.1 * j / max(1, len(available)), "판정 중")
        key = (sigungu_cd, b, chash)
        if results_cache is not None and key in results_cache:
            frames.append(results_cache[key])
            continue
        raw = raw_cache[(sigungu_cd, b)]
        if raw.empty:
            continue
        evaluated = evaluate(raw, notice, ordinance, eval_date, options)
        if test_mode:
            evaluated["test_mode"] = True
        if results_cache is not None:
            results_cache[key] = evaluated
        frames.append(evaluated)

    if frames:
        result.df = pd.concat(frames, ignore_index=True)
        n = normalize.normalize_df(result.df[[c for c in ("strctCdNm", "etcStrct", "mainPurpsCdNm", "etcPurps") if c in result.df.columns]])
        result.unmapped_structures, result.unmapped_uses = n.unmapped_structures, n.unmapped_uses
        result.stats = {"TOTAL": len(result.df), **status_counts(result.df)}
    else:
        result.stats = {"TOTAL": 0, "CANDIDATE": 0, "NEEDS_CHECK": 0, "ORDINANCE_ONLY": 0, "NOT_ELIGIBLE": 0}
    if progress:
        progress(1.0, "완료")
    return result
