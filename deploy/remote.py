"""极简 SSH 执行器（本地工具，不部署到服务器）。

用法：
    python deploy/remote.py "id"                  单条命令
    python deploy/remote.py --stdin "bash -s" < script.sh   脚本经 stdin 送过去
"""
import os
import sys

import paramiko

# 强制 UTF-8 输出，避免 Windows GBK 代码页报 UnicodeEncodeError
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HOST = os.environ.get("SMSF_HOST", "114.134.186.200")
PORT = int(os.environ.get("SMSF_PORT", "22"))
USER = os.environ.get("SMSF_USER", "root")
PASS = os.environ.get("SMSF_PASS", "")


def main() -> int:
    args = sys.argv[1:]
    send_stdin = False
    if args and args[0] == "--stdin":
        send_stdin = True
        args = args[1:]
    cmd = args[0] if args else sys.stdin.buffer.read().decode("utf-8", "replace")
    if not cmd.strip():
        print("没有可执行的命令", file=sys.stderr)
        return 2

    payload = sys.stdin.buffer.read() if send_stdin else None

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(HOST, port=PORT, username=USER, password=PASS,
                       timeout=25, banner_timeout=25, auth_timeout=25,
                       look_for_keys=False, allow_agent=False)
    except paramiko.AuthenticationException:
        print(f"AUTH_FAILED user={USER}@{HOST}:{PORT}  (用户名或密码不对)", file=sys.stderr)
        return 3
    except Exception as exc:
        print(f"CONNECT_FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
        return 4

    chan = client.get_transport().open_session()
    chan.settimeout(600)
    chan.exec_command(cmd)
    if payload:
        chan.sendall(payload)
    chan.shutdown_write()

    out = b""
    err = b""
    while True:
        if chan.recv_ready():
            out += chan.recv(65536)
        if chan.recv_stderr_ready():
            err += chan.recv_stderr(65536)
        if chan.exit_status_ready() and not chan.recv_ready() and not chan.recv_stderr_ready():
            break
    code = chan.recv_exit_status()
    sys.stdout.write(out.decode("utf-8", errors="replace"))
    if err.strip():
        sys.stderr.write(err.decode("utf-8", errors="replace"))
    client.close()
    print(f"[remote exit code = {code}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
