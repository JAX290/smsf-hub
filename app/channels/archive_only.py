"""仅归档 —— 不推送，只留档。"""
from __future__ import annotations

from typing import Sequence

from ..models import Incoming
from .base import Channel


class ArchiveOnly(Channel):
    name = "archive_only"
    display = "仅归档（不推送）"

    async def send(self, items: Sequence[Incoming], device: str = "") -> tuple[bool, str]:
        return True, f"仅归档 {len(items)} 条"
