#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把导出的任务包发布到 YYJio 任务库。

做的事：拷进仓库的 packages/ → 重建 index.json → git commit → git push。
用法：
    python tools/publish_task.py "D:\\Downloads\\yyjio.8888-1.0.0.yyjio-task"
    python tools/publish_task.py xxx.yyjio-task --repo E:\\YYJio-Tasks
    python tools/publish_task.py xxx.yyjio-task --no-push   # 只提交不推送
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from urllib.parse import quote

REPO_URL = "https://github.com/TesBot/YYJio-Tasks.git"
DEFAULT_REPO = Path(os.environ.get("YYJIO_TASKS_REPO") or r"E:\YYJio-Tasks")
SUFFIX = ".yyjio-task"


def die(msg: str) -> "None":
    print(f"[失败] {msg}", flush=True)
    sys.exit(1)


def step(msg: str) -> None:
    print(f"→ {msg}", flush=True)


def _text(raw) -> str:
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        # 控制台编码不一定是 utf-8（中文 Windows 是 936），解码失败也不要崩
        for enc in ("utf-8", "gbk"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", "replace")
    return str(raw)


def run(cmd: list[str], cwd: Path, *, quiet: bool = False) -> subprocess.CompletedProcess:
    """quiet=True 时拿 bytes 回来，自己按 utf-8/gbk 解码，避免子进程中文触发解码异常。"""
    try:
        return subprocess.run(cmd, cwd=str(cwd), check=True,
                              capture_output=quiet, text=not quiet)
    except FileNotFoundError:
        die(f"找不到命令 {cmd[0]}，请先安装 Git 并确保它在 PATH 里")
    except subprocess.CalledProcessError as exc:
        die(f"{' '.join(cmd)} 出错：\n{_text(exc.stdout) + _text(exc.stderr)}".strip())


def read_manifest(path: Path) -> dict:
    try:
        with zipfile.ZipFile(path) as zf:
            raw = zf.read("task.json")
    except zipfile.BadZipFile:
        die("这不是有效的任务包（应为 .yyjio-task，zip 格式）")
    except KeyError:
        die("包里没有 task.json，可能不是 YYJio 导出的文件")
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        die(f"task.json 不是合法 JSON：{exc}")
    if data.get("format") != "yyjio-task":
        die("包的 format 不是 yyjio-task，可能不是 YYJio 导出的文件")
    for key in ("id", "name", "author", "version"):
        if not str(data.get(key) or "").strip():
            die(f"包里缺少字段 {key}，请回到 YYJio 重新导出")
    return data


def _mask(url: str) -> str:
    return re.sub(r"//[^@/]+@", "//***@", url)


def _git_config(repo: Path, key: str) -> str:
    try:
        out = subprocess.run(["git", "config", "--get", key], cwd=str(repo),
                             capture_output=True, text=True, timeout=20)
        return (out.stdout or "").strip()
    except Exception:
        return ""


def _sync_remote(repo: Path) -> None:
    """先把远端引用拉新，否则 origin/main 可能是几小时前的，ahead 数会算错。

    拉取失败不影响后面 push（push 会自己连一次）。
    """
    try:
        subprocess.run(["git", "-c", "http.version=HTTP/1.1", "fetch", "-q", "origin"],
                       cwd=str(repo), capture_output=True, text=True, timeout=60,
                       stdin=subprocess.DEVNULL, env=_no_prompt_env())
    except Exception:
        pass


def _ahead_count(repo: Path) -> int:
    """本地比远端多几个提交；没有 upstream 时按 0 处理（后面 push 会显式推 HEAD）。"""
    try:
        res = subprocess.run(["git", "rev-list", "--count", "@{u}..HEAD"], cwd=str(repo),
                             capture_output=True, text=True, timeout=15, env=_no_prompt_env())
        if res.returncode != 0:
            return 0
        return int((res.stdout or "0").strip() or 0)
    except Exception:
        return 0


def _git_origin(repo: Path) -> str:
    try:
        res = subprocess.run(["git", "remote", "get-url", "origin"], cwd=str(repo),
                             capture_output=True, text=True, timeout=10,
                             env=_no_prompt_env())
        return (res.stdout or "").strip()
    except Exception:
        return ""


def _authed_url(user: str, token: str, repo: Path | None = None) -> str:
    """带上令牌的推送地址：必须用仓库自己的 origin，不能写死成官方仓库。"""
    origin = _git_origin(repo) if repo is not None else ""
    rest = (origin or REPO_URL).split("https://", 1)[-1]
    rest = rest.replace("git@github.com:", "github.com/")
    return f"https://{quote(user, safe='')}:{quote(token, safe='')}@{rest}"


def _remember(user: str, token: str) -> None:
    """把能用的令牌交给凭据管理器存起来，下次普通 git push 就不用再输。"""
    try:
        subprocess.run(["git", "credential", "approve"],
                       input=f"protocol=https\nhost=github.com\nusername={user}\npassword={token}\n\n",
                       capture_output=True, text=True, timeout=30)
    except Exception:
        pass


def _stored_credential() -> tuple[str, str]:
    """从凭据管理器里找已保存的 GitHub 令牌。

    Windows 上真正存着密码的是 wincred；只写 `git credential fill` 会因为默认
    helper 是 manager（GCM）而在无交互环境下失败，所以逐个 helper 试一遍。
    """
    payload = "protocol=https\nhost=github.com\n\n"
    for helper in ("wincred", "manager", ""):
        cmd = ["git"]
        if helper:
            cmd += ["-c", f"credential.helper={helper}"]
        cmd += ["credential", "fill"]
        try:
            res = subprocess.run(cmd, input=payload, capture_output=True, text=True,
                                 timeout=15, env=_no_prompt_env())
        except Exception:
            continue
        user = token = ""
        for line in (res.stdout or "").splitlines():
            if line.startswith("username="):
                user = line.split("=", 1)[1].strip()
            elif line.startswith("password="):
                token = line.split("=", 1)[1].strip()
        if user and token:
            return user, token
    return "", ""


def _token_file() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return base / "YYJio" / "github_token.txt"


def _saved_token() -> str:
    """读上次保存的令牌；没有就返回空串。"""
    try:
        return _token_file().read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _save_token(token: str) -> None:
    """把令牌记到本地文件，下次不用再粘（只有本人可读）。"""
    try:
        path = _token_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token.strip() + "\n", encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
    except Exception:
        pass


def _no_prompt_env() -> dict:
    """所有 git 调用都不许弹交互：批处理里一等待就卡死。"""
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}


def _push_with(repo: Path, url: str, env: dict) -> bool:
    """推送：带 HTTP/1.1 与重试。

    国内网络下 git 默认的 HTTP/2 推送经常被重置 / 卡在 connect，
    固定 HTTP/1.1 并重试 3 次能明显提高成功率。
    """
    cmd = ["git", "-c", "http.version=HTTP/1.1", "-c", "http.postBuffer=1048576",
           "-c", "http.lowSpeedLimit=500", "-c", "http.lowSpeedTime=60",
           "push", url, "HEAD"]
    last_err = ""
    for attempt in range(1, 4):
        try:
            res = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True,
                                 timeout=300, stdin=subprocess.DEVNULL, env=_no_prompt_env())
        except Exception as exc:  # 超时等
            last_err = str(exc)
            res = None
        if res is not None and res.returncode == 0:
            out = _text(res.stdout or "").strip()
            if out:
                print("      " + out.splitlines()[-1][:200], flush=True)
            return True
        if res is not None:
            err = _text(res.stderr or res.stdout or "").strip()
            lines = [ln.strip() for ln in err.splitlines() if ln.strip()]
            last_err = next((ln for ln in lines if not ln.startswith(("hint:", "To ", "branch"))),
                            lines[-1] if lines else "")
        if attempt < 3:
            print(f"      第 {attempt} 次推送失败，{attempt * 3} 秒后重试…", flush=True)
            time.sleep(attempt * 3)
    if last_err:
        print("      " + last_err[:220], flush=True)
    return False


def _prompt_token() -> str:
    if not sys.stdin or not sys.stdin.isatty():
        return ""
    print("\n  需要一次 GitHub 令牌（账号密码 + 2FA 推不上去）。", flush=True)
    print("  没有的话：https://github.com/settings/tokens → Generate new token (classic) → 只勾 repo", flush=True)
    try:
        return getpass.getpass("  粘贴令牌后回车（直接回车跳过）：").strip()
    except Exception:
        return ""


def push(repo: Path, token_arg: str) -> bool:
    """推送到 GitHub：优先用凭据管理器，其次用令牌（账号密码 + 2FA 走不通）。"""
    env = {**os.environ}
    token = (token_arg or os.environ.get("YYJIO_GITHUB_TOKEN")
             or os.environ.get("GITHUB_TOKEN") or _saved_token() or "").strip()
    print(f"      凭据管理器：{_git_config(repo, 'credential.helper') or '（未配置）'}", flush=True)

    if not token:
        # 凭据管理器里有能用的令牌就直接用（Windows 凭据 / GCM 都存在这里）
        user, saved = _stored_credential()
        if user and saved:
            print("      用已保存的凭据推送", flush=True)
            if _push_with(repo, _authed_url(user, saved, repo), env):
                return True

    if not token:
        token = _prompt_token()
    while token and token.strip():
        token = token.strip()
        print(f"      用令牌推送：{_mask(_authed_url('x-access-token', token, repo))}", flush=True)
        if _push_with(repo, _authed_url("x-access-token", token, repo), env):
            # 不写回凭据管理器（GCM 一弹窗就会卡住批处理），改成存到自己的令牌文件
            if token != _saved_token():
                _save_token(token)
                print(f"      令牌已记住：{_token_file()}", flush=True)
            return True
        token = _prompt_token()

    print("\n[提示] 没有推上去，包已经提交在本地，随时可以重试：", flush=True)
    print("      发布任务包.bat 再跑一次；或 --token 直接带令牌", flush=True)
    print("      python tools/publish_task.py 包路径 --token ghp_xxx", flush=True)
    print("      令牌在这里生成（勾 repo 就够）：https://github.com/settings/tokens", flush=True)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="发布任务包到 YYJio 任务库")
    ap.add_argument("package", help=".yyjio-task 文件路径")
    ap.add_argument("--repo", default=str(DEFAULT_REPO), help=f"任务库本地目录（默认 {DEFAULT_REPO}）")
    ap.add_argument("--no-push", action="store_true", help="只提交到本地，不推送")
    ap.add_argument("--token", default="", help="GitHub 令牌（也可用环境变量 YYJIO_GITHUB_TOKEN）")
    ap.add_argument("--message", default="", help="自定义提交信息")
    args = ap.parse_args()

    pkg = Path(args.package).expanduser().resolve()
    if not pkg.is_file():
        die(f"找不到文件：{pkg}")
    if pkg.suffix.lower() != SUFFIX:
        die(f"文件后缀应为 {SUFFIX}：{pkg.name}")

    repo = Path(args.repo).expanduser().resolve()
    if not (repo / ".git").is_dir():
        step(f"任务库还没克隆，正在克隆到 {repo}")
        repo.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", REPO_URL, str(repo)], repo.parent)

    manifest = read_manifest(pkg)
    pkg_id, name, version, author = (str(manifest[k]).strip() for k in ("id", "name", "version", "author"))
    size = pkg.stat().st_size
    shown = f"{size / 1024:.1f} KB" if size >= 1024 else f"{size} B"
    print(f"任务包：{name}  v{version}  作者 {author}", flush=True)
    print(f"      id {pkg_id}  {shown}", flush=True)

    packages = repo / "packages"
    packages.mkdir(parents=True, exist_ok=True)
    # 库里统一用 <id>-<version>.yyjio-task 命名，导出后被改过名也能对上
    dest = packages / f"{pkg_id}-{version}{SUFFIX}"
    existed = dest.exists()
    if not (existed and dest.resolve() == pkg.resolve()):
        # 包本来就在库目录里时不要自己拷自己（SameFileError）
        shutil.copy2(pkg, dest)
    step(("覆盖" if existed else "放入") + f" packages/{dest.name}")

    step("重建 index.json")
    built = run([sys.executable, "scripts/build_index.py"], repo, quiet=True)
    print(_text(built.stdout).strip(), flush=True)

    index = json.loads((repo / "index.json").read_text(encoding="utf-8"))
    entry = next((p for p in index.get("packages", []) if p.get("id") == pkg_id), None)
    if entry is None:
        die("重建后的 index.json 里找不到这个包，请检查 packages/ 目录")

    step("提交到 git")
    run(["git", "add", "-A"], repo)
    status = run(["git", "status", "--porcelain"], repo, quiet=True)
    changes = _text(status.stdout).strip()
    if not changes:
        print("[提示] 仓库没有新改动（同版本号重复上传？）")
    else:
        message = args.message or f"add: {name} v{version}（{author}）"
        run(["git", "commit", "-m", message], repo)

    # 关键：即使这次没有改动，之前提交但没推上去的也要补推，
    # 否则「本地 a head 1」会一直卡着，用户以为发布成功了。
    _sync_remote(repo)
    ahead = _ahead_count(repo)
    if args.no_push:
        step("已提交（--no-push，没有推送）" + (f"，本地领先 {ahead} 个提交" if ahead else ""))
    elif ahead == 0 and not changes:
        step("远端已经是最新的")
    else:
        if ahead:
            print(f"      本地领先远端 {ahead} 个提交，开始推送", flush=True)
        step("推送到 GitHub")
        if not push(repo, args.token):
            raise SystemExit(1)

    print("\n完成。清单条目：")
    print(json.dumps(entry, ensure_ascii=False, indent=2))
    remote = _git_origin(repo)
    m = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", remote or "")
    pages = f"https://{m.group(1).lower()}.github.io/{m.group(2)}" if m else "https://tesbot.github.io/YYJio-Tasks"
    print("\n在线地址（Pages 需要几十秒到一分钟）：")
    print(f"  {pages}/{entry['file']}")
    print(f"  {pages}/index.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
