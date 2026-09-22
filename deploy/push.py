"""把本地项目同步到服务器（本地工具，不部署到服务器）。"""
import os
import posixpath
import stat
import sys
from pathlib import Path

import paramiko

LOCAL = Path(os.environ.get("SMSF_LOCAL", r"C:\smsf-hub"))
REMOTE = os.environ.get("SMSF_REMOTE", "/opt/smsf-hub")
HOST = os.environ.get("SMSF_HOST", "114.134.186.200")
PORT = int(os.environ.get("SMSF_PORT", "22"))
USER = os.environ.get("SMSF_USER", "root")
PASS = os.environ.get("SMSF_PASS", "")

SKIP_DIRS = {".venv", "venv", "__pycache__", ".git", "data", ".idea", ".pytest_cache"}
SKIP_FILES = {"_pip.log"}
SKIP_SUFFIX = (".pyc", ".log.bak")


def ensure_dir(sftp, path: str) -> None:
    parts = path.strip("/").split("/")
    cur = ""
    for p in parts:
        cur += "/" + p
        try:
            sftp.stat(cur)
        except IOError:
            sftp.mkdir(cur)


def main() -> int:
    if not PASS:
        print("缺少 SMSF_PASS", file=sys.stderr)
        return 2
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(HOST, port=PORT, username=USER, password=PASS, timeout=25,
                look_for_keys=False, allow_agent=False)
    sftp = cli.open_sftp()

    ensure_dir(sftp, REMOTE)
    uploaded = 0
    for dirpath, dirnames, filenames in os.walk(LOCAL):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        rel = os.path.relpath(dirpath, LOCAL).replace("\\", "/")
        if rel == ".":
            rel = ""
        remote_dir = posixpath.join(REMOTE, rel) if rel else REMOTE
        ensure_dir(sftp, remote_dir)
        for fn in filenames:
            if fn in SKIP_FILES or fn.endswith(SKIP_SUFFIX):
                continue
            if fn.startswith("_") and fn.endswith(".log"):
                continue
            local_file = os.path.join(dirpath, fn)
            remote_file = posixpath.join(remote_dir, fn)
            try:
                sftp.put(local_file, remote_file)
                uploaded += 1
            except Exception as exc:
                print(f"  失败 {fn}: {exc}", file=sys.stderr)
    sftp.close()
    cli.close()
    print(f"已上传 {uploaded} 个文件 -> {REMOTE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
