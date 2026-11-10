# -*- coding: utf-8 -*-
"""OAS Python 运行时打包脚本。

把 runtime/python/（嵌入式 Python 3.10 + 全部依赖）打成独立 zip，供控制台
首次运行时下载安装；引擎/控制台更新不再携带此部分。

    python tools/pack_runtime.py [--version 1.0.0] [--out dist]

产物：dist/oas-python-runtime-<version>.zip（顶层即 python/ 目录内容）
"""
from __future__ import annotations

import argparse
import json
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = ROOT / "runtime" / "python"

EXCLUDE_DIRS = {"__pycache__"}
EXCLUDE_EXTS = {".pyc", ".pyo"}


def iter_files(base: Path):
    for p in base.rglob("*"):
        if p.is_file():
            if any(part in EXCLUDE_DIRS for part in p.parts):
                continue
            if p.suffix.lower() in EXCLUDE_EXTS:
                continue
            yield p


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="1.0.0")
    parser.add_argument("--out", default=str(ROOT / "dist"))
    args = parser.parse_args()

    if not (RUNTIME_DIR / "python.exe").exists():
        raise SystemExit("runtime/python 不存在，请先准备运行时目录")

    # 写入运行时清单（zip 内顶层为 python/）
    manifest_path = RUNTIME_DIR / "runtime_manifest.json"
    manifest_path.write_text(json.dumps({
        "name": "OAS Python Runtime",
        "version": args.version,
        "python": "3.10.11",
        "created": datetime.now().isoformat(timespec="seconds"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"oas-python-runtime-{args.version}.zip"

    count = 0
    total = 0
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in iter_files(RUNTIME_DIR):
            rel = p.relative_to(RUNTIME_DIR.parent)  # 顶层为 python/
            zf.write(p, rel)
            count += 1
            total += p.stat().st_size

    print(f"打包完成: {out_path}")
    print(f"文件数: {count}  原始: {total / 1048576:.1f} MB  压缩后: {out_path.stat().st_size / 1048576:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
