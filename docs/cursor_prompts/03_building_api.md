# [단계 3/7] 건축물대장 표제부 법정동 단위 일괄 조회 (인메모리)

## 목표
(sigunguCd, bjdongCd) → 해당 법정동 전체 표제부 DataFrame. 중간 파일 저장 없음.
"API로 추출 → 파일 저장 → 재입력" 흐름을 "조회 즉시 메모리에서 일괄 대조"로 바꾸는 기반이다.

## 구현 (core/building_api.py)
- legacy 조회 스크립트를 이식한다. 검증된 URL·파라미터·파싱은 유지하고, 아래와 다르면 legacy를 우선하고 보고한다.
- 서비스: 공공데이터포털 "국토교통부_건축HUB_건축물대장정보 서비스", 오퍼레이션 getBrTitleInfo
  (서비스 URL .../1613000/BldRgstHubService)
- 파라미터: serviceKey(.env BUILDING_API_KEY), sigunguCd, bjdongCd, numOfRows, pageNo, _type=json. bun·ji는 생략.
  - Decoding 키를 requests params로 넘겨 이중 인코딩을 피한다.
  - numOfRows: 공개 명세의 기본값은 10이다. 최대값은 실제 호출로 확인해 상수로 둔다(100으로 알려져 있음).
  - totalCount로 페이지 수를 계산한다.
- 응답 파싱 함정
  - items.item이 1건이면 dict, 0건이면 빈 문자열이거나 없음 → 항상 list로 정규화
  - 숫자 필드가 문자열로 옴 → 변환 실패는 NaN
  - useAprDay는 문자열로 유지(판정에서 해석)
  - 키 오류 등은 _type=json이어도 XML로 올 수 있음 → 감지해서 명확한 예외
- 오류 처리
  - resultCode가 정상이 아니면 예외
  - 일일 허용량 초과(코드 22) → BuildingApiQuotaError로 즉시 중단, 지금까지 받은 동은 유지
  - 초당 허용량 초과(코드 23), timeout, 5xx → tenacity 지수 백오프 최대 3회
- 동시성: 페이지 병렬 최대 3(설정 가능). progress(done, total) 콜백 인자.
- 반환 컬럼(원 필드명 유지): mgmBldrgstPk, platPlc, newPlatPlc, bldNm, dongNm, mainAtchGbCdNm,
  regstrGbCdNm, regstrKindCdNm, strctCdNm, etcStrct, mainPurpsCdNm, etcPurps, grndFlrCnt, ugrndFlrCnt,
  totArea, useAprDay, hhldCnt, fmlyCnt, sigunguCd, bjdongCd, platGbCd, bun, ji
  실제 응답에 없는 필드는 보고한다.
- make_pnu(row) -> 19자리: sigunguCd + bjdongCd + 토지구분(API platGbCd 0 → 1, 1 → 2) + bun 4자리 + ji 4자리.
  지도 단계에서 필지 단위 묶음에 쓴다.
- estimate_calls(sigunguCd, bjdongCds): numOfRows=1로 totalCount만 먼저 받아 예상 호출 수 계산(UI 경고용).

## 캐시 원칙
- core는 순수 함수(저장 없음).
- Streamlit에서는 st.session_state["raw"][(sigunguCd, bjdongCd)]에만 둔다.
  @st.cache_data는 서버 프로세스에 남아 다른 사용자 세션과 공유되므로 대장 데이터에는 쓰지 않는다.

## 테스트
- responses(또는 requests-mock)로: 0건, 1건(dict), 여러 페이지, 코드 22, 코드 23 후 성공, XML 오류 응답
- 실제 호출 테스트는 @pytest.mark.live(기본 skip)
- scripts/smoke_building_api.py: regions로 "서울특별시 종로구 청운동" 코드를 찾아 실조회 →
  총건수·소요시간·호출 수 출력, legacy 359건과 비교(대장 갱신으로 달라질 수 있다고 출력에 표시)

## 완료 기준
단위 테스트 통과, smoke 스크립트 실조회 성공. 조회 결과를 evaluator(v2)에 바로 넣어 상태별 건수가 나오는지 확인.
