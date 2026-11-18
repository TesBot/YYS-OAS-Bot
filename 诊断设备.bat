@echo off
setlocal enabledelayedexpansion
chcp 936 >nul
set "OUT=%USERPROFILE%\Desktop\YYJio诊断"
if exist "%OUT%" rd /s /q "%OUT%" 2>nul
mkdir "%OUT%" 2>nul
set "LOG=%OUT%\诊断.txt"
echo YYJio 设备诊断 > "%LOG%"
echo 时间: %DATE% %TIME% >> "%LOG%"
echo. >> "%LOG%"

set "ADB="
for %%P in (
  "%LOCALAPPDATA%\YYJio\runtime\python\Lib\site-packages\adbutils\binaries\adb.exe"
  "%LOCALAPPDATA%\OAS Studio\runtime\python\Lib\site-packages\adbutils\binaries\adb.exe"
  "C:\Program Files\Netease\MuMuPlayer-12.0\shell\adb.exe"
  "D:\Program Files\Netease\MuMuPlayer-12.0\shell\adb.exe"
  "C:\Program Files\Netease\MuMuPlayer-12.0\emulator\adb.exe"
  "D:\Program Files\Netease\MuMuPlayer-12.0\emulator\adb.exe"
) do if not defined ADB if exist %%P set "ADB=%%~P"
if not defined ADB for /f "delims=" %%I in ('where adb 2^>nul') do if not defined ADB set "ADB=%%I"
if not defined ADB (
  echo 没找到 adb.exe。请确认模拟器已安装，并把 MuMu 的 shell\adb.exe 路径告诉我。 >> "%LOG%"
  type "%LOG%"
  pause
  exit /b 1
)
echo adb: %ADB% >> "%LOG%"
echo. >> "%LOG%"

echo ===== 尝试连接 MuMu 常见 adb 端口 ===== >> "%LOG%"
for %%P in (16384 16416 16448 16480 16512) do "%ADB%" connect 127.0.0.1:%%P >> "%LOG%" 2>&1
echo. >> "%LOG%"

echo ===== adb devices -l ===== >> "%LOG%"
"%ADB%" devices -l >> "%LOG%" 2>&1
echo. >> "%LOG%"

set /a N=0
for /f "tokens=1,2" %%D in ('"%ADB%" devices 2^>nul') do (
  if "%%E"=="device" (
    set /a N+=1
    set "S=%%D"
    echo ===== 设备 !N!: !S! ===== >> "%LOG%"
    echo -- model / serialno / boot_id >> "%LOG%"
    "%ADB%" -s !S! shell "getprop ro.product.model; getprop ro.serialno; cat /proc/sys/kernel/random/boot_id" >> "%LOG%" 2>&1
    echo -- wm size / density >> "%LOG%"
    "%ADB%" -s !S! shell "wm size; wm density" >> "%LOG%" 2>&1
    echo -- 旋转状态 >> "%LOG%"
    "%ADB%" -s !S! shell "settings get system accelerometer_rotation; settings get system user_rotation; dumpsys window | grep -m1 -E 'mCurrentRotation|mRotation='" >> "%LOG%" 2>&1
    echo -- 前台窗口 / 顶层 Activity >> "%LOG%"
    "%ADB%" -s !S! shell "dumpsys window | grep -m1 -E 'mCurrentFocus|mFocusedApp'; dumpsys activity activities | grep -m1 -E 'mResumedActivity|topResumedActivity'" >> "%LOG%" 2>&1
    echo -- 游戏进程 >> "%LOG%"
    "%ADB%" -s !S! shell "pidof com.netease.onmyoji" >> "%LOG%" 2>&1
    echo -- adb 截图（对照用，和程序自己的截图方式无关）>> "%LOG%"
    "%ADB%" -s !S! exec-out screencap -p > "%OUT%\adb截图_设备!N!.png"
    echo 已保存: adb截图_设备!N!.png >> "%LOG%"
    echo. >> "%LOG%"
  )
)

if !N!==0 (
  echo 没有在线设备。请先启动模拟器并进入游戏，再运行本脚本。 >> "%LOG%"
)

echo 完成。结果在: %OUT% >> "%LOG%"
type "%LOG%"
echo.
echo 结果已保存到: %OUT%
echo 把这个文件夹（或里面的 诊断.txt 和 adb截图_*.png）发给我即可。
pause
