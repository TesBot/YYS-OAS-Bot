; OAS Studio 安装器定制
;
; 背景（两轮踩坑后的结论）：
;   1) 桥接服务 python 的 exe 在 %LOCALAPPDATA%\OAS Studio\runtime\python，
;      路径不在安装目录里，默认 CHECK_APP_RUNNING（只看 exe 路径前缀）看不见它；
;      而它的工作目录是 $INSTDIR\resources\engine，开着 bridge.py 等文件，
;      旧卸载器删不掉 → 返回非 0 → installUtil.nsh 的 uninstallOldVersion
;      重试 5 次后弹「$(appCannotBeClosed)」=「无法关闭」。
;   2) 但「命令行里出现 $INSTDIR」这个判据太宽：卸载器自己是带着
;      `_?=$INSTDIR` 运行的，安装器/卸载器都会命中自己 → 自锁 45 秒，
;      还会把自己杀掉（退出码非 0 → 又触发上面那个弹窗）。
;
; 现在的判据精确到「谁」：
;     (名字 == OAS Studio.exe 且 exe 路径在 $INSTDIR 下)      ← Electron 主进程 + GPU/渲染子进程
;  或 (名字 == python.exe  且 命令行里出现 $INSTDIR)          ← 引擎桥接服务
; 卸载器（Uninstall OAS Studio.exe）、安装包自身、old-uninstaller.exe 都不会命中。
;
; 全程不弹任何对话框：静默等待 + 强杀循环，45 秒仍不行才继续安装。

!echo "OAS-INSTALLER-PATCH-ACTIVE"

; 探测：$R0 == 0 表示还有残留，!= 0 表示干净
!macro oas_detect
  ${if} $IsPowerShellAvailable == 0
    nsExec::Exec `"$PowerShellPath" -NoProfile -NonInteractive -WindowStyle Hidden -C "if ((Get-CimInstance Win32_Process | ? { ($$_.Name -eq '${APP_EXECUTABLE_FILENAME}' -and $$_.Path -and $$_.Path.StartsWith('$INSTDIR','CurrentCultureIgnoreCase')) -or ($$_.Name -eq 'python.exe' -and $$_.CommandLine -like '*$INSTDIR*') }).Count -gt 0) { exit 0 } else { exit 1 }"`
  ${else}
    nsExec::Exec `"$CmdPath" /C tasklist /FI "IMAGENAME eq ${APP_EXECUTABLE_FILENAME}" /FO CSV /NH | "$SYSDIR\findstr.exe" /B /I /C:"\"${APP_EXECUTABLE_FILENAME}\""`
  ${endIf}
  Pop $R0
!macroend

; 强杀：只结束上面那两类进程
!macro oas_kill
  ${if} $IsPowerShellAvailable == 0
    nsExec::Exec `"$PowerShellPath" -NoProfile -NonInteractive -WindowStyle Hidden -C "Get-CimInstance Win32_Process | ? { ($$_.Name -eq '${APP_EXECUTABLE_FILENAME}' -and $$_.Path -and $$_.Path.StartsWith('$INSTDIR','CurrentCultureIgnoreCase')) -or ($$_.Name -eq 'python.exe' -and $$_.CommandLine -like '*$INSTDIR*') } | % { Stop-Process -Id $$_.ProcessId -Force -ErrorAction SilentlyContinue }"`
    Pop $R0
  ${endIf}
  nsExec::Exec `taskkill /F /IM "${APP_EXECUTABLE_FILENAME}"`
  Pop $R0
!macroend

!macro customCheckAppRunning
  ; 初始化 $IsPowerShellAvailable（本宏替换了默认实现，必须自己初始化一次）
  !insertmacro IS_POWERSHELL_AVAILABLE

  ; 注：不要在这里读注册表做「清理残留卸载登记」的自愈。
  ; 本宏在卸载器构建阶段也会被引用，那时 installUtil.nsh 尚未 include，
  ; GetInQuotes / GetFileParent 都不存在 → makensis 直接 abort。
  ; 而且实测旧卸载器即使删不掉文件，也会先清掉自己的注册表登记，
  ; 所以「登记还在、exe 没了」这种情况基本不会出现。

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

    ; 45 秒（90 × 500ms）还不行就放弃等待，直接装。
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
