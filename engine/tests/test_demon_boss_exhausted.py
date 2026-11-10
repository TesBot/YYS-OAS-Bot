# This Python file uses the following encoding: utf-8
"""逢魔之时「当日内容已耗尽」的回归测试。

场景：灯笼四个全空、地图上点不出首领集结面板时，
find_boss 重复点击地图中央会触发点击围栏
ClickResponseUnchanged: repeat blocked: dm_boss_click。
此时应判定为「今日已打完」并以 TaskEnd 正常收尾，
而不是把围栏异常抛给上层导致 RESULT: False。
"""
import time as _real_time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from module.device.click_verification import ClickResponseUnchanged
from module.exception import TaskEnd
from tasks.DemonEncounter.script_task import ScriptTask


class _FakeTime:
    """避免测试真的 sleep；monotonic 仍用真实时钟。"""

    sleep = staticmethod(lambda _seconds: None)
    monotonic = staticmethod(_real_time.monotonic)


def _make_exhausted_task(lantern_empty_count: int):
    task = Mock()
    task._lantern_empty_count = lantern_empty_count
    task.best_demon_enable = False
    task.I_DE_BOSS = object()
    task.I_DE_BOSS_BEST = object()
    task.I_BOSS_FIRE = object()
    task.I_BEST_BOSS_FIRE = object()
    task.I_UI_BACK_RED = object()
    task.C_DM_BOSS_CLICK = SimpleNamespace(name='dm_boss_click')
    task.screenshot = lambda: None
    # 永远看不到集结按钮 / 红色返回按钮
    task.appear = lambda *args, **kwargs: False
    # 搜寻按钮（逢魔首领）可以点到
    task.appear_then_click = lambda *args, **kwargs: True
    # 第二次点地图中央触发围栏
    task.click = Mock(side_effect=ClickResponseUnchanged(
        'Click state unchanged; repeat blocked: dm_boss_click'))
    task.device.click_record_clear = lambda: None
    task.ui_click_until_disappear = lambda *args, **kwargs: None
    task.set_next_run = Mock()
    return task


@patch('tasks.DemonEncounter.script_task.time', _FakeTime)
class TestBossExhaustedDay(unittest.TestCase):
    def test_exhausted_day_ends_as_done(self):
        """灯笼全空 + 点不出集结面板 -> TaskEnd 正常结束，标记 finish=True。"""
        task = _make_exhausted_task(lantern_empty_count=4)
        with self.assertRaises(TaskEnd):
            ScriptTask.execute_boss(task)
        # success 必须为 True：success=False 会被调度层记成任务失败，
        # 导致即便 TaskEnd 也判 RESULT: False。
        task.set_next_run.assert_called_once_with(
            task='DemonEncounter', success=True, finish=True, server=True)

    def test_fence_without_empty_lanterns_still_raises(self):
        """灯笼未全空时，围栏异常照常抛出（不掩盖真实卡死/模板漂移）。"""
        task = _make_exhausted_task(lantern_empty_count=1)
        with self.assertRaises(ClickResponseUnchanged):
            ScriptTask.execute_boss(task)
        task.set_next_run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
