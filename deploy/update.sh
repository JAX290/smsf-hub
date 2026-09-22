#!/bin/bash
# 从 GitHub 拉取最新代码并重启服务
set -euo pipefail
cd /opt/smsf-hub

echo "拉取最新代码…"
if [ -d .git ]; then
    git pull --ff-only
else
    echo "不是 git 仓库，跳过。请手动上传代码。"
fi

echo "同步依赖…"
./venv/bin/pip install -r requirements.txt -q

echo "重启服务…"
systemctl restart smsf-hub
sleep 2
systemctl --no-pager --full status smsf-hub | head -12
