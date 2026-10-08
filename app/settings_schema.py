"""面板上「可调参数」的定义表 —— 驱动自动生成表单。

每一项：path 是 config.yaml 里的键路径，label 是中文说明，
type 决定控件类型，choices 是下拉选项。
加新参数只要在这里加一行，面板和保存逻辑都自动生效。
"""
from __future__ import annotations

GROUP_LABELS = {
    "digest": "手机攒批发送",
    "priority": "消息分级（降噪）",
    "analysis": "分析监控",
    "merge": "合并发送",
    "dedup": "去重",
    "archive": "归档",
    "security": "安全",
    "panel": "面板",
    "log": "日志",
}

SCHEMA = [
    # ---- 手机攒批发送 ----
    # 手机端把消息攒成一批只发一次，省射频唤醒（实测一天 715 次 → 约 120 次）。
    # 这几个值由服务端通过心跳响应下发，改完手机端自动生效，不用重装 APK。
    {"group": "digest", "path": "digest.enable", "label": "启用手机端攒批发送", "type": "bool",
     "hint": "关掉就退回「来一条发一条」（费电但最实时）"},
    {"group": "digest", "path": "digest.near_minutes",
     "label": "普通通知攒多久发一波（分钟）", "type": "int", "min": 0, "max": 1440,
     "hint": "真人消息（微信/QQ/Telegram）也在这一档。0 = 立即发。默认 15 分钟"},
    {"group": "digest", "path": "digest.daily_hours",
     "label": "系统状态类攒多久发一波（小时）", "type": "int", "min": 0, "max": 168,
     "hint": "「正在后台运行」「睡眠服务运行中」这类零信息量的常驻通知。默认 24 小时；"
             "设 72 就是三天一批"},
    {"group": "digest", "path": "digest.instant_apps",
     "label": "这些应用的通知立即发（包名或名称）", "type": "str",
     "hint": "逗号分隔。留空 = 只有短信/来电/定位和下面的关键词立即发"},
    {"group": "digest", "path": "digest.instant_keywords",
     "label": "命中这些词立即发", "type": "str",
     "hint": "逗号分隔。默认验证码/扣款/转账/登录这类 —— 晚一秒都不行的那种"},
    {"group": "digest", "path": "digest.max_items",
     "label": "一个摘要包最多几条", "type": "int", "min": 20, "max": 1000,
     "hint": "太多就分几次发"},

    # ---- 消息分级（降噪核心）----
    # 判定「真正通知用户的消息」和「系统/应用自报状态」。
    # 判定优先看手机端上报的通知属性（常驻/类别/渠道重要度），再看类型、应用清单、关键词。
    {"group": "priority", "path": "priority.enable", "label": "启用消息分级", "type": "bool",
     "hint": "关掉就退回旧行为：所有消息一律同等对待"},
    {"group": "priority", "path": "priority.min_push_tier", "label": "推送门槛（低于此级别只归档不推送）",
     "type": "choice",
     "choices": [["4", "只推「关键」（短信/来电/验证码）"],
                 ["3", "推「重要」及以上（推荐：含微信/QQ 等真人消息）"],
                 ["2", "推「普通」及以上（噪音也会推，不推荐）"],
                 ["0", "全部推送（等于不分级）"]],
     "hint": "消息流面板不受这个影响，它只管「推送渠道」发不发"},
    {"group": "priority", "path": "priority.important_apps",
     "label": "重要应用清单（包名或名称）", "type": "str",
     "hint": "逗号分隔。命中即判为「重要」。留空 = 用内置默认（微信/QQ/钉钉/飞书/Telegram 等）"},
    {"group": "priority", "path": "priority.noise_apps",
     "label": "噪音应用清单（包名或名称）", "type": "str",
     "hint": "逗号分隔。命中即判为「噪音」，面板默认折叠、归档只留一行摘要。"
             "留空 = 用内置默认（系统组件、VPN、音乐播放器等自报状态的）"},
    {"group": "priority", "path": "priority.important_keywords",
     "label": "关键关键词（命中即判为「关键」）", "type": "str",
     "hint": "逗号分隔，例如 验证码,转账,快递,挂号。留空 = 用内置默认"},
    {"group": "priority", "path": "priority.noise_keywords",
     "label": "噪音关键词（命中即判为「噪音」）", "type": "str",
     "hint": "逗号分隔，例如 正在后台运行,正在获取,睡眠服务。留空 = 用内置默认"},

    # ---- 分析监控 ----
    {"group": "analysis", "path": "analysis.enable", "label": "启用分析监控", "type": "bool",
     "hint": "「分析监控」页的每日摘要 / 关键词监控 / 异常检测。只读不改数据"},
    {"group": "analysis", "path": "analysis.watch_keywords",
     "label": "关注词（命中就单独列出来）", "type": "str",
     "hint": "逗号分隔。留空 = 用内置默认（验证码/转账/扣款/登录/异常/快递…）"},
    {"group": "analysis", "path": "analysis.spike_factor",
     "label": "通知量暴涨倍数", "type": "float", "min": 1.5, "max": 20,
     "hint": "某应用某一小时的条数 ≥ 它平均每小时的这个倍数，就提醒你"},
    {"group": "analysis", "path": "analysis.spike_min_count",
     "label": "通知量暴涨下限（条）", "type": "int", "min": 5, "max": 500,
     "hint": "太少的量不值得提醒"},
    {"group": "analysis", "path": "analysis.code_burst",
     "label": "验证码突增阈值（条/小时）", "type": "int", "min": 2, "max": 100,
     "hint": "一小时内验证码达到这个数就报警 —— 可能是有人在拿你的号试探注册/登录"},

    # ---- 合并发送 ----
    {"group": "merge", "path": "merge.enable", "label": "启用合并发送", "type": "bool",
     "hint": "把短时间内的多条消息合并成一条再推送，避免刷屏、也绕开渠道限流"},
    {"group": "merge", "path": "merge.window_seconds", "label": "合并窗口（秒）", "type": "int",
     "min": 0, "max": 3600, "hint": "窗口内的消息攒起来一起发。想更实时就调小（如 15），想更省事就调大（如 300）"},
    {"group": "merge", "path": "merge.max_items", "label": "合并条数上限", "type": "int",
     "min": 1, "max": 200, "hint": "单条合并消息最多含几条，超过立刻发出"},
    {"group": "merge", "path": "merge.group_by", "label": "合并分组方式", "type": "choice",
     "choices": [["subject", "按来源主题（推荐）"], ["app", "按 App 名"], ["none", "全部混在一起"]],
     "hint": "决定哪些消息算「同类」可以合并"},

    # ---- 去重 ----
    {"group": "dedup", "path": "dedup.enable", "label": "启用去重", "type": "bool"},
    {"group": "dedup", "path": "dedup.window_seconds", "label": "去重窗口（秒）", "type": "int",
     "min": 1, "max": 3600, "hint": "同样内容在此时间内重复到达，只处理一次"},
    {"group": "dedup", "path": "dedup.max_entries", "label": "去重表容量", "type": "int", "min": 100, "max": 100000},

    # ---- 归档 ----
    {"group": "archive", "path": "archive.enable", "label": "启用归档", "type": "bool"},
    {"group": "archive", "path": "archive.file_max_mb", "label": "单文件大小上限（MB）", "type": "float",
     "min": 0.5, "max": 200, "hint": "超过就滚动成 2026-09-22.part2.md，避免单个文件无限变大"},
    {"group": "archive", "path": "archive.total_max_mb", "label": "归档总量上限（MB）", "type": "float",
     "min": 10, "max": 20000, "hint": "超过就在面板顶栏报警，提示你打包下载"},
    {"group": "archive", "path": "archive.warn_percent", "label": "预警阈值（%）", "type": "float",
     "min": 10, "max": 99, "hint": "占用达到这个百分比就变黄，100% 变红"},
    {"group": "archive", "path": "archive.content_max_chars", "label": "单条内容截断长度", "type": "int",
     "min": 0, "max": 100000, "hint": "0 表示不截断"},
    {"group": "archive", "path": "archive.subject_rules.sms", "label": "短信按什么分主题", "type": "choice",
     "choices": [["sender", "发件人号码"], ["app", "应用名"]], "hint": "决定归档目录的第二层文件夹名"},
    {"group": "archive", "path": "archive.subject_rules.call", "label": "来电按什么分主题", "type": "choice",
     "choices": [["sender", "来电号码"], ["app", "应用名"]]},
    {"group": "archive", "path": "archive.subject_rules.notify", "label": "APP通知按什么分主题", "type": "choice",
     "choices": [["app", "应用名"], ["sender", "发件人"]]},
    {"group": "archive", "path": "archive.subject_rules.location", "label": "定位按什么分主题", "type": "choice",
     "choices": [["none", "不分主题（推荐）"], ["sender", "来源"]],
     "hint": "定位没有发件人，一般选「不分主题」，直接按日期归档"},


    # ---- 安全 ----
    {"group": "security", "path": "security.timestamp_tolerance_seconds", "label": "时间戳容忍范围（秒）", "type": "int",
     "min": 30, "max": 86400, "hint": "手机时间与服务端相差超过这个值就拒收，防重放"},
    {"group": "security", "path": "security.extra_token_header", "label": "附加校验请求头名", "type": "str",
     "hint": "可选。留空则不启用。例如 X-Token"},
    {"group": "security", "path": "security.extra_token_value", "label": "附加校验请求头值", "type": "str"},
    {"group": "security", "path": "security.pair_key", "label": "配对钥匙（换服务器自动重配用）", "type": "str",
     "hint": "和手机 APK 里内置的一致。留空则配对功能不可用。生成：openssl rand -hex 32"},
    {"group": "security", "path": "security.pair_rate_limit_per_minute", "label": "配对请求限速（次/分钟）", "type": "int",
     "min": 1, "max": 120, "hint": "防止配对接口被反复试探"},

    # ---- 面板 ----
    {"group": "panel", "path": "panel.auth_enabled", "label": "面板要求登录口令", "type": "bool",
     "hint": "默认关闭。面板只绑 Tailscale IP，由 Tailscale 本身做访问控制。想再加一道口令就打开，并在下面填口令"},
    {"group": "panel", "path": "panel.password", "label": "面板口令（开启上面开关后才生效）", "type": "str"},
    {"group": "panel", "path": "panel.title", "label": "面板标题", "type": "str"},
    {"group": "panel", "path": "panel.page_size", "label": "每页条数", "type": "int", "min": 10, "max": 500},
    {"group": "panel", "path": "panel.recent_keep", "label": "内存中保留的最近消息数", "type": "int", "min": 50, "max": 10000},
    # 安装包下载开关不放在这里 —— 它是「临时授权」，请在【首页】顶部的大开关处操作：
    # 可开 X 分钟 / 允许 X 次 / 一直开启，到期或用完会自动关闭。

    # ---- 日志 ----
    {"group": "log", "path": "log.level", "label": "日志级别", "type": "choice",
     "choices": [["DEBUG", "DEBUG（最详细）"], ["INFO", "INFO（推荐）"], ["WARNING", "WARNING"], ["ERROR", "ERROR（最少）"]]},
    {"group": "log", "path": "log.max_mb", "label": "日志轮转大小（MB）", "type": "int", "min": 1, "max": 500},
]

# ---------------------------------------------------------------------------
# 渠道终端字段
# ---------------------------------------------------------------------------
#
# 每个渠道类型可以配多个「终端」——比如两台企业微信机器人、三个不同的群。
# 面板上点「+ 添加终端」就多一个。这里定义的是「一个终端有哪些字段」，
# 字段值存在 channels.yaml 里（面板全权管理，可以整份重写）。
#
# type: bool / str / int / choice；default 是新建终端时的初始值。

CHANNEL_EDITABLE = {
    "wework_robot": [
        {"key": "enable", "label": "启用", "type": "bool", "default": False},
        {"key": "webhook", "label": "WebHook 地址", "type": "str", "default": "",
         "hint": "企业微信群里添加「消息推送/群机器人」后复制整条地址"},
        {"key": "msgtype", "label": "消息类型", "type": "choice", "default": "markdown",
         "choices": [["markdown", "Markdown"], ["text", "纯文本"]]},
        {"key": "at_all", "label": "@所有人", "type": "bool", "default": False},
        {"key": "at_mobiles", "label": "@的手机号", "type": "str", "default": "",
         "hint": "多个用逗号分隔"},
    ],
    "wework_agent": [
        {"key": "enable", "label": "启用", "type": "bool", "default": False},
        {"key": "corp_id", "label": "企业 ID (corp_id)", "type": "str", "default": ""},
        {"key": "agent_id", "label": "应用 ID (agent_id)", "type": "str", "default": ""},
        {"key": "secret", "label": "应用 Secret", "type": "str", "default": ""},
        {"key": "to_user", "label": "接收人", "type": "str", "default": "@all",
         "hint": "@all 表示所有人"},
    ],
    "dingtalk_robot": [
        {"key": "enable", "label": "启用", "type": "bool", "default": False},
        {"key": "webhook", "label": "WebHook 地址", "type": "str", "default": ""},
        {"key": "secret", "label": "加签密钥（可选）", "type": "str", "default": "",
         "hint": "机器人安全设置里选「加签」时填"},
        {"key": "at_all", "label": "@所有人", "type": "bool", "default": False},
        {"key": "at_mobiles", "label": "@的手机号", "type": "str", "default": ""},
    ],
    "feishu_robot": [
        {"key": "enable", "label": "启用", "type": "bool", "default": False},
        {"key": "webhook", "label": "WebHook 地址", "type": "str", "default": ""},
        {"key": "secret", "label": "签名校验密钥（可选）", "type": "str", "default": ""},
    ],
    "telegram": [
        {"key": "enable", "label": "启用", "type": "bool", "default": False},
        {"key": "bot_token", "label": "Bot Token", "type": "str", "default": ""},
        {"key": "chat_id", "label": "Chat ID", "type": "str", "default": "",
         "hint": "群组 ID 是负数，别漏负号"},
        {"key": "api_base", "label": "API 地址", "type": "str",
         "default": "https://api.telegram.org"},
    ],
    "bark": [
        {"key": "enable", "label": "启用", "type": "bool", "default": False},
        {"key": "server", "label": "服务器地址", "type": "str", "default": "https://api.day.app"},
        {"key": "device_key", "label": "设备 Key", "type": "str", "default": ""},
        {"key": "group", "label": "分组名", "type": "str", "default": "短信转发"},
        {"key": "sound", "label": "提示音（可选）", "type": "str", "default": ""},
    ],
    "ntfy": [
        {"key": "enable", "label": "启用", "type": "bool", "default": False},
        {"key": "server", "label": "服务器地址", "type": "str", "default": "https://ntfy.sh"},
        {"key": "topic", "label": "主题 (topic)", "type": "str", "default": ""},
        {"key": "token", "label": "访问令牌（可选）", "type": "str", "default": ""},
    ],
    "gotify": [
        {"key": "enable", "label": "启用", "type": "bool", "default": False},
        {"key": "server", "label": "服务器地址", "type": "str", "default": ""},
        {"key": "token", "label": "应用令牌", "type": "str", "default": ""},
        {"key": "priority", "label": "优先级", "type": "int", "default": 5, "min": 0, "max": 10},
    ],
    "pushplus": [
        {"key": "enable", "label": "启用", "type": "bool", "default": False},
        {"key": "token", "label": "Token", "type": "str", "default": ""},
        {"key": "topic", "label": "群组编码（可选）", "type": "str", "default": ""},
    ],
    "serverchan": [
        {"key": "enable", "label": "启用", "type": "bool", "default": False},
        {"key": "send_key", "label": "SendKey", "type": "str", "default": ""},
    ],
    "smtp": [
        {"key": "enable", "label": "启用", "type": "bool", "default": False},
        {"key": "host", "label": "SMTP 服务器", "type": "str", "default": ""},
        {"key": "port", "label": "端口", "type": "int", "default": 465, "min": 1, "max": 65535},
        {"key": "ssl", "label": "使用 SSL", "type": "bool", "default": True},
        {"key": "username", "label": "用户名", "type": "str", "default": ""},
        {"key": "password", "label": "密码/授权码", "type": "str", "default": ""},
        {"key": "mail_from", "label": "发件人", "type": "str", "default": ""},
        {"key": "mail_to", "label": "收件人", "type": "str", "default": "",
         "hint": "多个用逗号分隔"},
        {"key": "subject_prefix", "label": "邮件主题前缀", "type": "str", "default": "[短信转发]"},
    ],
    "webhook": [
        {"key": "enable", "label": "启用", "type": "bool", "default": False},
        {"key": "url", "label": "目标地址", "type": "str", "default": ""},
        {"key": "method", "label": "请求方法", "type": "choice", "default": "POST",
         "choices": [["POST", "POST"], ["PUT", "PUT"], ["PATCH", "PATCH"], ["GET", "GET"]]},
    ],
    "archive_only": [
        {"key": "enable", "label": "启用（仅归档不推送）", "type": "bool", "default": False},
    ],
}

# 每个终端自己的「转发规则」：留空 = 不限制
RULE_FIELDS = [
    {"key": "devices", "label": "只转发这些手机", "type": "str", "default": "",
     "hint": "填手机的备注名或设备号，多个用逗号分隔。留空 = 全部手机"},
    {"key": "types", "label": "只转发这些类型", "type": "str", "default": "",
     "hint": "sms=短信、call=来电、app=应用通知、location=定位。多个用逗号分隔，留空 = 全部"},
    {"key": "apps", "label": "只转发这些应用", "type": "str", "default": "",
     "hint": "填应用名的一部分就行（如 微信、支付宝），多个用逗号分隔。留空 = 全部"},
]
