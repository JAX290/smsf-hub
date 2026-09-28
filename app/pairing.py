"""配对：换服务器后自动重新绑定 secret。

设计要点（为什么这么做，见 config.example.yaml 里 security.pair_key 的注释）：

  * 闸门【默认关闭】。配对接口本身是公开可达的（手机要走公网），
    所以判断依据不是「谁在问」，而是「闸门有没有开」。
    平时关着 —— 就算 pair_key 从 APK 里被逆出来也用不上。

  * 开闸有两种模式：
      minutes     —— 限时（如 30 分钟），到点自动关
      until_paired —— 一直开，直到配对成功那一刻自动关

  * 配对成功立即自动关闸 + 记一条日志（谁、何时、从哪来）。
    这样「曾经被配对过」这件事永远有迹可循。

状态文件很小，直接读写 JSON，和 APK 下载闸门（apk_gate.json）保持同一套路。
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

log = logging.getLogger("smsf-hub.pairing")

# 合法状态。注意：state() 里必须对每一个值都有显式分支，
# 不能依赖「掉到最后兜底」——那正是之前那个漏洞的来源。
MODES = ("off", "minutes", "until_paired")


class Pairing:
    """配对闸门 + 记录。"""

    def __init__(self, cfg, config_path: str):
        self.cfg = cfg
        self.config_path = config_path

        def _resolve(key: str, default: str) -> Path:
            p = Path(str(cfg.get(key, default)))
            return p if p.is_absolute() else Path(config_path).parent / p

        self.gate_file = _resolve("security.pair_gate_file", "./app/data/pair_gate.json")
        self.log_file = _resolve("security.pair_log_file", "./app/data/pair_log.jsonl")

        # 限速用的内存计数：{分钟戳: 次数}
        self._hits: dict[int, int] = {}

    # ---------------- 配置 ----------------

    @property
    def pair_key(self) -> str:
        return str(self.cfg.get("security.pair_key", "") or "")

    @property
    def rate_limit(self) -> int:
        try:
            return max(1, int(self.cfg.get("security.pair_rate_limit_per_minute", 6)))
        except Exception:
            return 6

    @property
    def configured(self) -> bool:
        """配对钥匙有没有配上。没配就整个功能不可用。"""
        return len(self.pair_key) >= 16

    # ---------------- 闸门状态 ----------------

    def _read_gate(self) -> dict:
        try:
            return json.loads(self.gate_file.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}

    def _write_gate(self, data: dict) -> None:
        try:
            self.gate_file.parent.mkdir(parents=True, exist_ok=True)
            self.gate_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            log.warning("写配对闸门状态失败: %s", exc)

    def state(self) -> dict:
        """当前状态。已到期的会顺手关掉并落盘（常闭优先）。"""
        if not self.configured:
            return {
                "on": False, "mode": "off", "configured": False,
                "text": "未配置配对钥匙", "detail": "config.yaml 里 security.pair_key 为空，配对功能不可用",
            }

        st = self._read_gate()
        mode = str(st.get("mode") or "off")

        if mode not in MODES:
            # 文件缺失/损坏一律按关闭处理 —— 绝不能因为读不到就放行
            self._write_gate({"mode": "off"})
            return {"on": False, "mode": "off", "configured": True,
                    "text": "已关闭", "detail": "配对闸门关闭中，手机无法自动重配"}

        # 显式处理「关闭」—— 绝不能省。
        # 之前漏掉这一支时，mode="off" 会一路掉到最后 until_paired 的兜底返回，
        # 结果闸门关着也放行（已由测试抓出）。
        if mode == "off":
            return {"on": False, "mode": "off", "configured": True,
                    "text": "已关闭", "detail": "配对闸门关闭中，手机无法自动重配"}

        if mode == "minutes":
            left = float(st.get("expires_at") or 0) - time.time()
            if left <= 0:
                self._write_gate({"mode": "off"})
                log.info("配对限时窗口已到期，自动关闭")
                return {"on": False, "mode": "off", "configured": True,
                        "text": "已关闭", "detail": "上次的限时窗口已到期，已自动关闭"}
            return {"on": True, "mode": "minutes", "configured": True, "left_seconds": int(left),
                    "text": "已开启（限时）",
                    "detail": "还剩 %d 分 %d 秒，到点自动关闭" % (int(left) // 60, int(left) % 60)}

        # until_paired
        return {"on": True, "mode": "until_paired", "configured": True,
                "text": "已开启（直到配对成功）",
                "detail": "手机配对成功后会立即自动关闭"}

    def open(self, mode: str, minutes: int = 30) -> dict:
        """开闸。mode: minutes / until_paired。"""
        if mode == "until_paired":
            self._write_gate({"mode": "until_paired", "opened_at": time.time()})
            log.info("配对闸门已开启（直到配对成功）")
        else:
            minutes = max(1, min(1440, int(minutes)))
            self._write_gate({"mode": "minutes", "opened_at": time.time(),
                              "expires_at": time.time() + minutes * 60})
            log.info("配对闸门已开启（%d 分钟）", minutes)
        return self.state()

    def close(self, reason: str = "手动关闭") -> dict:
        self._write_gate({"mode": "off"})
        log.info("配对闸门已关闭：%s", reason)
        return self.state()

    # ---------------- 放行判断 ----------------

    def allow(self) -> tuple[bool, str]:
        """现在允不允许配对。返回 (是否放行, 说明)。"""
        if not self.configured:
            return False, "服务器未配置配对钥匙"
        st = self.state()
        if not st.get("on"):
            return False, "配对未开启"

        # 限速：按分钟计数
        now_min = int(time.time() // 60)
        # 清掉旧分钟
        for k in [k for k in self._hits if k < now_min - 1]:
            self._hits.pop(k, None)
        used = self._hits.get(now_min, 0)
        if used >= self.rate_limit:
            return False, "请求过于频繁，请稍后再试"
        self._hits[now_min] = used + 1
        return True, "ok"

    # ---------------- 配对成功 ----------------

    def log_success(self, device: str, ip: str, note: str = "") -> dict:
        entry = {
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "device": device or "未知设备",
            "ip": ip or "未知",
            "note": note,
        }
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            with self.log_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            log.warning("写配对日志失败: %s", exc)
        log.warning("【配对成功】设备=%s 来自=%s", entry["device"], entry["ip"])
        return entry

    def recent_logs(self, limit: int = 10) -> list[dict]:
        try:
            lines = self.log_file.read_text(encoding="utf-8").strip().splitlines()
        except Exception:
            return []
        out = []
        for line in reversed(lines[-limit:]):
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out

    def last_success(self) -> dict | None:
        logs = self.recent_logs(1)
        return logs[0] if logs else None
