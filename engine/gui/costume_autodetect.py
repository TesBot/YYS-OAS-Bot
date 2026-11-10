# -*- coding: utf-8 -*-
"""庭院皮肤识别：任务启动前自动纠正 + 状态缓存 + 手动刷新（壳子层能力，不改引擎）。

背景
----
引擎的页面识别依赖 ``I_CHECK_MAIN`` / ``I_MAIN_GOTO_EXPLORATION`` 等模板，
模板必须与游戏**当前实际使用的庭院皮肤**（``tasks.Component.Costume.config.MainType``）
一致。上游提供 17 套皮肤 + 默认皮肤的资源，靠 ``costume_config.costume_main_type``
在运行时 ``replace_img()`` 换模板，但**没有任何自动识别**。换账号时皮肤不一致就表现为

    Page detect miss[goto_page] → Current page: None → GamePageUnknownError → restart

识别成本
--------
一次识别 = 1 帧截图 + 18 次模板匹配，实测约 110 ms（不含截图）。桥接服务每个编排
步骤都会拉起一个 runner，如果每步都识别就纯属浪费，因此这里做了缓存：

* 缓存 ``config/gui_costume_state.json``，按实例（profile）记录识别结果、得分、时间、adb 序列号；
* 默认 TTL 3600 秒，可用环境变量 ``OAS_COSTUME_TTL`` 覆盖（0 表示每次都重新比对）；
* adb 序列号变化（换了设备/端口）视为失效；
* 桥接服务发现实例离线时会清掉对应缓存（模拟器断开过 → 下次任务必重新识别）；
* 控制台「总览」的「刷新识别」按钮走 ``force=True``，用于「模拟器没下线，只是换了账号」。

安全策略
--------
只在一个候选**唯一命中且达到自身阈值**、与第二名分差 ≥ ``MARGIN`` 时才回写配置，
认不准一律保持原值——宁可沿用旧配置，也不要把皮肤指错。

实现注意
--------
``RuleImage.match()`` 命中后会改写 ``roi_front``，而 ``CostumeAssets`` 是共享类属性，
``check_costume_main()`` 又要从这些对象上取 ROI 去替换，所以探测前后必须快照/还原。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import List, Optional, Tuple

import cv2

from module.logger import logger

# 第一名与第二名的最小分差；低于该值认为「认不准」，不动配置
MARGIN = 0.03
# 达到该分数直接采信（避免相似皮肤撞车，如 main16 狐栖归处 / main17 玉岚狐庭）
HIGH_CONFIDENCE = 0.975
# 星座校验：功能锚点计入一致的最低分、平移容差(px)、确认所需的不同锚点数
ANCHOR_MIN_SCORE = 0.55
ANCHOR_TOLERANCE = 24
ANCHOR_CONFIRM_COUNT = 2
# 模板灰度缓存：(id(asset), scale) -> 灰度数组
_TPL_CACHE: dict = {}
# 缓存有效期（秒）；OAS_COSTUME_TTL=0 表示每次都重新比对
DEFAULT_TTL = 3600
STATE_FILE = Path("config") / "gui_costume_state.json"

# 皮肤枚举 → 中文名（与 tasks/Component/Costume/config.py 的注释保持一致）
SKIN_NAMES = {
    "costume_main": "初语谧景",
    "costume_main_1": "织梦莲庭",
    "costume_main_2": "琼夜淬光",
    "costume_main_3": "烬夜韶阁",
    "costume_main_4": "笔墨山河",
    "costume_main_5": "枫色秋庭",
    "costume_main_6": "暖池青苑",
    "costume_main_7": "盛夏幽庭",
    "costume_main_8": "远海航船",
    "costume_main_9": "结缘神社",
    "costume_main_10": "望月幽庭",
    "costume_main_11": "鏖刀禁府",
    "costume_main_12": "龙吟溯玉",
    "costume_main_13": "云景阆苑",
    "costume_main_14": "雪月华庭",
    "costume_main_15": "茨心乐园",
    "costume_main_16": "狐栖归处",
    "costume_main_17": "玉岚狐庭",
}


def name_of(skin: str) -> str:
    """皮肤枚举值 → 中文名，未知返回原值。"""
    return SKIN_NAMES.get(skin, skin)


_CANDIDATES: Optional[List[Tuple[object, List[object]]]] = None


def ttl() -> int:
    try:
        return max(0, int(os.environ.get("OAS_COSTUME_TTL", DEFAULT_TTL)))
    except (TypeError, ValueError):
        return DEFAULT_TTL


# --------------------------------------------------------------------------- 状态缓存
def _read_all() -> dict:
    try:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning(f"[Costume] 读取识别缓存失败: {exc}")
    return {}


def read_state(config_name: str) -> Optional[dict]:
    entry = _read_all().get(config_name)
    return entry if isinstance(entry, dict) else None


def write_state(config_name: str, payload: dict) -> None:
    data = _read_all()
    data[config_name] = payload
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning(f"[Costume] 写入识别缓存失败: {exc}")


def drop_state(config_name: str) -> None:
    """清掉某个实例的缓存（实例离线/解绑时调用）。"""
    data = _read_all()
    if data.pop(config_name, None) is None:
        return
    try:
        STATE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


# --------------------------------------------------------------------------- 识别
def _candidates() -> List[Tuple[object, List[object], List[object]]]:
    """构建候选表，只构建一次。

    Returns:
        [(main_type, check_assets, other_assets), ...]
        check_assets: 该皮肤的 CHECK_MAIN 模板（判断"在不在庭院"）；
        other_assets: 探索/召唤/町中/宠物屋等功能锚点（做结构一致性校验）。
    """
    global _CANDIDATES
    if _CANDIDATES is not None:
        return _CANDIDATES

    from tasks.Component.Costume.config import MainType
    from tasks.Component.Costume.assets import CostumeAssets
    from tasks.Component.Costume.costume_base import main_costume_model
    from tasks.GameUi.assets import GameUiAssets

    def _pick(names) -> List[object]:
        names = names if isinstance(names, list) else [names]
        return [getattr(CostumeAssets, name) for name in names if hasattr(CostumeAssets, name)]

    candidates: List[Tuple[object, List[object], List[object]]] = []
    for main_type, mapping in main_costume_model.items():
        check = _pick(mapping.get("I_CHECK_MAIN") or [])
        others: List[object] = []
        for key, value in mapping.items():
            if key == "I_CHECK_MAIN":
                continue
            others.extend(_pick(value))
        if check:
            candidates.append((main_type, check, others))

    # 默认庭院（初语谧景）不在 main_costume_model 里，走 GameUi 的资产
    default_others = [
        getattr(GameUiAssets, name) for name in
        ("I_MAIN_GOTO_EXPLORATION", "I_MAIN_GOTO_SUMMON", "I_MAIN_GOTO_TOWN")
        if hasattr(GameUiAssets, name)
    ]
    candidates.append((MainType.COSTUME_MAIN, [GameUiAssets.I_CHECK_MAIN], default_others))
    _CANDIDATES = candidates
    return _CANDIDATES


def _gray(frame) -> "cv2.Mat":
    """均值灰度：对 RGB/BGR 顺序不敏感（换成加权灰度会被通道顺序影响）。"""
    if frame.ndim == 2:
        return frame
    return frame.mean(axis=2).astype("uint8")


def _gray_template(asset, scale: float):
    """模板的灰度缓存（按缩放级别），避免每次重复解码。"""
    key = (id(asset), scale)
    cached = _TPL_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        template = asset.image  # 引擎按 RGB 加载
    except Exception:
        return None
    if template is None or template.size == 0:
        return None
    gray = _gray(template)
    if scale != 1.0:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    _TPL_CACHE[key] = gray
    return gray


def _coarse_one(small, asset, scale: float) -> Tuple[float, Tuple[int, int]]:
    """单个锚点的灰度半分辨率全图搜索，返回 (score, 原图尺度坐标)。

    用全图而不是固定 ROI：庭院是可拖动的场景，取景位置会变（实测漂移 26px+），
    上游模板注册的 roi_back 是采集时的位置，换个位置就 miss。
    用灰度均值而不是彩色：对 RGB/BGR 通道顺序不敏感（截图顺序随截图方式而变）。
    """
    template = _gray_template(asset, scale)
    if template is None or template.shape[0] > small.shape[0] or template.shape[1] > small.shape[1]:
        return 0.0, (0, 0)
    res = cv2.matchTemplate(small, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(res)
    return float(score), (int(loc[0] / scale), int(loc[1] / scale))


def detect(image) -> Tuple[Optional[object], List[Tuple[float, float, object]]]:
    """识别当前庭院皮肤。

    庭院画面会动态变化（昼夜/活动装饰/角色走动/取景平移），单张模板打分
    区分不了相似皮肤（实测 main16 狐栖归处与 main17 玉岚狐庭互为 0.93），
    所以用两轮策略：

    1. 粗筛：各皮肤 CHECK_MAIN 做灰度半分辨率全图搜索，取前 4 名；
    2. 星座校验：入选皮肤的全部功能锚点（探索/召唤/町中/宠物屋）也做全图
       搜索，比较每个锚点相对其注册位置的整体平移量——同一套皮肤的所有
       锚点平移量必须一致（场景整体平移），相似皮肤做不到。

    判定：不同锚点一致数 >= ANCHOR_CONFIRM_COUNT 直接采信；否则要求
    CHECK_MAIN 高分直通（>= HIGH_CONFIDENCE）；都不满足保持原配置。

    Returns:
        (命中的 MainType 或 None, [(cm_score, threshold, main_type), ...] 降序)
    """
    gray = _gray(image)
    height, width = gray.shape[:2]
    scale = 0.5 if width >= 800 else 1.0
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale != 1.0 else gray

    # 第一轮：CHECK_MAIN 粗筛
    first: List[Tuple[float, object, object, Tuple[int, int], List[object]]] = []
    for main_type, check_assets, other_assets in _candidates():
        best_score, best_asset, best_loc = 0.0, None, (0, 0)
        for asset in check_assets:
            score, loc = _coarse_one(small, asset, scale)
            if score > best_score:
                best_score, best_asset, best_loc = score, asset, loc
        if best_asset is not None:
            first.append((best_score, main_type, best_asset, best_loc, other_assets))
    first.sort(key=lambda item: item[0], reverse=True)
    if not first:
        return None, []

    # 第二轮：星座校验（只做前 4 名，控制耗时）
    scored: List[Tuple[float, float, object, int, object, Tuple[int, int]]] = []
    for cm_score, main_type, cm_asset, cm_loc, other_assets in first[:4]:
        dx0 = cm_loc[0] - cm_asset.roi_front[0]
        dy0 = cm_loc[1] - cm_asset.roi_front[1]
        # 同一锚点的多个变体（如 main17 的 A/B/C）按注册位置分组，各取最高分
        groups: dict = {}
        for asset in other_assets:
            score, loc = _coarse_one(small, asset, scale)
            if score < ANCHOR_MIN_SCORE:
                continue
            key = (asset.roi_front[0], asset.roi_front[1])
            if key not in groups or score > groups[key][0]:
                groups[key] = (score, loc)
        consistent = 0
        for (front_x, front_y), (_, loc) in groups.items():
            if abs((loc[0] - front_x) - dx0) <= ANCHOR_TOLERANCE and \
               abs((loc[1] - front_y) - dy0) <= ANCHOR_TOLERANCE:
                consistent += 1
        threshold = float(getattr(cm_asset, "threshold", 0.8))
        scored.append((cm_score, threshold, main_type, consistent, cm_asset, cm_loc))

    # 一致锚点数优先，其次 CHECK 分数
    scored.sort(key=lambda item: (item[3], item[0]), reverse=True)
    report = [(item[0], item[1], item[2]) for item in scored]
    best = scored[0]

    if best[3] >= ANCHOR_CONFIRM_COUNT:
        return best[2], report
    if best[0] >= HIGH_CONFIDENCE:
        logger.info(
            f"[Costume] 锚点一致性不足({best[3]})，但 CHECK 分数 {best[0]:.3f} 达到直通线"
        )
        return best[2], report

    top = "、".join(
        f"{getattr(mt, 'value', mt)}={sc:.3f}(锚点{cn})" for sc, _, mt, cn, _, _ in scored[:3]
    )
    logger.info(f"[Costume] 无法确认庭院皮肤，保持原配置。候选：{top}")
    return None, report


def _value(main_type) -> str:
    return str(getattr(main_type, "value", main_type))


def _label(main_type) -> str:
    skin = _value(main_type)
    name = name_of(skin)
    if name != skin:
        return f"{skin} ({name})"
    try:
        from module.server.i18n import I18n

        text = I18n.trans_zh_cn(main_type)
        if text and text != skin:
            return f"{skin} ({text})"
    except Exception:
        pass
    return skin


# --------------------------------------------------------------------------- 对外入口
def _serial_of(config) -> str:
    try:
        return str(config.model.script.device.serial or "")
    except Exception:
        return ""


def needs_check(config_name: str, configured: str, serial: str, max_age: int = None) -> Tuple[bool, str]:
    """是否需要重新识别。返回 (是否需要, 原因)。"""
    max_age = ttl() if max_age is None else max_age
    state = read_state(config_name)
    if state is None:
        return True, "首次运行，没有识别记录"
    if max_age and time.time() - float(state.get("checked_at") or 0) > max_age:
        return True, f"识别记录已过期（超过 {max_age // 60} 分钟）"
    if serial and state.get("serial") and state["serial"] != serial:
        return True, f"adb 设备变了（{state['serial']} → {serial}）"
    if state.get("skin") != configured:
        return True, "实际皮肤与配置不一致（上次识别结论未生效）"
    return False, ""


def detect_once(config, device, attempts: int = 3, interval: float = 2.0) -> Optional[dict]:
    """截屏识别一轮，命中则返回结果并写缓存；认不准返回 None。"""
    detected = None
    scored = []
    for index in range(max(1, attempts)):
        try:
            image = device.screenshot()
        except Exception as exc:
            logger.warning(f"[Costume] 截图失败，跳过皮肤识别: {exc}")
            return None
        detected, scored = detect(image)
        if detected is not None:
            break
        if index + 1 < attempts:
            logger.info(f"[Costume] 未识别到庭院画面（第 {index + 1}/{attempts} 次），稍后重试")
            time.sleep(interval)

    if detected is None:
        logger.info("[Costume] 未能确定庭院皮肤，沿用配置值")
        return None

    score = next(item[0] for item in scored if item[2] == detected)
    payload = {
        "skin": _value(detected),
        "label": _label(detected),
        "score": round(float(score), 3),
        "checked_at": int(time.time()),
        "serial": _serial_of(config),
    }
    write_state(config.config_name, payload)
    logger.info(
        f"Detected main costume: {payload['skin']} {name_of(payload['skin'])} score={payload['score']:.3f}"
    )
    return payload


def autofix(script, force: bool = False) -> bool:
    """任务启动前调用：命中缓存就跳过，否则识别并按需回写配置。

    Args:
        script: 已构造的 ``script.Script``；复用其 config/device（cached_property，不会重复初始化）。
        force: 忽略缓存强制识别（手动「刷新识别」用）。

    Returns:
        是否改写了配置。
    """
    try:
        config = script.config
        configured = _value(config.model.global_game.costume_config.costume_main_type)
    except Exception as exc:
        logger.warning(f"[Costume] 读取配置失败，跳过皮肤识别: {exc}")
        return False

    serial = _serial_of(config)
    if not force:
        need, reason = needs_check(config.config_name, configured, serial)
        if not need:
            state = read_state(config.config_name) or {}
            logger.attr("[Costume] 庭院皮肤", f"{state.get('label') or configured}（缓存命中，跳过识别）")
            return False
        logger.info(f"[Costume] 需要重新识别庭院皮肤：{reason}")

    try:
        device = script.device
    except Exception as exc:
        logger.warning(f"[Costume] 设备初始化失败，跳过皮肤识别: {exc}")
        return False

    payload = detect_once(config, device, attempts=4 if force else 2)
    if payload is None:
        return False

    if payload["skin"] == configured:
        logger.attr("[Costume] 庭院皮肤", f"{payload['label']} 与配置一致")
        return False

    logger.warning(
        f"[Costume] 庭院皮肤自动纠正: 配置 {configured} → 实际 {payload['label']}"
        f"（得分 {payload['score']:.3f}），已回写配置"
    )
    try:
        from tasks.Component.Costume.config import MainType

        config.model.global_game.costume_config.costume_main_type = MainType(payload["skin"])
    except Exception as exc:
        logger.warning(f"[Costume] 内存配置更新失败: {exc}")
        return False
    try:
        config.model.write_json(config.config_name, config.model.dict())
    except Exception as exc:
        logger.warning(f"[Costume] 回写配置失败（本次运行仍按识别结果执行）: {exc}")
    return True
