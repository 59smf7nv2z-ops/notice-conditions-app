#!/bin/bash
# 노후건축물 안전점검 대상 선별 앱 — Mac에서 더블클릭으로 실행
# 처음 실행: 필요한 프로그램을 이 폴더 안(.venv)에 설치하고, 키를 넣을 .env 파일을 만든다.
# 다음부터: 바로 앱을 켜고 브라우저를 연다.

cd "$(dirname "$0")" || exit 1

pause_and_exit() {
  echo ""
  read -r -p "엔터를 누르면 이 창이 닫힙니다." _
  exit "${1:-1}"
}

echo "=============================================="
echo " 노후건축물 안전점검 대상 선별 앱"
echo "=============================================="

# 1) 파이썬 3.11 이상 찾기
PY=""
for c in python3.14 python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
    PY="$c"
    break
  fi
done
if [ -z "$PY" ]; then
  echo ""
  echo "[필요] 파이썬 3.11 이상이 없습니다."
  echo "  https://www.python.org/downloads/ 에서 'Download Python' 버튼으로 설치한 뒤"
  echo "  이 파일을 다시 더블클릭하세요. (설치 페이지를 엽니다)"
  open "https://www.python.org/downloads/"
  pause_and_exit 1
fi

# 2) 처음이면 설치(이 폴더 안 .venv에만 설치되고 컴퓨터 다른 곳은 건드리지 않음)
if [ ! -x ".venv/bin/python" ]; then
  echo ""
  echo "처음 실행입니다. 필요한 프로그램을 설치합니다(인터넷 필요, 3~10분)."
  "$PY" -m venv .venv || { echo "[오류] 설치 폴더(.venv)를 만들지 못했습니다."; pause_and_exit 1; }
fi
if [ ! -f ".venv/.installed" ] || [ "requirements.txt" -nt ".venv/.installed" ]; then
  echo "프로그램 설치·갱신 중... (화면에 글자가 한동안 안 바뀌어도 기다려 주세요)"
  .venv/bin/python -m pip install -q --upgrade pip >/dev/null 2>&1
  if ! .venv/bin/python -m pip install -q -r requirements.txt; then
    echo "[오류] 설치에 실패했습니다. 인터넷 연결을 확인하고 다시 실행하세요."
    pause_and_exit 1
  fi
  touch ".venv/.installed"
fi

# 3) 키 파일(.env)이 없으면 만들고 열어 주기
if [ ! -f ".env" ]; then
  cp ".env.example" ".env"
  echo ""
  echo "[안내] 키를 넣는 파일(.env)을 만들고 텍스트 편집기로 열었습니다."
  echo "       받은 키를 '=' 뒤에 붙여 넣고 저장(Cmd+S)한 뒤, 이 파일을 다시 더블클릭하세요."
  open -e ".env"
  pause_and_exit 0
fi

if [ "$1" = "--setup-only" ]; then
  echo "설치 확인 완료"
  exit 0
fi

# 4) 앱 실행 → 브라우저가 자동으로 열림
echo ""
echo "앱을 켭니다. 브라우저에 http://localhost:8501 이 열립니다."
echo "끝내려면 이 창을 닫거나 Ctrl+C 를 누르세요. (조회한 데이터는 저장되지 않습니다)"
echo ""
.venv/bin/python -m streamlit run app/main.py --server.headless false --server.port 8501 --browser.gatherUsageStats false
pause_and_exit 0
