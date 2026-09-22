"""控制面板：全部用中文，所有可调参数都能在界面上改。"""
from __future__ import annotations

import io
import hmac
import json
import hashlib
import logging
import secrets
import time
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from .channels import CHANNEL_CLASSES, CHANNEL_NAMES
from .settings_schema import CHANNEL_EDITABLE, GROUP_LABELS, SCHEMA
from .verify import compute_sign
from .yaml_edit import update_many

log = logging.getLogger("smsf-hub.panel")

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

COOKIE_NAME = "smsf_session"
SESSION_TTL = 12 * 3600


def _token(password: str) -> str:
    return hmac.new(password.encode("utf-8"), b"smsf-hub-panel", hashlib.sha256).hexdigest()


def _is_authed(request: Request, password: str) -> bool:
    cookie = request.cookies.get(COOKIE_NAME, "")
    if not cookie or not password:
        return False
    try:
        raw, ts = cookie.split(".", 1)
        if time.time() - int(ts) > SESSION_TTL:
            return False
    except Exception:
        return False
    return hmac.compare_digest(raw, _token(password + ts))


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0
    return f"{n:.1f} GB"


def build_panel_router(cfg, pipeline) -> APIRouter:
    router = APIRouter()
    config_path = str(cfg.path)

    def auth_on() -> bool:
        """面板是否要求口令。默认关闭——面板只绑 Tailscale IP，由 Tailscale 做访问控制。"""
        return bool(cfg.get("panel.auth_enabled", False))

    def password() -> str:
        return str(cfg.get("panel.password", "") or "")

    def guard(request: Request):
        if not auth_on():
            return
        if not password():
            raise HTTPException(status_code=503, detail="已开启面板口令但未设置 panel.password，请在 config.yaml 里填写后重启服务")
        if not _is_authed(request, password()):
            raise HTTPException(status_code=401, detail="未登录")

    def ctx(request: Request, **kw):
        base = {
            "request": request,
            "title": cfg.get("panel.title", "短信转发中枢"),
            "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "active": kw.pop("active", ""),
            "overview": pipeline.overview(),
            "archive_stat": pipeline.archive.stats(),
        }
        base.update(kw)
        return base

    # ---------------- 登录 ----------------

    @router.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return RedirectResponse("/panel/")

    @router.get("/panel/", response_class=HTMLResponse)
    async def home(request: Request):
        if not auth_on():
            return templates.TemplateResponse("overview.html", ctx(request, active="overview"))
        if not password():
            return templates.TemplateResponse("login.html", ctx(request, need_setup=True))
        if not _is_authed(request, password()):
            return templates.TemplateResponse("login.html", ctx(request, need_setup=False))
        return templates.TemplateResponse("overview.html", ctx(request, active="overview"))

    @router.post("/panel/login")
    async def login(request: Request, pwd: str = Form("")):
        if not hmac.compare_digest(pwd, password()):
            return templates.TemplateResponse("login.html", ctx(request, need_setup=False, error="口令不正确"))
        ts = str(int(time.time()))
        resp = RedirectResponse("/panel/", status_code=303)
        resp.set_cookie(COOKIE_NAME, _token(password() + ts) + "." + ts, httponly=True, max_age=SESSION_TTL)
        return resp

    @router.get("/panel/logout")
    async def logout():
        resp = RedirectResponse("/panel/", status_code=303)
        resp.delete_cookie(COOKIE_NAME)
        return resp

    # ---------------- 总览 ----------------

    @router.get("/panel/overview", response_class=HTMLResponse)
    async def overview(request: Request):
        guard(request)
        return templates.TemplateResponse("overview.html", ctx(request, active="overview"))

    # ---------------- 消息流 ----------------

    @router.get("/panel/messages", response_class=HTMLResponse)
    async def messages(request: Request, q: str = Query(""), page: int = Query(1, ge=1)):
        guard(request)
        rows = list(pipeline.recent)
        if q:
            ql = q.lower()
            rows = [r for r in rows if ql in (r["content"] or "").lower()
                    or ql in (r["sender"] or "").lower() or ql in (r["app"] or "").lower()]
        size = int(cfg.get("panel.page_size", 50) or 50)
        total = len(rows)
        pages = max(1, (total + size - 1) // size)
        page = min(page, pages)
        page_rows = rows[(page - 1) * size: page * size]
        return templates.TemplateResponse("messages.html", ctx(
            request, active="messages", rows=page_rows, q=q, page=page, pages=pages, total=total))

    # ---------------- 手机管理 ----------------

    @router.get("/panel/devices", response_class=HTMLResponse)
    async def devices_page(request: Request):
        guard(request)
        rows = pipeline.devices.all()
        online5 = pipeline.devices.online_count(300)
        return templates.TemplateResponse("devices.html", ctx(
            request, active="devices", rows=rows, total=len(rows), online=online5))

    @router.post("/panel/devices/rename")
    async def devices_rename(request: Request, key: str = Form(""), remark: str = Form("")):
        guard(request)
        ok = pipeline.devices.rename(key, remark.strip())
        return templates.TemplateResponse("saved.html", ctx(
            request, active="devices", changed=[key] if ok else [],
            note=("备注名已保存为「%s」" % remark) if ok else "没找到这台手机"))

    @router.post("/panel/devices/remove")
    async def devices_remove(request: Request, key: str = Form("")):
        guard(request)
        ok = pipeline.devices.remove(key)
        return templates.TemplateResponse("saved.html", ctx(
            request, active="devices", changed=[],
            note="已删除该手机记录（下次它上报会重新登记为新的一台）" if ok else "没找到这台手机"))

    # ---------------- 归档 ----------------

    @router.get("/panel/archive", response_class=HTMLResponse)
    async def archive_page(request: Request):
        guard(request)
        groups = pipeline.archive.list_groups()
        for g in groups:
            g["human"] = _human(g["bytes"])
        return templates.TemplateResponse("archive.html", ctx(request, active="archive", groups=groups))

    def _zip_bytes(targets) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in targets:
                try:
                    zf.write(p, arcname=str(p.relative_to(pipeline.archive.root)))
                except OSError:
                    continue
        return buf.getvalue()

    @router.get("/panel/archive/download-all")
    async def download_all(request: Request):
        guard(request)
        files = sorted(pipeline.archive.root.rglob("*.md"))
        if not files:
            raise HTTPException(status_code=404, detail="归档为空")
        data = _zip_bytes(files)
        name = f"smsf-archive-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip"
        return StreamingResponse(io.BytesIO(data), media_type="application/zip",
                                 headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @router.get("/panel/archive/download")
    async def download_one(request: Request, type: str = Query(""), subject: str = Query("")):
        guard(request)
        sub = pipeline.archive.root / type / subject
        if not sub.exists() or pipeline.archive.root not in sub.resolve().parents:
            raise HTTPException(status_code=404, detail="找不到该分组")
        files = sorted(sub.glob("*.md"))
        if not files:
            raise HTTPException(status_code=404, detail="该分组没有文件")
        data = _zip_bytes(files)
        name = f"{type}-{subject}-{datetime.now().strftime('%Y%m%d')}.zip"
        return StreamingResponse(io.BytesIO(data), media_type="application/zip",
                                 headers={"Content-Disposition": f'attachment; filename="{name}"'})

    # ---------------- 参数设置（表单） ----------------

    def _render_form(values: dict, schema: list, action: str, heading: str, request: Request, active: str):
        groups = {}
        for item in schema:
            groups.setdefault(item.get("group", "其它"), []).append(item)
        return templates.TemplateResponse("settings.html", ctx(
            request, active=active, schema=schema, groups=groups,
            group_labels=GROUP_LABELS, values=values, action=action, heading=heading))

    @router.get("/panel/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        guard(request)
        values = {}
        for item in SCHEMA:
            values[item["path"]] = cfg.get(item["path"])
        return _render_form(values, SCHEMA, "/panel/settings", "参数设置", request, "settings")

    @router.post("/panel/settings")
    async def settings_save(request: Request):
        guard(request)
        form = await request.form()
        changes = {}
        for item in SCHEMA:
            if item["path"] not in form:
                continue
            raw = form[item["path"]]
            t = item["type"]
            if t == "bool":
                changes[item["path"]] = str(raw).lower() in ("on", "true", "1", "yes")
            elif t == "int":
                try:
                    changes[item["path"]] = int(float(str(raw)))
                except ValueError:
                    continue
            elif t == "float":
                try:
                    changes[item["path"]] = float(str(raw))
                except ValueError:
                    continue
            else:
                changes[item["path"]] = str(raw)
        done = update_many(config_path, changes)
        log.info("面板修改了参数: %s", ", ".join(done) or "(无变化)")
        return templates.TemplateResponse("saved.html", ctx(
            request, active="settings", changed=done,
            note="部分参数（如合并窗口）需要重启服务才生效：sudo systemctl restart smsf-hub"))

    # ---------------- 渠道 ----------------

    @router.get("/panel/channels", response_class=HTMLResponse)
    async def channels_page(request: Request):
        guard(request)
        blocks = []
        for cls in CHANNEL_CLASSES:
            schema = CHANNEL_EDITABLE.get(cls.name)
            if not schema:
                continue
            vals = {item["path"]: cfg.get(item["path"]) for item in schema}
            inst = next((c for c in pipeline.channels if c.name == cls.name), None)
            # 注意：键名不能叫 values —— Jinja2 里 b.values 会解析成字典的 .values() 方法
            blocks.append({"name": cls.name, "display": cls.display, "schema": schema, "vals": vals,
                           "enabled": bool(inst)})
        return templates.TemplateResponse("channels.html", ctx(
            request, active="channels", blocks=blocks, editable=CHANNEL_EDITABLE))

    @router.post("/panel/channels/{name}")
    async def channel_save(name: str, request: Request):
        guard(request)
        if name not in CHANNEL_EDITABLE:
            raise HTTPException(status_code=404, detail="未知渠道")
        form = await request.form()
        changes = {}
        for item in CHANNEL_EDITABLE[name]:
            if item["path"] not in form:
                continue
            raw = form[item["path"]]
            t = item["type"]
            if t == "bool":
                changes[item["path"]] = str(raw).lower() in ("on", "true", "1", "yes")
            elif t == "int":
                try:
                    changes[item["path"]] = int(float(str(raw)))
                except ValueError:
                    continue
            else:
                changes[item["path"]] = str(raw)
        done = update_many(config_path, changes)
        log.info("面板修改了渠道 %s: %s", name, ", ".join(done) or "(无变化)")
        return templates.TemplateResponse("saved.html", ctx(
            request, active="channels", changed=done,
            note="渠道开关需要重启服务才生效：sudo systemctl restart smsf-hub"))

    # ---------------- 修改面板口令 ----------------

    @router.post("/panel/password", response_class=HTMLResponse)
    async def change_password(request: Request, old_pwd: str = Form(""),
                              new_pwd: str = Form(""), new_pwd2: str = Form("")):
        guard(request)
        if not hmac.compare_digest(old_pwd, password()):
            return templates.TemplateResponse("saved.html", ctx(
                request, active="settings", changed=[], note="原口令不正确，未做修改"))
        if len(new_pwd) < 6:
            return templates.TemplateResponse("saved.html", ctx(
                request, active="settings", changed=[], note="新口令太短，至少 6 位"))
        if new_pwd != new_pwd2:
            return templates.TemplateResponse("saved.html", ctx(
                request, active="settings", changed=[], note="两次输入的新口令不一致"))
        done = update_many(config_path, {"panel.password": new_pwd})
        log.info("面板口令已修改")
        resp = templates.TemplateResponse("saved.html", ctx(
            request, active="settings", changed=done,
            note="口令已修改，请用新口令重新登录。"))
        resp.delete_cookie(COOKIE_NAME)
        return resp

    # ---------------- 自测 ----------------

    @router.post("/panel/test/{name}")
    async def channel_test(name: str, request: Request):
        guard(request)
        inst = next((c for c in pipeline.channels if c.name == name), None)
        if inst is None:
            return templates.TemplateResponse("saved.html", ctx(
                request, active="channels", changed=[],
                note=f"渠道 {name} 当前未启用（配置里 enable 是 false，或改完还没重启）"))
        from .models import Incoming
        sample = Incoming(type="sms", sender="10086", content="这是一条来自 SmsForwarder Hub 的测试消息。",
                          device=cfg.get("channels._device_placeholder", "") or "测试", ts=int(time.time() * 1000))
        ok, info = await inst.send([sample], sample.device)
        return templates.TemplateResponse("saved.html", ctx(
            request, active="channels", changed=[],
            note=("测试成功：" if ok else "测试失败：") + str(info)))

    # ---------------- 签名自测（给手机端配置用） ----------------

    @router.get("/panel/selftest", response_class=HTMLResponse)
    async def selftest(request: Request, ts: str = Query("")):
        guard(request)
        secret = str(cfg.get("security.secret", ""))
        timestamp = ts or str(int(time.time() * 1000))
        sign = compute_sign(secret, timestamp) if secret else ""
        import urllib.parse
        body = {
            "device": "自测设备",
            "from": "10086",
            "content": "面板自测消息",
            "ts": timestamp,
            "sign": urllib.parse.quote(sign, safe=""),
        }
        base = cfg.get("server.phone_base_url", "https://notic.mulinsen.win/smsf/hook")
        urls = {
            "短信": base + "/sms",
            "来电": base + "/call",
            "APP通知": base + "/notify",
        }
        body_template = (
            '{\n'
            '  "device": "[device_mark]",\n'
            '  "from": "[from]",\n'
            '  "content": "[content]",\n'
            '  "app": "",\n'
            '  "sim": "[title]",\n'
            '  "app_version": "[app_version]",\n'
            '  "receive_time": "[receive_time:yyyy-MM-dd HH:mm:ss]",\n'
            '  "ts": "[timestamp]",\n'
            '  "sign": "[sign]"\n'
            '}'
        )
        curl = ("curl -X POST '%s' -H 'Content-Type: application/json' -d '%s'"
                % (urls["短信"], json.dumps(body, ensure_ascii=False).replace("'", '"')))
        return templates.TemplateResponse("selftest.html", ctx(
            request, active="selftest", timestamp=timestamp, sign=sign, curl=curl, body=body,
            secret=secret, urls=urls, body_template=body_template, base=base))

    return router
