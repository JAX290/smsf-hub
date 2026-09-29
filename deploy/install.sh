#!/bin/bash
# ==============================================================================
#  SmsForwarder Hub 一键部署脚本
#
#  用法（在服务器上执行）：
#      bash install.sh
#
#  它会做的事：
#      建目录 -> 建虚拟环境 -> 装依赖 -> 【采集环境信息】 -> 生成配置
#      -> 生成填好 IP 的 nginx 片段 -> 装 systemd 服务 -> 启动
#
#  ── 换 VPS 时怎么省事 ──────────────────────────────────────────────
#  至少把旧的 secret / 配对钥匙带上，手机就不用动：
#
#      SMSF_SECRET=<旧secret> SMSF_PAIR_KEY=<配对钥匙> bash install.sh
#
#  想完全无人值守，连域名和 IP 也一起给：
#
#      SMSF_HOST=<新Tailscale IP> SMSF_DOMAIN=<上报域名> \
#      SMSF_SECRET=<旧secret> SMSF_PAIR_KEY=<配对钥匙> bash install.sh
#
#  也可以把这些写进 deploy/install.env（脚本会自动读取，该文件不进仓库）。
# ==============================================================================
set -euo pipefail

APP_DIR=/opt/smsf-hub
cd "$APP_DIR"
PY="$APP_DIR/venv/bin/python"

# 可选：把环境变量写进 install.env，省得每次敲一长串
if [ -f "$APP_DIR/deploy/install.env" ]; then
    # shellcheck disable=SC1091
    . "$APP_DIR/deploy/install.env"
    echo "（已读取 deploy/install.env）"
fi

echo "[1/8] 检查目录"
mkdir -p "$APP_DIR/app/data/archive" "$APP_DIR/app/data/logs"
chmod 700 "$APP_DIR/app/data"

echo "[2/8] 创建虚拟环境"
if [ ! -x "$PY" ]; then
    python3 -m venv "$APP_DIR/venv"
fi

echo "[3/8] 安装依赖"
"$APP_DIR/venv/bin/pip" install --upgrade pip -q
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" -q

# ------------------------------------------------------------------------------
#  采集环境信息
#
#  原则：能自己扫的自己扫，扫不出来的问人。
#    · Tailscale IP  -> 能扫（tailscale ip -4）；扫不到就问
#    · 上报域名      -> 扫不出来（取决于你的 DNS），必须问
#    · 下载目录      -> 自己生成随机名，不问
# ------------------------------------------------------------------------------

INTERACTIVE=1
[ -t 0 ] || INTERACTIVE=0
[ "${SMSF_NONINTERACTIVE:-0}" = "1" ] && INTERACTIVE=0

# 只接受「看起来像域名」的输入，避免把整串 URL 填进去
sanitize_domain() {
    local v="$1"
    v="${v#http://}"; v="${v#https://}"
    v="${v%%/*}"; v="${v%%:*}"
    echo "$v"
}

echo "[4/8] 采集环境信息"

# ---- (1) 面板地址 ----
TS_IP="${SMSF_HOST:-}"
if [ -z "$TS_IP" ]; then
    TS_IP=$(tailscale ip -4 2>/dev/null | head -1 || true)
fi
if [ -z "$TS_IP" ]; then
    TS_IP=$(ip -4 addr show tailscale0 2>/dev/null | grep -oE 'inet [0-9.]+' | awk '{print $2}' | head -1 || true)
fi

if [ "$INTERACTIVE" = "1" ]; then
    echo
    echo "  ────────────────────────────────────────────────"
    echo "   (1) 面板地址（面板绑在哪个 IP 上）"
    echo "  ────────────────────────────────────────────────"
    echo "   面板只绑这个地址，只有你自己的 Tailscale 网络能打开。"
    echo "   ⚠️ 不要填 0.0.0.0 —— 那等于把面板暴露到公网。"
    echo
    if [ -n "$TS_IP" ]; then
        echo "   自动检测到 Tailscale IP：$TS_IP"
        printf "   回车用这个，或输入别的： "
    else
        echo "   没检测到 Tailscale（可能还没装或还没登录）。"
        echo "   可以回车跳过，之后自己改 config.yaml 里的 server.panel_host。"
        printf "   面板地址（留空跳过）： "
    fi
    read -r _ans || true
    if [ -n "${_ans:-}" ]; then
        TS_IP="$_ans"
    fi
    if [ -z "$TS_IP" ]; then
        TS_IP="127.0.0.1"
        echo "   -> 面板将只监听本机（127.0.0.1），需要你自己改 config.yaml"
    else
        echo "   -> 面板地址：$TS_IP"
    fi
else
    [ -n "$TS_IP" ] || TS_IP="127.0.0.1"
    echo "  （非交互模式）面板地址：$TS_IP"
fi

# ---- (2) 上报域名 ----
DOMAIN="${SMSF_DOMAIN:-}"
if [ -z "$DOMAIN" ] && [ "$INTERACTIVE" = "1" ]; then
    echo
    echo "  ────────────────────────────────────────────────"
    echo "   (2) 上报域名（手机往这个地址发消息）"
    echo "  ────────────────────────────────────────────────"
    echo "   只填域名，不要带 https:// 和后面的路径。"
    echo "   例：  notic.example.com"
    echo
    echo "   两点建议："
    echo "     · 用 DNS 直连源站，不要走 Cloudflare"
    echo "       （Cloudflare 可能拦掉 POST，源站 IP 也会暴露在回源记录里）"
    echo "     · 这个域名要已经解析到本机"
    echo
    printf "   上报域名（留空跳过）： "
    read -r _dom || true
    if [ -n "${_dom:-}" ]; then
        DOMAIN=$(sanitize_domain "$_dom")
    fi
fi
if [ -n "$DOMAIN" ]; then
    echo "   -> 上报地址：https://$DOMAIN/smsf/hook"
else
    echo "   -> 未填。之后可在面板【参数设置】里补，或重跑本脚本。"
fi

# ---- (3) 下载目录（自己生成）----
DL_RAND=$(openssl rand -hex 8 2>/dev/null || head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')
DL_DIR="/var/www/smsf-dl-$DL_RAND"
echo "   -> APK 下载目录：$DL_DIR（随机名，避免被猜路径）"

echo "[5/8] 生成配置文件"
if [ ! -f "$APP_DIR/config.yaml" ]; then
    cp "$APP_DIR/config.example.yaml" "$APP_DIR/config.yaml"

    SECRET="${SMSF_SECRET:-}"
    PAIR_KEY="${SMSF_PAIR_KEY:-}"
    PANEL_PWD="${SMSF_PANEL_PWD:-}"
    [ -n "$SECRET" ]    || SECRET=$(openssl rand -hex 32)
    [ -n "$PANEL_PWD" ] || PANEL_PWD=$(openssl rand -base64 12 | tr -d '/+=' | cut -c1-12)

    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    #  关于配对钥匙（pair_key）—— 现在基本不用管了
    #
    #  手机上报被拒时会自动来配对。它的签名钥匙有两把来源：
    #
    #    ① 从【上报域名】派生   —— 服务器自动算，零配置
    #    ② 手工配置的 pair_key  —— 兼容旧版手机
    #
    #  因为域名是焊死在 APK 里的、换 VPS 时不变，所以新版手机（v42+）
    #  换服务器【不需要传任何东西】—— 它和服务器会各自算出同一把钥匙。
    #
    #  只有当手机上装的还是旧版 APK（v41 及以前，只认烧死的那把钥匙）时，
    #  才需要把旧 config.yaml 里的 pair_key 带过来：
    #      SMSF_PAIR_KEY=<旧钥匙> bash install.sh
    # ------------------------------------------------------------------
    if [ -z "$PAIR_KEY" ]; then
        if [ "$INTERACTIVE" = "1" ]; then
            echo
            echo "  提示：没提供配对钥匙（SMSF_PAIR_KEY）。"
            echo "        如果手机上的 APK 是 v42 或更新，这样就行 —— 不用管它。"
            echo "        如果手机上还是旧版（v41 及以前），建议现在填上旧钥匙，否则那台手机要重装 APK。"
            echo
            printf "        旧钥匙（直接回车 = 跳过）： "
            read -r _pk || true
            [ -n "${_pk:-}" ] && PAIR_KEY="$_pk"
        fi
    fi
    [ -n "$PAIR_KEY" ] || PAIR_KEY=$(openssl rand -hex 32)

    SMSF_X_SECRET="$SECRET" SMSF_X_PAIR="$PAIR_KEY" SMSF_X_PWD="$PANEL_PWD" \
    SMSF_X_HOST="$TS_IP" SMSF_X_DOMAIN="$DOMAIN" SMSF_X_DLDIR="$DL_DIR" \
    "$PY" - <<'PYEOF'
import os
from pathlib import Path
import yaml

p = Path("/opt/smsf-hub/config.yaml")
cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

cfg.setdefault("security", {})
cfg["security"]["secret"] = os.environ["SMSF_X_SECRET"]
cfg["security"]["pair_key"] = os.environ["SMSF_X_PAIR"]

cfg.setdefault("panel", {})
cfg["panel"]["password"] = os.environ["SMSF_X_PWD"]
cfg["panel"]["apk_download_dir"] = os.environ["SMSF_X_DLDIR"]

cfg.setdefault("server", {})
host = os.environ["SMSF_X_HOST"]
domain = os.environ["SMSF_X_DOMAIN"]
cfg["server"]["panel_host"] = host
cfg["server"]["panel_url"] = "http://%s:%s" % (host, cfg["server"].get("panel_port", 8702))
if domain:
    cfg["server"]["phone_base_url"] = "https://%s/smsf/hook" % domain
    cfg["server"]["public_base_url"] = "https://%s/smsf" % domain

p.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
print("   已写入 config.yaml：secret / 配对钥匙 / 口令 / 面板地址 / 上报域名 / 下载目录")
print()
print("   ⚠️ 注意：为了稳妥地写这些值，这里是用 yaml 库整体重写的，")
print("      原模板里的中文注释不会保留。想看带注释的版本，看 config.example.yaml。")
PYEOF

    chmod 600 "$APP_DIR/config.yaml"
    mkdir -p "$DL_DIR"; chmod 755 "$DL_DIR"

    echo
    echo "  ============================================"
    echo "   已生成配置，请记下这三个值："
    echo "   手机端 secret : $SECRET"
    echo "   配对钥匙      : $PAIR_KEY"
    echo "   面板登录口令  : $PANEL_PWD"
    echo "  ============================================"
    echo "   （换服务器时带上这三个环境变量重跑，手机就不用动）"
    echo
else
    echo "  config.yaml 已存在，保留不动"
    DL_EXIST=$("$PY" -c "import yaml;print((yaml.safe_load(open('/opt/smsf-hub/config.yaml',encoding='utf-8')).get('panel') or {}).get('apk_download_dir',''))" 2>/dev/null || true)
    if [ -n "$DL_EXIST" ]; then
        DL_DIR="$DL_EXIST"
    else
        mkdir -p "$DL_DIR"
        SMSF_X_DLDIR="$DL_DIR" "$PY" - <<'PYEOF2'
import os
from pathlib import Path
import yaml
p = Path("/opt/smsf-hub/config.yaml")
cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
cfg.setdefault("panel", {})["apk_download_dir"] = os.environ["SMSF_X_DLDIR"]
p.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
print("   已补填 panel.apk_download_dir")
PYEOF2
    fi
    mkdir -p "$DL_DIR"; chmod 755 "$DL_DIR"
    echo "   -> 下载目录：$DL_DIR"
fi

echo "[6/8] 生成 nginx 片段（IP 和端口已填好）"
PANEL_PORT=$("$PY" -c "import yaml;print((yaml.safe_load(open('/opt/smsf-hub/config.yaml',encoding='utf-8')).get('server') or {}).get('panel_port',8702))" 2>/dev/null || echo 8702)
sed -e "s|__PANEL_HOST__|$TS_IP|g" -e "s|__PANEL_PORT__|$PANEL_PORT|g" \
    "$APP_DIR/deploy/nginx-smsf.conf" > "$APP_DIR/deploy/nginx-smsf.filled.conf"
echo "   -> $APP_DIR/deploy/nginx-smsf.filled.conf"
echo "      把这个文件里的 location 段加进你的站点配置，然后："
echo "      nginx -t && systemctl reload nginx"

echo "[7/8] 安装 systemd 服务"
install -m 644 "$APP_DIR/deploy/smsf-hub.service" /etc/systemd/system/smsf-hub.service
systemctl daemon-reload
systemctl enable smsf-hub

echo "[8/8] 启动"
systemctl restart smsf-hub
sleep 3
systemctl --no-pager --full status smsf-hub | head -20 || true

echo
echo "完成。还剩两件脚本代替不了的事："
echo "   1. 把 nginx 片段接上（见 [6/8] 的输出）"
echo "   2. 确认上报域名已解析到本机"
echo
echo "强烈建议跑一次环境自检："
echo "   bash deploy/selfcheck.sh"
echo
echo "常用命令："
echo "   systemctl status smsf-hub    查看状态"
echo "   journalctl -u smsf-hub -f    实时日志"
echo "   systemctl restart smsf-hub   重启"
echo "   bash deploy/update.sh        拉最新代码并重启"
echo
