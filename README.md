# SmsForwarder Hub（短信转发中枢）

把安卓手机上的**短信 / 来电 / APP 通知**统一收集到自己的服务器，然后**分发到任意多个渠道**，同时自动归档成 Markdown 文件。

配套手机端：[SmsForwarder](https://github.com/pppscn/SmsForwarder)（本仓库只做服务端）。

---

## 为什么需要服务端？

手机直接推到渠道有几个绕不过去的问题，加一层服务端全部解决：

| 问题 | 直连渠道 | 经过本服务 |
|---|---|---|
| 企业微信群机器人 **20 条/分钟**限制 | 短信轰炸时丢消息 | 服务端合并窗口攒批发送 |
| 凭据要写进手机 | webhook 泄露风险 | 凭据只在服务器上 |
| 想同时推多个渠道 | 每个渠道配一遍 | 服务端一对多扇出 |
| 想留档 | 要自己另做 | 自动归档 Markdown |
| 想换渠道 | 要改手机配置 | 改服务器配置即可 |

---

## 功能

- **统一入口**：手机只发到一个地址，服务端负责其余一切
- **签名校验**：HMAC-SHA256 + 时间戳时效，拒绝伪造与重放
- **去重**：同样内容短时间内只处理一次
- **合并发送**：窗口内的多条消息攒成一条推送，避免刷屏、绕开渠道限流
- **Markdown 归档**：按 `类型/主题/日期.md` 组织，单文件超限自动滚动，总量超限面板报警
- **13 个推送渠道**：企业微信（群机器人/应用消息）、钉钉群机器人、飞书群机器人、Telegram、
  Bark、ntfy、Gotify、PushPlus、Server酱、邮件 SMTP、通用 Webhook、仅归档
- **控制面板**：总览 / 消息流 / 归档浏览与打包下载 / 渠道开关 / **所有参数表单化** / 签名自测
- **只走内网**：上报入口由 nginx 反代，面板只绑 Tailscale IP，不额外暴露端口

---

## 架构

```
[安卓手机] ──HTTPS POST──> [你的服务器]
                              │
                        ┌─────┴─────┐
                        │  smsf-hub │
                        └─────┬─────┘
                              │
        ┌─────────┬───────────┼───────────┬──────────┐
        ▼         ▼           ▼           ▼          ▼
     去重      归档MD      合并窗口    签名校验    多渠道分发
                                              ┌───┴───┬───────┬──────┐
                                              ▼       ▼       ▼      ▼
                                            企微    钉钉    飞书   Bark …
```

- 上报入口：`127.0.0.1:8701`（只给 nginx 反代，公网直接访问不到）
- 控制面板：`<Tailscale IP>:8702`（只有你自己的 tailnet 能打开）

---

## 部署（Ubuntu 24.04）

### 1. 拉代码

```bash
sudo mkdir -p /opt/smsf-hub
sudo git clone <本仓库地址> /opt/smsf-hub
cd /opt/smsf-hub
```

### 2. 一键安装

```bash
sudo bash deploy/install.sh
```

脚本会：建虚拟环境 → 装依赖 → 生成 `config.yaml`（含随机 secret 与面板口令）→ 装 systemd 服务 → 启动。

**脚本会打印两个值，请记下来：**
- `手机端 secret` —— 填到手机的 SmsForwarder 里
- `面板登录口令` —— 打开面板时用

### 3. 接上 nginx（让公网能上报）

参考 `deploy/nginx-smsf.conf`，把里面的 `location /smsf/hook` 加进你自己的站点配置，然后：

```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## 手机端配置

在 SmsForwarder 里新建**发送通道 → Webhook**，建议按类型建三个（这样服务端能区分）：

| 类型 | WebServer 地址 |
|---|---|
| 短信 | `https://你的域名/smsf/hook/sms` |
| 来电 | `https://你的域名/smsf/hook/call` |
| APP通知 | `https://你的域名/smsf/hook/notify` |

三个都用同一份配置：

| 字段 | 值 |
|---|---|
| 请求方式 | `POST` |
| secret | 安装脚本打印的那串 |
| headers | `{"Content-Type": "application/json"}` ← **必须** |
| webParams | 见下 |

**webParams（请求体模板，直接抄）**：

```json
{
  "device": "[device_mark]",
  "from": "[from]",
  "content": "[content]",
  "sim": "[title]",
  "app_version": "[app_version]",
  "receive_time": "[receive_time:yyyy-MM-dd HH:mm:ss]",
  "ts": "[timestamp]",
  "sign": "[sign]"
}
```

> APP通知那条建议把 `"app"` 也带上。可用变量：`[from]` `[content]` `[msg]`
> `[org_content]` `[device_mark]` `[app_version]` `[title]` `[card_slot]`
> `[timestamp]` `[sign]` `[receive_time]`。

配好后打开面板的**自测**页，里面有一条现成的 `curl` 命令，可以先在服务器上验证全链路。

---

## 常用命令

```bash
systemctl status smsf-hub      # 看状态
journalctl -u smsf-hub -f      # 实时日志
systemctl restart smsf-hub     # 重启（改完参数要重启）
bash deploy/update.sh          # 从 GitHub 拉最新代码并重启
```

---

## 参数怎么改？

**不用碰代码。** 两种情况：

1. **面板里改**（推荐）：打开面板 → 参数设置 / 推送渠道 → 表单里改 → 保存 → 重启服务
2. **改配置文件**：编辑 `/opt/smsf-hub/config.yaml`，每行都有中文注释说明，改完重启

面板保存时会**保留配置文件里的中文注释**（不是整个重写），所以配置始终是可读的。

---

## 归档说明

```
app/data/archive/
├── 短信/
│   └── 10086/
│       ├── 2026-09-22.md
│       └── 2026-09-22.part2.md     ← 单文件超过上限自动滚动
├── 来电/
│   └── 13800138000/
│       └── 2026-09-22.md
└── APP通知/
    └── 微信/
        └── 2026-09-22.md
```

- 目录第二层（主题）按什么分，可在面板改（发件人 / 应用名）
- 总量达到 `warn_percent` 百分比时面板变黄，达到 100% 变红并提示打包下载

---

## 安全

- 上报必须带合法 HMAC-SHA256 签名，且时间戳在容忍范围内（防重放）
- ⚠️ 该签名**不覆盖消息内容**，所以**必须走 HTTPS**，否则内容可被中间人篡改
- `config.yaml` 含凭据，权限 600，且已在 `.gitignore` 中
- 归档目录含短信正文，同样不进仓库
- 面板只绑 Tailscale IP，不在公网暴露

---

## 目录结构

```
app/
├── main.py              FastAPI 应用（上报入口 + 面板挂载）
├── panel.py             控制面板路由
├── pipeline.py          主流水线：去重 → 归档 → 合并 → 分发
├── verify.py            HMAC 签名与时间戳校验
├── archive.py           Markdown 归档（滚动 + 总量统计）
├── merge.py             合并窗口
├── dedup.py             去重
├── models.py            消息模型
├── config.py            配置加载（缺项自动补默认值）
├── yaml_edit.py         保留注释的配置改写
├── settings_schema.py   面板表单定义（加参数只改这里）
├── channels/            13 个推送渠道
└── templates/           面板页面
deploy/
├── install.sh           一键部署
├── update.sh            更新
├── smsf-hub.service     systemd 单元
└── nginx-smsf.conf      nginx 反代片段
run.py                   启动入口（一个进程两个监听）
config.example.yaml      配置模板（全中文注释）
```

---

## 许可

MIT
