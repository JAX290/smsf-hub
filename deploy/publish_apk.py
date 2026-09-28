# -*- coding: utf-8 -*-
"""一键发布 APK 到 VPS 的下载地址。

用法（在本地 Windows 上执行）：
    set SMSF_PASS=<VPS密码>
    python deploy/publish_apk.py            # 只上传
    python deploy/publish_apk.py --build    # 先编译再上传

做的事：
    1. （可选）跑 gradle 编译
    2. 从 build/app/outputs/apk/debug 找最新的 arm64 / v7a / universal 三个包
    3. 传到 VPS 的下载目录
    4. 校验：远端文件大小、下载地址 HTTP 状态、下载连接是否真的通
    5. 更新本地 .apk_hashes.json（.gitignore 已排除）

⚠️ 常见误解：
    「部署服务端」和「更新 APK」是两件独立的事。
    换 VPS 时只跑 install.sh，下载地址给到的还是旧版本 —— 必须再跑一次本脚本。
"""
import os
import sys
import json
import hashlib
import subprocess
from pathlib import Path

try:
    import paramiko
except ImportError:
    print("需要 paramiko：  pip install paramiko")
    sys.exit(1)

HOST = "100.118.119.84"
USER = "root"
DL_DIR = "/var/www/smsf-dl-e49cadd1bfb0d24ee8"
APK_SRC = Path(r"C:\AndroidDev\SmsForwarder\build\app\outputs\apk\debug")
HASH_FILE = Path(__file__).resolve().parent.parent / ".apk_hashes.json"

# 架构关键字 -> 远端文件名
TARGETS = [
    ("arm64-v8a", "smsf-arm64.apk"),
    ("armeabi-v7a", "smsf-v7a.apk"),
    ("universal", "smsf-universal.apk"),
]


def build():
    """跑一次 gradle。用和平时一样的参数。"""
    print("== 编译 ==")
    bat = APK_SRC.parents[4] / "gradlew.bat"
    env = dict(os.environ)
    env["JAVA_HOME"] = r"C:\AndroidDev\jdk17\jdk-17.0.20.1+1"
    env["ANDROID_SDK_ROOT"] = r"C:\AndroidDev\sdk"
    env["GRADLE_USER_HOME"] = r"C:\AndroidDev\gradle-home"
    env["PATH"] = env["JAVA_HOME"] + r"\bin;" + env.get("PATH", "")
    r = subprocess.run([str(bat), "assembleDebug", "--console=plain"], cwd=str(bat.parent), env=env)
    if r.returncode != 0:
        print("编译失败，终止")
        sys.exit(1)


def pick_latest(pattern: str):
    """在产物目录里找匹配的最新 apk（按修改时间）。"""
    cands = [p for p in APK_SRC.glob("*.apk") if pattern in p.name]
    if not cands:
        return None
    return max(cands, key=lambda p: p.stat().st_mtime)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    if "--build" in sys.argv:
        build()

    pw = os.environ.get("SMSF_PASS", "")
    if not pw:
        print("请先设置环境变量 SMSF_PASS")
        sys.exit(1)

    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(HOST, username=USER, password=pw, timeout=30)
    sftp = cli.open_sftp()

    hashes = {}
    failed = []

    print("== 上传 ==")
    for key, remote_name in TARGETS:
        src = pick_latest(key)
        if not src:
            print("  !! 没找到 %s 的包" % key)
            failed.append(key)
            continue
        size = src.stat().st_size
        print("  %-24s -> %s  (%.1f MB)" % (src.name, remote_name, size / 1024 / 1024))
        sftp.put(str(src), DL_DIR + "/" + remote_name)
        remote_size = sftp.stat(DL_DIR + "/" + remote_name).st_size
        if remote_size != size:
            print("     !! 远端大小不符：%d != %d" % (remote_size, size))
            failed.append(key)
        hashes[key] = {"file": src.name, "sha256": sha256(src), "size": size}

    print()
    print("== 校验下载地址 ==")
    def run(cmd):
        _, out, err = cli.exec_command(cmd)
        return (out.read() + err.read()).decode("utf-8", "replace")

    for path in ("/apk1", "/apk2", "/apk3"):
        r = run("curl -s -o /dev/null -w '%%{http_code} %%{size_download}' "
                "--max-time 20 --resolve notic.mulinsen.win:443:127.0.0.1 "
                "-r 0-65535 https://notic.mulinsen.win" + path)
        print("  %-6s -> %s" % (path, r.strip()))

    print()
    print("== 下载闸门 ==")
    print("  " + run("cat /opt/smsf-hub/app/data/apk_gate.json").strip().replace("\n", " "))

    sftp.close()
    cli.close()

    if hashes:
        HASH_FILE.write_text(json.dumps(hashes, ensure_ascii=False, indent=2), encoding="utf-8")
        print()
        print("已更新 .apk_hashes.json")

    if failed:
        print()
        print("!! 以下架构处理失败，请检查：%s" % ", ".join(failed))
        sys.exit(1)

    print()
    print("完成。如果闸门是关闭状态，记得在面板首页开一下下载授权。")


if __name__ == "__main__":
    main()
