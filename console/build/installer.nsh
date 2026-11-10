; OAS Studio 安装器定制
;
; 为什么要改：
;   electron-builder 默认的 CHECK_APP_RUNNING 只检查「exe 路径以 $INSTDIR 开头」
;   的进程，而本项目的 Python 桥接服务在 %LOCALAPPDATA%\OAS Studio\runtime\python，
;   路径完全不在安装目录里 —— 安装器看不见它，也就不会去结束它。
;   但它的工作目录正是 $INSTDIR\resources\engine，进程里开着 bridge.py 和一堆
;   .py/.pyc，旧版卸载器删不掉这些文件 → 卸载器返回非 0 → installUtil.nsh 的
;   uninstallOldVersion 重试 5 次后弹出「$(appCannotBeClosed)」= 「无法关闭」。
;   这就是「重装必弹一次、点重试又能装好」的真正原因。
;
; 所以这里把判据从「只看 exe 路径」扩成：
;     exe 路径在 $INSTDIR 下  或者  命令行里出现了 $INSTDIR
; 后者正好命中 python -X utf8 -B <安装目录>\resources\engine\gui\bridge.py。
;
; 另外全程不弹任何对话框：等待 + 强杀循环执行，45 秒仍不行才继续安装。

!echo "OAS-INSTALLER-PATCH-ACTIVE"

; 探测：$R0 == 0 表示还有残留，!= 0 表示干净
; $R9 = 本进程 PID，排除自己（万一安装包被放在安装目录里，否则会自杀）
!macro oas_detect
  System::Call 'kernel32::GetCurrentProcessId() i .r9'
  ${if} $IsPowerShellAvailable == 0
    nsExec::Exec `"$PowerShellPath" -NoProfile -NonInteractive -WindowStyle Hidden -C "if ((Get-CimInstance Win32_Process | ? { $$_.ProcessId -ne $R9 } | ? { ($$_.Path -and $$_.Path.StartsWith('$INSTDIR','CurrentCultureIgnoreCase')) -or ($$_.CommandLine -like '*$INSTDIR*') }).Count -gt 0) { exit 0 } else { exit 1 }"`
  ${else}
    nsExec::Exec `"$CmdPath" /C tasklist /FI "IMAGENAME eq ${APP_EXECUTABLE_FILENAME}" /FO CSV /NH | "$SYSDIR\findstr.exe" /B /I /C:"\"${APP_EXECUTABLE_FILENAME}\""`
  ${endIf}
  Pop $R0
!macroend

; 强杀：结束所有「路径在安装目录下」或「命令行提到安装目录」的进程（不含自己）
!macro oas_kill
  System::Call 'kernel32::GetCurrentProcessId() i .r9'
  ${if} $IsPowerShellAvailable == 0
    nsExec::Exec `"$PowerShellPath" -NoProfile -NonInteractive -WindowStyle Hidden -C "Get-CimInstance Win32_Process | ? { $$_.ProcessId -ne $R9 } | ? { ($$_.Path -and $$_.Path.StartsWith('$INSTDIR','CurrentCultureIgnoreCase')) -or ($$_.CommandLine -like '*$INSTDIR*') } | % { Stop-Process -Id $$_.ProcessId -Force -ErrorAction SilentlyContinue }"`
    Pop $R0
  ${endIf}
  nsExec::Exec `taskkill /F /IM "${APP_EXECUTABLE_FILENAME}"`
  Pop $R0
!macroend

!macro customCheckAppRunning
  ; 初始化 $IsPowerShellAvailable（FIND_PROCESS/KILL_PROCESS 依赖它；
  ; 本宏替换了默认实现，必须自己初始化一次，否则变量为空）
  !insertmacro IS_POWERSHELL_AVAILABLE

  DetailPrint "OAS: 检查上次的实例是否已完全退出…"
  StrCpy $R1 0

  oas_wait_loop:
    !insertmacro oas_detect
    ${if} $R0 != 0
      Goto oas_wait_done
    ${endIf}

    ; 第 2 秒起每轮先强杀，再等 500ms。前 2 秒不动手，给正常退出留时间。
    ${if} $R1 >= 4
      DetailPrint "OAS: 仍有残留进程，强制结束（第 $R1 次检查）…"
      !insertmacro oas_kill
    ${endIf}

    ; 45 秒（90 × 500ms）还不行就放弃等待，直接装——真被锁住时 NSIS 会明确
    ; 报「写入文件失败」，比无限弹框好。
    ${if} $R1 >= 90
      DetailPrint "OAS: 等待超时，继续安装（如有锁文件会提示写入失败）。"
      Goto oas_wait_done
    ${endIf}

    IntOp $R1 $R1 + 1
    Sleep 500
    Goto oas_wait_loop

  oas_wait_done:
  DetailPrint "OAS: 环境已清空，开始安装。"
!macroend
