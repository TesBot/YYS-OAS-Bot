@echo off
setlocal

rem ============================================================
rem  YYJio（痒痒鸡）一键打包（生成 NSIS 安装包）
rem  用法：双击本文件。不会改代码，只产出安装包。
rem  产物：dist\YYJio-Setup-<版本>.exe
rem ============================================================

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

if not exist "%ROOT%\console\package.json" (
  echo [错误] 没找到 %ROOT%\console\package.json
  echo        请把本脚本放在仓库根目录（和 console、engine 同级）。
  pause
  exit /b 1
)

set "CONSOLE=%ROOT%\console"
set "TMP=%ROOT%\.tmp"
set "TEMP=%ROOT%\.tmp"
set "TMPDIR=%ROOT%\.tmp"
set "ELECTRON_BUILDER_CACHE=%ROOT%\.eb-cache"
set "ELECTRON_CACHE=%ROOT%\.electron-cache"
set "ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/"
set "ELECTRON_BUILDER_BINARIES_MIRROR=https://npmmirror.com/mirrors/electron-builder-binaries/"
set "CSC_IDENTITY_AUTO_DISCOVERY=false"
set "ELECTRON_RUN_AS_NODE="

if not exist "%TMP%" mkdir "%TMP%"

where node >nul 2>nul
if errorlevel 1 (
  echo [错误] 没找到 node，请先安装 Node.js 并确保 node 在 PATH 里。
  pause
  exit /b 1
)

if not exist "%CONSOLE%\node_modules\electron\dist\electron.exe" (
  echo [错误] 缺少依赖，请先在 console 目录执行：npm install
  pause
  exit /b 1
)

echo [1/2] 正在打包，请稍候（约 1~3 分钟）...
cd /d "%CONSOLE%"
node node_modules\electron-builder\out\cli\cli.js --win nsis -c.electronDist=node_modules/electron/dist
if errorlevel 1 (
  echo.
  echo [失败] 打包出错，请把上面的输出发给开发者。
  pause
  exit /b 1
)

echo.
echo [2/2] 打包完成，产物：
for %%f in ("%ROOT%\dist\YYJio-Setup-*.exe") do (
  echo     %%f
  echo     大小：%%~zf 字节
)

echo.
echo 提示：安装包不要在仓库目录里直接双击，请先复制到别的目录（例如 D:\ 或桌面）再安装。
echo.
pause
endlocal
