"""配置加载：读取 config.yaml，缺失项用默认值补齐。"""
from __future__ import annotations
import copy
import os
from pathlib import Path
from typing import Any

import yaml

DEFAULTS: dict[str, Any] = {
    "server": {
        "listen_host": "0.0.0.0",
        "listen_port": 8788,
        "panel_host": "127.0.0.1",
        "panel_port": 8790,
        "public_base_url": "",
        "phone_base_url": "https://relay1.mulinsen.win/smsf/hook",
    },
    "security": {
        "secret": "",
        "timestamp_tolerance_seconds": 300,
        "extra_token_header": "",
        "extra_token_value": "",
    },
    "dedup": {"enable": True, "window_seconds": 60, "max_entries": 5000},
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
    },
    "channels": {},
    "panel": {
        "title": "短信转发中枢",
        "password": "",
        "page_size": 50,
        "recent_keep": 500,
        # 最近消息落盘文件：重启服务后列表不会丢
        "recent_file": "./app/data/recent.jsonl",
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
