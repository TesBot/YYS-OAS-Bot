# -*- coding: utf-8 -*-
"""任务启动前自动识别庭院皮肤（壳子层能力，不改动引擎）。

背景
----
引擎的页面识别依赖 ``I_CHECK_MAIN`` / ``I_MAIN_GOTO_EXPLORATION`` 等模板，
这些模板必须与游戏里**当前实际使用的庭院皮肤**（``tasks.Component.Costume.config.MainType``）
匹配。上游提供了 17 套皮肤 + 默认皮肤的资源，靠 ``costume_config.costume_main_type``
在运行时 ``replace_img()`` 换模板，但**没有任何自动识别**：换账号时如果庭院皮肤
和配置里写的不一致，就会表现为

    Page detect miss[goto_page] → Current page: None → GamePageUnknownError → restart

这里补上识别环节：截一张当前画面，把每套皮肤的 ``CHECK_MAIN`` 模板各跑一遍
（复用引擎自己的 ``RuleImage.match``，通道/ROI/掩码口径与引擎完全一致），
只在一个候选**唯一命中且达到自身阈值**时才回写配置，认不准就保持原值不动。

注意
----
``RuleImage.match()`` 命中后会改写 ``roi_front``，而 ``CostumeAssets`` 是共享的类属性，
``check_costume_main()`` 又要从这些对象上取 ROI 去替换，所以探测前后必须快照/还原，
否则会污染后续换肤（这里用 ``_probe()`` 统一处理）。
"""

from __future__ import annotations

import time
from typing import List, Optional, Tuple

from module.logger import logger

# 第一名与第二名的最小分差；低于该值认为「认不准」，不动配置
MARGIN = 0.03

_CANDIDATES: Optional[List[Tuple[object, List[object]]]] = None


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


def _label(main_type) -> str:
    try:
        from module.server.i18n import I18n

        text = I18n.trans_zh_cn(main_type)
        if text and text != getattr(main_type, "value", None):
            return f"{getattr(main_type, 'value', main_type)} ({text})"
    except Exception:
        pass
    return getattr(main_type, "value", str(main_type))


def autofix(script, attempts: int = 4, interval: float = 2.5) -> bool:
    """截屏识别当前庭院皮肤，与配置不一致时回写。

    Args:
        script: 已构造的 ``script.Script``，复用其 config/device（都是 cached_property，
            不会重复初始化）。
        attempts: 截图尝试次数（任务刚启动时可能还在加载界面）。
        interval: 两次尝试之间的间隔秒数。

    Returns:
        是否真的改写了配置。
    """
    try:
        config = script.config
        device = script.device
    except Exception as exc:
        logger.warning(f"[Costume] 初始化失败，跳过皮肤自动识别: {exc}")
        return False

    detected = None
    for index in range(max(1, attempts)):
        try:
            image = device.screenshot()
        except Exception as exc:
            logger.warning(f"[Costume] 截图失败，跳过皮肤自动识别: {exc}")
            return False
        detected, scored = detect(image)
        if detected is not None:
            break
        if index + 1 < attempts:
            logger.info(f"[Costume] 未识别到庭院画面（第 {index + 1}/{attempts} 次），稍后重试")
            time.sleep(interval)

    if detected is None:
        logger.info("[Costume] 未能确定庭院皮肤，沿用配置值")
        return False

    current = config.model.global_game.costume_config.costume_main_type
    if detected == current:
        logger.attr("[Costume] 庭院皮肤", f"{_label(detected)} 与配置一致")
        return False

    score = next(item[0] for item in scored if item[2] == detected)
    logger.warning(
        f"[Costume] 庭院皮肤自动纠正: 配置 {_label(current)} → 实际 {_label(detected)}"
        f"（得分 {score:.3f}），已回写配置"
    )
    config.model.global_game.costume_config.costume_main_type = detected
    try:
        config.model.write_json(config.config_name, config.model.dict())
    except Exception as exc:
        logger.warning(f"[Costume] 回写配置失败（本次运行仍按识别结果执行）: {exc}")
    return True
