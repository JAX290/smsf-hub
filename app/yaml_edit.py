"""保留注释的 YAML 值改写。

为什么不直接用 PyYAML dump：那会把 config.yaml 里的中文注释全部抹掉，
而用户恰恰靠那些注释理解每个参数的含义。

做法：按缩进定位到目标键所在行，只替换那一行的「值」部分，
其余内容（注释、空行、顺序）一字不动。
"""
from __future__ import annotations

import re
from pathlib import Path

_SCALAR = re.compile(r"^(\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:\s*)(.*?)(\s*(?:#.*)?)$")


def _fmt(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return '""'
    s = str(value)
    if s == "":
        return '""'
    if re.fullmatch(r"[A-Za-z0-9_./:+-]+", s):
        return s
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _find_parent(lines: list, path: list) -> tuple:
    """找到目标键所在行号与其缩进。返回 (行号, 缩进) 或 (None, None)。"""
    if not path:
        return None, None
    target = path[-1]
    parents = path[:-1]
    # 记录每个缩进层级上最近出现的键
    stack: list = []
    for idx, line in enumerate(lines):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _SCALAR.match(line)
        if not m:
            continue
        indent = len(m.group(1))
        key = m.group(2)
        while stack and stack[-1][1] >= indent:
            stack.pop()
        cur_path = [k for k, _ in stack] + [key]
        if cur_path == path:
            return idx, indent
        # 只有当前缀匹配时才把这个键压栈（说明它下面还有子级）
        if cur_path == parents + [key] or (parents and cur_path[: len(parents)] == parents and len(cur_path) <= len(parents) + 1):
            stack.append((key, indent))
    return None, None


def update_value(text: str, dotted: str, value) -> tuple:
    """把 text 里 dotted 路径对应的值改成 value。返回 (新文本, 是否改动)。"""
    path = dotted.split(".")
    lines = text.split("\n")
    idx, indent = _find_parent(lines, path)
    if idx is None:
        return text, False
    m = _SCALAR.match(lines[idx])
    if not m:
        return text, False
    comment = m.group(5)
    new_line = m.group(1) + m.group(2) + m.group(3) + _fmt(value) + comment
    if new_line == lines[idx]:
        return text, False
    lines[idx] = new_line
    return "\n".join(lines), True


def update_many(path: str | Path, changes: dict) -> list:
    """批量更新配置文件。返回成功改动的键列表。"""
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    done = []
    for dotted, value in changes.items():
        text, changed = update_value(text, dotted, value)
        if changed:
            done.append(dotted)
    if done:
        p.write_text(text, encoding="utf-8")
    return done
