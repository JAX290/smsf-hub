"""控制面板：全部用中文，所有可调参数都能在界面上改。"""
from __future__ import annotations

import io
import hmac
import json
import hashlib
import logging
import re
import secrets
import time
import zipfile

import yaml
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from .app_names import build_map, display_name
from .channels import CHANNEL_CLASSES, CHANNEL_NAMES
from . import analysis, channel_store
from .analysis import DEFAULT_WATCH_KEYWORDS
from .classify import TIER_CSS, TIER_LABEL, extract as extract_info, rules as priority_rules
from .models import Incoming, TYPE_DIR
from .settings_schema import CHANNEL_EDITABLE, GROUP_LABELS, RULE_FIELDS, SCHEMA
from .pipeline import fix_record
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


# ---------------- 归档全文搜索（"看不到之前的消息"的根治办法） ----------------
# 面板的「消息流」只是一内存窗口（默认 8000 条 / 约 2 天）；
# 更早的历史全在归档 md 里。这里把归档逐文件解析成条目并缓存，
# 支持关键词 / 设备 / 类型 / 日期范围，几万条也是秒级。
_SEARCH_CACHE: dict[str, tuple] = {}
_SEARCH_CACHE_MAX = 4000


def _archive_entries(path: Path) -> list:
    """把一个归档 md 解析成条目列表（带 mtime+size 缓存，文件没变就不重复解析）。"""
    try:
        st = path.stat()
    except OSError:
        return []
    key = str(path)
    hit = _SEARCH_CACHE.get(key)
    if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        return hit[2]

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    out = []
    head = None
    buf: list[str] = []

    def flush():
        if head is None:
            return
        body = "\n".join(buf).strip()
        parts = head.split(None, 1)
        out.append({
            "time": parts[0] if parts else "",
            "who": parts[1].strip() if len(parts) > 1 else "",
            "head": head,
            "body": body,
            "text": (head + "\n" + body).lower(),
        })

    for line in text.splitlines():
        if line.startswith("## "):
            flush()
            head = line[3:].strip()
            buf = []
        elif head is not None:
            buf.append(line)
    flush()

    if len(_SEARCH_CACHE) > _SEARCH_CACHE_MAX:
        _SEARCH_CACHE.clear()
    _SEARCH_CACHE[key] = (st.st_mtime_ns, st.st_size, out)
    return out


def build_panel_router(cfg, pipeline, pairing=None) -> APIRouter:
    router = APIRouter()
    config_path = str(cfg.path)

    def auth_on() -> bool:
        """面板是否要求口令。默认关闭——面板只绑 Tailscale IP，由 Tailscale 做访问控制。"""
        return bool(cfg.get("panel.auth_enabled", False))

    def password() -> str:
        return str(cfg.get("panel.password", "") or "")

    def apk_download_enabled() -> bool:
        """安装包下载总开关。

        刻意直接读配置文件、而不是内存里的 cfg：
        这样面板上改完立刻生效，不需要重启服务。
        """
        try:
            data = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
            return bool((data.get("panel") or {}).get("apk_download_enabled", False))
        except Exception as exc:  # 读不出来按「关闭」处理，安全优先
            log.warning("读取安装包下载开关失败，按关闭处理: %s", exc)
            return False

    # ---- 安装包下载的临时授权（限时 / 限次）----
    # 设计意图：开关保持常闭，需要下载时才临时开一小会儿，到期或用完自动关上。

    gate_file = Path(str(cfg.get("panel.apk_gate_file", "./app/data/apk_gate.json")))
    if not gate_file.is_absolute():
        gate_file = Path(config_path).parent / gate_file

    def _gate_read() -> dict:
        try:
            return json.loads(gate_file.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}

    def _gate_write(data: dict) -> None:
        try:
            gate_file.parent.mkdir(parents=True, exist_ok=True)
            gate_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            log.warning("写入下载授权状态失败: %s", exc)

    def _set_master(on: bool) -> None:
        """顺带改掉设置页那个总开关，保证两处显示始终一致。"""
        update_many(config_path, {"panel.apk_download_enabled": on})

    def gate_state() -> dict:
        """下载授权的实时状态；已到期/已用完的会顺手关掉并落盘。"""
        if not apk_download_enabled():
            return {"on": False, "mode": "off", "text": "已关闭",
                    "detail": "外部访问下载地址一律拒绝"}
        st = _gate_read()
        mode = str(st.get("mode") or "")

        # 状态文件缺失或损坏时按「关闭」处理 —— 常闭优先，绝不能因为文件读不到就放行。
        if mode not in ("minutes", "times", "forever"):
            _set_master(False)
            _gate_write({"mode": "off"})
            log.warning("下载授权状态缺失或未知（mode=%r），已按关闭处理", mode)
            return {"on": False, "mode": "off", "text": "已关闭",
                    "detail": "外部访问下载地址一律拒绝"}

        if mode == "minutes":
            left = float(st.get("expires_at") or 0) - time.time()
            if left <= 0:
                _set_master(False)
                _gate_write({"mode": "off"})
                log.info("安装包下载限时授权已到期，自动关闭")
                return {"on": False, "mode": "off", "text": "已关闭",
                        "detail": "上次的限时授权已到期，已自动关闭"}
            return {"on": True, "mode": "minutes", "left_seconds": int(left),
                    "text": "已开启（限时）",
                    "detail": "还剩 %d 分 %d 秒，到点自动关闭" % (int(left) // 60, int(left) % 60)}

        if mode == "times":
            rem = int(st.get("remaining") or 0)
            if rem <= 0:
                _set_master(False)
                _gate_write({"mode": "off"})
                log.info("安装包下载次数已用完，自动关闭")
                return {"on": False, "mode": "off", "text": "已关闭",
                        "detail": "下载次数已用完，已自动关闭"}
            return {"on": True, "mode": "times", "remaining": rem,
                    "text": "已开启（限次）", "detail": "还可下载 %d 次，用完自动关闭" % rem}

        return {"on": True, "mode": "forever", "text": "已开启（不限）",
                "detail": "一直开启，直到手动关闭"}

    def gate_consume() -> dict:
        """判定一次下载并计数（限次模式下消耗一次）。"""
        st = gate_state()
        if st.get("on") and st.get("mode") == "times":
            data = _gate_read()
            rem = max(0, int(data.get("remaining") or 0) - 1)
            data["remaining"] = rem
            _gate_write(data)
            st["remaining"] = rem
            if rem <= 0:
                _set_master(False)
                log.info("安装包下载次数用尽，已自动关闭")
        return st

    def guard(request: Request):
        if not auth_on():
            return
        if not password():
            raise HTTPException(status_code=503, detail="已开启面板口令但未设置 panel.password，请在 config.yaml 里填写后重启服务")
        if not _is_authed(request, password()):
            raise HTTPException(status_code=401, detail="未登录")

    def _device_status_list() -> list:
        """首页用：每台手机 + 它当前的状态（颜色/文字/权限明细）。

        数据来自手机端每 10 分钟一次的心跳。没装带心跳的版本，或一直没联网，
        就显示成「从未心跳」—— 这是正常的，不是错误。
        """
        try:
            return pipeline.devices.all_with_status()
        except Exception:
            log.exception("读取设备状态失败")
            return []

    def ctx(request: Request, **kw):
        base = {
            "request": request,
            "title": cfg.get("panel.title", "短信转发中枢"),
            "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "active": kw.pop("active", ""),
            "overview": pipeline.overview(),
            "archive_stat": pipeline.archive.stats(),
            "apk_gate": gate_state(),
            "pair_gate": _pair_state(),
            "pair_logs": _pair_logs(),
            "current_secret": _secret_view(bool(kw.pop("reveal", False))),
            "pair_configured": bool(pairing and pairing.configured),
            # 【新增】每台手机的状态（在线/离线、权限齐不齐），首页按手机分列显示
            "device_status": _device_status_list(),
        }
        base.update(kw)
        return base

    # ---------------- 配对（换服务器后自动重配 secret） ----------------

    def _device_label(key: str) -> str:
        """把归档目录里的设备 ID 换成面板上好看的名字。

        目录名用的是稳定的设备 ID（SF-xxxxxxxx），而 devices.json 里记着
        用户给它起的备注（如 nova6）。查不到就原样显示。
        """
        if not key:
            return "(未标注设备)"
        try:
            for rec in (pipeline.devices.all() or []):
                if rec.get("key") == key:
                    return rec.get("remark") or rec.get("label") or key
        except Exception:
            pass
        return key

    def _fallback_gate() -> dict:
        return {"on": False, "mode": "off", "configured": False,
                "text": "不可用", "detail": "配对模块未加载"}

    def _pair_state() -> dict:
        if not pairing:
            return _fallback_gate()
        try:
            return pairing.state()
        except Exception as exc:
            log.warning("读取配对状态失败: %s", exc)
            return _fallback_gate()

    def _pair_logs() -> list:
        if not pairing:
            return []
        try:
            return pairing.recent_logs(5)
        except Exception:
            return []

    def _secret_view(reveal: bool) -> dict:
        """当前手机上报用的 secret。

        默认打码显示；面板上点「显示完整值」才展开（走 ?reveal=1）。
        面板本身只绑 Tailscale，但打码能防投屏/截图时被顺手看到。
        """
        try:
            data = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
            val = str((data.get("security") or {}).get("secret") or "")
        except Exception:
            val = ""
        if not val:
            return {"has": False, "masked": "", "full": "", "len": 0}
        masked = f"{val[:6]}…{val[-4:]}" if len(val) > 12 else "•" * len(val)
        return {"has": True, "masked": masked, "full": val if reveal else "",
                "len": len(val), "revealed": reveal}

    # ---------------- 下载闸门（供 nginx auth_request 调用） ----------------

    @router.get("/gate/apk")
    async def gate_apk():
        """安装包下载闸门。

        nginx 在每个下载地址上用 auth_request 内部调用这里：
          HTTP 200 -> 放行下载
          HTTP 403 -> 拒绝

        刻意直接读配置文件、而不是内存里的 cfg：
        这样面板上改完开关立刻生效，不需要重启服务。
        """
        st = gate_consume()
        if not st.get("on"):
            raise HTTPException(status_code=403, detail="安装包下载未开启")
        return JSONResponse({"ok": True, "mode": st.get("mode"), "remaining": st.get("remaining")})

    @router.post("/panel/apk-grant")
    async def apk_grant(request: Request, mode: str = Form(""), amount: str = Form("")):
        """首页临时授权：开 X 分钟 / 允许 X 次 / 一直开启。"""
        guard(request)
        if mode == "minutes":
            try:
                n = max(1, min(1440, int(float(amount or 10))))
            except (ValueError, TypeError):
                n = 10
            _gate_write({"mode": "minutes", "expires_at": time.time() + n * 60,
                         "granted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
            _set_master(True)
            log.info("安装包下载授权：%d 分钟", n)
        elif mode == "times":
            try:
                n = max(1, min(999, int(float(amount or 3))))
            except (ValueError, TypeError):
                n = 3
            _gate_write({"mode": "times", "remaining": n,
                         "granted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
            _set_master(True)
            log.info("安装包下载授权：%d 次", n)
        else:
            _gate_write({"mode": "forever",
                         "granted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
            _set_master(True)
            log.info("安装包下载授权：一直开启")
        return RedirectResponse("/panel/", status_code=303)

    @router.post("/panel/apk-off")
    async def apk_off(request: Request):
        """立即关闭下载入口。"""
        guard(request)
        _set_master(False)
        _gate_write({"mode": "off"})
        log.info("安装包下载：已手动关闭")
        return RedirectResponse("/panel/", status_code=303)

    @router.post("/panel/pair-open")
    async def pair_open(request: Request, mode: str = Form(""), amount: str = Form("")):
        """开启配对闸门。

        三种模式：
          minutes         限时（默认 30 分钟）
          until_paired    一直开到手机取回 secret
          until_connected 一直开到手机真的上报成功（推荐，用户要求的行为）
        """
        guard(request)
        if not pairing or not pairing.configured:
            # 只要 config.yaml 里填了上报域名，就能从域名派生钥匙，
            # 所以正常部署下不该走到这里。
            log.warning("尝试开启配对，但配对功能不可用（缺 pair_key 且无法从域名派生）")
            return RedirectResponse("/panel/?pair_err=nokey", status_code=303)
        if mode in ("until_paired", "until_connected"):
            pairing.open(mode)
        else:
            try:
                n = max(1, min(1440, int(float(amount or 30))))
            except (ValueError, TypeError):
                n = 30
            pairing.open("minutes", n)
        return RedirectResponse("/panel/", status_code=303)

    @router.post("/panel/pair-off")
    async def pair_off(request: Request):
        """立即关闭配对闸门。"""
        guard(request)
        if pairing:
            pairing.close("手动关闭")
        return RedirectResponse("/panel/", status_code=303)

    # ---------------- 登录 ----------------

    @router.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return RedirectResponse("/panel/")

    @router.get("/panel/", response_class=HTMLResponse)
    async def home(request: Request, reveal: str = Query("")):
        _rv = reveal in ("1", "true", "yes")
        if not auth_on():
            return templates.TemplateResponse("overview.html", ctx(request, active="overview", reveal=_rv))
        if not password():
            return templates.TemplateResponse("login.html", ctx(request, need_setup=True))
        if not _is_authed(request, password()):
            return templates.TemplateResponse("login.html", ctx(request, need_setup=False))
        return templates.TemplateResponse("overview.html", ctx(request, active="overview", reveal=_rv))

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
    async def overview(request: Request, reveal: str = Query("")):
        guard(request)
        # 面板上要显示「去哪下载 APK」，这个地址从配置里取，不写死。
        # phone_base_url 形如 https://你的域名/smsf/hook，这里只要主机名部分。
        _base = (cfg.get("server.phone_base_url") or "").strip()
        dl_host = ""
        if _base:
            _m = re.match(r"^[a-zA-Z]+://([^/]+)", _base)
            dl_host = _m.group(1) if _m else _base
        return templates.TemplateResponse("overview.html", ctx(
            request, active="overview", reveal=reveal in ("1", "true", "yes"), dl_host=dl_host))

    # ---------------- 消息流 ----------------

    # 消息流支持的排序字段（表头点击切换）
    _MSG_SORT_FIELDS = {
        "time": "时间",
        "type": "类型",
        "sender": "发件人",
        "app": "应用",
        "device": "终端",
        "content": "内容",
    }

    @router.get("/panel/messages", response_class=HTMLResponse)
    async def messages(
        request: Request,
        q: str = Query(""),
        page: int = Query(1, ge=1),
        device: str = Query(""),
        mtype: str = Query(""),
        app: str = Query(""),
        sort: str = Query("time"),
        order: str = Query("desc"),
        min_tier: int = Query(3, ge=0, le=4),
    ):
        guard(request)
        base_rows = [fix_record(r) for r in pipeline.recent]

        # ---- 分级过滤（降噪）----
        # 默认只看 T3（重要）及以上：真人消息、验证码、短信、来电。
        # 系统组件自报状态（"正在后台运行"这类）属于 T0/T1，默认折叠，
        # 但只影响显示，磁盘上的原始数据一个字都没动。
        def _tier(r: dict) -> int:
            try:
                return int(r.get("tier", 2))
            except (TypeError, ValueError):
                return 2

        tier_counts = {t: 0 for t in range(5)}
        for r in base_rows:
            t = _tier(r)
            if t in tier_counts:
                tier_counts[t] += 1

        if min_tier > 0:
            base_rows = [r for r in base_rows if _tier(r) >= min_tier]
        hidden_low = sum(v for k, v in tier_counts.items() if k < max(min_tier, 1)) if min_tier > 0 else 0

        app_table = build_map(cfg.get("panel.app_names", {}) or {})

        def _disp(v: str) -> str:
            return display_name(v, app_table)

        def _apply(rows: list, skip: str) -> list:
            """按当前筛选条件过滤；skip 指定跳过哪个维度。

            跳过某个维度，是为了算那个下拉框自己的候选值 ——
            比如算「应用」候选时不能把 app 条件也套上，否则选完就只剩一项了。
            """
            if q and skip != "q":
                ql = q.lower()
                rows = [r for r in rows if ql in (r["content"] or "").lower()
                        or ql in (r["sender"] or "").lower() or ql in (r["app"] or "").lower()]
            if device and skip != "device":
                rows = [r for r in rows if (r.get("device") or "") == device]
            if mtype and skip != "mtype":
                rows = [r for r in rows if (r.get("type") or "") == mtype]
            if app and skip != "app":
                # 同一个应用可能有两种写法：中文名（Soul）和包名（cn.soulapp.android）。
                # 映射表会把包名翻成中文，于是两个 key 共用一个显示名。
                # 这里按「显示名」匹配，保证选一次就能把两种写法都筛出来。
                rows = [r for r in rows if (r.get("app") or "") == app
                        or _disp(r.get("app")) == app]
            return rows

        rows = _apply(base_rows, "")

        # 排序（表头点一下切换升降序）
        if sort not in _MSG_SORT_FIELDS:
            sort = "time"
        if order not in ("asc", "desc"):
            order = "desc"
        sort_key = {
            "time": lambda r: r.get("time") or "",
            "type": lambda r: r.get("type") or "",
            "sender": lambda r: (r.get("sender") or r.get("app") or ""),
            "app": lambda r: r.get("app") or "",
            "device": lambda r: r.get("device") or "",
            "content": lambda r: r.get("content") or "",
        }[sort]
        rows.sort(key=sort_key, reverse=(order == "desc"))

        size = int(cfg.get("panel.page_size", 50) or 50)
        total = len(rows)
        pages = max(1, (total + size - 1) // size)
        page = min(page, pages)
        page_rows = rows[(page - 1) * size: page * size]

        # ---- 下拉候选：跟随其他筛选条件联动 ----
        # 选完手机之后，应用下拉只该列出这台手机实际有的应用；
        # 反之亦然。当前已选中的值即使不在候选里也保留，避免下拉「跳变」。
        app_table = build_map(cfg.get("panel.app_names", {}) or {})

        dev_rows = _apply(base_rows, "device")
        dev_set = {(r.get("device") or "") for r in dev_rows} - {""}
        devices = [d["display"] for d in pipeline.devices.all() if d["display"] in dev_set]
        for d in sorted(dev_set):
            if d not in devices:
                devices.append(d)
        if device and device not in devices:
            devices.insert(0, device)

        _type_rows = _apply(base_rows, "mtype")
        _type_set = {(r.get("type") or "") for r in _type_rows} - {""}
        mtypes = [(k, v) for k, v in
                  (("sms", "短信"), ("call", "来电"), ("notify", "通知"), ("sent", "已发送"), ("location", "定位"))
                  if k in _type_set]
        if mtype and mtype not in [k for k, _ in mtypes]:
            mtypes.insert(0, (mtype, next((v for k, v in
                                          (("sms", "短信"), ("call", "来电"), ("notify", "通知"), ("sent", "已发送"), ("location", "定位"))
                                          if k == mtype), mtype)))

        app_rows = _apply(base_rows, "app")
        app_keys = sorted({(r.get("app") or "") for r in app_rows} - {""})
        # 按显示名合并：同一个应用若既有中文名又有包名，只在下拉里出一项，
        # 但 value 用显示名 —— 筛选时上面那段会把两种写法一起匹配。
        _merged = {}
        for k in app_keys:
            nm = _disp(k)
            if nm not in _merged:
                _merged[nm] = {"key": nm, "name": nm, "variants": [k]}
            else:
                _merged[nm]["variants"].append(k)
        apps = [{"key": v["key"], "name": v["name"], "variants": v["variants"]}
                for v in sorted(_merged.values(), key=lambda x: x["name"])]
        if app and app not in _merged:
            apps.insert(0, {"key": app, "name": app + "（当前筛选下没有）", "variants": []})
        for r in page_rows:
            r["app_display"] = display_name(r.get("app"), app_table)
            t = _tier(r)
            r["tier"] = t
            r["tier_label"] = TIER_LABEL.get(t, "")
            r["tier_css"] = TIER_CSS.get(t, "t2")
            r["tier_reason"] = r.get("tier_reason") or ""
            # 结构化提取：把手机端模板里的冗余行（包名/UID/时间/设备ID）剥掉，
            # 顺手把验证码、金额捞出来，面板上直接显示有用的那部分。
            try:
                r["ex"] = extract_info(Incoming(
                    type=r.get("type", ""), sender=r.get("sender", ""), app=r.get("app", ""),
                    content=r.get("content", ""), device=r.get("device", "")))
            except Exception:
                r["ex"] = {"summary": r.get("content", ""), "code": "", "amounts": [], "links": [], "title": "", "body": ""}

        # 表头排序链接：保留当前筛选条件，点一次切换升降序
        sort_links = {}
        for _k in _MSG_SORT_FIELDS:
            _nxt = "asc" if (sort == _k and order == "desc") else "desc"
            sort_links[_k] = "/panel/messages?" + urlencode(
                {"q": q, "device": device, "mtype": mtype, "app": app,
                 "sort": _k, "order": _nxt})

        return templates.TemplateResponse("messages.html", ctx(
            request, active="messages", rows=page_rows, q=q, page=page, pages=pages,
            total=total, device=device, mtype=mtype, sort=sort, order=order,
            devices=devices, apps=apps, app=app, mtypes=mtypes,
            sort_fields=_MSG_SORT_FIELDS, sort_links=sort_links,
            min_tier=min_tier, tier_counts=tier_counts, hidden_low=hidden_low,
            tier_label=TIER_LABEL, recent_keep=len(pipeline.recent),
            filtered=len(rows) != len(pipeline.recent)))

    # ---------------- 归档全文搜索 ----------------

    @router.get("/panel/search", response_class=HTMLResponse)
    async def archive_search(
        request: Request,
        q: str = Query(""),
        device: str = Query(""),
        mtype: str = Query(""),
        day_from: str = Query(""),
        day_to: str = Query(""),
        limit: int = Query(300, ge=10, le=2000),
    ):
        """在归档 Markdown 里全文搜索。

        消息流只有最近几千条（内存窗口），这里能搜到**全部历史**，
        这就是「看不到之前的消息」的根治办法。
        """
        guard(request)
        root = pipeline.archive.root
        ql = (q or "").strip().lower()

        hits: list = []
        scanned = 0
        truncated = False
        try:
            files = sorted(root.rglob("*.md"))
        except OSError:
            files = []

        for path in files:
            rel = path.relative_to(root)
            parts = rel.parts
            if len(parts) >= 3:
                dev, tname, subject = parts[0], parts[1], parts[2]
            elif len(parts) == 2:
                dev, tname, subject = "", parts[0], parts[1]
            else:
                dev, tname, subject = "", parts[0] if parts else "", ""

            if device and dev != device:
                continue
            if mtype and tname != mtype:
                continue
            day = path.stem.split(".")[0]
            if day_from and day < day_from:
                continue
            if day_to and day > day_to:
                continue

            for e in _archive_entries(path):
                scanned += 1
                if ql and ql not in e["text"]:
                    continue
                hits.append({
                    "day": day, "time": e["time"], "who": e["who"],
                    "device": dev, "type": tname, "subject": subject,
                    "body": e["body"], "text": e["text"],
                })

        hits.sort(key=lambda x: (x["day"], x["time"]), reverse=True)
        total_hits = len(hits)
        if total_hits > limit:
            hits = hits[:limit]
            truncated = True

        # 下拉候选：归档里实际出现过的设备与类型
        devs, types = set(), set()
        for path in files:
            parts = path.relative_to(root).parts
            if len(parts) >= 3:
                devs.add(parts[0])
                types.add(parts[1])
            elif len(parts) == 2:
                types.add(parts[0])

        return templates.TemplateResponse("search.html", ctx(
            request, active="search", rows=hits, q=q, device=device, mtype=mtype,
            day_from=day_from, day_to=day_to, limit=limit,
            total_hits=total_hits, truncated=truncated, scanned=scanned,
            files=len(files), devices=sorted(devs), mtypes=sorted(types),
            ptype=dict(TYPE_DIR)))

    # ---------------- 分析 / 监控 ----------------

    @router.get("/panel/analysis", response_class=HTMLResponse)
    async def analysis_page(
        request: Request,
        day: str = Query(""),
        days: int = Query(7, ge=1, le=30),
    ):
        """每日摘要 + 关键词监控 + 异常检测。全部只读，不改任何数据。"""
        guard(request)
        rows = [fix_record(r) for r in pipeline.recent]

        kw_raw = str(cfg.get("analysis.watch_keywords", "") or "")
        kws = [p.strip() for p in kw_raw.replace("，", ",").replace("；", ",").split(",") if p.strip()]
        if not kws:
            kws = list(DEFAULT_WATCH_KEYWORDS)

        def _num(key, default):
            try:
                return float(cfg.get(key, default))
            except (TypeError, ValueError):
                return float(default)

        summary = analysis.daily_summary(rows, day)
        tr = analysis.trend(rows, days)
        hits = analysis.watch_hits(rows, kws, limit=200)
        anom = analysis.anomalies(
            rows, days=days, device_status=_device_status_list(),
            spike_factor=_num("analysis.spike_factor", 3.0),
            spike_min=int(_num("analysis.spike_min_count", 15)),
            code_burst=int(_num("analysis.code_burst", 6)),
        )
        return templates.TemplateResponse("analysis.html", ctx(
            request, active="analysis", summary=summary, trend=tr, hits=hits,
            anomalies=anom, keywords=kws, days=days, recent_keep=len(rows)))

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
    async def archive_page(request: Request, device: str = Query("")):
        guard(request)
        groups = pipeline.archive.list_groups(device=device)
        devices = pipeline.archive.list_devices()
        app_table = build_map(cfg.get("panel.app_names", {}) or {})
        for g in groups:
            g["human"] = _human(g["bytes"])
            # 主题若是应用包名，额外给一个中文显示名（磁盘目录名不变）
            g["subject_display"] = display_name(g["subject"], app_table)
            g["is_pkg"] = g["subject_display"] != g["subject"]
            g["device_display"] = _device_label(g.get("device") or "")
        for d in devices:
            d["human"] = _human(d["bytes"])
            d["label"] = _device_label(d["device"])
        return templates.TemplateResponse("archive.html", ctx(
            request, active="archive", groups=groups, devices=devices, current_device=device))

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

    @router.get("/panel/archive/download-device")
    async def download_device(request: Request, device: str = Query("")):
        """把某一台手机的全部归档打包下载。"""
        guard(request)
        if not device:
            raise HTTPException(status_code=400, detail="缺少设备参数")
        files = pipeline.archive.files_of_device(device)
        if not files:
            raise HTTPException(status_code=404, detail="该设备没有归档文件")
        data = _zip_bytes(files)
        safe = device.replace("/", "_").replace("\\", "_")
        label = _device_label(device).replace("/", "_")
        name = f"{label}-{safe}-{datetime.now().strftime('%Y%m%d')}.zip"
        return StreamingResponse(io.BytesIO(data), media_type="application/zip",
                                 headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @router.get("/panel/archive/download")
    async def download_one(request: Request, type: str = Query(""), subject: str = Query(""),
                          device: str = Query("")):
        guard(request)
        sub = pipeline.archive.root / device / type / subject if device else pipeline.archive.root / type / subject
        if not sub.exists() or pipeline.archive.root not in sub.resolve().parents:
            raise HTTPException(status_code=404, detail="找不到该分组")
        files = sorted(sub.glob("*.md"))
        if not files:
            raise HTTPException(status_code=404, detail="该分组没有文件")
        data = _zip_bytes(files)
        name = f"{type}-{subject}-{datetime.now().strftime('%Y%m%d')}.zip"
        return StreamingResponse(io.BytesIO(data), media_type="application/zip",
                                 headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @router.get("/panel/archive/preview", response_class=HTMLResponse)
    async def archive_preview(
        request: Request,
        type: str = Query(""),
        subject: str = Query(""),
        device: str = Query(""),
        files_limit: int = Query(20, ge=1, le=300),
        chars: int = Query(4000, ge=200, le=100000),
    ):
        """归档分组「预览详情」：不下载也能看到组里有哪些文件、每个文件的开头内容。"""
        guard(request)
        sub = (pipeline.archive.root / device / type / subject) if device \
            else (pipeline.archive.root / type / subject)
        if not sub.exists() or pipeline.archive.root not in sub.resolve().parents:
            raise HTTPException(status_code=404, detail="找不到该分组")
        files = sorted(sub.glob("*.md"))
        items = []
        for f in files[:files_limit]:
            try:
                st = f.stat()
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            items.append({
                "name": f.name,
                "size": _human(st.st_size),
                "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                "entries": sum(1 for line in text.splitlines() if line.startswith("## ")),
                "head": text[:chars],
                "truncated": len(text) > chars,
            })
        return templates.TemplateResponse("archive_preview.html", ctx(
            request, active="archive", type=type, subject=subject, device=device,
            device_label=_device_label(device) if device else "",
            files=items, file_total=len(files), files_limit=files_limit, chars=chars))

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
            t = item["type"]
            # 复选框：没提交就代表「未勾选」。
            # 设置页会把所有 bool 项都渲染成复选框，未勾选的浏览器不会提交，
            # 所以这里不能沿用「不在表单里就跳过」的逻辑，否则开关只能开、不能关。
            if t == "bool":
                raw = form.get(item["path"])
                changes[item["path"]] = raw is not None and str(raw).lower() in ("on", "true", "1", "yes")
                continue
            if item["path"] not in form:
                continue
            raw = form[item["path"]]
            if t == "int":
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
        # 分级规则改动后立刻热加载，不用重启服务
        if any(str(k).startswith("priority.") for k in done):
            try:
                pipeline.reload_priority()
            except Exception:
                log.exception("重新加载分级规则失败")
        return templates.TemplateResponse("saved.html", ctx(
            request, active="settings", changed=done,
            note="部分参数（如合并窗口）需要重启服务才生效：sudo systemctl restart smsf-hub"))

    # ---------------- 渠道（终端） ----------------

    def _known_devices() -> list:
        """当前登记过的手机，给「只转发这些手机」当参考。"""
        out = []
        try:
            for d in pipeline.devices.all():
                label = str(d.get("label") or d.get("remark") or "").strip()
                key = str(d.get("key") or "").strip()
                if label and key:
                    out.append("%s（%s）" % (label, key))
                elif label or key:
                    out.append(label or key)
        except Exception:
            pass
        return out

    def _channel_view() -> list:
        data = channel_store.load(cfg)
        blocks = []
        for cls in CHANNEL_CLASSES:
            if not CHANNEL_EDITABLE.get(cls.name):
                continue
            blocks.append({
                "name": cls.name,
                "display": cls.display,
                "fields": channel_store.field_specs(cls.name),
                "instances": data.get(cls.name) or [],
                "live": [c.inst_id for c in pipeline.channels if c.name == cls.name],
            })
        return blocks

    def _after_change():
        """改完渠道立刻热加载，不用重启服务。"""
        pipeline.reload_channels()
        return RedirectResponse("/panel/channels", status_code=303)

    @router.get("/panel/channels", response_class=HTMLResponse)
    async def channels_page(request: Request):
        guard(request)
        return templates.TemplateResponse("channels.html", ctx(
            request, active="channels", blocks=_channel_view(),
            rules=RULE_FIELDS, known_devices=_known_devices()))

    @router.post("/panel/channels/{name}")
    async def channel_save(name: str, request: Request):
        guard(request)
        if name not in CHANNEL_EDITABLE:
            raise HTTPException(status_code=404, detail="未知渠道")
        form = await request.form()
        data = channel_store.load(cfg)
        insts = data.setdefault(name, [])
        by_id = {i["id"]: i for i in insts}
        specs = channel_store.field_specs(name)
        rpat = re.compile(r"^inst\.([A-Za-z0-9_]+)\.(.+)$")
        touched = []
        for raw_key in list(form.keys()):
            m = rpat.match(raw_key)
            if not m:
                continue
            iid, field = m.group(1), m.group(2)
            inst = by_id.get(iid)
            if inst is None:
                inst = channel_store.blank_instance(name, iid)
                insts.append(inst)
                by_id[iid] = inst
            if iid not in touched:
                touched.append(iid)
            if field.startswith("rules."):
                rk = field.split(".", 1)[1]
                if any(r["key"] == rk for r in RULE_FIELDS):
                    inst["rules"][rk] = str(form[raw_key])
                continue
            spec = next((f for f in specs if f["key"] == field), None)
            if spec is None:
                continue
            if spec["type"] == "int":
                try:
                    inst[field] = int(float(str(form[raw_key])))
                except ValueError:
                    pass
            else:
                inst[field] = str(form[raw_key])
        # 复选框没勾上就不会出现在表单里 —— 对这些字段按「关」处理
        for iid in touched:
            inst = by_id[iid]
            for f in specs:
                if f["type"] == "bool" and ("inst.%s.%s" % (iid, f["key"])) not in form:
                    inst[f["key"]] = False
        channel_store.save(cfg, data)
        log.info("面板保存了渠道 %s（%d 个终端）", name, len(touched))
        return _after_change()

    @router.post("/panel/channels/{name}/add")
    async def channel_add(name: str, request: Request):
        guard(request)
        if name not in CHANNEL_EDITABLE:
            raise HTTPException(status_code=404, detail="未知渠道")
        data = channel_store.load(cfg)
        insts = data.setdefault(name, [])
        insts.append(channel_store.blank_instance(
            name, channel_store.pick_id([i["id"] for i in insts])))
        channel_store.save(cfg, data)
        log.info("面板给渠道 %s 加了一个终端", name)
        return _after_change()

    @router.post("/panel/channels/{name}/delete")
    async def channel_delete(name: str, request: Request, inst_id: str = Form("")):
        guard(request)
        if name not in CHANNEL_EDITABLE:
            raise HTTPException(status_code=404, detail="未知渠道")
        data = channel_store.load(cfg)
        data[name] = [i for i in (data.get(name) or []) if i["id"] != inst_id]
        channel_store.save(cfg, data)
        log.info("面板删掉了渠道 %s 的终端 %s", name, inst_id)
        return _after_change()

    @router.post("/panel/sync_rules")
    async def sync_rules(request: Request):
        """把某个终端调好的转发规则，一次性复制给别的终端。"""
        guard(request)
        form = await request.form()
        src_full = str(form.get("src") or "")
        targets = [str(v) for v in form.getlist("targets")]
        sname, _, sid = src_full.partition(":")
        data = channel_store.load(cfg)
        src = next((i for i in (data.get(sname) or []) if i["id"] == sid), None)
        if src is None or not targets:
            return _after_change()
        n = 0
        for item in targets:
            tname, _, tid = item.partition(":")
            if tname not in CHANNEL_EDITABLE:
                continue
            if tname == sname and tid == sid:      # 别把自己覆盖了
                continue
            for i in (data.get(tname) or []):
                if i["id"] == tid:
                    i["rules"] = dict(src["rules"])
                    n += 1
        channel_store.save(cfg, data)
        log.info("转发规则已从 %s 同步给 %d 个终端", src_full, n)
        return _after_change()

    @router.post("/panel/channels/{name}/test")
    async def channel_test(name: str, request: Request, inst_id: str = Form("")):
        guard(request)
        inst = next((c for c in pipeline.channels
                     if c.name == name and (not inst_id or c.inst_id == inst_id)), None)
        if inst is None:
            return templates.TemplateResponse("saved.html", ctx(
                request, active="channels", changed=[],
                note="这个终端当前没启用（开关是关的，或者改完还没保存）"))
        from .models import Incoming
        sample = Incoming(type="sms", sender="10086",
                          content="这是一条来自 SmsForwarder Hub 的测试消息。",
                          device="测试", ts=int(time.time() * 1000))
        ok, info = await inst.send([sample], sample.device)
        return templates.TemplateResponse("saved.html", ctx(
            request, active="channels", changed=[],
            note=("测试成功：" if ok else "测试失败：") + str(info)))

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
        # 上报域名由安装时填写（见 config.yaml 的 server.phone_base_url）。
        # 没填就给个一眼能看懂的提示，而不是偷偷用一个写死的域名。
        base = (cfg.get("server.phone_base_url") or "").rstrip("/")
        if not base:
            base = "https://请先在【参数设置】里填写上报域名"
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
