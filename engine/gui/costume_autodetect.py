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

from module.logger import logger

# 第一名与第二名的最小分差；低于该值认为「认不准」，不动配置
MARGIN = 0.03
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
def _candidates() -> List[Tuple[object, List[object]]]:
    """构建 (MainType, [RuleImage, ...]) 候选表，只构建一次。"""
    global _CANDIDATES
    if _CANDIDATES is not None:
        return _CANDIDATES

    from tasks.Component.Costume.config import MainType
    from tasks.Component.Costume.assets import CostumeAssets
    from tasks.Component.Costume.costume_base import main_costume_model
    from tasks.GameUi.assets import GameUiAssets

    candidates: List[Tuple[object, List[object]]] = []
    for main_type, mapping in main_costume_model.items():
        names = mapping.get("I_CHECK_MAIN")
        if names is None:
            continue
        names = names if isinstance(names, list) else [names]
        assets = [getattr(CostumeAssets, name) for name in names if hasattr(CostumeAssets, name)]
        if assets:
            candidates.append((main_type, assets))

    # 默认庭院（初语谧景）不在 main_costume_model 里，走 GameUi 的资产
    candidates.append((MainType.COSTUME_MAIN, [GameUiAssets.I_CHECK_MAIN]))
    _CANDIDATES = candidates
    return _CANDIDATES


def _probe(asset, image) -> Tuple[bool, float]:
    """用引擎的匹配器试一次，并还原被 match() 改写的 roi_front。"""
    saved = list(asset.roi_front)
    try:
        matched = asset.match(image)
        return matched, float(getattr(asset, "last_score", 0.0) or 0.0)
    except Exception as exc:  # 模板损坏/尺寸异常都不该拖垮任务
        logger.warning(f"[Costume] 模板 {getattr(asset, 'name', '?')} 匹配异常: {exc}")
        return False, 0.0
    finally:
        asset.roi_front[:] = saved


def detect(image) -> Tuple[Optional[object], List[Tuple[float, float, object]]]:
    """识别当前庭院皮肤。

    Returns:
        (命中的 MainType 或 None, [(score, threshold, main_type), ...] 降序)
    """
    scored: List[Tuple[float, float, object]] = []
    for main_type, assets in _candidates():
        best, threshold = 0.0, 0.0
        for asset in assets:
            _, score = _probe(asset, image)
            best = max(best, score)
            threshold = max(threshold, float(getattr(asset, "threshold", 0.8)))
        scored.append((best, threshold, main_type))
    scored.sort(key=lambda item: item[0], reverse=True)

    passing = [item for item in scored if item[0] >= item[1]]
    if not passing:
        return None, scored
    if len(passing) > 1 and passing[0][0] - passing[1][0] < MARGIN:
        logger.warning(
            f"[Costume] 庭院皮肤识别不唯一: {passing[0][2]}={passing[0][0]:.3f} / "
            f"{passing[1][2]}={passing[1][0]:.3f}，保持原配置"
        )
        return None, scored
    return passing[0][2], scored


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
