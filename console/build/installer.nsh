; OAS Studio 安装器定制
;
; 背景：electron-builder 默认的 CHECK_APP_RUNNING 是
;   发现 $INSTDIR 下有进程 → 弹「正在运行」→ 结束进程 → 重试 3 次（约 6 秒）
;   → 还在就弹「无法关闭 / 重试」。
;
; 实测那 6 秒不够：Windows 上一个正在终止的进程（尤其是卡在 D3D 收尾的
; GPU 子进程）会在进程表里残留十几秒，Stop-Process 之后依然能被查到。
; 于是每次重装都要点一次「无法关闭 → 重试」。
;
; 这里换成「静默等待 + 两次强杀 + 最后才打扰用户」：
;   1. 先安静等 1.5 秒，给上次的残留进程自己退干净的机会；
;   2. 第 1.5 秒、第 6 秒各强杀一次（按安装目录路径精确匹配）；
;   3. 等满 25 秒还在，才弹出原来的「无法关闭」对话框（保留兜底）。
;
; 注意：本宏在 allowOnlyOneInstallerInstance.nsh 之前被 include，真正展开发生在
; CHECK_APP_RUNNING 里，那时 FIND_PROCESS 已经定义，可以直接复用。
; 但 KILL_PROCESS 内部引用了 $pid，而 $pid 只在「没有 customCheckAppRunning」
; 时才会声明（见 allowOnlyOneInstallerInstance.nsh 顶部），所以这里不用它，
; 自己写一条不依赖 $pid 的强杀命令。

!macro customCheckAppRunning
  ; 初始化 $IsPowerShellAvailable，让 FIND_PROCESS 走「按路径前缀匹配」的实现，
  ; 避免误判其它位置上同名的 OAS Studio.exe。
  !insertmacro IS_POWERSHELL_AVAILABLE

  DetailPrint "OAS: 检查上次的实例是否已完全退出…"
  StrCpy $R1 0

  oas_wait_loop:
    !insertmacro FIND_PROCESS "${APP_EXECUTABLE_FILENAME}" $R0
    ${if} $R0 != 0
      Goto oas_wait_done
    ${endIf}

    ; 第 3 次（约 1.5 秒）和第 12 次（约 6 秒）各强杀一次。
    ; 先别急着动手：窗口关掉后大多数进程会自己走完。
    ${if} $R1 == 3
    ${orIf} $R1 == 12
      DetailPrint "OAS: 仍有进程未退出，强制结束…"
      ${if} $IsPowerShellAvailable == 0
        nsExec::Exec `"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -WindowStyle Hidden -C "Get-CimInstance Win32_Process | ? { $$_.Path -and $$_.Path.StartsWith('$INSTDIR','CurrentCultureIgnoreCase') } | % { Stop-Process -Id $$_.ProcessId -Force -ErrorAction SilentlyContinue }"`
      ${else}
        nsExec::Exec `taskkill /IM "${APP_EXECUTABLE_FILENAME}" /F`
      ${endIf}
      Pop $R0
      Sleep 500
    ${endIf}

    ; 等满 25 秒（50 × 500ms）还不退，才打扰用户。
    ${if} $R1 >= 50
      MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "$(appCannotBeClosed)" /SD IDCANCEL IDRETRY oas_wait_reset
      Quit
      oas_wait_reset:
      StrCpy $R1 0
    ${endIf}

    IntOp $R1 $R1 + 1
    Sleep 500
    Goto oas_wait_loop

  oas_wait_done:
  DetailPrint "OAS: 环境已清空，开始安装。"
!macroend
