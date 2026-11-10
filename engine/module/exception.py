class CampaignEnd(Exception):
    pass


class MapDetectionError(Exception):
    pass


class MapWalkError(Exception):
    pass


class MapEnemyMoved(Exception):
    pass


class CampaignNameError(Exception):
    pass


class ScriptError(Exception):
    # This is likely to be a mistake of developers, but sometimes a random issue
    pass


class ScriptEnd(Exception):
    pass


class GameStuckError(Exception):
    pass


class GameBugError(Exception):
    # An error has occurred in Azur Lane game client. Alas is unable to handle.
    # A restart should fix it.
    pass


class GameTooManyClickError(Exception):
    pass


class EmulatorNotRunningError(Exception):
    pass


class GameNotRunningError(Exception):
    pass


class GamePageUnknownError(Exception):
    pass


class RequestHumanTakeover(Exception):
    # Request human takeover
    # Alas is unable to handle such error, probably because of wrong settings.
    pass

class TaskEnd(Exception):
    pass


# --- OAS Studio 壳子层兼容补丁 -------------------------------------------------
# 控制台（gui/ 与 module/script、module/device 增强）依赖此异常做有界恢复，
# 上游无此类。仅为保持壳子层可导入，不影响上游引擎逻辑。
class TaskRecoveryFailed(Exception):
    """Fail the current task after bounded ESC recovery, without game restart."""
    pass
