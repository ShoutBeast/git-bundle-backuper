# -*- coding: utf-8 -*-
"""Git Bundle 打包/恢复工具 —— customtkinter GUI 入口。

功能:
  * 打包: 把 git 仓库打成 {项目名}_v版本_时间.bundle
  * 恢复: 从 bundle 还原出"项目名"文件夹
  * 配置: 目录选择自动记忆到 exe 同目录 config.json
  * 编码: 单选框选择 git 输出解码编码(utf-8 / gbk), 自动记忆
  * 外观: 底部切换 浅色/深色/系统 外观模式, 主题为第三方 lavender, 自动记忆

运行:
  python main.py
打包 exe(见 build.bat):
  pyinstaller --onefile --windowed --collect-all customtkinter main.py
"""

import os
import queue
import sys
import threading
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk
from PIL import Image, ImageTk

# 源码运行时, 保证能 import 同目录 core(打包成 exe 后无需此行)
if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core

# 外观模式: 界面显示名 -> customtkinter 取值
APPEARANCE_LABELS = {"浅色": "Light", "深色": "Dark", "系统": "System"}


def _resource_base() -> str:
    """返回打包/源码运行时的资源根目录。
    打包后资源随 exe 解压到 _MEIPASS，源码运行时为脚本所在目录。
    """
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _theme_json_path():
    """lavender 主题文件路径: 打包后资源随 exe 解压到 _MEIPASS, 源码时为脚本同目录。"""
    path = os.path.join(_resource_base(), "themes", "lavender.json")
    return path if os.path.isfile(path) else "blue"   # 兜底: 找不到资源时退回官方内置 blue


def _app_icon_images() -> list:
    """加载多尺寸图标 PhotoImage 列表，供非 Windows 平台的 wm_iconphoto 使用。
    Windows 平台直接走 iconbitmap，此函数只在非 Windows 时调用。
    """
    base = _resource_base()
    png_path = os.path.join(base, "icon.png")
    ico_path = os.path.join(base, "GitBundleBackuper.ico")

    images = []
    try:
        if os.path.isfile(png_path):
            src = Image.open(png_path).convert("RGBA")
        elif os.path.isfile(ico_path):
            src = Image.open(ico_path).convert("RGBA")
        else:
            return []
        # 生成多个尺寸
        for sz in (256, 128, 64, 48, 32, 16):
            images.append(ImageTk.PhotoImage(src.resize((sz, sz), Image.LANCZOS)))
    except Exception:
        pass
    return images


def _set_window_icon(win: tk.Tk) -> None:
    """设置窗口图标。

    Windows：只用 iconbitmap + ICO 文件。ICO 内含 256/128/64/48/32/16 多帧，
    Windows Shell 会自动按 DPI 挑选最合适的帧，是最清晰的方式。
    wm_iconphoto 在 Windows 上会被 iconbitmap 覆盖且本身不支持 DPI 感知，故不用。

    非 Windows：用 wm_iconphoto + 多尺寸 PNG 帧。
    """
    base = _resource_base()
    ico_path = os.path.join(base, "GitBundleBackuper.ico")

    if sys.platform == "win32":
        # Windows：iconbitmap 直接读 ICO 文件，Shell 自动选最佳帧
        if os.path.isfile(ico_path):
            try:
                win.iconbitmap(default=ico_path)
            except Exception:
                pass
    else:
        # 非 Windows：用 PhotoImage 多帧
        images = _app_icon_images()
        if images:
            try:
                win.wm_iconphoto(True, *images)
            except Exception:
                pass


ctk.set_default_color_theme(_theme_json_path())   # 颜色主题须在创建任何控件之前设置
# 外观模式(浅色/深色/系统)在 __init__ 中读 config 后应用, 见 GitBundleApp.__init__

APP_TITLE = "Git Bundle 打包/恢复工具"
APP_VERSION = "v1.0.1"       # ★ 唯一版本源: 关于窗口显示此值; 升版本只改这里
APP_AUTHOR = "ShoutBeast"
GIT_SITE = "https://github.com/ShoutBeast/git-bundle-backuper/"
RELEASE_LINK = "https://github.com/ShoutBeast/git-bundle-backuper/releases"
ENTRY_W = 520      # 路径输入框宽度
LABEL_W = 120      # 左侧标签宽度


class GitBundleApp(ctk.CTk):
    """主窗口。"""

    def __init__(self):
        self.cfg = core.load_config()   # config.json 内容(内存中维护)
        # 应用上次选择的外观模式(须在窗口/任何控件创建前调用)
        mode = self.cfg.get("appearance_mode") or "System"
        if mode not in APPEARANCE_LABELS.values():
            mode = "System"
        ctk.set_appearance_mode(mode)

        super().__init__()
        self.title(APP_TITLE)
        self.geometry("880x700")
        self.minsize(820, 640)

        # 设置高清窗口图标（标题栏左上角 + 任务栏）
        _set_window_icon(self)
        self._running = False           # 是否有任务在跑
        self._msg_q = queue.Queue()     # 工作线程 -> 主线程的消息队列
        self._log_boxes = {}            # tag -> CTkTextbox
        self._progress = {}             # tag -> CTkProgressBar
        self._about_win = None          # 「关于」窗口引用(防止重复弹出)

        if not core.git_available():
            messagebox.showwarning(
                APP_TITLE,
                "未检测到 git 命令!\n\n请先安装 Git 并确保它在 PATH 中:\n"
                "https://git-scm.com/download/win\n"
                "(安装时勾选 Add to PATH, 或安装后重启本程序)",
            )

        self._build_ui()

        # 启动时把上一次/默认的仓库与目录填进界面
        self._restore_last_state()

        # 应用记忆/默认的 git 输出解码编码(utf-8 / gbk)
        self._apply_encoding()

        self.after(100, self._poll_messages)

    # ------------------------------------------------------------------ UI #
    def _build_ui(self):
        self._build_menu()          # 顶部菜单栏(须最先 pack, 使其占据最顶一行)

        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=12, pady=(2, 4))

        self._build_backup_tab(self.tabview.add("打包备份"))
        self._build_restore_tab(self.tabview.add("恢复还原"))

        self._build_settings_row()

        self.status_label = ctk.CTkLabel(
            self, text="就绪", anchor="w", text_color="gray60"
        )
        self.status_label.pack(fill="x", padx=14, pady=(2, 8))

    # ---- 顶部菜单栏(自绘, 跟随深浅主题) -------------------------------------
    def _build_menu(self):
        """顶部菜单栏: 原生 tk.Menu 由 Windows 系统绘制, 深色模式下仍是白条,
        不跟随主题; 故改为 CTk 自绘一行, 背景透明, 颜色随 浅色/深色 自动切换。"""
        bar = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0, height=36)
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)

        # 扁平"关于"按钮: (浅色, 深色) 双色元组, customtkinter 按当前外观自动取值
        about_btn = ctk.CTkButton(
            bar,
            text="关于",
            width=64,
            height=28,
            corner_radius=6,
            fg_color="transparent",
            hover_color=("#d7dce2", "#343a41"),
            text_color=("gray20", "gray85"),
            font=ctk.CTkFont(size=13),
            command=self._show_about,
        )
        about_btn.pack(side="left", padx=(10, 0), pady=4)

    def _show_about(self):
        """弹出「关于」窗口; 若已打开则只聚焦不重复弹出。"""
        win = self._about_win
        if win is not None:
            try:
                if win.winfo_exists():
                    win.lift()
                    win.focus_force()
                    return
            except tk.TclError:
                pass

        win = ctk.CTkToplevel(self)
        self._about_win = win
        win.title("关于")
        win.geometry("480x400")
        win.resizable(False, False)
        win.transient(self)
        # 关闭窗口时清空引用, 下次可重新打开
        win.protocol("WM_DELETE_WINDOW", win.destroy)

        def _on_destroy(event):
            if event.widget is win:
                self._about_win = None
        win.bind("<Destroy>", _on_destroy)

        # 标题区
        ctk.CTkLabel(
            win, text=APP_TITLE, font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(padx=24, pady=(18, 2))
        ctk.CTkLabel(
            win, text="基于 git bundle 的 Git 仓库打包备份 / 还原小工具",
            text_color="gray55",
        ).pack(padx=24, pady=(0, 8))

        # 信息区: 版本 / 作者
        info = ctk.CTkFrame(win, fg_color="transparent")
        info.pack(pady=4)
        for i, (key, val) in enumerate([
            ("版本", APP_VERSION),
            ("作者", APP_AUTHOR),
        ]):
            ctk.CTkLabel(info, text=key + ":", width=50, anchor="e",
                         text_color="gray55").grid(
                row=i, column=0, sticky="e", padx=(0, 10), pady=3)
            ctk.CTkLabel(info, text=val, anchor="w").grid(
                row=i, column=1, sticky="w", pady=3)

        # 可点击链接: GitHub 项目主页 + Releases(下载/检查更新)
        site_link = ctk.CTkLabel(
            win, text="GitHub 项目主页",
            text_color="#3495FF", cursor="hand2",
        )
        site_link.pack(pady=(10, 2))
        site_link.bind("<Button-1>", lambda _event: webbrowser.open(GIT_SITE))

        release_link = ctk.CTkLabel(
            win, text="下载 (GitHub Releases)",
            text_color="#3495FF", cursor="hand2",
        )
        release_link.pack(pady=2)
        release_link.bind("<Button-1>", lambda _event: webbrowser.open(RELEASE_LINK))

        ctk.CTkLabel(
            win, text="本项目基于 MIT License 开源, 详见 GitHub 仓库 LICENSE",
            text_color="gray55", font=ctk.CTkFont(size=12),
        ).pack(pady=(2, 6))
        ctk.CTkButton(win, text="关闭", width=90, command=win.destroy).pack(pady=6)

        

    # ---- 底部设置行(两个标签页共用): git 输出编码 + 外观模式 ----------------
    def _build_settings_row(self):
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 4))
        row.grid_columnconfigure(0, weight=1)

        # 左: git 输出解码编码
        left = ctk.CTkFrame(row, fg_color="transparent")
        left.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(left, text="git 输出编码:", width=100, anchor="w").pack(side="left")
        saved = (self.cfg.get("output_encoding") or "utf-8").strip().lower()
        if saved not in core.SUPPORTED_ENCODINGS:
            saved = "utf-8"
        self.enc_var = tk.StringVar(value=saved)
        ctk.CTkRadioButton(left, text="UTF-8 (默认)", variable=self.enc_var,
                           value="utf-8", command=self._on_encoding_changed).pack(
            side="left", padx=(0, 12))
        ctk.CTkRadioButton(left, text="GBK", variable=self.enc_var,
                           value="gbk", command=self._on_encoding_changed).pack(
            side="left", padx=(0, 12))
        ctk.CTkLabel(left, text="(乱码就切换另一项)", text_color="gray55").pack(side="left")

        # 右: 外观模式(浅色 / 深色 / 系统)
        right = ctk.CTkFrame(row, fg_color="transparent")
        right.grid(row=0, column=1, sticky="e")
        ctk.CTkLabel(right, text="外观模式:", anchor="e").pack(side="left", padx=(2, 6))
        self.appearance_seg = ctk.CTkSegmentedButton(
            right, values=list(APPEARANCE_LABELS), command=self._on_appearance_changed)
        cur = self.cfg.get("appearance_mode") or "System"
        if cur not in APPEARANCE_LABELS.values():
            cur = "System"
        cur_label = next(k for k, v in APPEARANCE_LABELS.items() if v == cur)
        self.appearance_seg.set(cur_label)
        self.appearance_seg.pack(side="left")

    def _on_appearance_changed(self, label):
        """切换外观模式: 立即整窗生效并记忆到 config.json。"""
        mode = APPEARANCE_LABELS.get(label, "System")
        ctk.set_appearance_mode(mode)
        self.cfg["appearance_mode"] = mode
        try:
            core.save_config(self.cfg)
        except Exception:
            pass

    def _on_encoding_changed(self):
        """用户点击单选框: 立即生效并记忆到 config.json。"""
        self._apply_encoding(save=True)

    def _apply_encoding(self, save=False):
        """把当前选择的编码应用到 core, 并同步到配置。"""
        if not hasattr(self, "enc_var"):
            enc = self.cfg.get("output_encoding") or "utf-8"
        else:
            enc = self.enc_var.get()
        enc = core.set_output_encoding(enc)
        self.cfg["output_encoding"] = enc
        if save:
            try:
                core.save_config(self.cfg)
            except Exception:
                pass

    # ---- 打包页 -------------------------------------------------------------
    def _build_backup_tab(self, tab):
        tab.grid_columnconfigure(1, weight=1)

        hint = ctk.CTkLabel(
            tab,
            text="提示: 程序启动时会优先选用本程序(exe)所在目录下的 .git 仓库, 也可以手动选择。",
            anchor="w",
            text_color="gray55",
        )
        hint.grid(row=0, column=0, columnspan=3, sticky="ew", padx=6, pady=(4, 2))

        # 仓库
        ctk.CTkLabel(tab, text="Git 仓库:", width=LABEL_W, anchor="e").grid(
            row=1, column=0, sticky="e", padx=6, pady=6)
        self.repo_var = tk.StringVar()
        ctk.CTkEntry(tab, textvariable=self.repo_var, width=ENTRY_W).grid(
            row=1, column=1, sticky="ew", padx=6, pady=6)
        ctk.CTkButton(tab, text="选择 .git / 仓库", width=120,
                      command=self._pick_repo).grid(row=1, column=2, padx=6, pady=6)

        # 项目名
        ctk.CTkLabel(tab, text="项目名:", width=LABEL_W, anchor="e").grid(
            row=2, column=0, sticky="e", padx=6, pady=6)
        self.project_var = tk.StringVar()
        ctk.CTkEntry(tab, textvariable=self.project_var, width=ENTRY_W).grid(
            row=2, column=1, sticky="ew", padx=6, pady=6)
        ctk.CTkLabel(tab, text="(默认取仓库目录名)", text_color="gray55").grid(
            row=2, column=2, sticky="w", padx=6, pady=6)

        # 版本号
        ctk.CTkLabel(tab, text="版本号:", width=LABEL_W, anchor="e").grid(
            row=3, column=0, sticky="e", padx=6, pady=6)
        self.version_var = tk.StringVar()
        ctk.CTkEntry(tab, textvariable=self.version_var, width=ENTRY_W).grid(
            row=3, column=1, sticky="ew", padx=6, pady=6)
        ctk.CTkButton(tab, text="自动探测", width=120,
                      command=self._detect_version).grid(row=3, column=2, padx=6, pady=6)

        # 备份输出目录
        ctk.CTkLabel(tab, text="备份目录:", width=LABEL_W, anchor="e").grid(
            row=4, column=0, sticky="e", padx=6, pady=6)
        self.out_dir_var = tk.StringVar()
        ctk.CTkEntry(tab, textvariable=self.out_dir_var, width=ENTRY_W).grid(
            row=4, column=1, sticky="ew", padx=6, pady=6)
        ctk.CTkButton(tab, text="选择文件夹", width=120,
                      command=self._pick_output_dir).grid(row=4, column=2, padx=6, pady=6)

        # 文件名预览
        self.backup_preview = ctk.CTkLabel(
            tab, text="", anchor="w", text_color="gray60", font=ctk.CTkFont(size=12))
        self.backup_preview.grid(row=5, column=0, columnspan=3, sticky="w",
                                 padx=10, pady=(0, 2))

        # 开始按钮 + 进度条
        action_row = ctk.CTkFrame(tab, fg_color="transparent")
        action_row.grid(row=6, column=0, columnspan=3, sticky="ew", padx=6, pady=4)
        action_row.grid_columnconfigure(0, weight=1)
        self.backup_btn = ctk.CTkButton(
            action_row, text="开始打包", height=34, command=self._on_backup)
        self.backup_btn.grid(row=0, column=0, sticky="w")
        self.backup_progress = ctk.CTkProgressBar(
            action_row, mode="indeterminate", width=360)
        self.backup_progress.grid(row=0, column=1, sticky="ew", padx=10)
        self.backup_progress.set(0)
        self._progress["backup"] = self.backup_progress

        # 日志
        self.backup_log = self._make_log_box(tab, 7)
        self._log_boxes["backup"] = self.backup_log

    # ---- 恢复页 -------------------------------------------------------------
    def _build_restore_tab(self, tab):
        tab.grid_columnconfigure(1, weight=1)

        # bundle 文件
        ctk.CTkLabel(tab, text="bundle 文件:", width=LABEL_W, anchor="e").grid(
            row=0, column=0, sticky="e", padx=6, pady=6)
        self.bundle_var = tk.StringVar()
        ctk.CTkEntry(tab, textvariable=self.bundle_var, width=ENTRY_W).grid(
            row=0, column=1, sticky="ew", padx=6, pady=6)
        ctk.CTkButton(tab, text="选择 .bundle", width=120,
                      command=self._pick_bundle).grid(row=0, column=2, padx=6, pady=6)

        # 项目名
        ctk.CTkLabel(tab, text="项目名:", width=LABEL_W, anchor="e").grid(
            row=1, column=0, sticky="e", padx=6, pady=6)
        self.restore_project_var = tk.StringVar()
        ctk.CTkEntry(tab, textvariable=self.restore_project_var, width=ENTRY_W).grid(
            row=1, column=1, sticky="ew", padx=6, pady=6)
        ctk.CTkLabel(tab, text="(默认从文件名解析)", text_color="gray55").grid(
            row=1, column=2, sticky="w", padx=6, pady=6)

        # 恢复位置(父目录)
        ctk.CTkLabel(tab, text="恢复到目录:", width=LABEL_W, anchor="e").grid(
            row=2, column=0, sticky="e", padx=6, pady=6)
        self.restore_dir_var = tk.StringVar()
        ctk.CTkEntry(tab, textvariable=self.restore_dir_var, width=ENTRY_W).grid(
            row=2, column=1, sticky="ew", padx=6, pady=6)
        ctk.CTkButton(tab, text="选择文件夹", width=120,
                      command=self._pick_restore_dir).grid(row=2, column=2, padx=6, pady=6)

        # 目标预览
        self.restore_preview = ctk.CTkLabel(
            tab, text="", anchor="w", text_color="gray60", font=ctk.CTkFont(size=12))
        self.restore_preview.grid(row=3, column=0, columnspan=3, sticky="w",
                                  padx=10, pady=(0, 2))

        # 开始按钮 + 进度条
        action_row = ctk.CTkFrame(tab, fg_color="transparent")
        action_row.grid(row=4, column=0, columnspan=3, sticky="ew", padx=6, pady=4)
        action_row.grid_columnconfigure(0, weight=1)
        self.restore_btn = ctk.CTkButton(
            action_row, text="开始恢复", height=34, command=self._on_restore)
        self.restore_btn.grid(row=0, column=0, sticky="w")
        self.restore_progress = ctk.CTkProgressBar(
            action_row, mode="indeterminate", width=360)
        self.restore_progress.grid(row=0, column=1, sticky="ew", padx=10)
        self.restore_progress.set(0)
        self._progress["restore"] = self.restore_progress

        # 日志
        self.restore_log = self._make_log_box(tab, 5)
        self._log_boxes["restore"] = self.restore_log

    def _make_log_box(self, parent, row):
        box = ctk.CTkTextbox(parent, height=200, font=ctk.CTkFont(family="Consolas", size=13))
        box.grid(row=row, column=0, columnspan=3, sticky="nsew",
                 padx=6, pady=(8, 6))
        parent.grid_rowconfigure(row, weight=1)
        box.configure(state="disabled")
        return box

    # ------------------------------------------------------------ 事件回调 #
    def _restore_last_state(self):
        """从 config 恢复上次目录, 并自动填充仓库信息。"""
        repo = (self.cfg.get("last_repo") or "").strip()
        if not repo:
            # 优先选用 exe/脚本所在目录的 .git
            d = core.app_dir()
            if core.resolve_repo(d):
                repo = d
        if repo:
            self.repo_var.set(repo)
            self._autofill_repo_info(repo)
        self.out_dir_var.set(self.cfg.get("last_output_dir", ""))
        self.bundle_var.set(self.cfg.get("last_bundle", ""))
        self.restore_dir_var.set(self.cfg.get("last_restore_dir", ""))
        if self.bundle_var.get():
            self._autofill_restore_project(self.bundle_var.get())

    def _pick_repo(self):
        chosen = filedialog.askdirectory(
            parent=self, title="选择 git 仓库根目录(或直接选中 .git 文件夹)")
        if not chosen:
            return
        repo = core.resolve_repo(chosen)
        if not repo:
            messagebox.showwarning(APP_TITLE, "所选文件夹不是 git 仓库:\n%s" % chosen)
            return
        self.repo_var.set(repo)
        self._autofill_repo_info(repo)

    def _autofill_repo_info(self, repo):
        """根据仓库自动填写项目名/版本号, 并更新文件名预览。"""
        try:
            self.project_var.set(core.get_project_name(repo))
            self.version_var.set(core.detect_version(repo))
        except Exception:
            self.project_var.set(core.get_project_name(repo))
            self.version_var.set("")
        self._update_backup_preview()

    def _detect_version(self):
        repo = core.resolve_repo(self.repo_var.get())
        if not repo:
            messagebox.showinfo(APP_TITLE, "请先选择有效的 git 仓库。")
            return
        try:
            self.version_var.set(core.detect_version(repo))
        except Exception as exc:
            messagebox.showwarning(APP_TITLE, str(exc))
        self._update_backup_preview()

    def _pick_output_dir(self):
        d = filedialog.askdirectory(parent=self, title="选择备份存放目录")
        if d:
            self.out_dir_var.set(d)
            self._update_backup_preview()

    def _pick_bundle(self):
        f = filedialog.askopenfilename(
            parent=self, title="选择 .bundle 备份文件",
            filetypes=[("Git Bundle", "*.bundle"), ("所有文件", "*.*")])
        if f:
            self.bundle_var.set(f)
            self._autofill_restore_project(f)

    def _autofill_restore_project(self, bundle_file):
        self.restore_project_var.set(core.parse_project_from_bundle(bundle_file))
        self._update_restore_preview()

    def _pick_restore_dir(self):
        d = filedialog.askdirectory(parent=self, title="选择恢复位置(将在此目录下生成项目文件夹)")
        if d:
            self.restore_dir_var.set(d)
            self._update_restore_preview()

    def _update_backup_preview(self):
        proj = core.clean_name(self.project_var.get() or core.get_project_name(
            core.resolve_repo(self.repo_var.get()) or "."))
        ver = self.version_var.get().strip() or "?"
        if ver and not ver.startswith("v"):
            ver = "v" + ver
        stamp = core.time_stamp()
        self.backup_preview.configure(
            text="即将生成: %s_%s_%s.bundle" % (proj, ver, stamp))

    def _update_restore_preview(self):
        root = self.restore_dir_var.get()
        proj = core.clean_name(self.restore_project_var.get() or "项目名")
        if root:
            self.restore_preview.configure(
                text="即将恢复: %s\n        到: %s" % (proj, os.path.join(root, proj)))
        else:
            self.restore_preview.configure(text="即将恢复: %s" % proj)

    # ------------------------------------------------------------ 打包流程 #
    def _on_backup(self):
        if self._running:
            return
        self._apply_encoding()
        if not core.git_available():
            messagebox.showerror(APP_TITLE, "未检测到 git, 无法打包。")
            return
        repo = core.resolve_repo(self.repo_var.get())
        out_dir = self.out_dir_var.get().strip()
        if not repo:
            messagebox.showerror(APP_TITLE, "请选择有效的 git 仓库(含 .git 的文件夹)。")
            return
        if not out_dir:
            messagebox.showerror(APP_TITLE, "请选择备份存放目录。")
            return

        project = self.project_var.get().strip()
        version = self.version_var.get().strip()

        # 记忆配置
        self.cfg["last_repo"] = repo
        self.cfg["last_output_dir"] = out_dir
        try:
            core.save_config(self.cfg)
        except Exception as exc:
            messagebox.showwarning(APP_TITLE, str(exc))

        self._clear_log("backup")
        self._set_running(True)
        self._start_worker("backup", core.run_backup,
                           repo, project, version, out_dir)

    # ------------------------------------------------------------ 恢复流程 #
    def _on_restore(self):
        if self._running:
            return
        self._apply_encoding()
        if not core.git_available():
            messagebox.showerror(APP_TITLE, "未检测到 git, 无法恢复。")
            return
        bundle_file = self.bundle_var.get().strip()
        restore_dir = self.restore_dir_var.get().strip()
        if not os.path.isfile(bundle_file):
            messagebox.showerror(APP_TITLE, "请选择有效的 .bundle 备份文件。")
            return
        if not restore_dir:
            messagebox.showerror(APP_TITLE, "请选择恢复位置目录。")
            return

        project = self.restore_project_var.get().strip()

        # 记忆配置
        self.cfg["last_bundle"] = bundle_file
        self.cfg["last_restore_dir"] = restore_dir
        try:
            core.save_config(self.cfg)
        except Exception as exc:
            messagebox.showwarning(APP_TITLE, str(exc))

        self._clear_log("restore")
        self._set_running(True)
        self._start_worker("restore", core.run_restore,
                           bundle_file, restore_dir, project)

    def _start_worker(self, tag, func, *args):
        """在工作线程执行 func, 输出经队列回主线程。"""
        def _work():
            try:
                result = func(*args, log=self._make_log_cb(tag))
                self._msg_q.put(("done", tag, result))
            except Exception as exc:
                self._msg_q.put(("fail", tag, str(exc)))
        threading.Thread(target=_work, daemon=True).start()

    # ------------------------------------------------------------ 辅助方法 #
    def _make_log_cb(self, tag):
        def _cb(text):
            self._msg_q.put(("log", tag, text))
        return _cb

    def _clear_log(self, tag):
        box = self._log_boxes[tag]
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.configure(state="disabled")

    def _append_log(self, tag, text):
        box = self._log_boxes[tag]
        box.configure(state="normal")
        box.insert("end", text + "\n")
        box.see("end")
        box.configure(state="disabled")

    def _set_running(self, running):
        self._running = running
        state = "disabled" if running else "normal"
        self.backup_btn.configure(state=state)
        self.restore_btn.configure(state=state)
        if running:
            self.status_label.configure(text="任务执行中...")
            for p in self._progress.values():
                p.start()
        else:
            self.status_label.configure(text="就绪")
            for p in self._progress.values():
                p.stop()
                p.set(0)

    def _poll_messages(self):
        """主线程定时处理工作线程消息。"""
        try:
            while True:
                kind, tag, data = self._msg_q.get_nowait()
                if kind == "log":
                    self._append_log(tag, data)
                elif kind == "done":
                    self._set_running(False)
                    self._append_log(tag, "")
                    self._append_log(tag, "[完成] %s" % data)
                    self.status_label.configure(text="完成: %s" % data)
                    messagebox.showinfo(APP_TITLE, "操作完成:\n%s" % data)
                elif kind == "fail":
                    self._set_running(False)
                    self._append_log(tag, "")
                    self._append_log(tag, "[失败] %s" % data)
                    self.status_label.configure(text="执行失败")
                    messagebox.showerror(APP_TITLE, "执行失败:\n%s" % data)
        except queue.Empty:
            pass
        self.after(100, self._poll_messages)


def main():
    app = GitBundleApp()
    app.mainloop()


if __name__ == "__main__":
    main()
