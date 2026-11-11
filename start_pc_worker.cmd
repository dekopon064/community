@echo off
setlocal
chcp 65001 >nul
title Machimoa PC Connector
cd /d "%~dp0"
echo 마치모아 PC 연결 프로그램
echo 이 창이 열려 있는 동안 연결을 유지합니다.
echo 시작만으로 수집·로그인·AI 작업을 실행하지 않습니다.
echo.
where python >nul 2>nul
if errorlevel 1 goto missing_python
if not exist "scripts\run_pc_worker.py" goto missing_worker
set "AI_PROVIDER=chatgpt_plan"
python -X utf8 -u "scripts\run_pc_worker.py" --project-ref czhiqikcpmujeujyfunq --local-config "%~dp0..\google-login\.env.local" --worker-root "%~dp0..\seoul-condition-navigation-release-20261111"
set "pc_exit=%errorlevel%"
echo.
if "%pc_exit%"=="0" goto stopped
echo [시작 또는 실행 오류] PC 연결 프로그램이 종료되었습니다.
echo 위 안내를 확인해 주세요. 자동으로 다시 실행하지 않습니다.
goto finish
:stopped
echo [종료] PC 연결 프로그램이 꺼졌습니다.
goto finish
:missing_python
set "pc_exit=1"
echo [시작 오류] Python을 찾지 못했습니다. 기존 Python 설치와 PATH를 확인해 주세요.
goto finish
:missing_worker
set "pc_exit=1"
echo [시작 오류] 실행 파일을 찾지 못했습니다. 이 시작 파일을 저장소 폴더에서 실행해 주세요.
:finish
echo.
echo 확인 후 아무 키나 누르면 이 창을 닫습니다.
pause >nul
exit /b %pc_exit%
