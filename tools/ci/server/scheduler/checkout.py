#!/usr/bin/env python3
# implements: FR-2
"""git checkout（仅 git；ssh 或 http 认证）到隔离工作区。
http token 经 GIT_ASKPASS 临时脚本提供，不落命令行/ps（C-1）。"""
import os
import shutil
import stat
import subprocess
import tempfile


def _askpass_script(token):
    """生成临时 askpass 脚本：git 取密码时执行它，stdout 返回 token（不进命令行）。"""
    fd, path = tempfile.mkstemp(prefix="askpass-", suffix=".sh")
    os.write(fd, ("#!/bin/sh\necho '%s'\n" % token).encode("utf-8"))
    os.close(fd)
    os.chmod(path, stat.S_IRWXU)
    return path


def checkout(repo, ref, dest, git_auth="ssh", ssh_key="", http_token="", log=None):
    """拉 repo@ref 到 dest（先清空 dest）。失败抛 RuntimeError。"""
    if os.path.exists(dest):
        shutil.rmtree(dest)
    os.makedirs(dest, exist_ok=True)

    env = dict(os.environ)
    askpass = None
    if git_auth == "ssh" and ssh_key:
        env["GIT_SSH_COMMAND"] = "ssh -i %s -o StrictHostKeyChecking=accept-new" % ssh_key
    elif git_auth == "http" and http_token:
        askpass = _askpass_script(http_token)
        env["GIT_ASKPASS"] = askpass
        env["GIT_TERMINAL_PROMPT"] = "0"

    try:
        rc = subprocess.call(["git", "clone", "--no-single-branch", repo, dest],
                             env=env, stdout=log, stderr=log)
        if rc != 0:
            raise RuntimeError("git clone 失败 rc=%d" % rc)
        rc = subprocess.call(["git", "-C", dest, "checkout", ref],
                             env=env, stdout=log, stderr=log)
        if rc != 0:
            raise RuntimeError("git checkout %s 失败 rc=%d" % (ref, rc))
    finally:
        if askpass and os.path.exists(askpass):
            os.remove(askpass)
