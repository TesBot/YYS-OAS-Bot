# This Python file uses the following encoding: utf-8
# @author runhey
# github https://github.com/runhey

from module.atom.image import RuleImage
from module.atom.gif import RuleGif
from module.logger import logger
from module.server.i18n import I18n

from tasks.Component.Costume.config import (
    MainType, CostumeConfig, RealmType,
    ThemeType, ShikigamiType, SignType,
    BattleType, BattleSceneType, CarpBannerType
)
from tasks.Component.Costume.assets import CostumeAssets
from tasks.Component.CostumeTheme.theme import apply_theme
from tasks.Component.CostumeBattle.assets import CostumeBattleAssets
from tasks.Component.CostumeShikigami.assets import CostumeShikigamiAssets
from tasks.Component.CostumeCarpBanner.assets import CostumeCarpBannerAssets
from tasks.Component.CostumeBattleScene.assets import CostumeBattleSceneAssets

# 庭院皮肤
# 主界面皮肤（使用字典推导式动态生成）
main_costume_model = {
    getattr(MainType, f"COSTUME_MAIN_{i}"): {
        'I_CHECK_MAIN': f'I_CHECK_MAIN_{i}',
        'I_MAIN_GOTO_EXPLORATION': f'I_MAIN_GOTO_EXPLORATION_{i}',
        'I_MAIN_GOTO_SUMMON': f'I_MAIN_GOTO_SUMMON_{i}',
        'I_MAIN_GOTO_TOWN': f'I_MAIN_GOTO_TOWN_{i}',
        'I_PET_HOUSE': f'I_PET_HOUSE_{i}'
    } for i in range(1, 17)
}
# 玉岚狐庭（issue #1824）
main_costume_model[getattr(MainType, "COSTUME_MAIN_17")] = {
    'I_CHECK_MAIN': ['I_CHECK_MAIN_17_A', 'I_CHECK_MAIN_17_B', 'I_CHECK_MAIN_17_C'],
    'I_MAIN_GOTO_EXPLORATION': ['I_MAIN_GOTO_EXPLORATION_17_A', 'I_MAIN_GOTO_EXPLORATION_17_B', 'I_MAIN_GOTO_EXPLORATION_17_C'],
    'I_MAIN_GOTO_SUMMON': ['I_MAIN_GOTO_SUMMON_17_A', 'I_MAIN_GOTO_SUMMON_17_B', 'I_MAIN_GOTO_SUMMON_17_C'],
    'I_MAIN_GOTO_TOWN': ['I_MAIN_GOTO_TOWN_17_A', 'I_MAIN_GOTO_TOWN_17_B', 'I_MAIN_GOTO_TOWN_17_C'],
    'I_PET_HOUSE': ['I_PET_HOUSE_17_A', 'I_PET_HOUSE_17_B', 'I_PET_HOUSE_17_C'],
}
main_costume_model[getattr(MainType, "COSTUME_MAIN_13")] = {
    'I_CHECK_MAIN': ['I_CHECK_MAIN_13',],
    'I_MAIN_GOTO_EXPLORATION': ['I_MAIN_GOTO_EXPLORATION_13', ],
    'I_MAIN_GOTO_SUMMON': ['I_MAIN_GOTO_SUMMON_13',],
    'I_MAIN_GOTO_TOWN': ['I_MAIN_GOTO_TOWN_13',],
    'I_PET_HOUSE': ['I_PET_HOUSE_13',],
}



# 鲤鱼旗皮肤
carpbanner_costume_model = {
    getattr(CarpBannerType, f"COSTUME_CARPBANNER_{i}"): {
        'I_SHI_CARD': f'I_SHI_CARD_{i}',
        'I_SHI_DEFENSE': f'I_SHI_DEFENSE_{i}',
        'I_SHI_GROWN': f'I_SHI_GROWN_{i}',
    } for i in range(1, 4)
}


# 战斗主题
battle_theme_model = {
    getattr(BattleType, f"COSTUME_BATTLE_{i}"): {
        'I_LOCAL': f'I_LOCAL_{i}',
        'I_EXIT': f'I_EXIT_{i}',
        'I_FRIENDS': f'I_FRIENDS_{i}',
        'I_BATTLE_INFO': f'I_BATTLE_INFO_{i}',
        # 以下资源并非所有主题都需要修改，未采集的资源将被跳过
        'I_WIN': f'I_WIN_{i}', # 已知：8，12，13，14
        'I_DE_WIN': f'I_DE_WIN_{i}', # 已知：8，12，13，14
        'I_FALSE': f'I_FALSE_{i}' # 已知：8，12，13，14
    } for i in range(1, 16)
}

# 战斗场景皮肤。图片资源待补充，先保留空映射。
battle_scene_model = {
    BattleSceneType.COSTUME_BATTLE_SCENE_1: {
        'I_REWARD': 'I_REWARD_1',
    },
}

# 战斗主题涉及的 7 个可替换资产键
BATTLE_THEME_ASSET_KEYS = (
    'I_LOCAL', 'I_EXIT', 'I_FRIENDS', 'I_BATTLE_INFO',
    'I_WIN', 'I_DE_WIN', 'I_FALSE',
)

# 进程级快照：记录战斗资产对象的默认主题参数（按对象 id 索引）。
# 资产是类属性且 replace_img 原地改写，主题一旦切换、即便配置改回
# default 也不会自动恢复，必须先存档才能恢复。
_BATTLE_DEFAULT_PARAMS: dict = {}

# 默认主题 I_BATTLE_INFO 的独立匹配代理（从快照参数构造，不受切换影响）
_BATTLE_DEFAULT_PROXIES: dict = {}

# 幕间主题
shikigami_costume_model = {
    getattr(ShikigamiType, f"COSTUME_SHIKIGAMI_{i}"): {
        # GameUi 进出式神录
        'I_CHECK_RECORDS': f'I_CHECK_RECORDS_{i}',
        'I_RECORD_SOUL_BACK': f'I_RECORD_SOUL_BACK_{i}',
        # SwitchSoul 相关
        'I_SOUL_PRESET': f'I_SOUL_PRESET_{i}',
        'I_SOU_CHECK_IN': f'I_SOU_CHECK_IN_{i}',
        'I_SOU_TEAM_PRESENT': f'I_SOU_TEAM_PRESENT_{i}',
        'I_SOU_CLICK_PRESENT': f'I_SOU_CLICK_PRESENT_{i}',
        # SwitchSoul 分组相关 (1-7组)
        **{f'I_SOU_CHECK_GROUP_{g}': f'I_SOU_CHECK_GROUP_{g}_{i}' for g in range(1, 8)},
        # SwitchSoul 队伍相关 (1-4队)
        **{f'I_SOU_SWITCH_{t}': f'I_SOU_SWITCH_{t}_{i}' for t in range(1, 5)},
        # SoulsTidy 相关
        'I_ST_SOULS': f'I_ST_SOULS_{i}',
        'I_ST_REPLACE': f'I_ST_REPLACE_{i}',
    }
    for i in range(1, 14)  # 目前支持 COSTUME_SHIKIGAMI_1 到 COSTUME_SHIKIGAMI_13
}

class CostumeBase:
    def check_costume(self, config: CostumeConfig=None):
        if config is None:
            config: CostumeConfig = self.config.model.global_game.costume_config
        current_task = self.get_task_name()
        logger.info(f'Current task: {current_task}')
        self.check_costume_main(config.costume_main_type)
        self.check_costume_carpbanner(config.costume_carpbanner_type)
        self.check_costume_battle(config.costume_battle_type)
        self.check_costume_battle_scene(config.costume_battle_scene_type)
        self.check_costume_shikigami(config.costume_shikigami_type)
        self.check_costume_theme(config.costume_theme_type)

    def check_costume_theme(self, theme_type: ThemeType):
        apply_theme(theme_type)
        if theme_type != ThemeType.COSTUME_THEME_DEFAULT:
            # Supplementary labels are available before the UI rebuilds its translations.
            labels = I18n.load_additions().get('zh-CN', {})
            theme_name = labels.get(theme_type.value)
            if not theme_name:
                theme_name = I18n.trans_zh_cn(theme_type)
            logger.info(f'Switch menu theme {theme_type} ({theme_name})')

    def replace_img(self,
                    asset_before: str,
                    asset_after: RuleImage,
                    rp_roi_back: bool = True):
        if not hasattr(self, asset_before):
            return
        # setattr(self, asset_before, asset_after)
        asset_before_object: RuleImage = getattr(self, asset_before)
        asset_before_object.roi_front = list(asset_after.roi_front)
        if rp_roi_back:
            asset_before_object.roi_back = asset_after.roi_back
        asset_before_object.threshold = asset_after.threshold
        asset_before_object.file = asset_after.file
        asset_before_object.method = asset_after.method
        # A cached dispatch flag must not retain the previous skin's method.
        for name in ('is_template_match', 'is_masked_template_match',
                     'is_multi_scale_template_match', 'is_sift_flann'):
            asset_before_object.__dict__.pop(name, None)
        # https://github.com/runhey/OnmyojiAutoScript/issues/1972
        asset_before_object.refresh()

    def check_costume_main(self, main_type: MainType):
        if main_type == MainType.COSTUME_MAIN:
            return
        logger.info(f'Switch main costume to {main_type} ({I18n.trans_zh_cn(main_type)})')
        costume_assets = CostumeAssets()
        for key, value in main_costume_model[main_type].items():
            if isinstance(value, list):
                if not hasattr(self, key):
                    continue
                rules: list[RuleImage] = [getattr(costume_assets, item) for item in value]
                RuleGif.attach_to(getattr(self, key), rules)
            else:
                assert_value: RuleImage = getattr(costume_assets, value)
                self.replace_img(key, assert_value)

    def check_costume_carpbanner(self, carpbanner_type: CarpBannerType):
        if carpbanner_type == CarpBannerType.COSTUME_CARPBANNER_DEFAULT:
            return
        logger.info(f'Switch carp banner theme {carpbanner_type} (override realm assets) ({I18n.trans_zh_cn(carpbanner_type)})')
        carpbanner_assets = CostumeCarpBannerAssets()
        model = carpbanner_costume_model.get(carpbanner_type, {})
        for key, value in model.items():
            if not hasattr(carpbanner_assets, value):
                logger.warning(f'Carp banner asset {value} not found, skip')
                continue
            assert_value: RuleImage = getattr(carpbanner_assets, value)
            # 执行替换（覆盖结界皮肤的同名key）
            self.replace_img(key, assert_value)

    def check_costume_battle(self, battle_type: BattleType):
        if battle_type == BattleType.COSTUME_BATTLE_DEFAULT:
            return
        logger.info(f'Switch battle theme {battle_type} ({I18n.trans_zh_cn(battle_type)})')
        costume_battle_assets = CostumeBattleAssets()
        for key, value in battle_theme_model[battle_type].items():
            if not hasattr(costume_battle_assets, value):
                # 尚未采集完成的资产，跳过
                continue
            assert_value: RuleImage = getattr(costume_battle_assets, value)
            # 绿标的坐标点范围不变
            if key == 'I_LOCAL':
                self.replace_img(key, assert_value, rp_roi_back=False)
            else:
                self.replace_img(key, assert_value)

    # ------------------------------------------------------------------
    # 战斗主题自动适配（动态更换主题时逐场识别，配置值仅作初始提示）
    # ------------------------------------------------------------------
    def snapshot_battle_defaults(self) -> None:
        """在 BaseTask 初始化（任何主题切换发生之前）记录战斗资产的默认参数。

        资产为类属性、replace_img 原地改写，切换后进程内无法自行恢复默认，
        必须先快照。按对象 id 存档，进程内只对首次遇到的资产对象生效。
        """
        for key in BATTLE_THEME_ASSET_KEYS:
            asset = getattr(self, key, None)
            if asset is None or id(asset) in _BATTLE_DEFAULT_PARAMS:
                continue
            _BATTLE_DEFAULT_PARAMS[id(asset)] = {
                'roi_front': list(asset.roi_front),
                'roi_back': list(asset.roi_back),
                'threshold': asset.threshold,
                'method': asset.method,
                'file': asset.file,
            }

    @staticmethod
    def _apply_battle_params(asset, params: dict) -> None:
        """把存档参数原样写回资产对象。

        不能走 RuleImage 构造器：构造时会对 roi_back 再做一次 expand_roi，
        导致恢复后的搜索区比原始参数大。这里直接赋值并清掉方法分派缓存。
        """
        asset.roi_front = list(params['roi_front'])
        asset.roi_back = list(params['roi_back'])
        asset.threshold = params['threshold']
        asset.method = params['method']
        asset.file = params['file']
        for name in ('is_template_match', 'is_masked_template_match',
                     'is_multi_scale_template_match', 'is_sift_flann'):
            asset.__dict__.pop(name, None)
        asset.refresh()

    def restore_battle_default(self) -> None:
        """把战斗资产恢复为默认主题参数（未快照过的资产跳过）。"""
        for key in BATTLE_THEME_ASSET_KEYS:
            asset = getattr(self, key, None)
            if asset is None:
                continue
            params = _BATTLE_DEFAULT_PARAMS.get(id(asset))
            if params is None:
                continue
            self._apply_battle_params(asset, params)

    def _default_battle_info_proxy(self):
        """返回默认主题 I_BATTLE_INFO 的独立匹配对象（从快照构造并缓存）。

        不能直接用 self.I_BATTLE_INFO：它可能已被换成主题模板。
        """
        asset = getattr(self, 'I_BATTLE_INFO', None)
        if asset is None:
            return None
        if id(asset) in _BATTLE_DEFAULT_PROXIES:
            return _BATTLE_DEFAULT_PROXIES[id(asset)]
        params = _BATTLE_DEFAULT_PARAMS.get(id(asset))
        if params is None:
            return None
        proxy = RuleImage(
            roi_front=params['roi_front'],
            roi_back=params['roi_back'],
            threshold=params['threshold'],
            method=params['method'],
            file=params['file'],
        )
        # 构造器会对 roi_back 再扩展一次，覆写回快照值
        proxy.roi_back = list(params['roi_back'])
        _BATTLE_DEFAULT_PROXIES[id(asset)] = proxy
        return proxy

    def detect_battle_theme(self, image):
        """在当前画面上识别战斗主题。

        对默认模板与 15 套主题模板的 I_BATTLE_INFO 逐一匹配打分，
        返回过自身阈值中得分最高的 BattleType；画面不在实战中
        （如加载/准备阶段）时所有候选都不过阈值，返回 None。
        """
        candidates = []
        default_proxy = self._default_battle_info_proxy()
        if default_proxy is not None:
            candidates.append((BattleType.COSTUME_BATTLE_DEFAULT, default_proxy))
        costume_battle_assets = CostumeBattleAssets()
        for i in range(1, 16):
            asset = getattr(costume_battle_assets, f'I_BATTLE_INFO_{i}', None)
            if asset is not None:
                candidates.append((getattr(BattleType, f'COSTUME_BATTLE_{i}'), asset))
        best_type = None
        best_score = 0.0
        for battle_type, asset in candidates:
            try:
                matched = asset.match(image)
            except Exception as e:
                logger.warning(f'Battle theme detect {asset}: {e}')
                continue
            score = float(asset.last_score or 0.0)
            if matched and score > best_score:
                best_type, best_score = battle_type, score
        if best_type is not None:
            logger.info(f'Battle theme auto-detected: {best_type} (score {best_score:.3f})')
        return best_type

    def battle_theme_autofix(self) -> None:
        """战斗中自动适配战斗主题，由 battle_wait 主循环逐帧调用。

        游戏内战斗主题可随时更换，配置一次性选死会导致 I_WIN 等模板失配、
        引擎在结算页干等到超时。每场战斗识别一次：命中即切换到对应主题
        （或恢复默认），未命中下一帧继续尝试。
        """
        if getattr(self, '_battle_theme_autofix_done', False):
            return
        theme = self.detect_battle_theme(self.device.image)
        if theme is None:
            return
        self._battle_theme_autofix_done = True
        if theme == BattleType.COSTUME_BATTLE_DEFAULT:
            self.restore_battle_default()
            logger.info('Battle theme auto-detected: default, restored default assets')
        else:
            self.check_costume_battle(theme)

    def check_costume_battle_scene(self, scene_type: BattleSceneType):
        if scene_type == BattleSceneType.COSTUME_BATTLE_SCENE_DEFAULT:
            return
        logger.info(f'Switch battle scene skin {scene_type} ({I18n.trans_zh_cn(scene_type)})')
        current_task = self.get_task_name()
        allowed_tasks = {
            'Orochi',
        }
        if current_task not in allowed_tasks:
            return

        costume_assets = CostumeBattleSceneAssets()
        for key, value in battle_scene_model.get(scene_type, {}).items():
            if not hasattr(costume_assets, value):
                # 尚未采集完成的资产，跳过
                continue
            assert_value: RuleImage = getattr(costume_assets, value)
            self.replace_img(key, assert_value)

    def check_costume_shikigami(self, shikigami_type: ShikigamiType):
        if shikigami_type == ShikigamiType.COSTUME_SHIKIGAMI_DEFAULT:
            return
        logger.info(f'Switch shikigami theme {shikigami_type} ({I18n.trans_zh_cn(shikigami_type)})')
        shikigami_assets = CostumeShikigamiAssets()
        model = shikigami_costume_model.get(shikigami_type, {})
        for key, value in model.items():
            if not hasattr(shikigami_assets, value):
                # 尚未采集完成的资产，跳过
                continue
            assert_value: RuleImage = getattr(shikigami_assets, value)
            # 一般不需要固定 back ROI，如确有需要可在此为特例设置 rp_roi_back=False
            self.replace_img(key, assert_value)


if __name__ == '__main__':
    c = CostumeBase()
    c.check_costume_main(MainType.COSTUME_MAIN_13)
