#!/usr/bin/env python3
"""启动入口：一个进程同时监听两个地址。

  * 上报入口  —— 绑定 127.0.0.1，只给 nginx 反代用
  * 控制面板  —— 绑定 Tailscale IP，只有你的 tailnet 能开

两个监听器共用同一个 FastAPI 实例，所以状态（统计、缓冲、去重表）是同一份。
"""
from __future__ import annotations

import asyncio
import logging
import sys

import uvicorn

from app.main import create_app

log = logging.getLogger("smsf-hub.run")


async def serve() -> None:
    app = create_app()
    cfg = app.state.cfg

    ingest_cfg = uvicorn.Config(
        app,
        host=str(cfg.get("server.listen_host", "127.0.0.1")),
        port=int(cfg.get("server.listen_port", 8701)),
        log_level=str(cfg.get("log.level", "INFO")).lower(),
        access_log=True,
        server_header=False,
    )
    panel_cfg = uvicorn.Config(
        app,
        host=str(cfg.get("server.panel_host", "127.0.0.1")),
        port=int(cfg.get("server.panel_port", 8702)),
        log_level=str(cfg.get("log.level", "INFO")).lower(),
        access_log=True,
        server_header=False,
    )

    servers = [uvicorn.Server(ingest_cfg), uvicorn.Server(panel_cfg)]
    try:
        await asyncio.gather(*(s.serve() for s in servers))
    except asyncio.CancelledError:
        pass


def main() -> int:
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
