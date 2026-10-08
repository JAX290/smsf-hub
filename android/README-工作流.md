# 收音机项目 —— 本工作区的用法（给未来的会话看）

工作区：`C:\Users\小米\Documents\deepseek-harness\radio`

## 为什么这么摆

真正的构建目录在 `C:\AndroidDev\SmsForwarder`（**必须是 ASCII 路径**，
构建工具拒绝中文路径——见交接文档第五章铁律）。
而 DSH 的文件沙箱只允许写工作区，工作区路径又含中文「小米」，
**所以「工作区里编译」这条路走不通**，只能用「镜像 + 一键同步编译」。

## 目录

| 路径 | 内容 |
|---|---|
| `src\SmsForwarder\` | 手机端源码镜像（排除 build/.gradle/.git，约 60MB）|
| `src\smsf-hub\` | 服务端源码镜像（排除 .git，约 38MB）|
| `dist\` | 本地产出的 APK 归档 |
| `sync_build.bat` | **镜像 → C:\AndroidDev → 编译**（需要一次提权）|
| `sync_from_source.bat` | 反向：`C:\AndroidDev` → 镜像（对齐用）|
| `redmi\` `ab\` `*.txt` | 排查过程中的原始数据（batterystats / exit-info / UI dump 等）|

## 改代码的标准流程

1. **在工作区镜像里改**（`src\SmsForwarder\...`）——这一步不需要任何授权。
2. 需要编译时，跑一条提权命令：
   ```
   cmd /c C:\Users\小米\Documents\deepseek-harness\radio\sync_build.bat
   ```
   它会先把镜像同步回 `C:\AndroidDev\SmsForwarder`，再 `assembleDebug`，
   日志写到 `C:\AndroidDev\build_last.log`。
3. 产物在 `C:\AndroidDev\SmsForwarder\build\app\outputs\apk\debug\`，
   命名 `SmsF_<版本名>_<versionCode>_<abi>_debug.apk`。
   arm64 的 versionCode = 300000 + `versions.gradle` 里的 `version_code`。
4. 顺手把 arm64 包复制一份到 `dist\` 归档。

## 注意

- **两边会漂移**：如果直接改了 `C:\AndroidDev`，先跑 `sync_from_source.bat`
  把镜像对齐，否则下次 `sync_build.bat` 会用旧代码覆盖回去。
- 构建前要清 `C:\AndroidDev\SmsForwarder\build\app\intermediates\merged-not-compiled-resources`
  并结束 java 进程（交接文档第五章）。
- 服务端（`smsf-hub`）改完后要**部署到 VPS**（`python deploy\remote.py` /
  `deploy\_upload_ts.py`），镜像本身不参与部署。
  - 本项目专用的部署脚本：`push_priority.py`（备份 `/opt/smsf-hub/_bak/` →
    SFTP 上传 → 服务器端 `py_compile` 自检 → 重启 → 面板页面自检）。
    改服务端代码后跑它即可：
    ```
    $env:SMSF_PASS="..."; $env:SMSF_HOST="100.118.119.84"
    py -3 push_priority.py
    ```
  - 排查用的服务器脚本都是 `q*.sh`，用
    `cmd /c "py -3 C:\smsf-hub\deploy\remote.py --stdin ""bash -s"" < qN.sh"` 执行。
    **脚本结尾记得 `exit 0`** —— 否则最后一条判断为假会让整体返回非零，
    被当成"运行失败"（踩过一次）。

## 已部署的服务端功能（2026-10-07/08）

| 功能 | 位置 |
|---|---|
| **手机端「攒一波再发」的接收与拆分** | `app/pipeline.py` 的 `parse_digest()` / `DIGEST_RE`；窗口配置在 `app/config.py` 的 `digest:` 段，面板「参数设置 → 手机攒批发送」可改 |
| 消息分级 T0–T4（降噪核心）| `app/classify.py`；规则在 `config.yaml` 的 `priority:` 段，面板「参数设置 → 消息分级」可改 |
| 分析监控（每日摘要/关键词监控/异常检测）| `app/analysis.py` + `/panel/analysis`；参数在 `config.yaml` 的 `analysis:` 段 |
| 面板「只看重要」过滤 + 级别色标 + 折叠计数 | `app/templates/messages.html` |
| **归档全文搜索**（不受消息流窗口限制）| `/panel/search` + `app/templates/search.html` |
| 噪音归档只留一行摘要 | `app/archive.py` 的 `append()` |
| 消息流窗口 500 → 8000（文件 20 万条）| `config.yaml` 的 `panel.recent_keep` / `panel.recent_file_keep` |
| 推送门槛（低于 T3 只归档不推送）| `app/channels/base.py` 的 `_match_tier()`；终端规则可加 `min_tier` 覆盖 |
| 归档永不自动删除 + 磁盘不足提示下载 | `app/archive.py` 的 `stats()`（`warn_free_gb`，默认 2GB）|

### 手机端「攒一波再发」是怎么工作的（v55）

```
手机 NotificationService
   ├─ 短信/来电/已发送/定位 ──────────────→ 各自的通道，立即发
   ├─ 命中「立即关键词」(验证码/扣款…) ──→ 立即发
   └─ 其余通知 → Digest 表（带 dueAt）
                     ↓ 到点
        DigestWorker 合并成一个 POST（content 形如 DIG|N + N 行 JSON）
                     ↓ 走 SendWorker（复用离线队列的重试能力）
        服务端 parse_digest() 拆回 N 条 → 各自去重/分级/归档
```

- **窗口值由服务端通过心跳响应下发**（`pipeline.digest_config`），
  手机端 `HeartbeatWorker.applyDigestConfig()` 收到即写入本地设置 ——
  所以**面板上改完就生效，不用重新编译 APK**
- 默认：短信/来电/定位/验证码 → 立即；其余通知 → 15 分钟；系统状态类 → 24 小时
- 实测收益：一天 715 条消息（=715 次射频唤醒）→ 约 120 次

## 手机端版本（v52 – v58）

| 版本 | 内容 |
|---|---|
| v52 | App 名 → `Radio`、收音机图标（`make_icon.py` / `make_glyph.py`）、默认不再播放无声音乐 |
| v53 | 正文末尾追加通知属性行 `NAT\|cat=..\|ong=..\|imp=..\|grp=..`；跳过系统应用发的纯状态通知 |
| v54 | 修 `imp=`（渠道重要度）上报不上：`NotificationManager` 只能看本应用的渠道，必须改用 `NotificationListenerService.getNotificationChannels(pkg, UserHandle)`（注意是**复数**且要 `UserHandle`）|
| v55 | **攒批发送**：新增 `Digest` 表（数据库 25→26）+ `DigestWorker`；心跳响应接收服务端下发的窗口配置 |
| v56 | 修「攒批没合并」：新消息复用同一批的 `dueAt`，否则相差几秒的消息会各自成批（实测 3 条被拆成 3 个请求）|
| v57 | 修类型别名：手机端内部叫 `app`、服务端叫 `notify`，不转会落到默认的 `sms`（每条通知都被当成短信）|
| v58 | **修积压队列**（见下方「僵尸记录」）；`MAX_PER_RUN` 200→500；心跳上报电池优化白名单状态；App 绿勾纳入电池优化白名单 |
| v59 | **按内容拦掉 MIUI「XX 正在后台运行」提示**（见下方第 4 条坑）——实测它占某台手机全部消息的 23% |
| v60 | 修 v59 的过滤没生效（读错了通知字段）+ **修摘要 worker 被「取消重排」饿死**（见下方第 6 条坑）|

## ⚠️ 六个必须记住的坑

### 1. nginx 限流会把上报打成 503（2026-10-08 抓出来的元凶）

```
/etc/nginx/conf.d/smsf-hook-ratelimit.conf:
    limit_req_zone $binary_remote_addr zone=smsf_hook:10m rate=5r/s;   # 原来是 5r/s
/etc/nginx/sites-available/stratum-public-status:
    limit_req zone=smsf_hook burst=10 nodelay;    # 原来是 10 / 20
    limit_req zone=smsf_hook burst=20 nodelay;
```

手机上报一快（积压补发、验证码连发）就被拒，手机端日志是
`ApiException: Service Temporarily Unavailable`，服务端 nginx 错误日志是
`limiting requests, excess: ... by zone "smsf_hook"`。

**而且所有手机的 `client` 都是 `127.0.0.1`（前面有中转），三台手机共用同一个
每秒 5 次的桶，会互相挤。** 2026-10-08 已改成 `rate=50r/s` + `burst=200`
（备份 `*.bak-20261008-145111`）。改完连发 120 个请求，503 = 0。

排查口诀：**手机上报延迟高 → 先看手机日志里的响应码，再看
`/var/log/nginx/smsf-notic.error.log` 有没有 `limiting requests`。**

### 2. 「僵尸记录」：`forward_status = 1` 的消息永远发不出去

`Logs` 表的 `forward_status` **默认值是 1**（不是 0）。新建一行是 1，
只有回调把它改成 2（成功）或 0（待重试）。所以任何「插入了行、但请求没跑完」
的情况（进程被杀、请求挂死、WorkManager 没调度、配对回调没回来）
都会留下一条**永远停在 1** 的记录 —— 而旧的重试查询只捞 `forward_status = 0`，
这些消息就永久丢了。

实测小米14：卡住的 3440 条横跨 8 天、`retry_count` 全是 0；
最近 3 小时成功 79 条、卡住 1917 条（它每小时产生约 640 条通知，只发得出 26 条）。

**v58 的修法**：`getPendingRetry` 改成
`forward_status = 0 OR (forward_status = 1 AND time < now - 10 分钟)`，
把「发起后长时间没回音」的当成待发重试（10 分钟余量是为了不误伤真正在传输中的请求）。

### 4. MIUI「XX 正在后台运行」提示：一条通知占 23% 的消息量

```
点按即可了解详情或停止应用。     9428 次（占该手机全部消息的 23%）
睡眠服务后台运行中              3237 次（8%）
```

这两条是 MIUI 的后台提示，**9229 条是用 `com.android.mms`（短信 App）的系统 uid
发出来的，既不是常驻、也没有通知类别** —— 所以 v53 那套「按属性判系统状态通知」
完全拦不住它们。它们把上报管道占满，是「僵尸记录」积压的重要推手。

**v59 的修法**：`isSystemStatusNoise()` 里先按**内容**拦一道
（`点按即可了解详情或停止应用` / `正在后台运行` / `后台运行中`），
见到就直接丢，比按属性判定可靠得多。

### 5. 拉手机数据库必须连 WAL 一起拉
Room 开了 WAL，`adb exec-out run-as ... cat databases/sms_forwarder.db`
拿到的是**没回写主库的旧数据**（表现为"队列明明是空的、Msg 数不动"）。
正确做法：把 `sms_forwarder.db`、`sms_forwarder.db-wal`、`sms_forwarder.db-shm`
三个文件拉到**同一个目录**再用 sqlite 打开。

### 6. 摘要 worker 会被「取消重排」饿死

`DigestWorker` 每来一条通知都会调用 `scheduleAtNextDue()`。如果里面无条件
`enqueueUniqueWork(..., REPLACE, ...)`，新通知就会把**已经排好、马上就要跑**的任务
取消再重排 —— 通知一多就一直在取消重排，worker 永远轮不到执行。
实测小米14：摘要队列堆到 20 条、最早一条过期 30 分钟，一条都没发出去。

**v60 的修法**：记住「当前排着的到期时刻」，**只在新的到期时间更早时才重排**：
- 同一批里的后续消息 → 到期时间相同 → 什么都不做（这正是攒批要的）
- 新来的短窗消息遇上已排的日摘要 → 15 分钟 < 24 小时 → 重排到更早

（踩坑顺序值得记：v59 先改成 `KEEP` 想避开这个问题，但那会让「24 小时那档已排」
挡住「15 分钟那档」；最后才是上面这个「更早才重排」的正解。）

### 附：MIUI 其实能看这个 App 的日志

```
adb -s <serial> shell "logcat -b all -d | grep -iE 'NotificationService|DigestWorker|OfflineRetryWorker|XHttp'"
```
交接文档里"MIUI 看不到日志"是误判 —— 排查先抓日志，比猜快得多。
（`XHttp` 那几行会直接打印请求/响应和响应码，判断 503/401 一目了然。）

**验证 NAT 的快捷办法**（手机连着时）：
```
adb -s <serial> shell "cmd notification post -t '验证码测试' dsh_test '您的验证码是 867530'"
```
几秒后服务端消息流里应出现一条 `tier=4`、正文含 `NAT|...` 的记录。

**验证攒批**：普通通知发出后日志出现
`NotificationService: 已存入摘要队列，15 分钟后合并发送`，
到点后服务端日志出现 `收到摘要包：设备=... 共 N 条`。

## ⚠️ 排查时踩过的两个坑

1. **拉手机数据库必须连 WAL 一起拉**。Room 开了 WAL，
   `adb exec-out run-as ... cat databases/sms_forwarder.db` 拿到的是**没回写主库的旧数据**
   （表现为"队列明明是空的、Msg 数不动"，害我白查一轮）。
   正确做法：把 `sms_forwarder.db`、`sms_forwarder.db-wal`、`sms_forwarder.db-shm`
   三个文件拉到**同一个目录**再用 sqlite 打开。
2. **MIUI 其实能看这个 App 的日志**：
   `adb -s <serial> shell "logcat -b all -d | grep -iE 'NotificationService|DigestWorker'"`。
   交接文档里"MIUI 看不到日志"是误判 —— 排查先抓日志，比猜快得多。

## 设备

| 设备 | adb serial | 说明 |
|---|---|---|
| nova6 (Huawei WLZ-AN00 / Android 12) | `ADFDU19C16036475` | |
| 红米 K20 Pro (MIUI 12.5 / Android 11) | `b8c84a6b` | |

`adb -s <serial>` 指定机型；**装包前必须 `adb devices -l` 确认是哪台**。
