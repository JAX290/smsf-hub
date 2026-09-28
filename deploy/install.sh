#!/bin/bash
# ==============================================================================
#  SmsForwarder Hub 一键部署脚本
#  用法（在服务器上执行）：
#      bash install.sh
#  做的事：建目录 -> 建虚拟环境 -> 装依赖 -> 装 systemd 服务 -> 启动
#  前提：代码已经放到 /opt/smsf-hub
# ==============================================================================
set -euo pipefail

APP_DIR=/opt/smsf-hub
cd "$APP_DIR"

echo "[1/6] 检查目录"
mkdir -p "$APP_DIR/app/data/archive" "$APP_DIR/app/data/logs"
chmod 700 "$APP_DIR/app/data"

echo "[2/6] 创建虚拟环境"
if [ ! -x "$APP_DIR/venv/bin/python" ]; then
    python3 -m venv "$APP_DIR/venv"
fi

echo "[3/6] 安装依赖"
"$APP_DIR/venv/bin/pip" install --upgrade pip -q
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" -q

echo "[4/6] 生成配置文件（若不存在）"
if [ ! -f "$APP_DIR/config.yaml" ]; then
    cp "$APP_DIR/config.example.yaml" "$APP_DIR/config.yaml"

    # 换服务器时，把原来那把 secret 和配对钥匙带上，手机就不用动：
    #     SMSF_SECRET=<旧secret> SMSF_PAIR_KEY=<配对钥匙> bash install.sh
    # 不传就随机生成（全新部署的情况）。
    SECRET="${SMSF_SECRET:-}"
    PAIR_KEY="${SMSF_PAIR_KEY:-}"
    PANEL_PWD="${SMSF_PANEL_PWD:-}"
    [ -n "$SECRET" ]    || SECRET=$(openssl rand -hex 32)
    [ -n "$PAIR_KEY" ]  || PAIR_KEY=$(openssl rand -hex 32)
    [ -n "$PANEL_PWD" ] || PANEL_PWD=$(openssl rand -base64 12 | tr -d '/+=' | cut -c1-12)

    sed -i "s|secret: \"请改成你自己的长随机串_至少32位\"|secret: \"$SECRET\"|" "$APP_DIR/config.yaml"
    sed -i "s|password: \"请改成你自己的口令\"|password: \"$PANEL_PWD\"|" "$APP_DIR/config.yaml"
    sed -i "s|^  pair_key: \"\"|  pair_key: \"$PAIR_KEY\"|" "$APP_DIR/config.yaml"
    chmod 600 "$APP_DIR/config.yaml"
    echo
    echo "  ============================================"
    echo "   已生成配置，请记下这三个值："
    echo "   手机端 secret : $SECRET"
    echo "   配对钥匙      : $PAIR_KEY"
    echo "   面板登录口令  : $PANEL_PWD"
    echo "  ============================================"
    echo "   （换服务器时想省事，下次带上这三个环境变量重跑本脚本即可）"
    echo
else
    echo "  config.yaml 已存在，跳过生成"
fi

echo "[5/6] 安装 systemd 服务"
install -m 644 "$APP_DIR/deploy/smsf-hub.service" /etc/systemd/system/smsf-hub.service
systemctl daemon-reload
systemctl enable smsf-hub

echo "[6/6] 启动"
systemctl restart smsf-hub
sleep 3
systemctl --no-pager --full status smsf-hub | head -20 || true

echo
echo "完成。常用命令："
echo "  查看状态  systemctl status smsf-hub"
echo "  看日志    journalctl -u smsf-hub -f"
echo "  重启      systemctl restart smsf-hub"
echo "  停止      systemctl stop smsf-hub"
