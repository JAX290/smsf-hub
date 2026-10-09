#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把最新编译出来的 APK 发布到下载地址。

下载地址（nginx 里用随机路径做保护，闸门开着才能下载）：
    https://notic.mulinsen.win/apk1   -> smsf-arm64.apk      （arm64，小米14/红米用这个）
    https://notic.mulinsen.win/apk2   -> smsf-universal.apk  （通用）
    https://notic.mulinsen.win/apk3   -> smsf-v7a.apk        （32 位）

为什么要专门写这个脚本（而不是手工 scp）：
    · 下载目录是随机的（/var/www/smsf-dl-<随机串>），路径从服务器配置里读，不写死
    · 上传前先备份旧的三个包，出问题能立刻回滚
    · 上传后按 md5 逐个核对，确认服务器上那份和本地编译出来的**完全一致**
      （之前踩过：文件推上去了但没生效，谁也发现不了）

用法：
    $env:SMSF_PASS="..."; $env:SMSF_HOST="<服务器>"
    py -3 publish_apk.py            # 自动找 build 目录里最新的一批
    py -3 publish_apk.py --dir <包含三个 apk 的目录>
"""
import hashlib
import os
import sys
from datetime import datetime
from pathlib import Path

# Windows 控制台默认是 GBK，打印 ✅ 之类的字符会直接抛 UnicodeEncodeError
# （发布脚本因此在校验那步崩过，上传其实已经成功了）—— 这里强制 UTF-8 输出。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

try:
    import paramiko
except ImportError:
    print("缺少 paramiko：py -3 -m pip install paramiko")
    sys.exit(1)

HOST = os.environ.get("SMSF_HOST", "")          # 必填：从环境变量给（别把地址写进仓库）
PORT = int(os.environ.get("SMSF_PORT", "22"))
USER = os.environ.get("SMSF_USER", "root")
PASS = os.environ.get("SMSF_PASS", "")

# 本地编译产物目录
BUILD_DIR = Path(r"C:\AndroidDev\SmsForwarder\build\app\outputs\apk\debug")

# 目标文件名（nginx 里写死的，不能改）
TARGETS = [
    ("arm64-v8a", "smsf-arm64.apk"),
    ("armeabi-v7a", "smsf-v7a.apk"),
    ("universal", "smsf-universal.apk"),
]


def md5_of(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def find_latest(dir_path: Path) -> dict:
    """在目录里按 ABI 找最新的一批 apk（文件名形如 Radio_v67_..._300088_arm64-v8a_debug.apk）"""
    out = {}
    for abi, _ in TARGETS:
        cands = sorted(dir_path.glob(f"Radio_*_{abi}_*.apk"), key=lambda p: p.stat().st_mtime)
        if cands:
            out[abi] = cands[-1]
    return out


def main() -> int:
    if not PASS:
        print("请先设置环境变量 SMSF_PASS")
        return 1

    # 1) 找出要发布的文件
    args = sys.argv[1:]
    src_dir = Path(args[args.index("--dir") + 1]) if "--dir" in args else BUILD_DIR
    if not src_dir.is_dir():
        print(f"找不到目录：{src_dir}")
        return 1
    picks = find_latest(src_dir)
    missing = [abi for abi, _ in TARGETS if abi not in picks]
    if missing:
        print(f"❌ 缺少这些 ABI 的包：{missing}（先跑 sync_build.bat）")
        return 1

    print("=== 1) 本次要发布的包 ===")
    for abi, name in TARGETS:
        p = picks[abi]
        print(f"  {name:<22} <- {p.name}  ({p.stat().st_size/1024/1024:.1f} MB, {md5_of(p)[:12]})")

    # 2) 连服务器，读出下载目录
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(HOST, port=PORT, username=USER, password=PASS,
                timeout=25, banner_timeout=25, auth_timeout=25,
                look_for_keys=False, allow_agent=False)

    def run(cmd: str) -> str:
        _in, out, err = cli.exec_command(cmd, timeout=120)
        o = out.read().decode("utf-8", "replace")
        e = err.read().decode("utf-8", "replace")
        return (o + e).strip()

    dl_dir = run("grep -oP '(?<=apk_download_dir: ).*' /opt/smsf-hub/config.yaml | head -1").strip()
    if not dl_dir or not dl_dir.startswith("/"):
        print(f"❌ 读不到 apk_download_dir（拿到的是 {dl_dir!r}）")
        return 1
    print(f"\n=== 2) 下载目录：{dl_dir} ===")
    print("  现有文件：")
    print("   " + run(f"ls -la --time-style=long-iso {dl_dir}/*.apk 2>/dev/null | awk '{{print $5, $6, $7, $8}}'").replace("\n", "\n   "))

    # 3) 备份
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = f"{dl_dir}/_bak-{ts}"
    print(f"\n=== 3) 备份到 {bak} ===")
    print("  " + run(f"mkdir -p {bak} && cp -a {dl_dir}/*.apk {bak}/ 2>/dev/null; ls {bak} | tr '\\n' ' '"))

    # 4) 上传
    print("\n=== 4) 上传 ===")
    sftp = cli.open_sftp()
    for abi, name in TARGETS:
        local = picks[abi]
        remote = f"{dl_dir}/{name}"
        sftp.put(str(local), remote)
        run(f"chmod 644 {remote}")
        print(f"  {name} 上传完成")

    # 5) 核对 md5
    print("\n=== 5) 逐个核对 md5（本地 vs 服务器）===")
    all_ok = True
    for abi, name in TARGETS:
        local_md5 = md5_of(picks[abi])
        remote_md5 = run(f"md5sum {dl_dir}/{name} | awk '{{print $1}}'").strip()
        ok = local_md5 == remote_md5
        all_ok = all_ok and ok
        print(f"  {name:<22} {'✅ 一致' if ok else '❌ 不一致'}  {remote_md5[:12]}")

    # 6) 收尾信息
    print("\n=== 6) 服务器上的最终状态 ===")
    print("  " + run(f"ls -la --time-style=long-iso {dl_dir}/*.apk | awk '{{print $5, $6, $7, $8}}'").replace("\n", "\n  "))
    gate = run("cat /opt/smsf-hub/app/data/apk_gate.json 2>/dev/null")
    print("\n=== 7) 下载闸门状态 ===")
    print("  " + gate.replace("\n", "\n  ") if gate else "  （没有闸门文件）")

    sftp.close()
    cli.close()

    print("\n=== 8) 下载地址（闸门开着才能下）===")
    print("  arm64（小米14 / 红米）：https://notic.mulinsen.win/apk1")
    print("  通用                 ：https://notic.mulinsen.win/apk2")
    print("  32 位                ：https://notic.mulinsen.win/apk3")
    print("\n" + ("✅ 发布成功" if all_ok else "❌ 有一致性校验没通过，请复查"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
