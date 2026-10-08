"""消息分析与监控。

三块，都基于面板那批最近消息（`pipeline.recent`，默认 8000 条）：

1. **每日摘要**（`daily_summary`）——今天收了什么：各级别条数、Top 应用、
   验证码清单、来电清单、每台手机的量。
2. **关键词监控**（`watch_hits`）——命中关注词的消息单独列出来
   （默认：验证码/转账/扣款/登录/异常/逾期…），不用翻消息流。
3. **异常检测**（`anomalies`）——设备静默、某应用通知量暴涨、验证码突增。

设计原则：**只读，不改数据**；判定阈值都能在 config.yaml 的 `analysis:` 段里调。
"""
from __future__ import annotations

import collections
from datetime import datetime, timedelta

from .classify import extract as extract_info
from .models import Incoming

# 验证码快速预筛：正文里出现这些词才值得做正则提取（避免对几千条全量解析）
_CODE_HINTS = ("验证码", "校验码", "动态码", "短信密码", "一次性密码", "code", "otp")


def _ex(r: dict) -> dict:
    """按需提取结构化字段，并缓存在记录上（同一条记录只算一次）。"""
    if "_ex" in r:
        return r["_ex"]
    try:
        e = extract_info(Incoming(
            type=str(r.get("type") or ""), sender=str(r.get("sender") or ""),
            app=str(r.get("app") or ""), content=str(r.get("content") or ""),
            device=str(r.get("device") or "")))
    except Exception:
        e = {}
    r["_ex"] = e
    return e


def _maybe_code(r: dict) -> str:
    text = (r.get("content") or "").lower()
    if not any(h in text for h in _CODE_HINTS):
        return ""
    return _ex(r).get("code") or ""

# ---------------------------------------------------------------- 默认参数

DEFAULT_WATCH_KEYWORDS = [
    "验证码", "校验码", "动态码",
    "转账", "扣款", "支出", "收入", "退款", "收款", "还款", "账单", "逾期", "到账",
    "登录", "密码", "异常", "风险", "冻结", "挂失",
    "快递", "取件", "签收", "预约", "挂号", "航班", "车次", "订单",
]

# 通知量暴涨：某个应用在某一小时内的条数 ≥ 平均值 × 这个倍数，且绝对值 ≥ min_count
SPIKE_FACTOR = 3.0
SPIKE_MIN_COUNT = 30
# 最多报几条暴涨（按「倍数」从大到小取，免得刷屏）
SPIKE_MAX_ALERTS = 5

# 验证码突增：一小时内验证码条数 ≥ 这个值
CODE_BURST = 6


def hour_key(t: str) -> str:
    return (t or "")[:13]


def day_key(t: str) -> str:
    return (t or "")[:10]


def _tier(r: dict) -> int:
    try:
        return int(r.get("tier", 2))
    except (TypeError, ValueError):
        return 2


# ---------------------------------------------------------------- 1. 每日摘要


def daily_summary(rows: list, day: str = "", devices=None) -> dict:
    """某一天（默认今天）的摘要。"""
    if not day:
        day = datetime.now().strftime("%Y-%m-%d")
    day_rows = [r for r in rows if day_key(r.get("time", "")) == day]

    tier_count = collections.Counter(_tier(r) for r in day_rows)
    app_count = collections.Counter(
        (r.get("app") or r.get("sender") or "(未知)") for r in day_rows if _tier(r) >= 3)
    dev_count = collections.Counter((r.get("device") or "(未知)") for r in day_rows)

    codes = []
    calls = []
    for r in day_rows:
        code = _maybe_code(r)
        if code:
            ex = _ex(r)
            codes.append({
                "time": r.get("time", "")[11:],
                "code": code,
                "app": r.get("app") or r.get("sender") or "",
                "device": r.get("device") or "",
                "summary": (ex.get("summary") or "")[:80],
            })
        if (r.get("type") or "") == "call":
            calls.append({
                "time": r.get("time", "")[11:],
                "from": r.get("sender") or "",
                "device": r.get("device") or "",
            })

    # 逐小时趋势（只统计「重要及以上」，即真正要看的东西）
    hourly = collections.Counter()
    for r in day_rows:
        if _tier(r) >= 3:
            hourly[hour_key(r.get("time", ""))[-2:] + ":00"] += 1

    return {
        "day": day,
        "total": len(day_rows),
        "tiers": {t: tier_count.get(t, 0) for t in (4, 3, 2, 1, 0)},
        "important": sum(v for t, v in tier_count.items() if t >= 3),
        "noise": tier_count.get(0, 0),
        "top_apps": app_count.most_common(12),
        "devices": dev_count.most_common(),
        "codes": codes[:30],
        "code_total": len(codes),
        "calls": calls[:20],
        "call_total": len(calls),
        "hourly": [{"hour": f"{h:02d}:00", "n": hourly.get(f"{h:02d}:00", 0)} for h in range(24)],
    }


def trend(rows: list, days: int = 7) -> list:
    """最近 N 天，按天 × 级别汇总（给趋势图用）。"""
    by_day = collections.defaultdict(lambda: collections.Counter())
    for r in rows:
        by_day[day_key(r.get("time", ""))][_tier(r)] += 1
    out = []
    today = datetime.now()
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        c = by_day.get(d, collections.Counter())
        total = sum(c.values())
        out.append({
            "day": d,
            "total": total,
            "t4": c.get(4, 0), "t3": c.get(3, 0), "t2": c.get(2, 0),
            "t1": c.get(1, 0), "t0": c.get(0, 0),
            "important": c.get(4, 0) + c.get(3, 0),
        })
    return out


# ---------------------------------------------------------------- 2. 关键词监控


def watch_hits(rows: list, keywords: list, limit: int = 200) -> list:
    """命中关注词的消息，按时间倒序。"""
    if not keywords:
        return []
    out = []
    for r in rows:
        blob = f"{r.get('app') or ''}\n{r.get('sender') or ''}\n{r.get('content') or ''}".lower()
        hit = ""
        for kw in keywords:
            k = str(kw).strip().lower()
            if k and k in blob:
                hit = kw
                break
        if not hit:
            continue
        ex = _ex(r)
        out.append({
            "time": r.get("time", ""),
            "device": r.get("device") or "",
            "app": r.get("app") or r.get("sender") or "",
            "tier": _tier(r),
            "keyword": hit,
            "summary": ex.get("summary") or (r.get("content") or "")[:80],
            "code": ex.get("code") or "",
        })
        if len(out) >= limit:
            break
    out.sort(key=lambda x: x["time"], reverse=True)
    return out


# ---------------------------------------------------------------- 3. 异常检测


def anomalies(rows: list, days: int = 3, device_status=None,
              spike_factor: float = SPIKE_FACTOR, spike_min: int = SPIKE_MIN_COUNT,
              code_burst: int = CODE_BURST) -> list:
    """返回一串「值得看一眼」的异常。每条是 {level, title, detail}。

    顺序即重要程度：设备静默 → 验证码突增 → 通知量暴涨 → 噪音占比。
    """
    out = []
    spikes = []

    # --- 设备静默 ---
    for d in (device_status or []):
        level = d.get("level") or ""
        if level == "offline":
            out.append({
                "level": "bad",
                "title": f"设备「{d.get('display') or d.get('key')}」已离线",
                "detail": f"最后一次心跳 {d.get('heartbeat_at') or '（从无）'}，"
                          f"最后一条消息 {d.get('last_seen') or '（从无）'}",
            })
        elif level == "warn":
            out.append({
                "level": "warn",
                "title": f"设备「{d.get('display') or d.get('key')}」状态异常",
                "detail": d.get("text") or "心跳正常但权限不全或服务没在跑",
            })

    # --- 通知量暴涨（按 应用 × 小时）---
    # 分母用「整个窗口出现过的小时数」，而不是「该应用出现过的小时数」——
    # 否则一个只在某一小时冒出来的应用，平均值就等于它自己，永远测不出爆发。
    hourly = collections.Counter()
    per_app_total = collections.Counter()
    window_hours = set()
    for r in rows:
        h = hour_key(r.get("time", ""))
        if not h:
            continue
        window_hours.add(h)
        app = r.get("app") or r.get("sender") or ""
        if not app:
            continue
        hourly[(app, h)] += 1
        per_app_total[app] += 1

    hours_n = max(1, len(window_hours))
    for (app, h), n in hourly.most_common(200):
        avg = per_app_total[app] / hours_n
        if n >= spike_min and avg > 0 and n >= avg * spike_factor:
            spikes.append((n / avg, n, app, h, avg))
    spikes.sort(reverse=True)
    for ratio, n, app, h, avg in spikes[:SPIKE_MAX_ALERTS]:
        out.append({
            "level": "warn",
            "title": f"「{app}」通知量突增",
            "detail": f"{h} 点这一小时 {n} 条，是该应用平均每小时（{avg:.1f} 条）的 {ratio:.1f} 倍",
        })

    # --- 验证码突增 ---
    codes_hour = collections.Counter()
    for r in rows:
        if _maybe_code(r):
            codes_hour[hour_key(r.get("time", ""))] += 1
    for h, n in codes_hour.most_common(5):
        if n >= code_burst:
            out.append({
                "level": "warn",
                "title": f"验证码突增：{h} 点 {n} 条",
                "detail": "短时间大量验证码通常是被人拿你的号试探注册/登录，建议核对",
            })

    # --- 手机端上报积压（收到 → 送达 延迟过大）---
    # 常见原因是系统限制了 App 的后台（省电策略 / 自启动没开），
    # 消息攒在手机里发不出来，早上才集中补发 —— 表现为「11 点收到的 14 点才弹」。
    delayed = [r for r in rows if int(r.get("delay_sec") or 0) >= 900]
    if len(delayed) >= 10:
        by_dev = collections.Counter((r.get("device") or "?") for r in delayed)
        worst = max(int(r.get("delay_sec") or 0) for r in delayed)
        out.append({
            "level": "warn",
            "title": f"手机端上报积压：{len(delayed)} 条延迟超过 15 分钟",
            "detail": "按设备 " + "、".join(f"{k} {v} 条" for k, v in by_dev.most_common()) +
                      f"；最长延迟 {worst / 3600:.1f} 小时。"
                      "多半是系统限制了 App 后台（省电策略改成「无限制」、打开自启动、"
                      "加入电池优化白名单），消息攒在手机里发不出来",
        })

    # --- 噪音占比过高 ---
    if rows:
        recent = rows[: min(300, len(rows))]
        noise = sum(1 for r in recent if _tier(r) == 0)
        ratio = noise / len(recent)
        if ratio >= 0.8:
            out.append({
                "level": "info",
                "title": f"最近消息里噪音占 {ratio * 100:.0f}%",
                "detail": "系统/应用自报状态太多，可在「参数设置 → 消息分级」里补噪音关键词或包名",
            })

    return out
