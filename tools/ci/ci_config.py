#!/usr/bin/env python3
# implements: C-7
"""
公共配置读取/回写模块（Python 3.8 标准库，零依赖）。
所有脚本经本模块读 config.ini，保证单一事实源（宪法 C-7）。
敏感值（代理明文密码、Jenkins admin 密码）放 config.local.ini（gitignore）或环境变量，
不入仓（C-1）。run/secret 为各脚本共用，消除重复实现（C-7）。
"""
import configparser
import os
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


def run(cmd, check=True, env=None):
    """统一子进程执行：回显命令后执行（各脚本共用，消除私有 run，C-7）。env 非空时用作子进程环境。"""
    cmd = [str(c) for c in cmd]
    print("+ " + " ".join(cmd))
    return subprocess.run(cmd, check=check, env=env)


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
