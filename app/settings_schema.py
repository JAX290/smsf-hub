"""面板上「可调参数」的定义表 —— 驱动自动生成表单。

每一项：path 是 config.yaml 里的键路径，label 是中文说明，
type 决定控件类型，choices 是下拉选项。
加新参数只要在这里加一行，面板和保存逻辑都自动生效。
"""
from __future__ import annotations

GROUP_LABELS = {
    "merge": "合并发送",
    "dedup": "去重",
    "archive": "归档",
    "security": "安全",
    "panel": "面板",
    "log": "日志",
}

SCHEMA = [
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

    # ---- 安全 ----
    {"group": "security", "path": "security.timestamp_tolerance_seconds", "label": "时间戳容忍范围（秒）", "type": "int",
     "min": 30, "max": 86400, "hint": "手机时间与服务端相差超过这个值就拒收，防重放"},
    {"group": "security", "path": "security.extra_token_header", "label": "附加校验请求头名", "type": "str",
     "hint": "可选。留空则不启用。例如 X-Token"},
    {"group": "security", "path": "security.extra_token_value", "label": "附加校验请求头值", "type": "str"},

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

# 渠道里有这几个通用可调项（其余属于凭据，单独在渠道页维护）
CHANNEL_EDITABLE = {
    "wework_robot": [
        {"path": "channels.wework_robot.enable", "label": "启用", "type": "bool"},
        {"path": "channels.wework_robot.webhook", "label": "WebHook 地址", "type": "str",
         "hint": "企业微信群里添加「消息推送/群机器人」后复制整条地址"},
        {"path": "channels.wework_robot.msgtype", "label": "消息类型", "type": "choice",
         "choices": [["markdown", "Markdown"], ["text", "纯文本"]]},
        {"path": "channels.wework_robot.at_all", "label": "@所有人", "type": "bool"},
        {"path": "channels.wework_robot.at_mobiles", "label": "@的手机号", "type": "str", "hint": "多个用逗号分隔"},
    ],
    "wework_agent": [
        {"path": "channels.wework_agent.enable", "label": "启用", "type": "bool"},
        {"path": "channels.wework_agent.corp_id", "label": "企业 ID (corp_id)", "type": "str"},
        {"path": "channels.wework_agent.agent_id", "label": "应用 ID (agent_id)", "type": "str"},
        {"path": "channels.wework_agent.secret", "label": "应用 Secret", "type": "str"},
        {"path": "channels.wework_agent.to_user", "label": "接收人", "type": "str", "hint": "@all 表示所有人"},
    ],
    "dingtalk_robot": [
        {"path": "channels.dingtalk_robot.enable", "label": "启用", "type": "bool"},
        {"path": "channels.dingtalk_robot.webhook", "label": "WebHook 地址", "type": "str"},
        {"path": "channels.dingtalk_robot.secret", "label": "加签密钥（可选）", "type": "str", "hint": "机器人安全设置里选「加签」时填"},
        {"path": "channels.dingtalk_robot.at_all", "label": "@所有人", "type": "bool"},
        {"path": "channels.dingtalk_robot.at_mobiles", "label": "@的手机号", "type": "str"},
    ],
    "feishu_robot": [
        {"path": "channels.feishu_robot.enable", "label": "启用", "type": "bool"},
        {"path": "channels.feishu_robot.webhook", "label": "WebHook 地址", "type": "str"},
        {"path": "channels.feishu_robot.secret", "label": "签名校验密钥（可选）", "type": "str"},
    ],
    "telegram": [
        {"path": "channels.telegram.enable", "label": "启用", "type": "bool"},
        {"path": "channels.telegram.bot_token", "label": "Bot Token", "type": "str"},
        {"path": "channels.telegram.chat_id", "label": "Chat ID", "type": "str", "hint": "群组 ID 是负数，别漏负号"},
        {"path": "channels.telegram.api_base", "label": "API 地址", "type": "str"},
    ],
    "bark": [
        {"path": "channels.bark.enable", "label": "启用", "type": "bool"},
        {"path": "channels.bark.server", "label": "服务器地址", "type": "str"},
        {"path": "channels.bark.device_key", "label": "设备 Key", "type": "str"},
        {"path": "channels.bark.group", "label": "分组名", "type": "str"},
    ],
    "ntfy": [
        {"path": "channels.ntfy.enable", "label": "启用", "type": "bool"},
        {"path": "channels.ntfy.server", "label": "服务器地址", "type": "str"},
        {"path": "channels.ntfy.topic", "label": "主题 (topic)", "type": "str"},
        {"path": "channels.ntfy.token", "label": "访问令牌（可选）", "type": "str"},
    ],
    "gotify": [
        {"path": "channels.gotify.enable", "label": "启用", "type": "bool"},
        {"path": "channels.gotify.server", "label": "服务器地址", "type": "str"},
        {"path": "channels.gotify.token", "label": "应用令牌", "type": "str"},
        {"path": "channels.gotify.priority", "label": "优先级", "type": "int", "min": 0, "max": 10},
    ],
    "pushplus": [
        {"path": "channels.pushplus.enable", "label": "启用", "type": "bool"},
        {"path": "channels.pushplus.token", "label": "Token", "type": "str"},
        {"path": "channels.pushplus.topic", "label": "群组编码（可选）", "type": "str"},
    ],
    "serverchan": [
        {"path": "channels.serverchan.enable", "label": "启用", "type": "bool"},
        {"path": "channels.serverchan.send_key", "label": "SendKey", "type": "str"},
    ],
    "smtp": [
        {"path": "channels.smtp.enable", "label": "启用", "type": "bool"},
        {"path": "channels.smtp.host", "label": "SMTP 服务器", "type": "str"},
        {"path": "channels.smtp.port", "label": "端口", "type": "int", "min": 1, "max": 65535},
        {"path": "channels.smtp.ssl", "label": "使用 SSL", "type": "bool"},
        {"path": "channels.smtp.username", "label": "用户名", "type": "str"},
        {"path": "channels.smtp.password", "label": "密码/授权码", "type": "str"},
        {"path": "channels.smtp.mail_from", "label": "发件人", "type": "str"},
        {"path": "channels.smtp.mail_to", "label": "收件人", "type": "str", "hint": "多个用逗号分隔"},
        {"path": "channels.smtp.subject_prefix", "label": "邮件主题前缀", "type": "str"},
    ],
    "webhook": [
        {"path": "channels.webhook.enable", "label": "启用", "type": "bool"},
        {"path": "channels.webhook.url", "label": "目标地址", "type": "str"},
        {"path": "channels.webhook.method", "label": "请求方法", "type": "choice",
         "choices": [["POST", "POST"], ["PUT", "PUT"], ["PATCH", "PATCH"], ["GET", "GET"]]},
    ],
    "archive_only": [
        {"path": "channels.archive_only.enable", "label": "启用（仅归档不推送）", "type": "bool"},
    ],
}
