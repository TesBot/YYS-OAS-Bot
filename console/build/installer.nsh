; OAS Studio 安装器定制
;
; 背景（三轮踩坑后的结论）：
;   1) 「无法关闭/请点重试」弹窗有两个来源，都在 electron-builder 模板里：
;      a) installUtil.nsh 的 uninstallOldVersion：旧卸载器退出码非 0 → 重试 5 次 → 弹窗；
;      b) include/installer.nsh 的 extractUsing7za：解包后用 CopyFiles 拷入 $INSTDIR，
;         任一目标文件被占用 → 重试 5 次 → 弹窗。引擎全部文件都在 app-64.7z 里，
;         走的就是 b) 这条路。模板本身已通过 scripts/patch-nsis-template.mjs
;         打补丁移除所有弹窗（见该脚本）。
;   2) 桥接服务 python 的 exe 在 %LOCALAPPDATA%\OAS Studio\runtime\python，
;      路径不在安装目录里。而 OCR 是 multiprocessing 子进程，命令行只有
;      `-c from multiprocessing...`，不含安装目录 → 按「命令行含 $INSTDIR」
;      的判据看不见它们；adbutils 拉起的 adb fork-server 也是孤儿存活
;      （工作目录锁定在 $INSTDIR\resources\engine）。
;      因此判据改为「exe 路径在安装目录或 %LOCALAPPDATA%\OAS Studio 下」，
;      覆盖 Electron 全家、runtime python、adb、以及任何未来新增的孤儿。
;   3) 判据太宽的历史教训：卸载器/安装器的命令行或路径也可能命中关键词，
;      出现自锁或自杀。排除规则：
;      - 路径以 ${UNINSTALL_FILENAME} 结尾 → 不杀（独立卸载器自己）；
;      - ProcessId == $PID → 不杀（探测/清理用的 powershell 自己，其命令行
;        里嵌着 $INSTDIR 文本，会自命中）。
;
; 全程不弹任何对话框：静默等待 + 强杀循环，45 秒仍不行才继续安装；
; 删不掉的文件跳过；被占用的目标文件由模板补丁降级为直接解压（尽力而为）。

!echo "OAS-INSTALLER-PATCH-ACTIVE"

; 进程命中判据（PowerShell 谓词，detect/kill 共用）：
;   命中 = exe 路径以 $INSTDIR 或 %LOCALAPPDATA%\${PRODUCT_FILENAME} 开头
;          且 exe 文件名不是卸载器
;       或 (python/pythonw 且 命令行含 $INSTDIR 或 ${PRODUCT_FILENAME}\runtime)
;   排除 = 卸载器自身、当前 powershell 进程
!macro oas_pred
($$p=$$_.Path; $$c=$$_.CommandLine; $$h=$$false; if ($$p -and -not $$p.EndsWith('${UNINSTALL_FILENAME}')) { if ($$p.StartsWith('$INSTDIR','CurrentCultureIgnoreCase') -or $$p.StartsWith('$LOCALAPPDATA\${PRODUCT_FILENAME}','CurrentCultureIgnoreCase')) { $$h=$$true } }; if (-not $$h -and ($$_.Name -eq 'python.exe' -or $$_.Name -eq 'pythonw.exe') -and $$c -and ($$c -like '*$INSTDIR*' -or $$c -like '*${PRODUCT_FILENAME}\runtime*')) { $$h=$$true }; if ($$h -and $$_.ProcessId -eq $$PID) { $$h=$$false }; $$h)
!macroend

; 探测：$R0 == 0 表示还有残留，!= 0 表示干净
!macro oas_detect
  ${if} $IsPowerShellAvailable == 0
    nsExec::Exec `"$PowerShellPath" -NoProfile -NonInteractive -WindowStyle Hidden -C "if ((Get-CimInstance Win32_Process | ? { !insertmacro oas_pred }).Count -gt 0) { exit 0 } else { exit 1 }"`
  ${else}
    nsExec::Exec `"$CmdPath" /C tasklist /FI "IMAGENAME eq ${APP_EXECUTABLE_FILENAME}" /FO CSV /NH | "$SYSDIR\findstr.exe" /B /I /C:"\"${APP_EXECUTABLE_FILENAME}\""`
  ${endIf}
  Pop $R0
!macroend

; 强杀：结束所有命中进程
!macro oas_kill
  ${if} $IsPowerShellAvailable == 0
    nsExec::Exec `"$PowerShellPath" -NoProfile -NonInteractive -WindowStyle Hidden -C "Get-CimInstance Win32_Process | ? { !insertmacro oas_pred } | % { Stop-Process -Id $$_.ProcessId -Force -ErrorAction SilentlyContinue }"`
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
      DetailPrint "OAS: 等待超时，继续安装（残留文件会被尽力覆盖）。"
      Goto oas_wait_done
    ${endIf}

    IntOp $R1 $R1 + 1
    Sleep 500
    Goto oas_wait_loop

  oas_wait_done:
  DetailPrint "OAS: 环境已清空，开始安装。"
!macroend

; ---------------------------------------------------------------------------
; 覆盖更新/卸载的文件删除策略（替换默认实现）
;
; 背景（1.1.22/1.1.23 实测踩坑）：
;   默认实现（electron-builder 26 atomicRMDir）在覆盖更新时把整个安装目录
;   逐文件 Rename 到 $PLUGINSDIR\old-install，成功后旧文件随安装器退出被
;   丢弃 —— 两个后果：
;     1) config 下的用户数据（实例 oas*.json、自定义方案 gui_*.json、
;        deploy.yaml）被一起搬走清空，更新一次丢一次；
;     2) 任何一个文件被占用 → 整体回滚 Abort → 退出码非 0 → 重试 5 次
;        → 弹「无法关闭 OAS Studio / 请点重试」——即使用户早就关了程序。
;
; 这里的策略：
;   - 直接 RMDir /r 删除，多轮重试兜住「杀进程后句柄延迟释放」的窗口；
;     个别仍被占用的文件忽略错误留在原地（由模板补丁的尽力覆盖兜底）；
;   - 覆盖更新时先把 config 用户数据搬到插件临时目录，删完再原位放回；
;   - 卸载（非更新）不备份，用户数据随目录清理。
!macro customRemoveFiles
  ${if} ${isUpdated}
    DetailPrint "OAS: 备份 config 用户数据（实例 / 自定义方案 / 部署配置）…"
    CreateDirectory "$PLUGINSDIR\oas-keep"
    CopyFiles /SILENT "$INSTDIR\resources\engine\config\oas*.json" "$PLUGINSDIR\oas-keep"
    CopyFiles /SILENT "$INSTDIR\resources\engine\config\gui_*.json" "$PLUGINSDIR\oas-keep"
    CopyFiles /SILENT "$INSTDIR\resources\engine\config\deploy.yaml" "$PLUGINSDIR\oas-keep"
  ${endIf}

  SetOutPath $TEMP
  DetailPrint "OAS: 删除旧版本文件（被占用的文件会跳过，不影响安装）…"
  RMDir /r $INSTDIR
  Sleep 500
  RMDir /r $INSTDIR
  Sleep 1000
  RMDir /r $INSTDIR

  ${if} ${isUpdated}
    DetailPrint "OAS: 还原 config 用户数据…"
    CreateDirectory "$INSTDIR\resources\engine\config"
    CopyFiles /SILENT "$PLUGINSDIR\oas-keep\*" "$INSTDIR\resources\engine\config"
  ${endIf}
!macroend
