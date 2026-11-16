@echo off
chcp 65001 >nul
rem 노후건축물 안전점검 대상 선별 앱 - Windows에서 더블클릭으로 실행
cd /d "%~dp0"

echo ==============================================
echo  노후건축물 안전점검 대상 선별 앱
echo ==============================================

rem 1) 파이썬 3.11 이상 찾기 (py 런처 우선)
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=py -3"
if not defined PY (
  python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo.
  echo [필요] 파이썬 3.11 이상이 없습니다.
  echo   https://www.python.org/downloads/ 에서 설치하세요.
  echo   설치 첫 화면에서 "Add python.exe to PATH" 를 반드시 체크하세요.
  start "" "https://www.python.org/downloads/"
  pause
  exit /b 1
)

rem 2) 처음이면 설치(이 폴더 안 .venv에만 설치)
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo 처음 실행입니다. 필요한 프로그램을 설치합니다(인터넷 필요, 3~10분).
  %PY% -m venv .venv
  if errorlevel 1 ( echo [오류] 설치 폴더를 만들지 못했습니다. & pause & exit /b 1 )
)
if not exist ".venv\.installed" (
  echo 프로그램 설치 중... 화면이 한동안 멈춰 보여도 기다려 주세요.
  ".venv\Scripts\python.exe" -m pip install -q --upgrade pip >nul 2>&1
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
  if errorlevel 1 ( echo [오류] 설치에 실패했습니다. 인터넷 연결을 확인하세요. & pause & exit /b 1 )
  type nul > ".venv\.installed"
)

rem 3) 키 파일(.env)이 없으면 만들고 메모장으로 열기
if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo.
  echo [안내] 키를 넣는 파일(.env)을 만들고 메모장으로 열었습니다.
  echo        받은 키를 '=' 뒤에 붙여 넣고 저장(Ctrl+S)한 뒤, 이 파일을 다시 더블클릭하세요.
  start "" notepad ".env"
  pause
  exit /b 0
)

rem 4) 앱 실행
echo.
echo 앱을 켭니다. 브라우저에 http://localhost:8501 이 열립니다.
echo 끝내려면 이 창을 닫으세요. (조회한 데이터는 저장되지 않습니다)
echo.
".venv\Scripts\python.exe" -m streamlit run app\main.py --server.headless false --server.port 8501 --browser.gatherUsageStats false
pause
