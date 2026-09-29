"""FastAPI 应用：手机上报入口 + 控制面板。

同一个 app 实例会被两个 uvicorn 监听器共用（见 run.py）：
  * ingest 监听 127.0.0.1:8701  —— 只给 nginx 反代用，公网直接访问不到
  * panel  监听 config.yaml 里的 server.panel_host:panel_port
            通常绑的是 Tailscale IP —— 只有你自己的 tailnet 能打开
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .config import load_config
from .pipeline import Pipeline
from .pairing import Pairing
from .models import Incoming
from .channels import dispatch as dispatch_channels
from .verify import check_timestamp, verify_sign, verify_pair_sign

log = logging.getLogger("smsf-hub")

VALID_KINDS = {"sent", "sms", "call", "notify", "location"}


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
    pairing = Pairing(cfg, str(cfg.path))

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
    app.state.pairing = pairing

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

    # ---------------- 配对：换服务器后自动重配 secret ----------------

    def _client_ip(request: Request) -> str:
        fwd = request.headers.get("X-Forwarded-For", "")
        real = request.headers.get("X-Real-IP", "") or (fwd.split(",")[0].strip() if fwd else "")
        return real or (request.client.host if request.client else "")

    async def _notify_paired(entry: dict) -> None:
        """配对成功通知。走已启用的渠道；一个渠道都没配就只留日志。"""
        if not pipeline.channels:
            log.warning("配对成功，但当前没有任何启用的推送渠道，仅在面板显示")
            return
        notice = Incoming(
            type="notify",
            app="配对",
            title="配对成功",
            content=("【配对成功】%s 于 %s 从 %s 完成了配对。\n"
                     "配对闸门已自动关闭。如果不是你本人操作，请立刻在面板上检查。"
                     % (entry.get("device"), entry.get("at"), entry.get("ip"))),
            device="服务端",
        )
        try:
            await dispatch_channels(pipeline.channels, [notice], "")
        except Exception as exc:
            log.warning("发送配对通知失败: %s", exc)

    @app.post("/smsf/pair")
    async def pair(request: Request):
        """手机凭配对钥匙换回当前 secret。

        三层防护（缺一不可）：
          1. 闸门默认关闭 —— 没在面板上开过，这里直接拒；
          2. 限速 —— 防止被反复试探；
          3. 签名含时间戳 + 设备名 —— 防重放。
        """
        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="请求体不是合法 JSON")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="请求体必须是 JSON 对象")

        ip = _client_ip(request)
        device = str(payload.get("device") or "")
        ts = payload.get("ts") or ""
        sign = payload.get("sign") or ""

        # 1) 闸门
        allowed, why = pairing.allow()
        if not allowed:
            log.warning("配对请求被拒（%s），来自 %s", why, ip)
            raise HTTPException(status_code=403, detail=why)

        # 2) 时间戳
        ok_ts, ts_msg = check_timestamp(ts, int(cfg.get("security.timestamp_tolerance_seconds", 300)))
        if not ok_ts:
            log.warning("配对请求时间戳无效（%s），来自 %s", ts_msg, ip)
            raise HTTPException(status_code=401, detail=ts_msg)

        # 3) 签名
        if not verify_pair_sign(pairing.pair_key, ts, device, sign):
            log.warning("配对签名校验失败，来自 %s（设备 %s）", ip, device or "未知")
            raise HTTPException(status_code=401, detail="配对签名校验失败")

        # 4) 通过：发回 secret，关闸，留痕，通知
        secret = str(cfg.get("security.secret", ""))
        if not secret:
            raise HTTPException(status_code=500, detail="服务器未配置 secret")
        entry = pairing.log_success(device, ip)
        pairing.close("配对成功")
        await _notify_paired(entry)
        log.info("已向设备 %s 下发 secret，配对闸门关闭", device or "未知")
        return JSONResponse({"ok": True, "secret": secret, "paired_at": entry["at"]})

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
    app.include_router(build_panel_router(cfg, pipeline, pairing))

    return app
