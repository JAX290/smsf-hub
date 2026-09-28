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
- 只保留一页，标题改为「收音机」；底部标签栏、权限分组隐藏
- 桌面无图标，拨号盘输入 `*#*#5555#*#*` 进入
- 功能1/2/3/4/7/8 可见，功能6 隐藏

### 上报
- 通知上报的 `from` 统一用**包名**（此前用应用名，取不到会退成包名，导致同一应用出现两种值）
- 上报模板的 `app` 字段填 `{{APP_NAME}}`，中文名由这里携带
- 新增「已发送短信」转发（读 `content://sms` 的 `type=2`）
- 新增**换服务器自动配对**：上报被拒时用配对钥匙取回新 secret 并重发

### 保活
- Cactus 多进程保活；定位改**被动模式**（`PASSIVE_PROVIDER`），消除系统定位提示

### 关键约定
- **多进程**：Cactus 会让 App 跑在 `:cactusRemoteService` 进程，该进程也会执行 `App.onCreate()`。
  所以**注册 ContentObserver 这类监听前必须判断主进程**（见 `App.isMainProcess()`），
  否则同一事件会被上报两次。

## 数据库版本

`AppDatabase` 当前 `version = 23`。改动表结构时记得同时加迁移。
