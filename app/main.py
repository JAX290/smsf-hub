"""FastAPI 应用：手机上报入口 + 控制面板。

同一个 app 实例会被两个 uvicorn 监听器共用（见 run.py）：
  * ingest 监听 127.0.0.1:8701  —— 只给 nginx 反代用，公网直接访问不到
  * panel  监听 100.118.119.84:8702 —— 只有 Tailscale 网络内能开
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .config import load_config
from .pipeline import Pipeline
from .verify import check_timestamp, verify_sign

log = logging.getLogger("smsf-hub")

VALID_KINDS = {"sms", "call", "notify"}


def setup_logging(cfg) -> None:
    import logging.handlers
    from pathlib import Path

    level = getattr(logging, str(cfg.get("log.level", "INFO")).upper(), logging.INFO)
    logfile = Path(str(cfg.get("log.file", "./data/logs/hub.log")))
    logfile.parent.mkdir(parents=True, exist_ok=True)

    handler = logging.handlers.RotatingFileHandler(
        logfile,
        maxBytes=int(cfg.get("log.max_mb", 20)) * 1024 * 1024,
        backupCount=int(cfg.get("log.backup_count", 5)),
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s"))
    console = logging.StreamHandler()
    console.setFormatter(handler.formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.addHandler(console)
    root.setLevel(level)


def create_app(config_path: str | None = None) -> FastAPI:
    cfg = load_config(config_path)
    setup_logging(cfg)
    pipeline = Pipeline(cfg)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        log.info("SmsForwarder Hub 启动")
        log.info("  上报入口: %s:%s%s/hook", cfg.get("server.listen_host"), cfg.get("server.listen_port"), cfg.get("server.url_prefix", ""))
        log.info("  控制面板: http://%s:%s", cfg.get("server.panel_host"), cfg.get("server.panel_port"))
        log.info("  已启用渠道: %s", ", ".join(c.display for c in pipeline.channels) or "(无)")
        log.info("  归档根目录: %s", pipeline.archive.root)
        yield
        log.info("正在刷出合并缓冲…")
        await pipeline.shutdown()
        log.info("SmsForwarder Hub 已停止")

    app = FastAPI(title="SmsForwarder Hub", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.cfg = cfg
    app.state.pipeline = pipeline

    @app.middleware("http")
    async def _panel_no_cache(request: Request, call_next):
        """面板页面禁用浏览器缓存。

        改完设置刷新就能看到最新状态，不会因为缓存看到旧页面。
        """
        resp = await call_next(request)
        if request.url.path.startswith("/panel"):
            resp.headers["Cache-Control"] = "no-store, must-revalidate"
        return resp

    # ---------------- 手机上报 ----------------

    async def _ingest(request: Request, kind: str | None) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="请求体不是合法 JSON")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="请求体必须是 JSON 对象")

        secret = str(cfg.get("security.secret", ""))
        ts = payload.get("ts") or payload.get("timestamp") or ""
        sign = payload.get("sign") or request.headers.get("X-Sign", "")

        if not secret:
            log.error("服务器未配置 security.secret，拒绝所有上报")
            raise HTTPException(status_code=500, detail="服务器未配置 secret")

        ok_ts, ts_msg = check_timestamp(ts, int(cfg.get("security.timestamp_tolerance_seconds", 300)))
        if not ok_ts:
            log.warning("拒绝上报：%s", ts_msg)
            raise HTTPException(status_code=401, detail=ts_msg)

        if not verify_sign(secret, ts, sign):
            log.warning("拒绝上报：签名校验失败 (来自 %s)", request.client.host if request.client else "?")
            raise HTTPException(status_code=401, detail="签名校验失败")

        extra_h = str(cfg.get("security.extra_token_header", "")).strip()
        if extra_h:
            got = request.headers.get(extra_h, "")
            if got != str(cfg.get("security.extra_token_value", "")):
                raise HTTPException(status_code=401, detail="附加令牌校验失败")

        if kind is None:
            kind = str(payload.get("type", "sms")).lower()
        if kind not in VALID_KINDS:
            kind = "sms"
        payload.setdefault("type", kind)

        # 取真实来源 IP（nginx 会设置 X-Real-IP / X-Forwarded-For）
        fwd = request.headers.get("X-Forwarded-For", "")
        real_ip = request.headers.get("X-Real-IP", "") or (fwd.split(",")[0].strip() if fwd else "")
        client_ip = real_ip or (request.client.host if request.client else "")

        result = await pipeline.handle(payload, client_ip)
        return JSONResponse(result)

    @app.post("/smsf/hook")
    async def hook_root(request: Request):
        return await _ingest(request, None)

    @app.post("/smsf/hook/{kind}")
    async def hook_kind(kind: str, request: Request):
        k = kind.lower()
        return await _ingest(request, k if k in VALID_KINDS else None)

    # 方便本地自测（nginx 之外直连时用）
    @app.post("/hook")
    async def hook_short(request: Request):
        return await _ingest(request, None)

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "channels": len(pipeline.channels),
            "received": pipeline.stats["received"],
            "archived": pipeline.stats["archived"],
            "pending_merge": pipeline.merger.pending(),
        }

    # ---------------- 控制面板 ----------------

    from .panel import build_panel_router
    app.include_router(build_panel_router(cfg, pipeline))

    return app
