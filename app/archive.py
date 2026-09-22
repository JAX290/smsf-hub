"""Markdown 归档。

目录结构：  归档根 / 类型 / 主题 / 日期.md
  例：      短信/1069xxxx/2026-09-22.md
            APP通知/微信/2026-09-22.md
            来电/13800138000/2026-09-22.md

单文件超过 archive.file_max_mb 时滚动为  2026-09-22.part2.md
归档总量超过 archive.total_max_mb 时，面板报警并提示下载。
"""
from __future__ import annotations

import re
from pathlib import Path

from .models import Incoming, TYPE_DIR

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
FENCE = "```"


def safe_name(raw: str, fallback: str = "未知") -> str:
    """把主题名清洗成安全的目录/文件名。"""
    s = (raw or "").strip() or fallback
    s = _UNSAFE.sub("_", s).strip(". ")
    if len(s) > 60:
        s = s[:60]
    return s or fallback


class Archive:
    def __init__(self, root: Path, subject_rules: dict, file_max_mb: float,
                 total_max_mb: float, warn_percent: float, content_max_chars: int):
        self.root = Path(root)
        self.subject_rules = subject_rules or {}
        self.file_max_bytes = int(float(file_max_mb) * 1024 * 1024)
        self.total_max_bytes = int(float(total_max_mb) * 1024 * 1024)
        self.warn_percent = float(warn_percent)
        self.content_max_chars = int(content_max_chars or 0)
        self.root.mkdir(parents=True, exist_ok=True)

    def _rule_for(self, msg: Incoming) -> str:
        return self.subject_rules.get(msg.type, "sender")

    def _dir_for(self, msg: Incoming) -> Path:
        type_dir = TYPE_DIR.get(msg.type, msg.type or "其它")
        return self.root / safe_name(type_dir) / safe_name(msg.subject(self._rule_for(msg)))

    def _target_file(self, dirpath: Path, day: str) -> Path:
        """返回应该写入的文件；超过大小上限则用 partN 滚动。"""
        base = dirpath / f"{day}.md"
        if not base.exists() or base.stat().st_size < self.file_max_bytes:
            return base
        n = 2
        while n <= 999:
            cand = dirpath / f"{day}.part{n}.md"
            if not cand.exists() or cand.stat().st_size < self.file_max_bytes:
                return cand
            n += 1
        return dirpath / f"{day}.part999.md"

    def append(self, msg: Incoming) -> Path:
        """把一条消息追加进归档，返回写入的文件路径。"""
        dirpath = self._dir_for(msg)
        dirpath.mkdir(parents=True, exist_ok=True)
        day = msg.when.strftime("%Y-%m-%d")
        target = self._target_file(dirpath, day)

        content = msg.content or ""
        if self.content_max_chars and len(content) > self.content_max_chars:
            content = content[: self.content_max_chars] + f"\n…（内容过长已截断，原长 {len(msg.content)} 字）"

        lines = [f"## {msg.when.strftime('%H:%M:%S')}  {msg.sender or msg.app or '未知'}", ""]
        meta = []
        if msg.device:
            meta.append(f"设备: {msg.device}")
        if msg.sim:
            meta.append(f"SIM: {msg.sim}")
        if msg.app:
            meta.append(f"应用: {msg.app}")
        if msg.app_version:
            meta.append(f"版本: {msg.app_version}")
        if meta:
            lines.append("> " + " ｜ ".join(meta))
            lines.append("")
        lines.append(FENCE + "text")
        lines.append(content.rstrip() or "(空)")
        lines.append(FENCE)
        lines.append("")

        new_file = not target.exists()
        with target.open("a", encoding="utf-8") as f:
            if new_file:
                f.write(f"# {target.stem} —— {msg.subject(self._rule_for(msg))}\n\n")
            f.write("\n".join(lines))
        return target

    def total_bytes(self) -> int:
        total = 0
        for p in self.root.rglob("*.md"):
            try:
                total += p.stat().st_size
            except OSError:
                pass
        return total

    def stats(self) -> dict:
        used = self.total_bytes()
        pct = (used / self.total_max_bytes * 100) if self.total_max_bytes else 0
        level = "red" if pct >= 100 else ("yellow" if pct >= self.warn_percent else "green")
        return {
            "used_bytes": used,
            "used_mb": round(used / 1024 / 1024, 2),
            "limit_mb": round(self.total_max_bytes / 1024 / 1024, 2),
            "percent": round(pct, 1),
            "level": level,
            "need_download": level == "red",
        }

    def list_groups(self) -> list:
        """列出 类型/主题 分组及大小，供面板展示与打包下载。"""
        out = []
        if not self.root.exists():
            return out
        for type_dir in sorted([d for d in self.root.iterdir() if d.is_dir()]):
            for sub in sorted([d for d in type_dir.iterdir() if d.is_dir()]):
                files = sorted(sub.glob("*.md"))
                size = sum(f.stat().st_size for f in files if f.exists())
                out.append({
                    "type": type_dir.name,
                    "subject": sub.name,
                    "files": len(files),
                    "bytes": size,
                    "mb": round(size / 1024 / 1024, 2),
                    "path": str(sub),
                })
        return out
