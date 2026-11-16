# [단계 6/7] LLM 공급자 추상화(Claude/Gemini) + 공고 업로드 추출 연결

## 목표
기존 추출 코드를 공급자 독립 구조로 바꾸고, 같은 정답셋으로 Claude와 Gemini를 비교해
비용·정확도 근거로 공급자를 고를 수 있게 한다. 공급자 선택은 사람이 한다.

## 6-1 core/llm/
- base.py
  - class LLMProvider(Protocol):
    - generate_json(system: str, parts: list[Part], schema: type[BaseModel]) -> tuple[BaseModel, Usage]
    - generate_text(system: str, prompt: str) -> tuple[str, Usage]
  - Part = 텍스트 또는 (bytes, mime) — application/pdf, image/png, image/jpeg
- claude.py(anthropic SDK), gemini.py(google-genai SDK)
  - 각 SDK의 JSON 스키마 강제 기능으로 구조화 출력을 받는다.
  - pydantic 검증 실패 시 오류 메시지를 붙여 1회 재시도, 그래도 실패하면 원문과 함께 예외.
- mock.py: 키가 없을 때 샘플 결과를 돌려주는 MockProvider(grok 앱의 "키가 없으면 샘플 결과" 동작 유지)
- factory.py: .env LLM_PROVIDER=claude|gemini|mock, LLM_MODEL_EXTRACT, LLM_MODEL_WRITE.
  모델명은 자주 바뀌므로 코드에 하드코딩하지 않는다.
- 사용량 기록: data/logs/llm_usage.csv에 시각, 공급자, 모델, 작업(classify/extract/template),
  입력·출력 토큰, 문서 해시만 남긴다. 본문·주소는 남기지 않는다.

## 6-2 문서 전처리 (core/llm/preprocess.py)
- HWP·HWPX는 두 공급자 모두 직접 읽지 못한다. 기존 변환 코드를 그대로 쓴다.
  기존 코드가 없으면: HWPX는 zip 안 Contents/section*.xml 파싱(표는 마크다운 표로),
  HWP는 pyhwp(hwp5txt) 또는 LibreOffice 변환. 표 누락 여부를 정답셋 공고로 확인한다.
- PDF·이미지는 원본 그대로 전달한다. 리플릿처럼 여러 장이면 한 요청에 모두 넣는다.
  (예전 "리플릿 이미지 한 장 누락" 오류 재발 방지: 업로드 파일 수와 전달 part 수를 비교해 다르면 경고)
- 파일당 8MB 제한. 업로드 파일은 메모리에서만 처리한다.

## 6-3 분류·추출 (core/llm/extractor.py)
- classify(parts) -> business_type + 근거 인용
  APPLY_INSPECTION이 아니면 추출하지 않고 화면에 유형과 근거를 보여준다.
- extract(parts) -> NoticeConditions(단계 2 스키마) + evidence
  한 문서에 안전점검 지원과 보수·보강 지원이 함께 있으면 안전점검 섹션 조건만 추출한다.
- 기존 추출 프롬프트와 팀이 정한 항목 정의(선정방식 분류, 용도 제한과 우선순위 구분 등)를 그대로 옮긴다.
- 프롬프트에 오늘 날짜를 넣거나 마감 여부를 묻지 않는다. 날짜는 원문 그대로 추출하고 마감 판정은 코드가 한다.
- 결과는 reviewed=False로 만든다.

## 6-4 탭1 연결
- 업로드(HWP, HWPX, PDF, PNG, JPG, 여러 파일 = 한 묶음) → 분류 → 추출 → 조건 편집기(항목 클릭 시 원문 근거 표시)
- "검수 완료로 저장": reviewed=True로 data/notices/에 저장(공고 조건은 공개 문서 정보라 저장 허용).
  저장 즉시 탭2 공고 선택 목록에 나타난다.
- 화면 문구: "실제 추출을 누르면 올린 공고 파일이 {공급자}로 전송됩니다. 키가 없으면 샘플 결과만 씁니다."

## 6-5 안내문 틀 생성 연결
- letters.make_template(notice, tone)을 LLM 구현으로 교체. 공고·말투별 1회만 호출하고 세션에 캐시.
- LLM 입력은 공고 조건(접수기간, 신청방법, 접수처, 문의처, 제출서류)과 말투 지시뿐. 건물 데이터는 넣지 않는다.
- 단계 4의 틀 검증을 통과하지 못하면 내장 틀로 대체하고 경고한다.
- "문구 재생성" 버튼은 같은 공고·말투로 틀만 다시 만든다.

## 6-6 공급자 비교 (scripts/compare_providers.py)
- 기존 정답셋(공고 6건 + 사람이 확정한 정답)으로 키가 있는 공급자를 모두 실행
- 기존 정확도 계산 코드를 재사용해 표로 출력:
  공급자·모델별 항목 일치율, 문서 형식별(hwpx/hwp/이미지/PDF) 일치율, 분류 정확도,
  공고 1건당 평균 입력·출력 토큰, 재시도·실패 수
- 표만 출력하고 선택은 하지 않는다.

## 완료 기준
- MockProvider로 단위 테스트 통과
- 키가 있는 공급자로 정답셋 실행 성공
- 탭1에서 HWPX·PDF·이미지 업로드 → 분류 → 추출 → 편집 → 검수 저장 → 탭2 판정 반영까지 동작
- llm_usage.csv에 본문·주소가 없음을 테스트로 확인
