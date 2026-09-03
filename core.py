# -*- coding: utf-8 -*-
"""Git bundle 打包/恢复核心逻辑(与 GUI 解耦, 便于独立测试)。

文件名规则: {项目名}_v{版本号}_{yyyyMMdd_HHmmss}.bundle
配置文件:   exe/脚本同目录下的 config.json
"""

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

CONFIG_NAME = "config.json"

# 匹配我们生成的文件名: xxx_v1.2.3_20260903_143000.bundle
_BUNDLE_NAME_RE = re.compile(r"^(?P<name>.+)_v[^_]+_\d{8}_\d{6}\.bundle$")
# 文件名中不允许出现 / 用于切分, 其余非法字符一律替换为 _
_ILLEGAL_RE = re.compile(r'[\\/:*?"<>|\s]+')


# --------------------------------------------------------------------------- #
# 路径与配置
# --------------------------------------------------------------------------- #
def app_dir() -> str:
    """返回程序所在目录: 打包成 exe 后为 exe 目录, 源码运行为脚本目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def config_path() -> str:
    return os.path.join(app_dir(), CONFIG_NAME)


def load_config() -> dict[str, str]:
    """读取 exe 同目录 config.json, 不存在或损坏时返回默认值。"""
    defaults = {
        "last_repo": "",        # 打包: 上次选择的仓库目录
        "last_output_dir": "",  # 打包: 上次的备份输出目录
        "last_bundle": "",      # 恢复: 上次选择的 bundle 文件
        "last_restore_dir": "",  # 恢复: 上次的恢复目标目录
    }
    try:
        with open(config_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            defaults.update(data)
    except Exception:
        pass
    return defaults


def save_config(cfg: dict[str, str]) -> None:
    """把配置写回 exe 同目录 config.json(UTF-8, 保留中文)。"""
    try:
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        raise RuntimeError("写入配置文件失败: %s" % exc)


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
# git 子进程输出解码编码。git 对管道输出默认按 UTF-8(路径内部即 UTF-8);
# 但少数环境(如 git 配置了 GBK 输出)需要切换为 gbk。GUI 通过
# set_output_encoding() 切换, 选择会记忆到 config.json。
SUPPORTED_ENCODINGS = ("utf-8", "gbk")
_output_encoding = "utf-8"


def set_output_encoding(name):
    """设置 git 输出解码编码, 支持 utf-8 / gbk。非法值忽略。

    返回当前生效的编码名。
    """
    global _output_encoding
    if name:
        enc = name.strip().lower()
        if enc in SUPPORTED_ENCODINGS:
            _output_encoding = enc
    return _output_encoding


def get_output_encoding() -> str:
    """返回当前生效的 git 输出解码编码。"""
    return _output_encoding


def git_available() -> bool:
    """检测 git 是否可用。"""
    return shutil.which("git") is not None


def _run_git(args, cwd=None):
    """运行 git 并捕获输出; 成功返回 stdout(去首尾空白), 失败返回 None。"""
    try:
        # 解码编码由 set_output_encoding() 决定(默认 utf-8), 见 _output_encoding。
        cp = subprocess.run(
            ["git"] + list(args),
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding=_output_encoding,
            errors="replace",
        )
        return cp.stdout.strip() if cp.returncode == 0 else None
    except Exception:
        return None


def _stream_proc(proc, log):
    """逐行转发子进程输出到 log 回调, 结束后校验退出码。"""
    for raw in proc.stdout:
        line = raw.rstrip("\r\n")
        # git 进度用 \r 原地刷新, 只保留该行的最后一段
        if "\r" in line:
            line = line.rsplit("\r", 1)[-1]
        if line:
            log(line)
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("git 命令执行失败 (exit=%d), 请查看上方输出。" % proc.returncode)


def clean_name(name: str) -> str:
    """把用户输入/目录名清洗为安全的文件名片段。"""
    name = _ILLEGAL_RE.sub("_", name or "").strip("_")
    return name or "untitled"


def time_stamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def is_git_repo(path: str) -> bool:
    """判断目录是否为 git 仓库根(支持 .git 目录与 .git 文件)。"""
    if not path:
        return False
    dot = os.path.join(path, ".git")
    return os.path.isdir(dot) or os.path.isfile(dot)


def resolve_repo(path: str) -> str:
    """传入仓库根目录或 .git 目录, 返回真正的仓库根; 无效返回空串。"""
    if not path:
        return ""
    p = os.path.abspath(path)
    if os.path.basename(p) == ".git":
        p = os.path.dirname(p)
    if is_git_repo(p):
        return p
    return ""


def get_project_name(repo_dir: str) -> str:
    """取仓库目录名作为默认项目名。"""
    return os.path.basename(os.path.normpath(repo_dir))


def detect_version(repo_dir: str) -> str:
    """自动探测版本号: HEAD 最近 tag -> 最新 v* tag -> commit 短哈希。"""
    ver = _run_git(["describe", "--tags", "--abbrev=0"], cwd=repo_dir)
    if not ver:
        out = _run_git(["tag", "--list", "v*", "--sort=-v:refname"], cwd=repo_dir)
        if out:
            for line in out.splitlines():
                if line.strip():
                    ver = line.strip()
                    break
    if not ver:
        ver = _run_git(["rev-parse", "--short", "HEAD"], cwd=repo_dir)
    if not ver:
        raise RuntimeError("无法自动获取版本号(仓库无 tag 且无提交)。请手动填写版本号。")
    if not ver.startswith("v"):
        ver = "v" + ver
    return ver


def parse_project_from_bundle(bundle_file: str) -> str:
    """从 {项目名}_v版本_时间.bundle 文件名解析项目名。"""
    base = os.path.basename(bundle_file)
    m = _BUNDLE_NAME_RE.match(base)
    if m:
        return m.group("name")
    return os.path.splitext(base)[0]


# --------------------------------------------------------------------------- #
# 打包
# --------------------------------------------------------------------------- #
def run_backup(repo_dir, project_name, version, output_dir, log=None):
    """把仓库打包为 bundle 文件。

    参数:
        repo_dir    仓库根目录(也可直接传 .git 目录)
        project_name 项目名, 传空则取仓库目录名
        version      版本号, 传空则自动探测(tag / 短哈希)
        output_dir   bundle 保存目录(不存在会自动创建)
        log          逐行输出回调 log(text)
    返回:
        生成的 bundle 文件绝对路径
    """
    def emit(text):
        if log:
            log(text)

    repo = resolve_repo(repo_dir)
    if not repo:
        raise RuntimeError("未找到有效的 git 仓库: %s\n请选择仓库根目录(含 .git 的文件夹), 或直接选择 .git 文件夹。" % repo_dir)

    if not project_name or not project_name.strip():
        project_name = get_project_name(repo)
    project = clean_name(project_name)

    if not version or not version.strip():
        version = detect_version(repo)
    else:
        version = version.strip()
    version = clean_name(version)
    if not version.startswith("v"):
        version = "v" + version

    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as exc:
        raise RuntimeError("无法创建备份目录: %s\n%s" % (output_dir, exc))

    bundle_file = os.path.join(output_dir, "%s_%s_%s.bundle" % (project, version, time_stamp()))

    emit("== 开始打包 ==")
    emit("项目名称  : %s" % project)
    emit("版本号    : %s" % version)
    emit("仓库目录  : %s" % repo)
    emit("输出目录  : %s" % output_dir)
    emit("")

    # 未提交改动提示(不会包含进 bundle)
    status = _run_git(["status", "--porcelain"], cwd=repo)
    if status:
        emit("[警告] 工作区存在未提交的改动, 它们不会被包含进 bundle。")
        emit("[提示] 如需包含, 请先在仓库中 git commit 或 git stash。")
        emit("")

    emit("== git bundle create --all ==")
    proc = subprocess.Popen(
        ["git", "bundle", "create", bundle_file, "--all"],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding=_output_encoding,
        errors="replace",
        bufsize=1,
    )
    _stream_proc(proc, emit)

    if not os.path.exists(bundle_file):
        raise RuntimeError("打包失败: 未生成 bundle 文件, 请检查上方 git 输出。")

    emit("")
    emit("== git bundle verify ==")
    # verify 需要在某个 git 仓库内执行, 这里与 create 一致以源仓库为上下文
    proc = subprocess.Popen(
        ["git", "bundle", "verify", bundle_file],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding=_output_encoding,
        errors="replace",
        bufsize=1,
    )
    _stream_proc(proc, emit)

    size_mb = os.path.getsize(bundle_file) / 1024.0 / 1024.0
    emit("")
    emit("打包完成: %s" % bundle_file)
    emit("文件大小: %.2f MB" % size_mb)
    return bundle_file


# --------------------------------------------------------------------------- #
# 恢复
# --------------------------------------------------------------------------- #
def run_restore(bundle_file, restore_root, project_name="", log=None):
    """从 bundle 恢复到 restore_root/项目名 目录。

    参数:
        bundle_file  要恢复的 .bundle 文件
        restore_root 恢复的父目录(在其下新建"项目名"文件夹)
        project_name 项目名, 传空则从文件名自动解析
        log          逐行输出回调
    返回:
        恢复出的仓库目录绝对路径
    """
    def emit(text):
        if log:
            log(text)

    if not os.path.isfile(bundle_file):
        raise RuntimeError("bundle 文件不存在: %s" % bundle_file)

    if not project_name or not project_name.strip():
        project_name = parse_project_from_bundle(bundle_file)
    project = clean_name(project_name)

    try:
        os.makedirs(restore_root, exist_ok=True)
    except OSError as exc:
        raise RuntimeError("无法创建恢复目录: %s\n%s" % (restore_root, exc))

    dest = os.path.join(restore_root, project)

    emit("== 开始恢复 ==")
    emit("bundle 文件 : %s" % bundle_file)
    emit("项目名      : %s" % project)
    emit("恢复位置    : %s" % dest)
    emit("")

    if os.path.exists(dest):
        raise RuntimeError("目标目录已存在, 请先移除或更换恢复位置:\n%s" % dest)

    emit("== git bundle verify ==")
    # git bundle verify 必须在某个 git 仓库内执行; 恢复前目标仓库尚不存在,
    # 故在系统临时目录建一个空仓库作为验证上下文(随 with 退出自动清理)。
    with tempfile.TemporaryDirectory(prefix="gbb_verify_") as tmp_repo:
        subprocess.run(["git", "init", "-q"], cwd=tmp_repo,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        proc = subprocess.Popen(
            ["git", "bundle", "verify", bundle_file],
            cwd=tmp_repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding=_output_encoding,
            errors="replace",
            bufsize=1,
        )
        _stream_proc(proc, emit)

    emit("")
    emit("== git clone ==")
    proc = subprocess.Popen(
        ["git", "clone", bundle_file, dest],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding=_output_encoding,
        errors="replace",
        bufsize=1,
    )
    _stream_proc(proc, emit)

    if not is_git_repo(dest):
        raise RuntimeError("恢复失败: 未生成有效的仓库目录。")

    emit("")
    emit("恢复完成: %s" % dest)
    return dest
