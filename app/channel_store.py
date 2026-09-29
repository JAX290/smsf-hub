"""渠道实例配置的存取。

为什么不写在 config.yaml 里：
    config.yaml 是「安装时手写、带中文注释」的文件，用正则去它里面增删一段，
    很容易把注释和缩进弄坏。而渠道实例（终端）是面板完全接管的 —— 增删改都走
    界面，所以单独放一个 channels.yaml，可以整份重写，风险小得多。

    config.yaml 里那份老的 channels 段不删，只在第一次升级时当种子用
    （见 seed_from_config）。之后以 channels.yaml 为准。

结构：
    wework_robot:
      - id: i1
        label: 1号群
        enable: true
        webhook: https://...
        msgtype: markdown
        rules:
          devices: ""
          types: ""
          apps: ""
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from .settings_schema import CHANNEL_EDITABLE, RULE_FIELDS

log = logging.getLogger("smsf-hub.channel-store")

# 终端名称是所有渠道共有的字段，不在各自的字段表里重复写
LABEL_FIELD = {"key": "label", "label": "终端名称", "type": "str", "default": "",
               "hint": "只是给你自己看的，比如「工作群」。留空就按序号显示"}

_ID_RE = re.compile(r"^i(\d+)$")


def store_path(cfg) -> Path:
    """channels.yaml 的位置：跟着 config.yaml 放同一个目录。"""
    p = Path(str(cfg.get("channels_file", "./channels.yaml")))
    if not p.is_absolute():
        p = Path(cfg.path).parent / p
    return p


def field_specs(name: str) -> list:
    """某个渠道类型的一个终端有哪些字段（名称在最前）。"""
    return [LABEL_FIELD] + list(CHANNEL_EDITABLE.get(name) or [])


def field_names(name: str) -> list:
    return [f["key"] for f in field_specs(name)]


def _type_of(name: str, key: str) -> str:
    for f in field_specs(name):
        if f["key"] == key:
            return f.get("type", "str")
    return "str"


def blank_instance(name: str, inst_id: str = "") -> dict:
    """按字段表造一个空终端（各字段用 default 填）。"""
    inst = {"id": inst_id}
    for f in field_specs(name):
        inst[f["key"]] = f.get("default", False if f.get("type") == "bool" else "")
    inst["rules"] = {r["key"]: "" for r in RULE_FIELDS}
    return inst


def pick_id(used) -> str:
    """在已用掉的 id 集合里挑一个没用过的（i1、i2……）。"""
    used = set(used or ())
    n = 1
    while ("i%d" % n) in used:
        n += 1
    return "i%d" % n


def seed_from_config(cfg) -> dict:
    """把 config.yaml 里老的单实例渠道结构，转成新的多实例结构。

    只搬「已经启用」的那几个 —— 没启用的渠道，面板上点一下「+ 添加终端」
    就能拿到一条带默认值的新终端，不必从旧结构里搬一份空气过来。
    """
    data = {}
    raw = cfg.get("channels") or {}
    if not isinstance(raw, dict):
        return data
    for name in CHANNEL_EDITABLE:
        old = raw.get(name)
        if not isinstance(old, dict) or not old or not old.get("enable"):
            continue
        inst = blank_instance(name, "i1")
        for k, v in old.items():
            if k in inst and k != "rules" and v not in ("", None):
                inst[k] = v
        inst["enable"] = True
        data[name] = [inst]
    return data


def _normalize(name: str, item: dict) -> dict:
    """补全缺的字段，保证面板拿到的结构一致。"""
    inst = blank_instance(name)
    for k in field_names(name):
        if k in item:
            inst[k] = item[k]
    rules = item.get("rules") if isinstance(item.get("rules"), dict) else {}
    for r in RULE_FIELDS:
        if r["key"] in rules:
            inst["rules"][r["key"]] = rules[r["key"]]
    inst["id"] = str(item.get("id") or "")
    return inst


def load(cfg) -> dict:
    """读 channels.yaml。文件不在就先从 config.yaml 迁移一份。"""
    p = store_path(cfg)
    if not p.exists():
        data = seed_from_config(cfg)
        if data:
            save(cfg, data)
            log.info("已把 config.yaml 里的渠道配置迁移到 %s", p)
        return data
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        log.error("channels.yaml 读不出来（%s），本次按「没有渠道」处理", exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    out = {}
    for name in CHANNEL_EDITABLE:
        lst = raw.get(name)
        if not isinstance(lst, list):
            continue
        items = [_normalize(name, it) for it in lst if isinstance(it, dict)]
        used = set()
        for it in items:
            i = it["id"]
            if not i or i in used:
                i = pick_id(used)
                it["id"] = i
            used.add(i)
        out[name] = items
    return out


_HEADER = "\n".join([
    "# 推送渠道的「终端」配置 —— 由面板【推送渠道】页自动维护。",
    "# 想加一台就点界面上的「+ 添加终端」，不用手改这个文件。",
    "# 换服务器时，把这个文件（或它的备份）拷回同一目录即可。",
    "#",
    "# rules 留空 = 不限制；写了值 = 只转发匹配的消息。",
    "",
])


def _clean(name: str, inst: dict) -> dict:
    """写出前的清洗：只留该渠道认识的字段，顺序固定，好读。"""
    out = {"id": str(inst.get("id") or "")}
    for k in field_names(name):
        v = inst.get(k, False if _type_of(name, k) == "bool" else "")
        out[k] = bool(v) if _type_of(name, k) == "bool" else v
    rules_in = inst.get("rules") if isinstance(inst.get("rules"), dict) else {}
    out["rules"] = {r["key"]: str(rules_in.get(r["key"], "") or "") for r in RULE_FIELDS}
    return out


def save(cfg, data: dict) -> None:
    """整份写回 channels.yaml。"""
    p = store_path(cfg)
    clean = {}
    for name, items in (data or {}).items():
        if name not in CHANNEL_EDITABLE:
            continue
        clean[name] = [_clean(name, it) for it in (items or [])]
    body = yaml.safe_dump(clean, allow_unicode=True, sort_keys=False,
                          default_flow_style=False) if clean else "{}"
    p.write_text(_HEADER + body, encoding="utf-8")
    try:
        p.chmod(0o600)
    except Exception:
        pass
