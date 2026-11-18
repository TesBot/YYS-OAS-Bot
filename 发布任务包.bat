@echo off
chcp 936 >nul
setlocal enabledelayedexpansion
set "ROOT=%~dp0"
set "PY=%LOCALAPPDATA%\YYJio\runtime\python\python.exe"
if not exist "%PY%" set "PY=python"

echo ============================================
echo   发布任务包到 YYJio 任务库
echo ============================================
echo.
echo 用法：把 .yyjio-task 文件拖到这个 bat 上，或直接把路径粘进来回车。
echo 第一次推送会让你粘贴一次 GitHub 令牌（账号密码 + 2FA 推不上去），
echo 粘贴后脚本会记住，以后直接推。
echo 令牌生成：https://github.com/settings/tokens  ->  Generate new token (classic)  ->  只勾 repo
echo.

set "PKG=%~1"
if "%PKG%"=="" (
  set /p PKG=任务包路径：
)
if "%PKG%"=="" (
  echo [错误] 没有给任务包路径。
  pause
  exit /b 1
)

"%PY%" -X utf8 -B "%ROOT%tools\publish_task.py" "%PKG%"
if errorlevel 1 (
  echo.
  echo [失败] 上面有原因。包已经提交在本地仓库，修好后再跑一次这个 bat 就行。
) else (
  echo.
  echo [完成] 任务库里已经有这个包，客户端「在线刷新」几分钟后能看到。
)
echo.
pause