# data/notices — 검수된 공고 조건 JSON

공고 조건은 공개 문서 정보라 저장을 허용한다(건축물대장·좌표는 저장 금지).
단계 2에서 NoticeConditions 스키마가 정해지면 공고별 JSON을 여기에 둔다.

아직 비어 있다. 팀의 공고 6건 추출 결과와 사람 확정 정답을 받으면 원본은
`data/notices/legacy/`에 그대로 두고, scripts/migrate_notices.py로 새 스키마로 변환한다.

참고: frontend_grok/lib/sample-extract.json 은 화면 확인용 샘플(대전 중구, 가상)이며 정답셋이 아니다.
