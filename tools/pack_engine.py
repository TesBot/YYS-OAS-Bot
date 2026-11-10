# -*- coding: utf-8 -*-
"""OAS Engine 打包脚本。

把 engine/ 目录打成单文件 zip 供最终用户下载解压使用：
    python tools/pack_engine.py [--version 1.0.0] [--out dist]

产物：dist/oas-engine-<version>.zip
排除：tests/、__pycache__、.venv、log/（用户本地生成）等非运行时内容。
"""
from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # 仓库根（含 engine/、dist/）
ENGINE_DIR = ROOT / "engine"

# 运行时不需要的内容
EXCLUDE_DIRS = {"tests", "__pycache__", ".venv", "log", ".cache", ".idea", ".vscode"}
EXCLUDE_EXTS = {".pyc", ".pyo", ".log"}


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
    parser.add_argument("--version", default=None, help="覆盖 engine_manifest.json 里的版本号")
    parser.add_argument("--out", default=str(ROOT / "dist"))
    args = parser.parse_args()

    manifest_path = ENGINE_DIR / "engine_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = args.version or manifest.get("version", "0.0.0")
    if args.version:
        manifest["version"] = version
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"oas-engine-{version}.zip"

    count = 0
    total = 0
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in iter_files(ENGINE_DIR):
            rel = p.relative_to(ENGINE_DIR.parent)  # zip 内顶层为 engine/
            zf.write(p, rel)
            count += 1
            total += p.stat().st_size

    print(f"打包完成: {out_path}")
    print(f"文件数: {count}  原始: {total / 1048576:.1f} MB  压缩后: {out_path.stat().st_size / 1048576:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
