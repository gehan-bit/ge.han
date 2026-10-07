@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === 원더바레 네이버 블로그 올리기 ===
where py >nul 2>nul || where python >nul 2>nul || (
  echo 파이썬이 없습니다. https://www.python.org/downloads/ 에서 설치할 때 "Add python.exe to PATH"에 체크하고 다시 실행해 주세요.
  pause & exit /b 1
)
set PY=py
where py >nul 2>nul || set PY=python
if not exist ".설치완료" (
  echo [1/3] 필요한 프로그램을 설치합니다 (처음 한 번, 몇 분 걸립니다)...
  %PY% -m pip install -q -r requirements.txt || (echo 설치 실패 & pause & exit /b 1)
  %PY% -m playwright install chromium || (echo 브라우저 설치 실패 & pause & exit /b 1)
  echo ok > ".설치완료"
)
if not exist ".naver-profile" (
  echo [2/3] 네이버 로그인 창을 엽니다. 로그인하면 자동으로 이어집니다.
  %PY% -m naver_blog login || (pause & exit /b 1)
)
echo.
echo 올릴 글 폴더:
dir /b drafts
set /p TAB=[3/3] 올릴 글 이름을 입력하세요 (예: 1주차): 
if "%TAB%"=="" set TAB=1주차
%PY% -m naver_blog post --tab "%TAB%" --keep-open
echo 끝났습니다.
pause
