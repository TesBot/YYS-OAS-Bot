"""Answer the 「协助悬赏封印」 invite a friend can push at any moment.

The popup is a full-screen modal: taps aimed at the page underneath land on it
instead, so a battle that is waiting on 「准备」 never leaves the prepare screen
and the task eventually dies of a click that "did nothing".  This component is
called from ``BaseTask.screenshot`` so every task answers it before using the
frame, exactly like the talisman-gift popup.
"""
import json
import time
from pathlib import Path

from module.atom.image import RuleImage
from module.exception import GameStuckError
from module.logger import logger

# The two answer rows, captured 2026-11-09 on MuMu 1280x720.  roi_back stays
# inside its own row so the accept and the reject template can never be read
# from each other's pixels.
WQ_ASSIST_ACCEPT = RuleImage(
    roi_front=(843, 460, 62, 62), roi_back=(820, 436, 250, 104),
    threshold=0.90, method='Template matching',
    file='./tasks/Component/wq_assist/wq_assist_accept.png',
)
WQ_ASSIST_REJECT = RuleImage(
    roi_front=(843, 545, 62, 62), roi_back=(820, 531, 250, 104),
    threshold=0.88, method='Template matching',
    file='./tasks/Component/wq_assist/wq_assist_reject.png',
)

MAX_ANSWER_ATTEMPTS = 3

# 检测节流：本组件挂在 BaseTask.screenshot 里，每帧都会被调到（截图间隔
# 可低至 0.3 秒），两行模板匹配每次都要走 RPC。每 5 秒检查一次足够及时——
# 弹窗是全屏遮罩，早到晚到几秒不影响应答正确性。
CHECK_INTERVAL = 5.0
_last_check = 0.0

# 弹窗策略热加载缓存：GUI 里切换「接受/关闭弹窗」时，正在运行的任务进程
# 不会重读配置。这里按配置文件 mtime 重新读取，改动最多滞后一次文件检查。
_policy_cache: dict = {'key': None, 'value': 'reject'}


def _visible(task) -> bool:
    """Both rows must be present: one lone tick belongs to many other modals."""
    return task.appear(WQ_ASSIST_ACCEPT) and task.appear(WQ_ASSIST_REJECT)


def _policy(task) -> str:
    """Read ``global_game.popup.wanted_assist`` without trusting its shape.

    Falls back to the in-memory config when the file cannot be read.  The file
    is re-read only when its mtime changed, so the per-frame cost is one
    ``stat`` call.
    """
    popup = getattr(getattr(task.config, 'global_game', None), 'popup', None)
    value = getattr(popup, 'wanted_assist', None)
    value = getattr(value, 'value', value)
    result = 'accept' if str(value).lower() == 'accept' else 'reject'

    name = getattr(task.config, 'config_name', None)
    if not name:
        return result
    path = Path('config') / f'{name}.json'
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return result
    key = (str(path), mtime)
    if _policy_cache['key'] == key:
        return _policy_cache['value']
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        raw = (data.get('global_game') or {}).get('popup') or {}
        fresh = 'accept' if str(raw.get('wanted_assist', '')).lower() == 'accept' else 'reject'
    except Exception:  # noqa: BLE001 - 文件损坏时退回内存配置
        fresh = result
    _policy_cache['key'] = key
    _policy_cache['value'] = fresh
    if fresh != result:
        logger.info(f'Wanted-assist policy hot-reloaded: {result} -> {fresh}')
    return fresh


def wanted_assist_popup(task) -> bool:
    """Answer the invite once, then confirm the modal actually left.

    Returns ``True`` when this call answered an invite.  A rejection leaves the
    caller's page untouched; an acceptance hands the game to the assist battle,
    which is why ``accept`` must be a deliberate choice in settings.

    The visibility check itself is throttled to one pass every ``CHECK_INTERVAL``
    seconds: the component runs on every frame, but the two template matches
    only need to happen once in a while to catch the popup within seconds.
    """
    global _last_check
    now = time.monotonic()
    if now - _last_check < CHECK_INTERVAL:
        return False
    _last_check = now
    handled = False
    for _ in range(MAX_ANSWER_ATTEMPTS):
        if not _visible(task):
            return handled
        policy = _policy(task)
        target = WQ_ASSIST_ACCEPT if policy == 'accept' else WQ_ASSIST_REJECT
        logger.info(f'Wanted-assist invite detected: answer {policy}')
        task.click(target)
        handled = True
        task.device.sleep(0.6)
        task.device.screenshot()
    if _visible(task):
        raise GameStuckError('Wanted-assist invite survived 3 answers')
    return handled
