// Patch electron-builder NSIS templates: remove all "app cannot be closed / retry"
// dialogs so overwrite installs never prompt. Locked files are skipped / best-effort
// overwritten instead of aborting with a Retry/Cancel box.
//
// Why: the engine's ~3k files are packed inside app-64.7z. During an overwrite
// install the installer extracts to a temp dir, then CopyFiles into $INSTDIR.
// If ANY target file is still locked (orphaned OCR python, adb fork-server,
// antivirus, ...), the template's CopyFiles retry loop pops a MessageBox asking
// the user to click Retry - even though the app was closed long ago.
//
// Wired as "postinstall" so a fresh `npm install` re-applies the patch.
// Idempotent: patches are keyed on the original source strings; already-patched
// templates are skipped.
import { readFileSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const tplDir = join(here, "..", "node_modules", "app-builder-lib", "templates", "nsis");

let changed = 0;

function patchFile(rel, replacements) {
  const p = join(tplDir, rel);
  let src = readFileSync(p, "utf8");
  let dirty = false;
  for (const [oldText, newText, label] of replacements) {
    if (src.includes(newText.split("\n")[0].trim()) && !src.includes(oldText)) {
      console.log(`[nsis-patch] ${rel}: ${label} already applied`);
      continue;
    }
    if (!src.includes(oldText)) {
      console.warn(`[nsis-patch] WARN ${rel}: pattern for "${label}" not found - template changed?`);
      continue;
    }
    src = src.replace(oldText, newText);
    dirty = true;
    changed++;
    console.log(`[nsis-patch] ${rel}: applied "${label}"`);
  }
  if (dirty) writeFileSync(p, src, "utf8");
}

// 1) extractUsing7za (include/extractAppPackage.nsh): on persistent CopyFiles
//    failure, fall back to direct Nsis7z extraction (ignores errors on locked
//    files) instead of MessageBox.
patchFile(join("include", "extractAppPackage.nsh"), [
  [
    `      MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "$(appCannotBeClosed)" /SD IDRETRY IDCANCEL AbortExtract7za`,
    `      # OAS-PATCH: never prompt - best-effort direct extraction instead.\n` +
      `      RMDir /r "$PLUGINSDIR\\7z-out"\n` +
      `      Nsis7z::Extract "\${FILE}"\n` +
      `      Goto DoneExtract7za`,
    "extractUsing7za no-dialog fallback",
  ],
  // removed MessageBox left the AbortExtract7za label unreferenced ->
  // NSIS warning 6012 (treated as error by electron-builder)
  [
    `  AbortExtract7za:\n    Quit`,
    `    Quit`,
    "remove unused AbortExtract7za label",
  ],
]);

// 2) uninstallOldVersion: give up retrying the old uninstaller after 5 failed
//    attempts instead of showing the "cannot be closed / Retry" box. Leftover
//    files are handled by customRemoveFiles / best-effort overwrite.
patchFile(join("include", "installUtil.nsh"), [
  [
    `      MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "$(appCannotBeClosed)" /SD IDCANCEL IDRETRY OneMoreAttempt`,
    `      DetailPrint "OAS-PATCH: old uninstaller did not exit cleanly; continuing installation."\n` +
      `      Return`,
    "uninstallOldVersion no-retry-box",
  ],
  // removed MessageBox left the OneMoreAttempt label unreferenced
  [
    `  OneMoreAttempt:\n    ExecWait '"$uninstallerFileNameTemp" /S /KEEP_APP_DATA $0 _?=$installationDir' $R0`,
    `    ExecWait '"$uninstallerFileNameTemp" /S /KEEP_APP_DATA $0 _?=$installationDir' $R0`,
    "remove unused OneMoreAttempt label",
  ],
  // 3) handleUninstallResult: log and continue instead of OK-box + Quit.
  [
    `    MessageBox MB_OK|MB_ICONEXCLAMATION "$(uninstallFailed): $R0"\n` +
      `    DetailPrint \`Uninstall was not successful. Uninstaller error code: $R0.\`\n` +
      `    SetErrorLevel 2\n` +
      `    Quit`,
    `    DetailPrint "OAS-PATCH: uninstaller returned code $R0; continuing installation."`,
    "handleUninstallResult continue-on-error",
  ],
]);

if (changed > 0) {
  console.log(`[nsis-patch] done, ${changed} patch(es) applied`);
} else {
  console.log("[nsis-patch] nothing to patch (already applied)");
}
