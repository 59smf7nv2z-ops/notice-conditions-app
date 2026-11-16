# [단계 5/7] 지도 드릴다운 — 특정 구역 내 가능 대상 전체 표시

## 결정 사항
- 지오코딩과 행정경계는 브이월드만 쓴다. 카카오는 쓰지 않는다.
- 브이월드 지오코더는 일일 최대 40,000건, 응답을 저장장치·DB에 저장할 수 없다 → 세션 메모리만.
- 지도 라이브러리: folium + streamlit-folium (Leaflet). 배경은 OSM 또는 브이월드 배경지도.

## 5-1 core/geocode.py
- 대상: CANDIDATE, NEEDS_CHECK (옵션으로 ORDINANCE_ONLY). NOT_ELIGIBLE은 지오코딩하지 않는다.
- 1순위 지번주소(platPlc, type=PARCEL), 실패 시 도로명주소(newPlatPlc, type=ROAD).
- 요청 파라미터는 브이월드 지오코더 API 2.0 가이드를 확인해 맞춘다
  (service=address, request=getcoord, version=2.0, crs=EPSG:4326, type, address, format=json, key 등).
  응답 status(OK / NOT_FOUND / ERROR)를 처리한다.
- 같은 PNU(필지)는 한 번만 호출한다. 한 필지에 여러 동이 있으면 마커 하나에 목록으로 넣는다.
- 병렬 최대 5, 백오프, progress 콜백. 실패 건은 "좌표 없음" 목록으로 반환(표에는 보이고 지도에만 없음).
- 캐시는 호출 측이 넘겨주는 dict(st.session_state["geo"][pnu])만 쓴다. 파일 캐시 금지.
- .env VWORLD_API_KEY. README에 "브이월드 인증키 발급 시 서비스 URL에 localhost:8501과 배포 도메인 등록" 안내.

## 5-2 core/boundaries.py
- 브이월드 2D 데이터 API로 시군구(LT_C_ADSIGG_INFO), 읍면동(LT_C_ADEMD_INFO), 리(LT_C_ADRI_INFO) 경계 GeoJSON 조회.
- attrFilter 문법과 코드 자릿수(시군구 5자리, 읍면동 8자리 = sigunguCd + bjdongCd 앞 3자리, 리 10자리)는 가이드로 확인.
- 기본은 세션 캐시. 브이월드 이용약관에서 경계 데이터 저장이 허용되는지 확인되면 data/cache/boundaries/ 파일 캐시를 옵션으로 추가(확인 전에는 구현하지 말고 TODO).

## 5-3 지도 UI (app/map_view.py, 탭4)
Level 1 — 시·군·구 포커싱
- 상단 배너: 공고명, 접수기간·마감 여부, 검수 여부, 조례 유형, 핵심 수치(경과연수·층수·연면적·이하/미만)
- 시군구 경계 표시 후 fit_bounds. 법정동 폴리곤 표시:
  조회·판정 완료 동은 1차 후보 수로 채색, 미조회 동은 회색
- 동 폴리곤 클릭 → 그 동 선택. 미조회면 "이 동 조회·판정" 버튼(단계 4 파이프라인 재사용)

Level 2 — 법정동 단위 대상 전체 표시
- MarkerCluster + CircleMarker, 상태별 색(1차 후보 초록, 확인필요 주황, 조례만 충족 파랑), 범례
- 상태 토글 체크박스(조례만 충족은 기본 off)
- tooltip: 지번주소 + 상태 + 대장PK(클릭 식별용)
- 여러 동을 조회했으면 누적 표시

Level 3 — 개별 건축물 드릴다운
- st_folium 반환값의 last_object_clicked_tooltip(또는 클릭 좌표 최근접 마커)으로 건물 식별
- 화면을 st.columns([2, 1])로 나눠 오른쪽 상세 패널:
  대장 스펙(사용승인일, 경과연수, 연면적, 지상·지하층수, 주구조, 주용도·기타용도),
  조건별 충족 비교표, 확인필요 사유, 현장확인 체크리스트(체크는 세션에만), "안내문 대상에 추가" 버튼
- 지도 아래 결과 표에서 행을 선택해도 같은 패널이 열리고 지도 중심이 그 건물로 이동
- 좌표 없는 건물은 표에만 "좌표 없음"으로 표시

성능
- st_folium(returned_objects=[필요한 키만])로 불필요한 rerun을 줄인다.
- 마커 2,000개 이상이면 클러스터 필수 + 경고.

Level 0 (선택) — 지역별 현황
- 기존 grok 화면의 "공고 있는 지역 / 없는 지역" 지도: 시도를 고르면 해당 시도의 시군구 경계를
  조례 유형 또는 공고 보유 여부로 채색. 전국 단위 한 번에 그리기는 하지 않는다.

## 완료 기준
- 청운동 조회 후 1차 후보·확인필요 핀 표시, 클릭 시 상세 패널 표시
- 두 개 이상 동을 누적 조회하면 Level 1 채색 갱신
- 지오코딩 실패 목록 표시, 앱 재시작 시 좌표가 남아 있지 않음
- geocode·boundaries 단위 테스트(모킹) 통과
