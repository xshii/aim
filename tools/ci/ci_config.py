#!/usr/bin/env python3
# implements: C-7
"""
公共配置读取/回写模块（Python 3.8 标准库，零依赖）。
所有脚本经本模块读 config.ini，保证单一事实源（宪法 C-7）。
敏感值（代理明文密码、webhook 密钥、token）放 config.local.ini（gitignore）或环境变量，
不入仓（C-1）。set_value/run 为各脚本共用，消除重复实现（C-7）。
"""
import configparser
import os
import re
import subprocess

CI_ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(CI_ROOT, "config.ini")
LOCAL_CONFIG_PATH = os.path.join(CI_ROOT, "config.local.ini")  # 敏感覆盖，勿入仓


def load(path=None):
    """加载配置；存在 config.local.ini 时叠加覆盖（单一读取入口，C-7）。"""
    path = path or CONFIG_PATH
    if not os.path.exists(path):
        raise SystemExit("找不到配置文件：%s。请基于 config.ini 模板填写。" % path)
    cfg = configparser.ConfigParser(interpolation=None)  # 关插值：代理密码/密钥含 % 也不报错
    read_list = [path]
    if path == CONFIG_PATH and os.path.exists(LOCAL_CONFIG_PATH):
        read_list.append(LOCAL_CONFIG_PATH)   # 覆盖含密钥/代理（C-1）
    cfg.read(read_list, encoding="utf-8")
    return cfg


def expand(value):
    """展开 ~ 和环境变量（用于路径）。"""
    return os.path.expandvars(os.path.expanduser(value.strip()))


def get(cfg, section, key, fallback=None):
    if cfg.has_option(section, key):
        return cfg.get(section, key)
    if fallback is not None:
        return fallback
    raise SystemExit("配置缺少 [%s] %s，请在 config.ini 中填写。" % (section, key))


def set_value(section, key, value, path=None):
    """回写 config.ini 单项：精确匹配键名；缺失则在 section 内追加；保留其余行与注释。
    单一实现，替代各脚本私有写回（C-7）。"""
    path = path or CONFIG_PATH
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    key_re = re.compile(r"^(\s*)%s\s*=" % re.escape(key))
    out, in_sec, done, sec_at = [], False, False, -1
    for ln in lines:
        st = ln.strip()
        if st.startswith("[") and st.endswith("]"):
            in_sec = (st == "[%s]" % section)
            if in_sec:
                sec_at = len(out)
        m = key_re.match(ln)
        if in_sec and not done and m:
            out.append("%s%s = %s\n" % (m.group(1), key, value))
            done = True
            continue
        out.append(ln)
    if not done:                                  # 键不存在（含被注释项）→ 在 section 内追加
        entry = "%s = %s\n" % (key, value)
        if sec_at >= 0:
            out.insert(sec_at + 1, entry)
        else:
            if out and not out[-1].endswith("\n"):
                out.append("\n")
            out.append("\n[%s]\n%s" % (section, entry))
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(out)


def run(cmd, check=True, redact=None):
    """统一子进程执行：回显命令后执行（替代各脚本私有 run/sh，C-7）。
    redact：需对其“下一个值”脱敏的参数名集合，如 {"--token"}（防 token 落日志，C-1）。"""
    redact = redact or set()
    cmd = [str(c) for c in cmd]
    shown, mask = [], False
    for tok in cmd:
        shown.append("***" if mask else tok)
        mask = (not mask) and (tok in redact)
    print("+ " + " ".join(shown))
    return subprocess.run(cmd, check=check)


def local_ip():
    """探测本机内网 IP（供 deploy 显式锁定 host 用）。失败回退 127.0.0.1。"""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
        finally:
            s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def get_deps_dir(cfg):
    """[offline] deps_dir：为空时用 当前工作目录/offline。"""
    d = get(cfg, "offline", "deps_dir", "").strip()
    if d:
        return expand(d)
    return os.path.join(os.getcwd(), "offline")


def external_url(cfg):
    """GitLab 对外地址：优先 [gitlab] external_url，否则 [server] host + [gitlab] http_port 组装。
    缺 host/port 即停（C-10）。单一实现，供 deploy 与 setup_runner 复用（C-7）。"""
    if cfg.has_option("gitlab", "external_url") and get(cfg, "gitlab", "external_url").strip():
        return get(cfg, "gitlab", "external_url").strip()
    host = get(cfg, "server", "host", "").strip()
    if not host:
        raise SystemExit("host 未锁定，请先运行：python3 deploy.py host（或 all）")
    port = get(cfg, "gitlab", "http_port", "").strip()
    if not port:
        raise SystemExit("http_port 未锁定，请先运行：python3 deploy.py port")
    return "http://%s:%s" % (host, port)


def proxies(cfg=None):
    """HTTP(S) 代理：优先环境变量，其次 config.local.ini [proxy]（含明文密码，不入仓）。
    返回 urllib.ProxyHandler 可用的 {scheme: url}。"""
    cfg = cfg or load()
    out = {}
    for scheme, env in (("http", "HTTP_PROXY"), ("https", "HTTPS_PROXY")):
        val = (os.environ.get(env) or os.environ.get(env.lower()) or
               (cfg.get("proxy", scheme + "_proxy", fallback="")
                if cfg.has_section("proxy") else ""))
        if val.strip():
            out[scheme] = val.strip()
    return out


def secret(env_name, cfg=None, section="secrets", key=None):
    """取敏感值：优先环境变量 env_name，其次 config.local.ini [section] key（不入仓，C-1）。"""
    v = os.environ.get(env_name, "")
    if v:
        return v
    cfg = cfg or load()
    key = key or env_name.lower()
    if cfg.has_section(section) and cfg.has_option(section, key):
        return cfg.get(section, key)
    return ""


if __name__ == "__main__":
    c = load()
    print("=== 配置摘要 ===")
    for sec in c.sections():
        print("[%s]" % sec)
        for k, v in c.items(sec):
            print("  %s = %s" % (k, v))
