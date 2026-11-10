"""庭院 → 町中 的入口认不出时，必须还有一次固定坐标兜底。

2026-11-09 实例：costume_main_17 的町中模板实测只剩 0.54（阈值 0.8），
`page_main -> page_town` 因此一次点击都没发出去，四次 Transition failed
之后直接 Navigation recovery limit exceeded。入口在屏幕上的位置是稳定的，
只有外观会漂，所以「认不出 → 点 roi_front 中心」这条兜底不该只属于 page_town。
"""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from module.atom.click import RuleClick
from module.atom.image import RuleImage
from tasks.GameUi.navigator import GameUi


def rule() -> RuleImage:
    return RuleImage(roi_front=(1011, 339, 23, 43), roi_back=(941, 262, 200, 190),
                     threshold=0.8, method="Template matching",
                     file="./tasks/Component/Costume/main17/main17_main_goto_town_17.png")


class FixedClickFallbackPolicyTest(unittest.TestCase):
    def test_main_to_town_uses_the_fixed_position_fallback(self):
        allowed = GameUi._fixed_click_fallback_allowed(
            SimpleNamespace(key="page_main"), SimpleNamespace(key="page_town"),
            Mock(action=rule()),
        )
        self.assertTrue(allowed)

    def test_town_entrances_keep_their_existing_fallback(self):
        allowed = GameUi._fixed_click_fallback_allowed(
            SimpleNamespace(key="page_town"), SimpleNamespace(key="page_duel"),
            Mock(action=rule()),
        )
        self.assertTrue(allowed)

    def test_unrelated_edges_do_not_click_blindly(self):
        cases = [
            ("page_main", "page_exploration"),
            ("page_exploration", "page_main"),
            ("page_main", "page_summon"),
            ("page_rwt", "page_town"),
        ]
        for source, destination in cases:
            with self.subTest(source=source, destination=destination):
                allowed = GameUi._fixed_click_fallback_allowed(
                    SimpleNamespace(key=source), SimpleNamespace(key=destination), Mock(action=rule()),
                )
                self.assertFalse(allowed)

    def test_only_image_actions_have_a_fixed_region(self):
        allowed = GameUi._fixed_click_fallback_allowed(
            SimpleNamespace(key="page_main"), SimpleNamespace(key="page_town"),
            Mock(action=RuleClick(roi_front=(100, 100, 10, 10),
                                  roi_back=(100, 100, 10, 10), name="somewhere")),
        )
        self.assertFalse(allowed)


if __name__ == '__main__':
    unittest.main()
