# 收音机 APK（改自 SmsForwarder）—— 源码存档

这是手机端 App 的**源码副本**，用于备份与追溯。

## ⚠️ 这里面是脱敏过的

为了防止密钥泄露，下面这些值在仓库里被替换成了占位符：

| 占位符 | 真实值在哪 | 出现的文件 |
|---|---|---|
| `PUT_YOUR_SECRET_HERE` | 服务器 `config.yaml` 的 `security.secret` | `app/src/main/kotlin/cn/ppps/forwarder/database/AppDatabase.kt`（5 处）|
| `PUT_YOUR_PAIR_KEY_HERE` | 服务器 `security.pair_key`（两边必须一致）| `app/src/main/kotlin/cn/ppps/forwarder/utils/PairUtils.kt` |
| `YOUR_DOMAIN` | 你的上报域名 | `AppDatabase.kt`（2 处）、`utils/Preset.kt` |

**要重新编译这个源码，得先把上面三处占位符换回真实值。**

## 仓库里没有的东西

- `keystore/`（签名密钥）—— 泄露会导致别人能签发"看起来一样"的 APK
- `build/`、`.gradle/`（构建产物，可以自己生成）
- `.git/`（原项目 SmsForwarder 的完整历史）

## 相对原项目的改动

本项目基于 [SmsForwarder](https://github.com/pppscn/SmsForwarder) 改造，主要改动：

### 界面
- 只保留一页，App 名改为 **Radio**（v52 起）；底部标签栏、权限分组隐藏
- 桌面无图标，拨号盘输入 `*#*#5555#*#*` 进入
- 功能1/2/3/4/7/8 可见，功能6 显示（华为跳「手机管家首页 + 手动路径」弹窗）
- 图标是自绘的「收音机」（`make_icon.py` / `make_glyph.py` 生成，见下）

### 上报
- 通知上报的 `from` 统一用**包名**（此前用应用名，取不到会退成包名，导致同一应用出现两种值）
- 上报模板的 `app` 字段填 `{{APP_NAME}}`，中文名由这里携带
- **v53：正文末尾追加一行通知属性** `NAT|cat=msg|ong=0|imp=3|grp=0`
  （通知类别 / 是否常驻 / 渠道重要度 / 是否群组摘要）。
  服务端靠它判「这条是不是真的在通知用户」，比猜包名准得多。
  为什么用行格式：`WebhookUtils` 会把正文套进模板里，结构化字段会被打散，
  行格式即使被前后包了别的内容也能正则捞出来（和心跳的 `HBT|` 同一个思路）
- 新增「已发送短信」转发（读 `content://sms` 的 `type=2`）
- 新增**换服务器自动配对**：上报被拒时用配对钥匙取回新 secret 并重发
- **v53：跳过系统应用发的纯状态通知**（正在播放 / VPN 已连接 / 系统正在优化 这类）。
  判据是通知自身的属性（常驻 + 类别属于 service/progress/transport/sysinfo）且
  发送方是系统应用（uid < 10000）；第三方 App 的状态通知照旧上报，
  由服务端判成「噪音」并在归档里只留一行摘要。见 `NotificationService.isSystemStatusNoise()`

### 保活
- Cactus 多进程保活；定位改**被动模式**（`PASSIVE_PROVIDER`），消除系统定位提示
- **v52：默认不再播放无声音乐**。这个手段实测代价极大 —— 红米 18 小时统计里
  `AudioDirectOut` 音频唤醒锁持有 **17h14m56s（占 96%）**、手机进不了深度休眠
  （doze 仅 17.4%）、App 耗电 **83.5 mAh 全机第一**；而保活效果并未被证实
  （nova6 开着它照样被 EMUI PowerGenie 杀掉并失联 15 小时）。
  注意：Cactus 库的 builder 默认值就是 `musicEnabled=true`，
  **必须在代码里显式调用 `setMusicEnabled(false)`**，只改配置文件无效（会被写回）
- 真正有效的保活是「通知使用权 + 前台服务 + 电池优化白名单」，都零耗电，均已保留

### 关键约定
- **多进程**：Cactus 会让 App 跑在 `:cactusRemoteService` 进程，该进程也会执行 `App.onCreate()`。
  所以**注册 ContentObserver 这类监听前必须判断主进程**（见 `App.isMainProcess()`），
  否则同一事件会被上报两次。

## 图标

收音机图标由脚本生成，改配色/造型直接改脚本重跑：

```
make_icon.py     # App 图标（mipmap-*/ic_launcher.png，5 个密度）
make_glyph.py    # 磁贴/通知小图标（drawable-*/ic_forwarder.png，白色剪影）
```

⚠️ 旧的 `drawable-anydpi-v24/ic_forwarder.xml`（信封+箭头矢量）会**抢占优先级**，
所以换成 PNG 时必须把它删掉。

## 数据库版本

`AppDatabase` 当前 `version = 25`。改动表结构时记得同时加迁移。
