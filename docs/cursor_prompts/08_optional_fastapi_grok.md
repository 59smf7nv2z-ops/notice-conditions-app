# [선택] grok 웹앱 화면을 계속 쓰는 경우 — FastAPI 백엔드
조건: grok 웹앱 소스를 내려받아 frontend/에 넣을 수 있고, 발표·배포를 그 화면으로 하기로 했을 때만 진행한다.
Streamlit 앱과 같은 core/를 공유하므로 단계 1~6의 로직은 그대로 쓴다.

## 할 일
- api/main.py (FastAPI)
  - GET  /regions/sido, /regions/sigungu?sido=, /regions/bjdong?sigunguCd=
  - GET  /notices?sigunguCd=, GET /ordinances/{sigunguCd}
  - POST /evaluate {sigunguCd, bjdongCds, notice_id 또는 notice_json, eval_date} → 판정 결과 JSON
  - POST /geocode {pnus 또는 행 목록} → 좌표 (서버 저장 없음)
  - POST /extract (multipart, 여러 파일) → 분류 + NoticeConditions
  - POST /letters {notice, tone, 대상 행} → docx 스트림
  - POST /export {결과} → xlsx 스트림
- 서버는 요청-응답만 처리하고 대장·좌표를 저장하지 않는다. 클라이언트가 세션 동안 결과를 들고 있는다.
- 키는 서버 .env에만 둔다. 프런트에 키를 노출하지 않는다. CORS는 프런트 도메인만 허용.
- 프런트의 샘플 데이터·모의 대장 호출부를 위 API 호출로 바꾼다. 화면 구조는 유지한다.
- 지도는 프런트의 Leaflet을 그대로 쓰고 /geocode 결과로 마커를 그린다.

## 완료 기준
Streamlit과 grok 화면에서 같은 지역·공고로 판정했을 때 상태별 건수가 같다(tests/test_api_parity.py).
