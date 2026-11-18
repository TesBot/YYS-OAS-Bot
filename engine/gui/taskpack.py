# -*- coding: utf-8 -*-
"""任务包格式（``.yyjio-task``）：把一份「自定义点击」方案打包成可分发的小文件。

设计原则
--------
1. **只装声明式内容**：包里只有 JSON 与 PNG，绝不包含可执行脚本；导入时先校验再落盘。
2. **图片外置**：方案里的参考画面 / 目标图案以 base64 存在配置里，出口时抽成
   ``assets/*.png``，配置文件因此可读、可 diff；导入时再还原成 base64，运行路径不变。
3. **一包一方案**：一个包 = 一份自定义点击方案（可含多层 direct / scroll 混排）。
4. **版本即身份**：包内 ``id`` + ``version`` 一起决定落盘后的方案 id
   （``<id>@<version>``），编排引用旧版本时不会因为别人更新而变。

包结构::

    task.json          # 清单 + 方案（图片以 asset: 引用）
    assets/0001.png    # 参考画面
    assets/0002.png    # 滚动目标图
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import zipfile
from datetime import date
from typing import Any

FORMAT = "yyjio-task"
FORMAT_VERSION = 1
SUFFIX = ".yyjio-task"

MAX_PACKAGE_BYTES = 8 * 1024 * 1024      # 整包 ≤ 8 MB
MAX_ASSET_BYTES = 2 * 1024 * 1024        # 单张图 ≤ 2 MB
MAX_STEPS = 60

ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,48}$")
VERSION_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}$")
SCREEN = (1280, 720)

# 包里允许出现的清单字段（其余一律丢弃，避免夹带奇怪的东西）
MANIFEST_KEYS = (
    "format", "format_version", "id", "name", "author", "version", "date",
    "description", "plan", "index_entry",
)


class PackError(ValueError):
    """包内容不合法。消息直接给用户看。"""


def _data_url_parts(value: str) -> tuple[str, bytes] | None:
    """``data:image/png;base64,xxxx`` → (扩展名, 原始字节)；不是 data URL 返回 None。"""
    if not isinstance(value, str) or not value.startswith("data:image/"):
        return None
    try:
        header, payload = value.split(",", 1)
    except ValueError:
        return None
    mime = header[5:].split(";")[0].strip().lower()
    ext = {"image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg"}.get(mime)
    if not ext:
        return None
    try:
        raw = base64.b64decode(payload, validate=False)
    except Exception:  # noqa: BLE001
        return None
    return ext, raw


def _to_data_url(raw: bytes, ext: str) -> str:
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else "image/png"
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def slugify(text: str, fallback: str = "task") -> str:
    """把中文/英文名字变成可做文件名的 slug；全中文时退化成 fallback。"""
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9._-]+", "-", text).strip("-._")
    return text or fallback


def default_id(author: str, name: str) -> str:
    """作者名/方案名多为中文时 slugify 会退化，用短哈希兜底，保证每次结果稳定。"""
    author_slug = slugify(author, "author")[:16]
    name_slug = slugify(name, "")
    if not name_slug:
        name_slug = "task-" + hashlib.sha1((name or "").encode("utf-8")).hexdigest()[:6]
    return f"{author_slug}.{name_slug[:24]}"


def _check_coords(rect: Any) -> bool:
    if not isinstance(rect, (list, tuple)) or len(rect) != 4:
        return False
    try:
        x1, y1, x2, y2 = (int(v) for v in rect)
    except (TypeError, ValueError):
        return False
    return 0 <= x1 < x2 <= SCREEN[0] and 0 <= y1 < y2 <= SCREEN[1]


def validate_plan(plan: dict) -> None:
    """方案层面的硬校验：坐标必须落在 1280×720 内。"""
    steps = plan.get("steps") or []
    if not steps:
        raise PackError("这个包里的方案没有任何层级")
    if len(steps) > MAX_STEPS:
        raise PackError(f"层级太多（{len(steps)}），最多 {MAX_STEPS} 层")
    for i, step in enumerate(steps, 1):
        if step.get("mode") == "scroll":
            area = (step.get("scroll") or {}).get("anchor_rect")
            if not _check_coords(area):
                raise PackError(f"第 {i} 层：鼠标停留区域不合法（必须在 1280×720 内）")
            if not (step.get("scroll") or {}).get("template"):
                raise PackError(f"第 {i} 层：滚动找图缺少目标图案")
        else:
            if not _check_coords(step.get("rect")):
                raise PackError(f"第 {i} 层：点击区域不合法（必须在 1280×720 内）")
            if not (step.get("texts") or []):
                raise PackError(f"第 {i} 层：没有填写判定文字")


def build_package(plan: dict, info: dict) -> tuple[bytes, dict]:
    """把方案 + 清单信息打成 zip 字节流，同时返回 index.json 用的条目。"""
    plan = json.loads(json.dumps(plan))  # 深拷贝，避免改到调用方的对象
    assets: dict[str, bytes] = {}
    counter = {"n": 0}

    def take(value: str, prefix: str) -> str:
        parts = _data_url_parts(value)
        if parts is None:
            return value
        ext, raw = parts
        if len(raw) > MAX_ASSET_BYTES:
            raise PackError(f"{prefix} 图片太大（{len(raw) // 1024} KB），单张最多 2 MB")
        counter["n"] += 1
        name = f"{counter['n']:04d}-{prefix}.{ext}"
        assets[f"assets/{name}"] = raw
        return f"asset:{name}"

    for i, step in enumerate(plan.get("steps") or [], 1):
        if step.get("preview"):
            step["preview"] = take(step["preview"], f"step{i}-screen")
        scroll = step.get("scroll") or {}
        if scroll.get("template"):
            scroll["template"] = take(scroll["template"], f"step{i}-target")

    pkg_id = (info.get("id") or "").strip()
    if not ID_RE.match(pkg_id):
        raise PackError("包 ID 不合法：只能用小写字母、数字、点、下划线、短横线，3~49 位")
    version = (info.get("version") or "1.0.0").strip()
    if not VERSION_RE.match(version):
        raise PackError("版本号不合法：请用 1.0.0 这样的三段式数字")
    name = (info.get("name") or plan.get("name") or "未命名任务").strip()[:60]
    author = (info.get("author") or "").strip()[:40]
    if not name:
        raise PackError("任务名称不能为空")

    manifest = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "id": pkg_id,
        "name": name,
        "author": author,
        "version": version,
        "date": (info.get("date") or date.today().isoformat())[:32],
        "description": (info.get("description") or "").strip()[:600],
        "plan": plan,
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("task.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for name_, raw in sorted(assets.items()):
            zf.writestr(name_, raw)
    data = buf.getvalue()
    if len(data) > MAX_PACKAGE_BYTES:
        raise PackError(f"包太大（{len(data) // 1024} KB），最多 8 MB；先把参考画面减少几层")

    entry = {
        "id": pkg_id,
        "name": name,
        "author": author,
        "version": version,
        "date": manifest["date"],
        "description": manifest["description"],
        "file": f"packages/{pkg_id}-{version}{SUFFIX}",
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "steps": len(plan.get("steps") or []),
    }

    # 把「发布清单条目」也打进包里：发布时只要把包交给任务库、重建 index.json 就行。
    # size / sha256 依赖最终文件本身，无法自引用，由 build_index.py 在入库时计算并回填。
    publish_entry = {k: v for k, v in entry.items() if k not in ("size", "sha256")}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("task.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.writestr("index_entry.json", json.dumps(publish_entry, ensure_ascii=False, indent=2))
        for name_, raw in sorted(assets.items()):
            zf.writestr(name_, raw)
    data = buf.getvalue()
    if len(data) > MAX_PACKAGE_BYTES:
        raise PackError(f"包太大（{len(data) // 1024} KB），最多 8 MB；先把参考画面减少几层")
    entry["size"] = len(data)
    entry["sha256"] = hashlib.sha256(data).hexdigest()
    return data, entry


def read_package(data: bytes) -> dict:
    """解析并校验一个包，返回清单（``plan`` 里的图片已还原成 data URL）。"""
    if not data:
        raise PackError("文件是空的")
    if len(data) > MAX_PACKAGE_BYTES:
        raise PackError(f"包太大（{len(data) // 1024} KB），最多 8 MB")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise PackError("不是有效的任务包（应为 .yyjio-task，zip 格式）") from exc

    names = set(zf.namelist())
    if "task.json" not in names:
        raise PackError("包里缺少 task.json")
    try:
        manifest = json.loads(zf.read("task.json").decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise PackError("task.json 不是有效的 JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise PackError("不是 YYJio 任务包（format 字段不对）")

    fv = manifest.get("format_version")
    if not isinstance(fv, int) or fv > FORMAT_VERSION:
        raise PackError(f"这个包用了更新的格式版本（{fv}），请升级 YYJio 后再导入")

    out = {k: manifest.get(k) for k in MANIFEST_KEYS if k != "plan"}
    out["format_version"] = FORMAT_VERSION

    if not ID_RE.match(str(out.get("id") or "")):
        raise PackError("包 ID 不合法")
    if not VERSION_RE.match(str(out.get("version") or "")):
        raise PackError("包版本号不合法")
    out["name"] = (out.get("name") or "未命名任务").strip()[:60]
    out["author"] = (out.get("author") or "").strip()[:40]
    out["description"] = (out.get("description") or "").strip()[:600]
    out["date"] = (out.get("date") or "")[:32]

    plan = manifest.get("plan")
    if not isinstance(plan, dict):
        raise PackError("包里没有方案内容")
    plan = json.loads(json.dumps(plan))

    def restore(value: str, where: str) -> str:
        if not isinstance(value, str) or not value.startswith("asset:"):
            return value
        name = value[len("asset:"):]
        full = name if name.startswith("assets/") else f"assets/{name}"
        if full not in names:
            raise PackError(f"{where} 引用的图片缺失：{full}")
        name = full
        raw = zf.read(name)
        if len(raw) > MAX_ASSET_BYTES:
            raise PackError(f"{where} 的图片太大")
        ext = ("jpg" if name.lower().endswith((".jpg", ".jpeg")) else "png")
        return _to_data_url(raw, ext)

    def restore_plan(one: dict, label: str) -> dict:
        for i, step in enumerate(one.get("steps") or [], 1):
            if step.get("preview"):
                step["preview"] = restore(step["preview"], f"{label} 第 {i} 层参考画面")
            scroll = step.get("scroll") or {}
            if scroll.get("template"):
                scroll["template"] = restore(scroll["template"], f"{label} 第 {i} 层目标图案")
        return one

    out["size"] = len(data)
    out["sha256"] = hashlib.sha256(data).hexdigest()

    plan = restore_plan(plan, "第")
    out["plan"] = plan
    out["steps"] = len(plan.get("steps") or [])
    validate_plan(plan)
    return out


def summary(manifest: dict) -> dict:
    """给界面用的精简信息（不含方案本体，避免一次性塞太多 base64）。"""
    return {
        "id": manifest.get("id"),
        "name": manifest.get("name"),
        "author": manifest.get("author"),
        "version": manifest.get("version"),
        "date": manifest.get("date"),
        "description": manifest.get("description"),
        "steps": manifest.get("steps") or len((manifest.get("plan") or {}).get("steps") or []),
        "size": manifest.get("size") or 0,
    }


def parse_index(text: str) -> list[dict]:
    """解析在线源 index.json，挑出合法条目。"""
    try:
        payload = json.loads(text)
    except Exception as exc:  # noqa: BLE001
        raise PackError("在线清单不是有效的 JSON") from exc
    if not isinstance(payload, dict) or payload.get("format") != "yyjio-tasks":
        raise PackError("在线清单格式不对（缺少 format=yyjio-tasks）")
    items = []
    for raw in payload.get("packages") or []:
        if not isinstance(raw, dict):
            continue
        if not ID_RE.match(str(raw.get("id") or "")):
            continue
        if not VERSION_RE.match(str(raw.get("version") or "")):
            continue
        file = str(raw.get("file") or "").strip()
        if not file or ".." in file or file.startswith("/"):
            continue
        items.append({
            "id": raw["id"],
            "name": (raw.get("name") or raw["id"])[:60],
            "author": (raw.get("author") or "")[:40],
            "version": raw["version"],
            "date": (raw.get("date") or "")[:32],
            "description": (raw.get("description") or "")[:600],
            "file": file,
            "sha256": (raw.get("sha256") or "").lower(),
            "size": int(raw.get("size") or 0),
            "steps": int(raw.get("steps") or 0),
        })
    return items
