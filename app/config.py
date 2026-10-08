"""配置加载：读取 config.yaml，缺失项用默认值补齐。"""
from __future__ import annotations
import copy
import os
from pathlib import Path
from typing import Any

import yaml

from .analysis import DEFAULT_WATCH_KEYWORDS
from .classify import (
    DEFAULT_IMPORTANT_APPS,
    DEFAULT_IMPORTANT_KEYWORDS,
    DEFAULT_NOISE_APPS,
    DEFAULT_NOISE_KEYWORDS,
)

DEFAULTS: dict[str, Any] = {
    "server": {
        "listen_host": "0.0.0.0",
        "listen_port": 8788,
        "panel_host": "127.0.0.1",
        "panel_port": 8790,
        # 下面这两个由 deploy/install.sh 在安装时问你（或自动探测）后填入，
        # 这里故意留空 —— 不写死任何具体域名，换服务器时不用改代码。
        "public_base_url": "",
        "phone_base_url": "",
    },
    "security": {
        "secret": "",
        "timestamp_tolerance_seconds": 300,
        "extra_token_header": "",
        "extra_token_value": "",
    },
    "dedup": {"enable": True, "window_seconds": 900, "max_entries": 20000},
    "merge": {
        "enable": True,
        "window_seconds": 60,
        "max_items": 20,
        "group_by": "subject",
        "separator": "\n---\n",
    },
    "archive": {
        "enable": True,
        "root": "./data/archive",
        "subject_rules": {"sms": "sender", "call": "sender", "notify": "app"},
        "file_max_mb": 5,
        "total_max_mb": 512,
        "warn_percent": 80,
        "content_max_chars": 4000,
        # 归档不做任何自动删除：原始数据一直留着，
        # 只在总量超限或磁盘剩余空间不足时，在面板提示「该下载清理了」。
        "warn_free_gb": 2.0,
    },
    # ---- 消息分级（降噪核心）--------------------------------------------
    # 目的：把「真正通知用户的消息」和「系统/应用自报状态」分开。
    # 判定优先看手机端上报的通知属性（常驻 / 类别 / 渠道重要度），
    # 再看类型、应用清单、关键词。四个清单都能在这里改，面板表单也能改。
    "priority": {
        "enable": True,
        # 低于这个层级不推送（只归档）。3 = 重要及以上才推。0 = 全部推。
        "min_push_tier": 3,
        # 下面四个清单用「逗号分隔的字符串」存 —— 面板表单是单行输入框，
        # 这样能直接编辑；留空表示用 classify.py 里的内置默认清单。
        "important_apps": ",".join(DEFAULT_IMPORTANT_APPS),
        "noise_apps": ",".join(DEFAULT_NOISE_APPS),
        "important_keywords": ",".join(DEFAULT_IMPORTANT_KEYWORDS),
        "noise_keywords": ",".join(DEFAULT_NOISE_KEYWORDS),
    },
    "channels": {},
    # ------------------------------------------------------------------
    # 手机端「攒一波再发」的窗口（摘要包）
    #
    # 为什么要攒：手机每发一条消息就要唤醒一次射频。实测某台手机一天 715 条
    # 消息 = 715 次射频唤醒，其中 73% 是真人消息、20% 是系统状态。
    # 攒成一批只发一次，能把唤醒次数压到 1/6 左右。
    #
    # 这些值由服务端通过**心跳响应**下发给手机（见 pipeline.digest_config），
    # 所以在这里/面板改完就生效，不用重新编译 APK。
    # 窗口设成 0 表示该类不攒、立即发。
    # ------------------------------------------------------------------
    "digest": {
        "enable": True,
        # 普通通知（含真人消息）攒多久发一波：15 分钟
        "near_minutes": 15,
        # 系统/应用状态类（常驻通知、"正在后台运行"这类）攒多久：24 小时
        "daily_hours": 24,
        # 这些应用的通知**立即发**（逗号分隔包名或名称；短信/来电/定位本来就走别的通道）
        "instant_apps": "",
        # 命中这些词的**立即发**（验证码这类晚一秒都不行）
        "instant_keywords": "验证码,校验码,动态码,短信密码,一次性密码,扣款,转账,支出,退款,登录,密码",
        # 一个摘要包最多带多少条（太大就分几次发）
        "max_items": 200,
    },
    # ---- 消息分析 / 监控 -------------------------------------------------
    # 每日摘要、关键词监控、异常检测（设备静默、通知量暴涨、验证码突增）。
    # 全部只读不改数据，阈值在这里调，面板「参数设置 → 分析监控」也能改。
    "analysis": {
        "enable": True,
        # 关注词：命中的消息会单独列在「关键词监控」里（逗号分隔）
        "watch_keywords": ",".join(DEFAULT_WATCH_KEYWORDS),
        # 通知量暴涨判定：某应用某一小时 ≥ 平均 × 倍数，且绝对值 ≥ 下限
        "spike_factor": 3.0,
        "spike_min_count": 30,
        # 一小时内验证码达到这个条数就报警（可能是被撞库/骚扰）
        "code_burst": 6,
    },
    # 渠道的「终端」配置另存一个文件 —— 它由面板完全接管（增删终端、改转发规则），
    # 可以整份重写，所以不放 config.yaml，免得把这里的注释和缩进弄坏。
    # config.yaml 里那份老的 channels 段只在第一次升级时当种子用。
    "channels_file": "./channels.yaml",
    "panel": {
        "title": "短信转发中枢",
        "password": "",
        "page_size": 50,
        # 面板「消息流」内存里保留多少条（越大能翻得越早，占内存）
        # 500 条在忙的手机上只覆盖 3 小时，2026-10-07 调到 8000 条（约覆盖 2 天）
        "recent_keep": 8000,
        # 最近消息落盘文件保留多少条（比内存大得多，重启后还能翻回去）
        # 估算：单条约 300 字节，200000 条 ≈ 60MB
        "recent_file_keep": 200000,
        # 最近消息落盘文件：重启服务后列表不会丢
        "recent_file": "./app/data/recent.jsonl",
        # 手机注册表（自动登记上报过的手机）
        "devices_file": "./app/data/devices.json",
        # 面板是否要求登录口令。默认 false —— 面板只绑 Tailscale IP，
        # 由 Tailscale 本身做访问控制。想加一道口令就改成 true。
        "auth_enabled": False,
        # 安装包（APK）下载总开关。false = 外部访问 apk1/apk2/apk3 一律拒绝。
        "apk_download_enabled": False,
        # 临时授权的运行时状态（限时/限次），自动生成，一般不用手改。
        "apk_gate_file": "./app/data/apk_gate.json",
    },
    "log": {
        "level": "INFO",
        "file": "./data/logs/hub.log",
        "max_mb": 20,
        "backup_count": 5,
    },
}


def _deep_merge(base: dict, over: dict) -> dict:
    """把 over 合并进 base 的副本；只递归合并 dict，其它类型直接覆盖。"""
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self, data: dict, path: Path):
        self._data = data
        self.path = path

    def get(self, dotted: str, default: Any = None) -> Any:
        """支持 'merge.window_seconds' 这种点号取值。"""
        cur: Any = self._data
        for part in dotted.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    @property
    def raw(self) -> dict:
        return self._data

    def enabled_channels(self) -> dict:
        """返回所有 enable=true 的渠道配置。"""
        out = {}
        for name, val in (self._data.get("channels") or {}).items():
            if isinstance(val, dict) and val.get("enable"):
                out[name] = val
        return out

    def archive_root(self) -> Path:
        p = Path(str(self.get("archive.root", "./data/archive")))
        if not p.is_absolute():
            p = (self.path.parent / p).resolve()
        return p


def load_config(path: str | os.PathLike | None = None) -> Config:
    if path is None:
        path = os.environ.get("SMSF_CONFIG", "config.yaml")
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"配置文件不存在: {p}")
    with p.open("r", encoding="utf-8") as f:
        user = yaml.safe_load(f) or {}
    return Config(_deep_merge(DEFAULTS, user), p)
