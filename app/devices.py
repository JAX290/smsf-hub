"""手机注册表：自动登记上报过的手机，支持编号与备注名。

识别逻辑（按优先级）：
  1. 上报数据里的 device 字段（APK 首次启动自动生成的设备 ID）
  2. 若为空，退回用来源 IP（同一 WiFi 下的多台手机会被算作一台，属已知限制）

首次出现的设备自动编号为「手机1」「手机2」…
备注名可在面板里改，改完以备注名显示。
"""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path

log = logging.getLogger("smsf-hub.devices")


_VERSION_LABEL_RE = re.compile(r"\.(v\d+)$")


def version_label(version_name: str, version_code: int) -> str:
    """从版本名/版本号推出「v66」这样的标签，方便一眼看出装的是哪个包。

    背景：手机上显示的版本名原来是 3.5.0.<日期>（例 3.5.0.261009），
    同一天编出来的多个包长得一模一样，分不出是 v 几。
    v67 起版本名末尾会带上标签（3.5.0.261009.v66），优先用它；
    老版本没有标签，就按 versionCode 反推 —— APK 里 versionCode = v号 + 21
    （v51=72 那次定下来的偏移，见 versions.gradle 的 version_code）。
    """
    m = _VERSION_LABEL_RE.search(str(version_name or "").strip())
    if m:
        return m.group(1)
    try:
        code = int(version_code or 0)
    except (TypeError, ValueError):
        code = 0
    # ⚠️ 心跳上报的是**装上去之后的完整 versionCode**，里面带了 ABI 前缀：
    #    300078 = 3 * 100000 + 78（78 才是真正的内部序号）。
    #    一开始忘了取模，结果算出个 v300057 这种鬼东西。
    if code >= 100000:
        code = code % 100000
    if code >= 30:
        return "v%d" % (code - 21)
    return ""


class DeviceRegistry:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._devices: dict = {}
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                self._devices = json.loads(self.path.read_text(encoding="utf-8"))
                log.info("已加载 %d 台手机记录", len(self._devices))
        except Exception:
            log.exception("读取手机注册表失败，从空开始")
            self._devices = {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._devices, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except Exception:
            log.exception("写入手机注册表失败")

    def _next_label(self) -> str:
        n = 1
        used = {d.get("label") for d in self._devices.values()}
        while f"手机{n}" in used:
            n += 1
        return f"手机{n}"

    def touch(self, device_value: str, source_ip: str = "", kind: str = "message") -> dict:
        """登记一次上报，返回该设备的记录。

        kind: "message"（普通消息，计入条数）/ "heartbeat"（心跳，不计入）。
        心跳只是「我还活着」的信号，把它算进消息条数会让面板上的统计虚高。
        """
        key = (device_value or "").strip()
        if not key:
            key = f"ip:{source_ip}" if source_ip else "unknown"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self._lock:
            rec = self._devices.get(key)
            if rec is None:
                rec = {
                    "key": key,
                    "label": self._next_label(),
                    "remark": "",
                    "first_seen": now,
                    "last_seen": now,
                    "count": 0,
                    "last_ip": source_ip,
                }
                self._devices[key] = rec
                log.info("发现新手机：%s (key=%s)", rec["label"], key[:24])
            rec["last_seen"] = now
            if kind != "heartbeat":
                rec["count"] = int(rec.get("count", 0)) + 1
            if source_ip:
                rec["last_ip"] = source_ip
            self._save()
            return dict(rec)

    def rename(self, key: str, remark: str) -> bool:
        with self._lock:
            if key not in self._devices:
                return False
            self._devices[key]["remark"] = remark
            self._save()
            return True

    def remove(self, key: str) -> bool:
        with self._lock:
            if key not in self._devices:
                return False
            self._devices.pop(key)
            self._save()
            return True

    def all(self) -> list:
        rows = []
        for rec in self._devices.values():
            rows.append({
                "key": rec["key"],
                "label": rec["label"],
                "remark": rec.get("remark", ""),
                "display": rec.get("remark") or rec["label"],
                "first_seen": rec.get("first_seen", ""),
                "last_seen": rec.get("last_seen", ""),
                "count": rec.get("count", 0),
                "last_ip": rec.get("last_ip", ""),
            })
        rows.sort(key=lambda r: r["first_seen"])
        return rows

    def count(self) -> int:
        return len(self._devices)

    def online_count(self, within_seconds: int = 300) -> int:
        """最近 N 秒内有上报的算「在线」。"""
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(seconds=within_seconds)
        n = 0
        for rec in self._devices.values():
            try:
                if datetime.strptime(rec.get("last_seen", ""), "%Y-%m-%d %H:%M:%S") >= cutoff:
                    n += 1
            except Exception:
                pass
        return n

    # ==================== 心跳 / 状态 ====================
    #  手机端每 10 分钟报一次心跳，带上「App 版本 / 权限是否齐全 / 服务是否在跑」。
    #  这里负责存下来，并算出一个「颜色 + 文字」给它看。
    #
    #  为什么要单独做：光看「最近有没有消息上报」判断不了死活 ——
    #  手机安静一晚上（没短信没通知）和手机被杀了，在数据上是一样的。
    #  心跳是个主动信号，能把这俩区分开。

    # 心跳超时阈值。手机端每 10 分钟一次，这里给 2.5 倍余量，
    # 免得因为系统调度延迟（Doze、后台限制）误判成离线。
    HEARTBEAT_TIMEOUT_SEC = 25 * 60

    def update_heartbeat(self, device_value: str, status: dict) -> bool:
        """记一次心跳。返回是否找到了对应设备。"""
        key = (device_value or "").strip()
        if not key:
            return False
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            rec = self._devices.get(key)
            if rec is None:
                return False
            rec["heartbeat_at"] = now
            rec["app_version"] = str(status.get("version") or "")
            try:
                rec["version_code"] = int(status.get("code") or 0)
            except Exception:
                rec["version_code"] = 0
            perms = status.get("perms")
            rec["perms"] = perms if isinstance(perms, dict) else {}
            rec["working"] = bool(status.get("working"))
            rec["locked"] = bool(status.get("locked"))
            rec["uptime_sec"] = int(status.get("uptime") or 0)
            self._save()
            return True

    def status_of(self, rec: dict) -> dict:
        """算出一台手机当前该显示成什么样。

        返回 {"level", "color", "text", "detail", "perms"}：
            level: ok / warn / offline / unknown
            color: 给前端用的颜色 key（模板里映射到具体色值）
        """
        from datetime import timedelta
        hb = rec.get("heartbeat_at") or ""
        perms = rec.get("perms") or {}

        # 记下权限明细，面板要逐项显示
        perm_view = {
            "sms": bool(perms.get("sms")),
            "call": bool(perms.get("call")),
            "notify": bool(perms.get("notify")),
            "location": bool(perms.get("location")),
        }
        # 电池优化白名单（v58 起手机端才上报这个字段，老版本没有 → 不判断）
        has_battery = "battery" in perms
        battery_ok = bool(perms.get("battery")) if has_battery else True
        missing = [k for k, v in perm_view.items() if not v]

        if not hb:
            return {
                "level": "unknown", "color": "gray",
                "text": "从未心跳",
                "detail": "这台手机还没装带心跳的版本（v50+），或一直没联网",
                "perms": perm_view, "missing": missing, "battery_ok": battery_ok,
            }

        try:
            age = (datetime.now() - datetime.strptime(hb, "%Y-%m-%d %H:%M:%S")).total_seconds()
        except Exception:
            age = 1e9

        if age > self.HEARTBEAT_TIMEOUT_SEC:
            mins = int(age // 60)
            return {
                "level": "offline", "color": "red",
                "text": "已离线",
                "detail": "最后一次心跳在 %s（%s 前）—— App 可能被系统杀了、被撤销了权限、或手机没网"
                          % (hb, ("%d 小时 %d 分" % (mins // 60, mins % 60)) if mins >= 60 else ("%d 分钟" % mins)),
                "perms": perm_view, "missing": missing,
            }

        # 在线。再看权限和服务状态
        if missing:
            label = {"sms": "短信", "call": "通话", "notify": "通知使用权", "location": "定位"}
            return {
                "level": "warn", "color": "yellow",
                "text": "在线 · 权限不全",
                "detail": "缺少：%s —— 这些权限没给，对应类型的消息会转发不出来"
                          % "、".join(label.get(k, k) for k in missing),
                "perms": perm_view, "missing": missing, "battery_ok": battery_ok,
            }

        # 电池优化白名单：为什么单列一条 ——
        # 实测（2026-10-08）没加白名单的 Xiaomi14，夜里进深度休眠后**网络被系统切断**，
        # 01:00 到 08:00 整整 7 小时一次心跳、一条消息都发不出去，全攒在本地；
        # 早上补发又追不上新消息，导致白天也延迟数小时（当天 46% 的消息晚了 6 小时以上）。
        # 而加过白名单的红米整夜心跳正常（每 10 分钟一次）。
        # 关键在于：这个状态**不在运行时权限里**，所以 App 里那个绿勾亮着也不代表后台放行。
        if has_battery and not battery_ok:
            return {
                "level": "warn", "color": "yellow",
                "text": "在线 · 未加入电池优化白名单",
                "detail": "手机夜间进入深度休眠会切断网络，心跳和上报都会失败、消息全攒在本地，"
                          "早上才补发（实测有手机因此 46% 的消息晚了 6 小时以上）。"
                          "在 App 里打开「功能7 忽略电池优化」即可",
                "perms": perm_view, "missing": missing, "battery_ok": battery_ok,
            }

        if not rec.get("working"):
            return {
                "level": "warn", "color": "yellow",
                "text": "在线 · 但服务没在跑",
                "detail": "心跳能上来，说明网络是通的；但 App 自报「转发服务未运行」，",
                "perms": perm_view, "missing": missing, "battery_ok": battery_ok,
            }

        return {
            "level": "ok", "color": "green",
            "text": "在线 · 一切正常",
            "detail": "权限齐全、服务运行中，最后心跳 %s" % hb,
            "perms": perm_view, "missing": missing, "battery_ok": battery_ok,
        }

    def all_with_status(self) -> list:
        """给面板首页用：每台手机 + 它的状态。

        ⚠️ 这里刻意【不走 self.all()】。
        all() 是个白名单：它只输出自己认识的那 8 个字段
        （key/label/remark/display/first_seen/last_seen/count/last_ip），
        心跳相关的 heartbeat_at / app_version / perms 会被它整个丢掉 ——
        一开始就是踩了这个坑，首页一直显示「从未心跳」，而文件里明明有值。

        用 self._devices 直接拿原始记录，既拿得到新字段，
        也不用去动 all() 的现有语义（面板别处还在用它）。
        """
        out = []
        with self._lock:
            recs = [dict(r) for r in self._devices.values()]
        for rec in recs:
            item = dict(rec)
            item["display"] = rec.get("remark") or rec.get("label") or rec.get("key", "")
            # 【v67】「v66」这样的标签：面板上直接显示，不用去猜 versionCode 的偏移
            item["version_label"] = version_label(
                rec.get("app_version") or "", rec.get("version_code") or 0
            )
            item["status"] = self.status_of(rec)
            out.append(item)
        # 把离线的排后面（在线的先看）
        order = {"ok": 0, "warn": 1, "unknown": 2, "offline": 3}
        out.sort(key=lambda x: (order.get(x["status"]["level"], 9), x.get("label") or ""))
        return out

    def name_for(self, device_value: str) -> str:
        """给一条消息取设备显示名。"""
        key = (device_value or "").strip()
        rec = self._devices.get(key)
        if rec:
            return rec.get("remark") or rec["label"]
        return device_value or "未登记"
