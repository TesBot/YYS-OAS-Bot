# -*- coding: utf-8 -*-
"""任务知识层：展示名 / 游戏模块分类 / 玩法说明 / 组队能力 / 已知问题。

设计原则
--------
1. **只描述、不执行**：本模块不导入引擎任何代码，UI 与执行引擎彻底解耦。
2. **分类对齐游戏内模块**：采用庭院底部菜单的真实分区（探索/御魂/觉醒/结界/
   阴阳寮/逢魔之时/斗技/商店/活动），避免出现玩家看不懂的自造分类。
3. **组队能力来自引擎事实**：只有配置里带 ``user_status``（队长/队员）的玩法
   才能做双账号联动，见 ``TEAM_TASKS``。
"""

from __future__ import annotations

# ─────────────────────────── 分类 ───────────────────────────

# 顺序即 UI 中任务库的排列顺序，贴近玩家日常操作路径
CATEGORY_ORDER = [
    "探索、觉醒",
    "御魂、契灵",
    "组队副本",
    "逢魔之时",
    "结界、阴阳寮",
    "活动",
    "商店",
    "其他",
]

# 不在任务库展示的分类（任务保留、分组隐藏）：账号运维/每日必做/斗技对弈
HIDDEN_CATEGORIES = {"账号运维", "每日必做", "斗技对弈"}

# 旧分类名 → 新分类名（TASK_META 里的历史数据按此映射展示）
CATEGORY_ALIAS = {
    "探索": "探索、觉醒",
    "觉醒": "探索、觉醒",
    "御魂": "御魂、契灵",
    "结界": "结界、阴阳寮",
    "阴阳寮": "结界、阴阳寮",
    "组队": "组队副本",
}

CATEGORY_META: dict[str, dict] = {
    "探索、觉醒": {"cat": "剧情探索、秘闻副本与觉醒材料本，产出经验、达摩与觉醒材料。",
                  "icon": "map"},
    "御魂、契灵": {"cat": "御魂及其它装备副本（八岐大蛇/业原火/日轮之陨/永生之海/六道之门/御灵），以及契灵之境。",
                  "icon": "shield"},
    "组队副本": {"cat": "石距/经验妖怪/金币妖怪，游戏内自动匹配队友，无需双开。", "icon": "users"},
    "逢魔之时": {"cat": "每日 20:00 后的鬼王玩法：逢魔之时鬼王、地域鬼王、LBS 鬼王。",
                 "icon": "moon"},
    "结界、阴阳寮": {"cat": "结界突破/寮突破/结界寄养/结界卡，以及寮活动（狩猎战/道馆/首领退治/宴会/集体任务）。",
                    "icon": "gate"},
    "活动": {"cat": "限时活动与版本玩法，开放时间以游戏内为准。", "icon": "spark"},
    "商店": {"cat": "喵喵商店、神秘商店、每周采购等资源兑换。", "icon": "cart"},
    "其他": {"cat": "百鬼夜行、寻玉等零散玩法。", "icon": "dots"},
}

# ─────────────────────────── 任务 ───────────────────────────

# key: (中文名, 分类, 玩法说明, 是否支持双账号组队)
TASK_META: dict[str, tuple[str, str, str, bool]] = {
    # 账号运维
    "restart": ("重启游戏", "账号运维", "强制结束并重开游戏客户端，解决卡界面/黑屏。", False),

    # 每日必做
    "daily_trifles": ("每日琐事", "每日必做", "一键处理签到、庭院事务、购买寿司等每日零碎操作。", False),
    "weekly_trifles": ("每周琐事", "每日必做", "每周刷新的一次性事务（分享、破碎符咒等）。", False),
    "wanted_quests": ("悬赏封印", "每日必做", "按悬赏要求刷指定妖怪，产出勾玉与金币。", False),
    "pets": ("宠物喂养", "每日必做", "宠物后院喂食与领取产出。", False),
    "delegation": ("式神委派", "每日必做", "派遣式神执行委派任务，产出达摩/碎片。", False),
    "talisman_pass": ("花合战", "每日必做", "领取花合战等级奖励与 1500 签御魂。", False),
    "souls_tidy": ("御魂整理", "每日必做", "贪吃鬼吞噬 + 御魂奉纳，清理背包。", False),
    "memory_scrolls": ("追忆绘卷", "每日必做", "绘卷捐献，换取碎片与奖励。", False),
    "auto_checkin_big_god": ("大神签到", "每日必做", "网易大神 App 每日签到。", False),
    "quiz": ("每日答题", "每日必做", "自动完成游戏内答题活动。", False),

    # 探索
    "exploration": ("探索副本", "探索、觉醒", "刷剧情/困难探索，支持队长带队双人刷。", True),
    "secret": ("秘闻副本", "探索、觉醒", "挑战式神秘闻，产出皮肤券与达摩。", False),

    # 御魂
    "orochi": ("御魂·八岐大蛇", "御魂、契灵", "御魂主产区，可选层数与悲鸣；支持队长带队组队刷。", True),
    "orochi_moans": ("御魂·悲鸣", "御魂、契灵", "悲鸣模式御魂本，高等级御魂产出。", False),
    "sougenbi": ("业原火", "御魂、契灵", "业原火御魂副本，产出特定部位御魂。", False),
    "fallen_sun": ("日轮之陨", "御魂、契灵", "日轮之陨御魂本，支持双人组队。", True),
    "eternity_sea": ("永生之海", "御魂、契灵", "永生之海御魂本，支持双人组队。", True),
    "true_orochi": ("真·八岐大蛇", "御魂、契灵", "真蛇挑战，产出高品质御魂。", False),
    "six_realms": ("六道之门", "御魂、契灵", "六道之门副本，产出御魂与六道素材。", False),
    "other_world_twilight": ("六道·彼岸", "御魂、契灵", "六道之门·彼岸，支持双人组队。", True),
    "goryou_realm": ("御灵之境", "御魂、契灵", "御灵兽养成材料副本（风/雷/水/火）。", False),

    # 觉醒
    "evo_zone": ("觉醒副本", "探索、觉醒", "觉醒材料主产区，可选麒麟属性与层数；支持队长带队。", True),

    # 组队副本
    "tako": ("石距", "组队副本", "石距副本，可开金币/经验加成，产出大量资源。", False),
    "experience_youkai": ("经验妖怪", "组队副本", "经验妖怪，快速升级式神。", False),
    "gold_youkai": ("金币妖怪", "组队副本", "金币妖怪，刷取金币。", False),

    # 逢魔之时
    "demon_encounter": ("逢魔之时", "逢魔之时", "每日 20:00 后的逢魔鬼王（鬼灵歌姬/蜃气楼/土蜘蛛等）。", False),
    "area_boss": ("地域鬼王", "逢魔之时", "地域鬼王挑战，按单只/多只配置；已挑战过会被跳过。", False),
    "lbs": ("LBS 鬼王", "逢魔之时", "LBS 定位鬼王，支持单人/组队匹配/开车模式。", False),

    # 斗技对弈
    "duel": ("斗技", "斗技对弈", "斗技 PVP，按段位自动匹配。", False),
    "draft_duel": ("协同对弈", "斗技对弈", "每周协同对弈任务，需选人与队友配合。", False),
    "chess": ("百鬼棋局", "斗技对弈", "百鬼棋局自走棋玩法，可配置羁绊与局数。", False),
    "martial_arts": ("武道大会", "斗技对弈", "武道大会爬塔式 PVP。", False),

    # 结界
    "realm_raid": ("结界突破", "结界、阴阳寮", "个人结界突破，按勋章与失败策略自动打。", False),
    "ryou_toppa": ("寮突破", "结界、阴阳寮", "阴阳寮结界突破，可跳过难打的结界。", False),
    "kekkai_utilize": ("结界寄养", "结界、阴阳寮", "把式神寄养到好友结界，优先太鼓/斗鱼。", False),
    "kekkai_activation": ("结界卡激活", "结界、阴阳寮", "自动筛选并激活结界卡（太鼓/斗鱼）。", False),

    # 阴阳寮
    "hunt": ("狩猎战", "结界、阴阳寮", "寮狩猎战：麒麟降临与阴界之门。", False),
    "dokan": ("道馆突破", "结界、阴阳寮", "寮道馆突破，含馆主与成员战。", False),
    "demon_retreat": ("首领退治", "结界、阴阳寮", "寮首领退治，按开启时间自动参与。", False),
    "guild_banquet": ("寮宴会", "结界、阴阳寮", "寮宴会参与与式神切换。", False),
    "collective_missions": ("集体任务", "结界、阴阳寮", "寮集体任务：提交觉醒材料、御魂与喂养。", False),
    "guild_activity_monitor": ("寮活动监控", "结界、阴阳寮", "监控寮活动开启状态，用于编排前置判断。", False),

    # 活动
    "moment_activity": ("版本活动", "活动", "当前版本主题活动的主线任务。", False),
    "activity_shikigami": ("式神活动", "活动", "式神主题活动（探索/大富翁两条线）。", False),
    "moonlight": ("月华流光", "活动", "限时活动·月华流光，按次数挑战。", False),
    "hero_test": ("式神试炼", "活动", "鬼兵演武 / 兵藏秘境 / 传承试炼三选一。", False),
    "dye_trials": ("染色试炼", "活动", "染色试炼活动关卡。", False),
    "gugu_art_studio": ("姑姑艺术工坊", "活动", "姑姑艺术工坊活动战斗关卡。", False),
    "bondling_fairyland": ("契灵之境", "御魂、契灵", "契灵之境：探查与契灵（低级/中级式盘），支持双人。", True),
    "float_parade": ("花车巡游", "活动", "花车巡游玩法，可选奖励偏向。", False),
    "abyss_shadows": ("深渊暗影", "活动", "暗域玩法（神龙暗域等），按区域推进。", False),
    "meta_demon": ("超鬼王", "活动", "超鬼王活动，按星级顺序攻击并合成鬼王。", False),
    "frog_boss": ("呱太来袭", "活动", "呱太来袭活动 BOSS。", False),
    "nian": ("年兽", "活动", "春节年兽活动 BOSS。", False),

    # 商店
    "kitty_shop": ("喵喵商店", "商店", "喵喵商店兑换。", False),
    "mystery_shop": ("神秘商店", "商店", "神秘商店购买（可邀请好友刷新）。", False),
    "weekly_purchase": ("每周采购", "商店", "每周商店采购：勋章/荣誉/友点等货币兑换。", False),

    # 其他
    "hyakkiyakou": ("百鬼夜行", "其他", "撒豆玩法，可切换阴阳师与豆子数量。", False),
    "find_jade": ("寻玉", "其他", "邀请小号协作完成任务换勾玉，需要第二个账号在线。", False),
}

# 支持「组队联动」的玩法（引擎用 user_status = 队长/队员 表示）
TEAM_TASKS: set[str] = {k for k, v in TASK_META.items() if v[3]}

# ─────────────────────────── 伪任务：组队 ───────────────────────────
# 「自定义组队」不是引擎玩法，而是编排表里的一条前置步骤：
# 它只声明「谁当队长、谁当队员」，后续组队玩法步骤沿用这支队伍。
TEAM_SETUP_KEY = "team_setup"
TEAM_SETUP = {
    "key": TEAM_SETUP_KEY,
    "name": "自定义组队",
    "category": "组队",
    "desc": "指定队长与队员。放在刷本任务之前，后面的组队玩法就按这支队伍执行。",
    "team": False,
}
PSEUDO_TASKS = [TEAM_SETUP]

# 编排表行内摘要优先展示的字段（按优先级取到 3 个）
SUMMARY_KEYS = [
    "layer", "kirin_type", "user_status", "limit_count", "limit_time",
    "challenge_count", "boss_number", "run_count", "completion_count",
    "preset_enable", "preset_group", "preset_team", "soul_buff_enable",
]

# 常用字段中文名：引擎自带 zh-CN 字典只覆盖新玩法，这里补齐高频字段。
# 按字段名全局匹配（各任务的同名字段含义一致），翻译依据 tasks/*/config.py 注释。
FIELD_LABELS: dict[str, str] = {
    # 调度
    "enable": "启用", "next_run": "下次运行", "priority": "优先级",
    "success_interval": "成功间隔", "failure_interval": "失败间隔",
    "server_update": "服务器刷新时间", "scheduler": "任务调度",
    "delay_date": "延迟日期", "float_time": "浮动时间", "wait_interval": "等待间隔",
    # 通用战斗
    "limit_time": "时间限制", "limit_count": "次数限制", "battle_timeout": "战斗超时",
    "continuous_battle": "连续战斗", "lock_team_enable": "锁定阵容",
    "preset_enable": "应用预设", "preset_group": "预设组", "preset_team": "预设队伍",
    "battle_time": "战斗时间", "battle_count": "战斗次数",
    "green_enable": "绿标标记", "green_mark": "绿标位置", "green_mark_type": "绿标方式",
    "green_mark_name": "绿标式神名称",
    "random_click_swipt_enable": "战斗随机点击/滑动",
    "max_continuous": "最大连战次数", "quick_exit": "快速退出",
    # 组队
    "user_status": "组队方式", "invite_enable": "邀请队友", "invite_interval": "邀请间隔",
    "default_invite": "默认邀请", "friend_list": "好友列表",
    "find_mode": "查找好友方式", "wait_time": "等待时间",
    # 御魂 / 觉醒
    "layer": "层数", "kirin_type": "麒麟属性", "soul_buff_enable": "觉醒加成",
    "switch_group_team": "御魂组套", "switch_enable": "切换御魂",
    "enable_switch_by_name": "按名称切换御魂", "group_name": "御魂组名", "team_name": "御魂套名",
    "auto_switch_soul": "自动切换御魂", "switch_once": "只切换一次",
    "ten_switch": "十层御魂配置", "eleven_switch": "十一层御魂配置", "twelve_switch": "十二层御魂配置",
    "one_star": "一星鬼王御魂", "two_stars": "二星鬼王御魂", "three_stars": "三星鬼王御魂",
    "four_stars": "四星鬼王御魂", "five_stars": "五星鬼王御魂", "six_stars": "六星鬼王御魂",
    "enable_one_star_preset": "一星应用预设", "enable_two_stars_preset": "二星应用预设",
    "enable_three_stars_preset": "三星应用预设", "enable_four_stars_preset": "四星应用预设",
    "enable_five_stars_preset": "五星应用预设", "enable_six_stars_preset": "六星应用预设",
    "search_switch": "探查御魂", "tomb_guard_switch": "墓守御魂", "snowball_switch": "雪球御魂",
    "little_kuro_switch": "小黑御魂", "azure_basan_switch": "波山御魂",
    # 玩法专属
    "boss_number": "挑战鬼王数", "boss_reward": "悬赏额外挑战",
    "reward_floor": "悬赏鬼王星级下限", "use_collect": "使用收藏的鬼王",
    "run_count": "执行次数", "completion_count": "完成次数",
    "challenge_count": "挑战次数", "challenge_limit": "挑战次数",
    "skip_difficult": "跳过困难结界", "random_delay": "随机延迟",
    "attack_count": "进攻次数", "attack_number": "进攻次数",
    "buy_ap": "购买体力", "buy_sushi": "购买寿司",
    "ticket_switch": "切换门票", "ticket_type": "门票类型",
    "auto_tea": "疲劳时自动喝茶", "fire_sequence": "攻击顺序", "powerful_list": "强力鬼王列表",
    "rank_protection": "保段位",
    # 重启 / 登录
    "enable_daily": "每日重启", "reset_task_datetime_enable": "重置任务时间",
    "reset_task_datetime": "重置时间点", "character": "登录角色",
    # 每日琐事
    "one_summon": "每日单抽", "summon_type": "抽卡类型", "draw_mystery_pattern": "画神秘图案",
    "luck_msg": "抽取运势签", "store_sign": "商店签到", "buy_sushi_count": "购买寿司次数",
    "notify_enable": "通知开关",
    "courtyard_affairs_dt": "庭院事务时间（自动记录）", "pickup_email_dt": "邮件领取时间（自动记录）",
    "summon_dt": "抽卡时间（自动记录）", "guild_donate_dt": "寮捐赠时间（自动记录）",
    "luck_msg_dt": "运势签时间（自动记录）", "store_sign_dt": "商店签到时间（自动记录）",
    "sushi_dt": "寿司购买时间（自动记录）", "guild_donate_finish": "寮捐赠已完成（自动记录）",
    # 每周琐事
    "share_collect": "分享集结", "share_area_boss": "分享地域鬼王", "share_secret": "分享秘闻",
    "broken_amulet": "使用破碎的符咒",
    # 悬赏封印
    "before_end": "截止前完成时刻", "invite_friend_name": "邀请好友名称",
    "cooperation_type": "协作奖励类型", "battle_priority": "找怪优先级",
    "cooperation_only": "只做协作任务", "unwanted_boss_names": "忽略的目标名称",
    # 式神委派
    "miyoshino_painting": "弥助的画（六星变异卡）", "bird_feather": "鸟之羽（大蛇逆鳞）",
    "find_earring": "寻找耳环（金币28万）", "cat_boss": "猫老大（四星白蛋）",
    "miyoshino": "接送弥助（三星结界卡）", "strange_trace": "奇怪的痕迹（金币）",
    # 花合战
    "level_reward": "领取等级奖励", "harvest_soul": "领取签御魂",
    # 御魂整理
    "enable_greed": "贪吃鬼吞噬", "enable_maneki": "御魂奉纳",
    # 追忆绘卷
    "auto_contribute_memoryscrolls": "自动捐献绘卷", "double_scrolls": "双倍捐献",
    "scroll_number": "绘卷编号", "auto_close_exploration": "自动关闭探索",
    "auto_finish_exploration": "自动完成探索", "next_exploration_time": "下次探索时间",
    # 每日答题
    "quiz_cnt": "答题次数", "quiz_per_round": "每轮答题数",
    # 探索
    "up_type": "探索加成类型",
    # 御魂副本
    "sougenbi_class": "业原火种类", "buff_enable": "使用加成",
    "find_true_orochi": "寻找真蛇", "current_success": "当前成功次数",
    "goryou_class": "御灵类型",
    # 逢魔之时
    "box_buy_sushi": "宝箱购买寿司",
    "best_demon_kiryou_utahime_select": "极逢魔·鬼灵歌姬", "best_demon_shinkirou_select": "极逢魔·蜃气楼",
    "best_demon_tsuchigumo_select": "极逢魔·土蜘蛛", "best_demon_gashadokuro_select": "极逢魔·荒骷髅",
    "best_demon_namazu_select": "极逢魔·地震鲶", "best_demon_oboroguruma_select": "极逢魔·胧车",
    "best_demon_nightly_aramitama_select": "极逢魔·夜之荒魂",
    "demon_kiryou_utahime": "鬼灵歌姬御魂组套", "demon_shinkirou": "蜃气楼御魂组套",
    "demon_tsuchigumo": "土蜘蛛御魂组套", "demon_gashadokuro": "荒骷髅御魂组套",
    "demon_namazu": "地震鲶御魂组套", "demon_oboroguruma": "胧车御魂组套",
    "demon_nightly_aramitama": "夜之荒魂御魂组套",
    "best_demon_kiryou_utahime": "极逢魔·鬼灵歌姬御魂组套", "best_demon_shinkirou": "极逢魔·蜃气楼御魂组套",
    "best_demon_tsuchigumo": "极逢魔·土蜘蛛御魂组套", "best_demon_gashadokuro": "极逢魔·荒骷髅御魂组套",
    "best_demon_namazu": "极逢魔·地震鲶御魂组套", "best_demon_oboroguruma": "极逢魔·胧车御魂组套",
    "best_demon_nightly_aramitamau": "极逢魔·夜之荒魂御魂组套",
    "best_demon_oboroguruma_enable": "启用胧车御魂切换", "best_demon_nightly_aramitama_enable": "启用夜之荒魂御魂切换",
    # 斗技
    "switch_all_soul": "一键切换斗技御魂", "target_score": "目标分数", "honor_full_exit": "荣誉满退出",
    # 结界突破 / 寮突破
    "number_attack": "进攻结界数", "number_base": "保底勋章数",
    "exit_four": "勋章满 4 退出", "order_attack": "进攻顺序（勋章数）",
    "three_refresh": "三次刷新", "when_attack_fail": "进攻失败后",
    "next_ryoutoppa_time": "下次寮突破时间", "next_ryoutoppa_enable": "启用下次寮突破时间",
    "ryou_access": "寮管理身份",
    # 地域鬼王·极
    "Attack_60": "无极时拉到 60 级再打",
    # 探索
    "minions_cnt": "战斗次数", "exploration_level": "探索等级",
    "auto_rotate": "自动添加候补式神", "choose_rarity": "选择狗粮稀有度",
    "collect_paper_reward": "领取纸符奖励",
    # 探索·绘卷模式
    "scrolls_enable": "绘卷模式", "scrolls_cd": "绘卷捐献间隔", "scrolls_threshold": "突破票数量下限",
    # 加成点击（通用）
    "buff_gold_50_click": "点击金币 50% 加成", "buff_gold_100_click": "点击金币 100% 加成",
    "buff_exp_50_click": "点击经验 50% 加成", "buff_exp_100_click": "点击经验 100% 加成",
    "exp_50_buff_enable_help": "打开经验 50% 加成", "exp_100_buff_enable_help": "打开经验 100% 加成",
    # 每周采购
    "ap_100": "购买 100 体力",
    # 秘闻
    "secret_gold_50": "秘闻金币 50 加成", "secret_gold_100": "秘闻金币 100 加成",
    "layer_9": "九层", "layer_10": "十层",
    # 神秘商店
    "shop_kaiko_3": "购买太鼓 3 星", "shop_kaiko_4": "购买太鼓 4 星",
    # 寮宴会
    "day_1": "每周第 1 次运行日", "day_2": "每周第 2 次运行日",
    # 契灵御魂分组
    "bondling_2_1_switch": "针女御魂分组", "bondling_2_2_switch": "薙魂御魂分组",
    "bondling_2_3_switch": "月魔兔御魂分组", "bondling_2_4_switch": "狐火御魂分组",
    # 邀请
    "invite_friend_list": "邀请好友名单",
    # 协同对弈
    "role": "对弈身份",
    # 寮活动监控
    "Dokan": "监控道馆突破", "AbyssShadows": "监控狭间暗影",
    "GuildBanquet": "监控寮宴会", "DemonRetreat": "监控首领退治",
    # 追忆绘卷
    "notification_95": "95% 进度时通知",
    # 结界寄养 / 激活
    "utilize_rule": "寄养规则", "shikigami_class": "寄养式神稀有度", "shikigami_order": "寄养槽位顺序",
    "box_exp_waste": "溢出经验也寄养", "card_type": "结界卡类型",
    "min_taiko_num": "太鼓最低收益", "min_fish_num": "斗鱼最低收益",
    "exchange_before": "先兑换再挂卡", "exchange_max": "兑换最大数量", "card_not_found_count": "未发现结界卡次数（自动记录）",
    # 狩猎战 / 首领退治
    "kirin_time": "麒麟开启时间", "netherworld_time": "阴界之门开启时间",
    "kirin_group_team": "麒麟御魂组套", "netherworld_group_team": "阴界之门御魂组套",
    "custom_run_time": "自定义运行时间",
    # 道馆突破
    "dokan_attack_priority": "道馆进攻优先级", "dokan_auto_cheering_while_cd": "冷却时自动喝彩",
    "monday_to_thursday": "周一至周四设置", "try_start_dokan": "尝试开启道馆",
    "find_dokan_score": "查找道馆得分", "min_people_num": "最少人数", "min_bounty": "最低悬赏",
    "find_dokan_refresh_count": "查找刷新次数",
    "remain_attack_count": "剩余进攻次数（自动记录）", "attack_date": "记录日期（自动记录）",
    "daily_attack_count": "每日进攻次数", "attack_dokan_master": "馆主进攻策略",
    # 集体任务 / 寮监控
    "missions_select": "集体任务选择",
    "detection_interval": "检测间隔（秒）", "monitor_duration": "监控持续时间（分）",
    "recheck_interval": "复查间隔（分）", "run_days": "运行日期", "use_ocr": "OCR 检测模式",
    # 契灵之境
    "bondling_mode": "契灵模式", "bondling_stone_class": "契灵种类",
    "bondling_stone_enable": "鸣契石购买契灵", "bondling_search_enable": "自动探查补充",
    "check_enable": "检查契忆数量", "limit_num": "契忆数量上限",
    # 超鬼王
    "synthesis_list": "鬼王合成列表",
    # 呱太来袭
    "before_end_frog": "截止前完成时刻", "strategy_frog": "选边策略",
    # 商店
    "kitty_attempts": "喵喵商店尝试次数", "kitty_quit_when_finished": "完成后退出",
    "time_of_mystery": "神秘商店刷新时刻", "mystery_amulet": "购买神秘符咒",
    "black_daruma_scrap": "购买黑达摩碎片", "black_daruma": "购买黑达摩", "white_daruma_five": "白达摩×5",
    "white_daruma_four": "白达摩×4", "totem_pass": "御魂票", "medium_bondling_discs": "中级契忆盘",
    "low_bondling_discs": "低级契忆盘", "high_bondling_discs": "高级契忆盘",
    "white_daruma": "购买白达摩", "red_daruma": "购买红达摩", "random_soul": "购买随机御魂",
    "challenge_pass": "购买挑战券", "skin_ticket": "皮肤券", "ap": "购买体力",
    "black_daruma_fragment": "黑达摩碎片", "buy_sale_ticket": "购买寄售券",
    "orochi_scales": "蛇皮数量", "demon_souls": "逢魔之魂数量", "demon_class": "兑换鬼王种类",
    "demon_position": "鬼王兑换位次", "picture_book_scrap": "图鉴碎片", "picture_book_rule": "图鉴碎片规则",
    "bondling_stone": "契灵石",
    # 百鬼夜行
    "hya_limit_time": "限时", "hya_limit_count": "次数限制", "hya_invite_friend": "邀请好友",
    "hya_auto_bean": "自动调整豆子", "hya_priorities": "优先砸的式神",
    "hya_sp": "SP 追击概率", "hya_ssr": "SSR 追击概率", "hya_sr": "SR 追击概率",
    "hya_r": "R 追击概率", "hya_n": "N 追击概率", "hya_g": "呱太追击概率",
    "conf_threshold": "置信度阈值", "iou_threshold": "重叠阈值", "model_precision": "模型精度",
    "inference_engine": "推理引擎",
    # 调试
    "hya_show": "显示识别框", "hya_info": "显示详细信息", "continuous_learning": "持续学习",
    "hya_save_result": "保存结果图", "hya_interval": "截图间隔",
    "hya_screenshot_method": "截图方式", "hya_control_method": "点击方式",
    # 寻玉
    "invite_info_count": "邀请信息次数", "sup_account_count": "小号数量",
    # 自动记录（各任务通用）
    "save_date": "保存日期（自动记录）", "done": "已完成（自动记录）", "unavailable": "不可用（自动记录）",
    # 设备
    "serial": "adb 地址", "package_name": "游戏包名",
    "screenshot_method": "截图方式", "control_method": "点击方式",
    "screenshot_interval": "截图间隔", "combat_screenshot_interval": "战斗截图间隔",
    "costume_main_type": "庭院皮肤候选", "costume_realm_type": "结界皮肤",
    "costume_theme_type": "主题皮肤", "costume_shikigami_type": "式神皮肤",
    "costume_sign_type": "签到皮肤", "costume_battle_type": "战斗皮肤",
}

# 配置分组（section）中文名：schema 的 properties 键 → 中文标题
SECTION_LABELS: dict[str, str] = {
    "scheduler": "任务调度", "general_battle": "通用战斗设置", "general_battle_config": "通用战斗设置",
    "switch_soul": "御魂切换", "switch_soul_config": "执行任务前切换御魂",
    "invite_config": "邀请设置", "invite": "邀请设置",
    "boss": "鬼王设置", "raid_config": "突破设置",
    "dokan_config": "道馆设置", "tako_config": "石距设置",
    "tasks_config_reset": "任务时间重置", "login_character_config": "登录角色",
    "trifles_config": "每日琐事", "done_record": "完成记录（自动维护）", "trifles": "每周琐事",
    "talisman": "花合战", "simple_tidy": "御魂整理",
    "memory_scrolls_finish": "收尾设置（自动维护）", "scrolls": "追忆绘卷",
    "six_realms_gate": "六道之门", "goryou_config": "御灵设置",
    "experience_youkai": "经验妖怪", "gold_youkai": "金币妖怪",
    "box_buy_config": "宝箱购买", "best_demon_boss_config": "极逢魔·首领选择",
    "demon_soul_config": "逢魔御魂切换", "best_demon_soul_config": "极逢魔御魂切换",
    "utilize_config": "结界寄养设置", "activation_config": "结界卡激活设置",
    "hunt_time": "狩猎战时间", "demon_retreat_time": "首领退治时间",
    "missions_config": "集体任务", "herotest": "式神试炼",
    "bondling_config": "契灵之境设置", "bondling_switch_soul": "契灵御魂切换",
    "float_parade": "花车巡游", "abyss_shadows_time": "深渊暗影时间",
    "saved_params": "保存的参数（自动维护）", "shop_config": "神秘商店",
    "special_room": "杂货铺·特殊", "honor_room": "杂货铺·荣誉", "friendship_points": "杂货铺·友情点",
    "medal_room": "杂货铺·勋章", "charisma": "杂货铺·魅力", "thousand_things": "千物屋",
    "consignment": "寄售屋", "scales": "密卷屋", "bondlings": "契灵商店",
    "shrine": "神社", "guild_store": "寮商店", "itachi_coin_shop": "鼬乐币商店",
    "hyakkiyakou_models": "百鬼夜行模型（高级）", "debug_config": "调试设置",
    "restart_config": "重启设置", "demon_battle_config": "逢魔战斗设置",
    "best_demon_battle_config": "极逢魔战斗设置", "kirin_battle_config": "麒麟战斗设置",
    "netherworld_battle_config": "阴界之门战斗设置", "dokan_member_battle_conf": "道馆成员战设置",
    "dokan_owner_battle_conf": "道馆馆主战设置", "attack_count_config": "进攻次数记录（自动维护）",
    "guild_activity_monitor_combat_time": "寮活动监控时间",
    "version_ruins_battle_conf": "活动·遗迹战斗设置", "version_trial_battle_conf": "活动·试炼战斗设置",
    "rich_man_battle_conf": "活动·大富翁战斗设置", "pass_battle_conf": "活动·关卡战斗设置",
    "fakegod_battle_conf": "超鬼王战斗设置", "exp_encounter_battle_conf": "式神活动战斗设置",
    "moonlight_battle_conf": "月华流光战斗设置", "battle_config": "战斗设置",
    "ap_battle_conf": "体力本战斗设置", "boss_battle_conf": "鬼王战斗设置",
    "quiz_config": "答题设置", "hyakkiyakou_config": "百鬼夜行设置",
    "kitty_shop_config": "喵喵商店设置", "frog_boss_config": "呱太来袭设置",
    "find_jade_config": "寻玉设置", "meta_demon_config": "超鬼王设置",
    "wanted_quests_config": "悬赏封印设置", "delegation_config": "式神委派设置",
    "memory_scrolls_config": "追忆绘卷设置", "exploration_config": "探索设置",
    "sougenbi_config": "业原火设置", "true_orochi_config": "真蛇设置",
    "duel_config": "斗技设置", "orochi_config": "八岐大蛇设置", "evo_zone_config": "觉醒设置",
    "moment_activity_config": "版本活动设置", "mystery_shop_config": "神秘商店设置",
    "guild_donate": "寮捐赠",
    "eternity_sea_config": "永生之海设置", "fallen_sun_config": "日轮之陨设置",
    "hunt_config": "狩猎战设置", "nian_config": "年兽设置", "pets_config": "宠物设置",
    "secret_config": "秘闻副本设置", "guild_activity": "监控的活动类型",
    "switch_soul_config_1": "御魂切换·队伍一", "switch_soul_config_2": "御魂切换·队伍二",
}

_FIELD_NOTES: dict[str, str] = {
    "limit_time": "任务最长运行时间，到达后安全收尾。",
    "limit_count": "最多挑战次数，第一次验证时建议设 1。",
    "user_status": "组长负责建房邀请，队员负责接受邀请。",
    "preset_enable": "在出战准备界面应用指定预设。",
    "preset_group": "预设组，游戏内最多 7 组。",
    "preset_team": "预设队伍，引擎素材只支持 1-4 队。",
    "layer": "挑战层数，层数越高奖励越好。",
    "kirin_type": "麒麟属性，决定掉落材料种类。",
    "boss_number": "挑战几只鬼王，日常建议 1-3。",
    "soul_buff_enable": "开启后消耗加成券，收益翻倍。",
    "continuous_battle": "同一阵容连续战斗，节省重复准备时间。",
}


def field_label(name: str) -> str:
    if name in FIELD_LABELS:
        return FIELD_LABELS[name]
    return name.replace("_", " ")


def section_label(name: str) -> str:
    """配置分组名 → 中文标题；带 _config 后缀自动兼容。"""
    if name in SECTION_LABELS:
        return SECTION_LABELS[name]
    base = name[:-7] if name.endswith("_config") else name
    if base in SECTION_LABELS:
        return SECTION_LABELS[base]
    return name.replace("_", " ")


def field_note(name: str) -> str:
    return _FIELD_NOTES.get(name, "")


# 枚举值中文映射：引擎里部分枚举用英文存储（alone/leader/member…）
ENUM_LABELS: dict[str, str] = {
    "alone": "单人",
    "leader": "队长（建房邀请）",
    "member": "队员（接受邀请）",
    "handoff1": "契灵交接·先手",
    "handoff2": "契灵交接·后手",
    "wild": "路人匹配（未实现）",
    "group": "组队",
    "solo": "单人",
    "team": "组队",
    "true": "是",
    "false": "否",
    "auto": "自动",
    "default": "默认",
    "none": "不设置",
    "server": "按服务器时间",
    "client": "按本地时间",
    # 通用战斗·绿标
    "green_left1": "绿标·左侧第 1 位", "green_left2": "绿标·左侧第 2 位",
    "green_left3": "绿标·左侧第 3 位", "green_left4": "绿标·左侧第 4 位",
    "green_left5": "绿标·左侧第 5 位", "green_main": "绿标·主力位",
    "choose": "按位置选择", "name": "按名称选择",
    # 邀请好友
    "auto_find": "自动查找好友", "recent_friend": "最近联机好友",
    # 稀有度（游戏内通用叫法，保留字母并附注）
    "UR": "UR 阶", "SP": "SP 阶", "SSR": "SSR 阶", "SR": "SR 阶", "R": "R 阶", "N": "N 阶",
    "MATERIAL": "素材",
    # 百鬼夜行模型
    "FP32": "FP32 全精度", "INT8": "INT8 量化（更快）",
    "Onnxruntime": "OnnxRuntime 引擎", "TensorRT": "TensorRT 引擎",
    # 悬赏协作奖励
    "NoInvite": "不邀请协作", "GoldOnly": "只要金币", "JadeOnly": "只要勾玉",
    "FoodOnly": "只要食物", "SushiOnly": "只要寿司", "GoldAndJade": "金币+勾玉",
    "GoldAndFood": "金币+食物", "JadeAndFood": "勾玉+食物", "GoldAndJadeAndFood": "金币+勾玉+食物",
    "GoldAndSushi": "金币+寿司", "JadeAndSushi": "勾玉+寿司", "GoldAndJadeAndSushi": "金币+勾玉+寿司",
    "FoodAndSushi": "食物+寿司", "GoldAndFoodAndSushi": "金币+食物+寿司",
    "JadeAndFoodAndSushi": "勾玉+食物+寿司", "Any": "任意奖励",
    # 探索加成
    "up_all": "全部加成", "up_exp": "经验加成", "up_coin": "金币加成", "up_daruma": "达摩加成",
    # 六道之门
    "MoonSea": "月之海", "PeacockKingdom": "孔雀之国",
    # 快速换装
    "mode_number": "按编号识别", "mode_ocr": "按文字识别",
    # 结界突破失败策略
    "Exit": "退出", "Continue": "继续下一个", "Refresh": "刷新结界",
    # 结界寄养规则
    "kaiko": "优先太鼓", "fish": "优先斗鱼",
    # 好友列表
    "same_server": "同服好友", "different_server": "跨服好友",
    # 道馆馆主策略
    "ATTACK_ZERO_ZERO": "两馆都不打馆主",
    "ATTACK_ZERO_ONE": "仅第二馆打馆主一阵",
    "ATTACK_ZERO_TWO": "仅第二馆打馆主两阵",
    "ATTACK_ONE_ZERO": "仅第一馆打馆主一阵",
    "ATTACK_ONE_ONE": "两馆各打馆主一阵",
    "ATTACK_ONE_TWO": "第一馆一阵·第二馆两阵",
    "ATTACK_TWO_TWO": "两馆各打馆主两阵",
    # 式神试炼
    "PVE": "挑战怪物（PVE）", "PVP": "挑战玩家（PVP）",
    # 深渊暗影·标记主怪
    "NONE": "不标记", "BOSS_ONLY": "仅标记首领", "GENERAL_ONLY": "仅标记副将",
    "ELITE_ONLY": "仅标记精英", "BOSS_AND_GENERAL": "首领+副将",
    "ELITE_AND_GENERAL": "精英+副将", "ELITE_AND_BOSS": "精英+首领", "ALL": "全部标记",
    # 深渊暗影·难度
    "EASY": "简单", "NORMAL": "普通", "HARD": "困难", "EXTREME": "极难",
    # 呱太来袭策略
    "frog_majority": "跟随多数投票", "frog_minority": "跟随少数投票",
    "frog_bilibili": "参考 B 站弹幕", "frog_dashen": "参考大神（网易大神）",
    "frog_oas": "使用内置答案", "frog_always_red": "永远选红方", "frog_always_blue": "永远选蓝方",
    # 截图/点击方式
    "window_background": "窗口后台截图", "nemu_ipc": "MuMu IPC（推荐）",
    "minitouch": "minitouch（推荐）", "window_message": "窗口消息",
}


def enum_label(value: str) -> str:
    return ENUM_LABELS.get(str(value), str(value))


# 关键字段说明：按字段路径后缀匹配，UI 自动挂到对应控件上做提示
FIELD_HINTS: list[tuple[str, str]] = [
    ("scheduler.enable",
     "引擎调度器开关。GUI 的编排表不依赖它——编排表按顺序直接调用任务，"
     "这里只在「任务库」单独跑定时任务时才需要打开。"),
    ("scheduler.next_run", "下次自动执行时间，仅引擎调度器使用。"),
    ("scheduler.priority", "数值越小越先执行，多个任务同时到期时用于排序。"),
    ("scheduler.success_interval", "成功后的间隔，格式 `DD HH:MM:SS`。"),
    ("scheduler.failure_interval", "失败后的重试间隔，格式 `DD HH:MM:SS`。"),
    ("limit_time", "任务最长运行时间，到达后安全收尾并尽量回庭院。"),
    ("limit_count", "最多挑战次数。第一次验证流程时建议设 1。"),
    ("user_status", "双账号联动的关键：队长负责建房邀请，队员负责接受邀请。"
                    "在编排表里把两个账号绑到同一步，UI 会自动分别设为队长/队员。"),
    ("preset_enable", "出战准备界面自动点「预设」并应用指定组/队。游戏只允许在准备界面应用预设。"),
    ("preset_group", "预设组编号，范围 1-7（游戏内最多 7 组）。"),
    ("preset_team", "预设队伍编号。引擎只提供 1-4 队的按钮素材，选 5 会回退到第 1 队。"),
    ("lock_team_enable", "锁阵容后无法在准备界面换预设，与 preset_enable 互斥。"),
    ("switch_group_team", "格式 `组,套`，如 `2,3` 表示第 2 组第 3 套；`-1,-1` 表示不切换。"),
    ("switch_soul_config.enable", "进入战斗前先去式神录切换整套御魂，这是真正的『战斗前』调整。"),
    ("costume_main_type", "庭院皮肤候选。必须包含账号实际皮肤，否则导航会失败；"
                          "建议全选 19 个候选让引擎自动探测。"),
    ("boss_number", "挑战几个地域鬼王。日常建议 1-3。"),
    ("boss_reward", "悬赏鬼王额外挑战一次，会消耗额外体力。"),
    ("continuous_battle", "连续战斗（同一阵容连打）。部分玩法不支持连战。"),
    ("battle_timeout", "战斗超时秒数，-1 表示用默认 420 秒。"),
    ("screenshot_interval", "截图间隔，越小越灵敏但 CPU 占用越高，默认 0.3 秒。"),
    ("combat_screenshot_interval", "战斗中截图间隔，默认 1.0 秒。"),
    ("control_method", "点击方式。minitouch 最快最稳（推荐）；uiautomator2 兼容性好但更慢。"),
    ("screenshot_method", "截图方式。MuMu 推荐 nemu_ipc；其它模拟器用 adb。"),
    ("serial", "模拟器 adb 地址，格式 `127.0.0.1:端口`。MuMu 12 多开端口从 16384 起递增。"),
    ("package_name", "游戏包名，auto 表示自动探测。"),
]

# ─────────────────────────── 已知问题 ───────────────────────────

KNOWN_ISSUES: list[dict] = [
    {
        "id": "costume-main-type",
        "severity": "error",
        "title": "庭院皮肤未声明 → 所有导航失败",
        "scope": "账号运维 / global_game.costume_config.costume_main_type",
        "detail": "账号使用了非默认庭院皮肤，而配置只写了 costume_main 时，庭院→探索入口的模板匹配会失败"
                  "（实测 0.355，阈值 0.8），任务卡在 page_main → page_exploration 反复重试。",
        "fix": "在「账号绑定 → 庭院皮肤」里一键全选 19 个候选，引擎启动时会自动探测实际皮肤。",
    },
    {
        "id": "multi-device-login",
        "severity": "error",
        "title": "账号在其它设备登录会把模拟器挤下线",
        "scope": "所有任务",
        "detail": "游戏检测到多端登录会弹「检测到账号在其他设备登录」，点确定后模拟器被踢回登录界面。",
        "fix": "挂机期间不要在手机/平板上登录同一账号；双开时两个模拟器要登录不同账号。",
    },
    {
        "id": "preset-soul-diff-popup",
        "severity": "warn",
        "title": "应用预设后可能弹「御魂不一致」确认框",
        "scope": "启用 preset_enable 的任务",
        "detail": "预设保存的御魂与式神当前御魂不一致时游戏会弹确认框挡住「准备」，"
                  "引擎素材在部分分辨率下匹配仅 0.756（阈值 0.8）会漏检。",
        "fix": "本地已将 I_CONFIRM_CLOSE_DIFF_SOUL 阈值降到 0.7（弹窗 0.756 / 非弹窗 ≤0.223）。"
               "也可在游戏里勾选「7 日内不再提示」。",
    },
    {
        "id": "preset-team-5",
        "severity": "warn",
        "title": "预设队伍只支持 1-4",
        "scope": "御魂/觉醒等带 preset_team 的任务",
        "detail": "配置校验允许 1-5，但引擎只定义了 4 个队伍按钮素材，选 5 会回退到第 1 队。",
        "fix": "使用 1-4；需要更多阵容时改用御魂切换。",
    },
    {
        "id": "team-duo-prereq",
        "severity": "warn",
        "title": "双账号联动的前置条件",
        "scope": "编排表 · 双人步骤",
        "detail": "队长建房邀请、队员接受邀请，要求两个账号互为好友/同寮，且队员端在邀请到达时处于庭院；"
                  "两个模拟器同时运行会明显抬高 CPU 与内存占用。",
        "fix": "先用「任务库 → 单次验证」分别跑通队长端与队员端，再放进编排表；"
               "建议给每个模拟器限制帧率并关闭多余窗口。",
    },
    {
        "id": "area-boss-settlement",
        "severity": "info",
        "title": "地域鬼王结算屏与通用胜利素材不匹配（已修复）",
        "scope": "地域鬼王",
        "detail": "鬼王团体战胜利屏是专属样式（金色扇面+小组排名），与 gb_win 互匹配仅 0.174；"
                  "战斗期间识别不到 page_battle，60 秒短超时误触发 ESC 导致任务误报失败。",
        "fix": "已新增 I_AB_BATTLE_WIN 模板并入结算页识别，并让未识别战斗维持 300 秒长守卫。实测通过。",
    },
    {
        "id": "battle-theme",
        "severity": "info",
        "title": "自定义战斗主题可能影响识别",
        "scope": "所有战斗任务",
        "detail": "账号开启战斗主题（自定义战斗 UI）时，标准战斗胜负素材可能失配。"
                  "当前账号未开启，实测正常。",
        "fix": "若标准战斗频繁识别失败，先关闭战斗主题再试。",
    },
    {
        "id": "adb-venv-layout",
        "severity": "info",
        "title": "adb 路径依赖运行布局",
        "scope": "部署 / 环境",
        "detail": "引擎按 `python.exe/../Lib/site-packages/adbutils/binaries/adb.exe` 推导 adb，"
                  "只在发布包布局下成立。",
        "fix": "本机已用 `.venv/Scripts/Lib` 目录联接修复；重装环境时需重建。",
    },
    {
        "id": "team-flow-mqtt",
        "severity": "info",
        "title": "引擎内置联动总线（MQTT）默认关闭",
        "scope": "高级设置 · global_game.team_flow",
        "detail": "引擎自带基于 MQTT 的跨进程联动（发布策略/抢占任务），需要自备 broker。"
                  "本 UI 的联动采用「双进程并行 + 角色注入」方式，不依赖 broker。",
        "fix": "除非你有稳定的私有 broker，否则保持 team_flow.enable = false。",
    },
]

# ─────────────────────────── 编排模板 ───────────────────────────

# patch 结构：{任务段名: {字段: 值}}，按步骤顺序生成
FLOW_TEMPLATES: list[dict] = [
    {
        "id": "daily-main",
        "name": "日常一条龙",
        "desc": "签到 → 悬赏 → 宠物 → 委派 → 花合战 → 御魂整理，适合每天早上挂一遍。",
        "accounts": 1,
        "steps": [
            {"task": "daily_trifles"},
            {"task": "wanted_quests"},
            {"task": "pets"},
            {"task": "delegation"},
            {"task": "talisman_pass"},
            {"task": "souls_tidy"},
        ],
    },
    {
        "id": "farm-orochi",
        "name": "御魂 30 次",
        "desc": "八岐大蛇 30 次 + 应用预设第 1 组第 1 队。",
        "accounts": 1,
        "steps": [
            {"task": "orochi", "patch": {"orochi_config": {"limit_count": 30},
                                         "general_battle_config": {"preset_enable": True,
                                                                   "preset_group": 1,
                                                                   "preset_team": 1}}},
        ],
    },
    {
        "id": "duo-evo",
        "name": "双人觉醒 30 次",
        "desc": "主号做队长建房、小号接受邀请，配置在步骤上统一设置，两端自动同步层数。",
        "accounts": 2,
        "steps": [
            {"task": "evo_zone", "mode": "duo",
             "patch": {"evo_zone_config": {"kirin_type": "火麒麟", "layer": "壹层", "limit_count": 30}}},
        ],
    },
    {
        "id": "duo-orochi",
        "name": "双人御魂 50 次",
        "desc": "队长/队员自动分工，适合两个账号互相带。",
        "accounts": 2,
        "steps": [
            {"task": "orochi", "mode": "duo",
             "patch": {"orochi_config": {"limit_count": 50},
                       "general_battle_config": {"preset_enable": True, "preset_group": 1,
                                                 "preset_team": 1}}},
        ],
    },
    {
        "id": "evening-boss",
        "name": "晚间鬼王",
        "desc": "逢魔之时 + 地域鬼王 3 只 + LBS 鬼王，20:00 之后执行。",
        "accounts": 1,
        "steps": [
            {"task": "demon_encounter"},
            {"task": "area_boss", "patch": {"boss": {"boss_number": 3, "boss_reward": False}}},
            {"task": "lbs"},
        ],
    },
]


def task_display(key: str) -> tuple[str, str]:
    """返回 (中文名, 分类)；旧分类名经 CATEGORY_ALIAS 归并到新分类；未知任务回退到原始键名。"""
    meta = TASK_META.get(key)
    if meta is None:
        return key, "其他"
    return meta[0], CATEGORY_ALIAS.get(meta[1], meta[1])


def task_desc(key: str) -> str:
    meta = TASK_META.get(key)
    return meta[2] if meta else ""


def task_team(key: str) -> bool:
    meta = TASK_META.get(key)
    return bool(meta[3]) if meta else False
