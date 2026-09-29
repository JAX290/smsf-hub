#!/bin/bash
# ==============================================================================
#  SmsForwarder Hub 环境自检
#
#  用法（在服务器上执行）：
#      bash deploy/selfcheck.sh
#
#  什么时候跑：
#      · 刚部署完
#      · 【换了 VPS 之后】（最重要 —— 逐项确认该改的都改了）
#      · 手机突然上报不了，想快速定位是哪一环断了
#
#  它只读不写，不会改任何东西。
# ==============================================================================
cd /opt/smsf-hub

PY=./venv/bin/python
OK=0; WARN=0; BAD=0
ok()   { echo "  [OK]   $1"; OK=$((OK+1)); }
warn() { echo "  [注意] $1"; WARN=$((WARN+1)); }
bad()  { echo "  [问题] $1"; BAD=$((BAD+1)); }

echo "=================================================================="
echo " SmsForwarder Hub 环境自检"
echo " 时间：$(date '+%Y-%m-%d %H:%M:%S')"
echo "=================================================================="
echo

# ----------------------------------------------------------------------
echo "── 1. 服务进程 ──"
if systemctl is-active --quiet smsf-hub; then
    ok "smsf-hub 正在运行"
else
    bad "smsf-hub 没在跑。看日志：journalctl -u smsf-hub -n 50"
fi

listen_host=$("$PY" -c "import yaml;print((yaml.safe_load(open('config.yaml',encoding='utf-8')).get('server') or {}).get('listen_host',''))" 2>/dev/null || true)
listen_port=$("$PY" -c "import yaml;print((yaml.safe_load(open('config.yaml',encoding='utf-8')).get('server') or {}).get('listen_port',''))" 2>/dev/null || true)
panel_host=$("$PY"  -c "import yaml;print((yaml.safe_load(open('config.yaml',encoding='utf-8')).get('server') or {}).get('panel_host',''))" 2>/dev/null || true)
panel_port=$("$PY"  -c "import yaml;print((yaml.safe_load(open('config.yaml',encoding='utf-8')).get('server') or {}).get('panel_port',''))" 2>/dev/null || true)
domain=$("$PY" -c "import yaml;print((yaml.safe_load(open('config.yaml',encoding='utf-8')).get('server') or {}).get('phone_base_url',''))" 2>/dev/null || true)
dldir=$("$PY" -c "import yaml;print((yaml.safe_load(open('config.yaml',encoding='utf-8')).get('panel') or {}).get('apk_download_dir',''))" 2>/dev/null || true)
secret=$("$PY" -c "import yaml;print((yaml.safe_load(open('config.yaml',encoding='utf-8')).get('security') or {}).get('secret',''))" 2>/dev/null || true)
pairkey=$("$PY" -c "import yaml;print((yaml.safe_load(open('config.yaml',encoding='utf-8')).get('security') or {}).get('pair_key',''))" 2>/dev/null || true)
window=$("$PY" -c "import yaml;print((yaml.safe_load(open('config.yaml',encoding='utf-8')).get('dedup') or {}).get('window_seconds',''))" 2>/dev/null || true)
echo

# ----------------------------------------------------------------------
echo "── 2. 监听端口 ──"
if ss -lnt 2>/dev/null | grep -q ":$listen_port "; then
    ok "上报入口 $listen_host:$listen_port 在监听"
else
    bad "上报入口 $listen_port 没在监听"
fi
if [ "$panel_host" = "0.0.0.0" ] || [ "$panel_host" = "::" ]; then
    bad "面板绑在 $panel_host —— 等于暴露到公网！改成 Tailscale IP"
elif [ -n "$panel_host" ] && ss -lnt 2>/dev/null | grep -q "$panel_host:$panel_port "; then
    ok "面板 $panel_host:$panel_port 在监听"
elif [ -n "$panel_host" ]; then
    bad "面板 $panel_port 没在 $panel_host 上监听"
else
    warn "读不到 panel_host"
fi
echo

# ----------------------------------------------------------------------
echo "── 3. Tailscale ──"
if command -v tailscale >/dev/null 2>&1; then
    ts_now=$(tailscale ip -4 2>/dev/null | head -1 || true)
    if [ -z "$ts_now" ]; then
        bad "tailscale 在，但查不到 IP（可能没登录：tailscale up）"
    else
        if ip -4 addr show tailscale0 2>/dev/null | grep -q "$ts_now"; then
            ok "tailscale0 网卡上有地址 $ts_now"
        else
            bad "tailscale 说自己是 $ts_now，但网卡上没有这个地址 —— 跑 systemctl restart tailscaled"
        fi
        if [ -n "$panel_host" ] && [ "$panel_host" != "$ts_now" ]; then
            warn "配置里的 panel_host=$panel_host 和当前 Tailscale IP=$ts_now 不一致（换机器后最容易漏这条）"
        fi
    fi
else
    warn "这台机器没装 tailscale（如果面板不打算走 Tailscale，忽略这条）"
fi
echo

# ----------------------------------------------------------------------
echo "── 4. 配置项 ──"
[ -n "$secret" ] && [ "${#secret}" -ge 32 ] && ok "secret 已设置（${#secret} 位）" || bad "secret 没设置或太短"
if [ -n "$pairkey" ]; then
    ok "pair_key 已设置"
    if [ "${#pairkey}" -lt 32 ]; then warn "pair_key 偏短"; fi
else
    warn "pair_key 为空 —— 换服务器时手机无法自动配对"
fi
if [ -n "$domain" ]; then
    ok "上报地址：$domain"
    case "$domain" in
        *请先*|*你的域名*) bad "上报地址还是占位符，去面板【参数设置】填真实的" ;;
    esac
else
    bad "没配上报域名（server.phone_base_url 为空）"
fi
if [ -n "$dldir" ]; then
    if [ -d "$dldir" ]; then ok "APK 下载目录存在：$dldir"
    else bad "APK 下载目录不存在：$dldir（跑 install.sh 会创建）"; fi
else
    warn "没配 panel.apk_download_dir，publish_apk.py 会没法上传"
fi
case "$window" in
    ''|0)  warn "读不到去重窗口" ;;
    6[0-9]|6[0-9][0-9])
        bad "去重窗口 $window 秒太小 —— 手机离线补发的退避最长 10 分钟，
        重发会落到窗口外，导致消息被重复记录。建议改成 900" ;;
    *) ok "去重窗口 $window 秒" ;;
esac
echo

# ----------------------------------------------------------------------
echo "── 5. nginx 反代 ──"
if systemctl is-active --quiet nginx; then
    ok "nginx 在跑"
else
    bad "nginx 没在跑"
fi
if [ -f deploy/nginx-smsf.filled.conf ]; then
    if grep -q "__PANEL_HOST__" deploy/nginx-smsf.filled.conf 2>/dev/null; then
        warn "nginx-smsf.filled.conf 里还有未替换的占位符，重新跑 install.sh"
    else
        ok "已生成填好的 nginx 片段"
    fi
else
    warn "没有 deploy/nginx-smsf.filled.conf（跑 install.sh 会生成）"
fi
# 本地直连上报入口（绕开 nginx），验证应用本身正常
# 空 POST 打过去，看服务是否活着。预期会被签名校验拦下（401/403），
# 或者因为 body 不是合法 JSON 而返回 400 —— 三种都说明服务在正常响应。
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:$listen_port/smsf/hook/sms" --max-time 5 2>/dev/null || echo 000)
case "$code" in
    401|403) ok "上报入口有响应（$code = 签名校验拦下了空请求，符合预期）" ;;
    400)     ok "上报入口有响应（$code = body 不是合法 JSON，符合预期）" ;;
    422)     ok "上报入口有响应（$code = 参数校验拒绝，符合预期）" ;;
    000)     bad "上报入口连不上" ;;
    *)       warn "上报入口返回 $code（预期 400/401/403/422）" ;;
esac
echo

# ----------------------------------------------------------------------
echo "── 6. 数据目录 ──"
[ -d app/data/archive ] && ok "归档目录存在" || bad "归档目录不存在"
n=$(find app/data/archive -name '*.md' 2>/dev/null | wc -l)
echo "         当前归档 $n 个 markdown 文件"
if [ -f app/data/devices.json ]; then
    d=$(grep -c '"key"' app/data/devices.json 2>/dev/null || echo 0)
    ok "已登记 $d 台手机"
else
    warn "还没有手机上报过（app/data/devices.json 不存在）"
fi
echo

# ----------------------------------------------------------------------
echo "=================================================================="
echo " 结果：$OK 项正常 · $WARN 项注意 · $BAD 项有问题"
echo "=================================================================="
if [ "$BAD" -gt 0 ]; then
    echo
    echo " 有问题的那几项按上面提示处理。常见原因："
    echo "   · 换了 VPS 但没重跑 install.sh -> panel_host / 下载目录 还是旧的"
    echo "   · Tailscale 重启后网卡没拿到地址 -> systemctl restart tailscaled"
    echo "   · nginx 片段没接上 -> 看 deploy/nginx-smsf.filled.conf"
    echo
    exit 1
fi
echo
echo " 全部正常。如果手机还是上报不了，检查："
echo "   1. 域名是否解析到本机（dig +short <你的域名>）"
echo "   2. 手机端填的 secret 是否和 config.yaml 里的一致"
echo "   3. 手机端能不能上网、是不是被系统限制了后台联网"
echo
