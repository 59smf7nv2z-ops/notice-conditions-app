"""세션 상태와 화면 공통 맥락.

대장 원본·판정 결과는 st.session_state에만 둔다. @st.cache_data는 서버 프로세스에 남아
다른 사용자 세션과 공유되므로 대장 데이터에는 쓰지 않는다. 새로고침·세션 종료 시 사라지는 것이 정상이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import streamlit as st

from core.conditions import NoticeConditions
from core.evaluator import EvalOptions
from core.ordinances import OrdinanceConditions

KEYS = {
    "raw": dict,  # (sigunguCd, bjdongCd) → 대장 DataFrame
    "results": dict,  # (sigunguCd, bjdongCd, condition_hash) → 판정 DataFrame
    "queried": dict,  # sigunguCd → set(bjdongCd) 조회한 동(누적)
    "failed": dict,  # sigunguCd → {bjdongCd: 사유}
    "notice_edits": dict,  # notice_id → 담당자 수정본(세션 한정)
    "estimate": dict,  # (sigunguCd, 동 목록) → estimate_calls 결과
    "checklist": dict,  # (대장PK, 항목) → 체크 여부
}


def load_secrets_into_env() -> None:
    """배포 서버(Streamlit Community Cloud 등)의 Secrets를 환경변수로 옮긴다.

    core/는 os.environ(.env)에서만 키를 읽는다. 서버에는 .env가 없으므로 Secrets 맨 위 단계의
    문자열 값을 같은 이름의 환경변수로 넣는다. 이미 있는 환경변수는 덮어쓰지 않는다.
    secrets.toml이 없는 로컬 PC에서는 아무것도 하지 않는다. 값은 화면·로그에 쓰지 않는다.
    """
    import os

    try:
        items = dict(st.secrets)
    except Exception:  # secrets.toml 없음(로컬 .env 사용)
        return
    for name, value in items.items():
        if isinstance(value, (str, int, float)) and not isinstance(value, bool) and not os.environ.get(name):
            os.environ[name] = str(value)


def init() -> None:
    for k, factory in KEYS.items():
        if k not in st.session_state:
            st.session_state[k] = factory()


def clear() -> None:
    for k in KEYS:
        st.session_state.pop(k, None)
    init()


@dataclass
class Ctx:
    sido: str
    sigungu_cd: str
    sigungu_name: str
    bjdong_cds: list[str]
    bjdong_names: dict[str, str]
    all_selected: bool
    eval_date: date
    notice: NoticeConditions | None
    notice_edited: bool
    test_mode: bool
    ordinance: OrdinanceConditions | None
    options: EvalOptions = field(default_factory=EvalOptions)

    @property
    def region_label(self) -> str:
        return f"{self.sido} {self.sigungu_name}".replace(f"{self.sido} {self.sido}", self.sido)

    @property
    def dong_label(self) -> str:
        """사이드바에서 고른 읍·면·동. 전체면 '모든 동'(읍·면이 있으면 '모든 읍·면·동'), 셋 이상이면 'OO동 외 N곳'."""
        if self.all_selected:
            rural = any(n.endswith(("읍", "면")) for n in self.bjdong_names.values())
            return "모든 읍·면·동" if rural else "모든 동"
        names = [self.bjdong_names.get(b, b) for b in self.bjdong_cds]
        if not names:
            return ""
        return "·".join(names) if len(names) <= 2 else f"{names[0]} 외 {len(names) - 1}곳"
