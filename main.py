import sys
import os
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTreeWidget, QTreeWidgetItem, QPushButton, QTextEdit,
    QDialog, QFormLayout, QLineEdit, QDialogButtonBox, QMessageBox,
    QLabel, QComboBox, QFrame, QProgressBar,
    QStatusBar, QListWidget, QSplitter, QTabWidget, QTextBrowser,
    QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QTimer
from PyQt6.QtGui import QFont, QColor, QPixmap, QIcon
from PyQt6.QtWidgets import QSplashScreen
from PyQt6.QtGui import QFont, QColor
from datetime import datetime
import subprocess
import paramiko

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data.database import db

# ─── 暗色配色 ─────────────────────────────────────────────────────────────────
C = {
    'bg': '#0f1117',
    'surface': '#1a1d27',
    'surface2': '#252836',
    'border': '#2e3147',
    'accent': '#7c6af7',
    'accent2': '#6ee7b7',
    'danger': '#f87171',
    'warn': '#fbbf24',
    'text': '#e2e8f0',
    'text2': '#94a3b8',
    'text3': '#64748b',
}


# ─── 部署线程（重构版）────────────────────────────────────────────────────────
class DeployThread(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, str)
    finished_ok = pyqtSignal()
    finished_err = pyqtSignal(str)

    def __init__(self, app_info, maven_home='', maven_repo='', jdk_home=''):
        super().__init__()
        self.app_info = app_info
        self.maven_home = maven_home
        self.maven_repo = maven_repo
        self.jdk_home = jdk_home
        self._cancel = False
        self._ssh = None
        self._sftp = None

    def cancel(self):
        self._cancel = True
        if self._ssh:
            try:
                self._ssh.close()
            except Exception:
                pass

    def _log(self, msg):
        self.log_signal.emit(msg)

    def run(self):
        app = self.app_info
        project_path = app.get('local_project_path', '').strip()

        def log(msg):
            self.log_signal.emit(msg)

        def cancel_check():
            if self._cancel:
                raise Exception("⚠️  用户取消了部署")

        # ── 建立单一 SSH 连接（全程复用）─────────────────────────────────
        try:
            self._ssh = paramiko.SSHClient()
            self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self._ssh.connect(
                hostname=app['ip'],
                username=app['username'],
                password=app['password'],
                timeout=15,
                banner_timeout=15
            )
            log(f"[连接] ✅ 已建立 SSH 到 {app['ip']}")
        except Exception as e:
            self.finished_err.emit(f"❌ SSH 连接失败: {e}")
            return

        try:
            log("═" * 56)
            log(f"🚀 部署开始  [{datetime.now().strftime('%H:%M:%S')}]")
            log(f"📦 应用：{app['name']}  |  Jar：{app['jar_name']}")
            log("═" * 56)

            # Step 1: Maven 打包
            cancel_check()
            self.progress_signal.emit(10, 'maven')
            log("[1/6] 📦 Maven 打包中 ...")
            if not self._maven_package(project_path, log, cancel_check):
                return
            log("[1/6] ✅ Maven 打包完成")

            # Step 2: 找 Jar
            cancel_check()
            self.progress_signal.emit(30, 'find_jar')
            jar_path = self._find_jar(project_path, app['jar_name'], log)
            if not jar_path:
                return
            log(f"[2/6] 📦 Jar: {jar_path}")

            # Step 3: 上传 Jar
            cancel_check()
            self.progress_signal.emit(45, 'upload')
            remote_basename = os.path.basename(jar_path)
            # 脚本目录：优先用 sh_path，不填则用 server_path
            script_dir = app.get('sh_path') or app['server_path']
            remote_jar = script_dir.replace("\\", "/") + "/" + remote_basename
            size_kb = os.path.getsize(jar_path) // 1024
            log(f"[3/6] 📤 上传 Jar ({size_kb} KB) ...")
            if not self._upload_file(jar_path, remote_jar, log, cancel_check):
                return
            log("[3/6] ✅ Jar 上传完成")

            # Step 4: 生成部署记录
            cancel_check()
            self.progress_signal.emit(60, 'hello')
            script_args = app.get('script_args', 'restart')
            deploy_txt_content = (
                f"部署时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"应用: {app['name']}\n"
                f"Jar: {remote_basename}\n"
                f"服务器: {app['ip']}\n"
                f"脚本: {app['sh_name']} {script_args}\n"
            )
            remote_deploy_txt = script_dir.replace("\\", "/") + "/deploy.txt"
            self._write_remote_file(remote_deploy_txt, deploy_txt_content, log)
            log("[4/6] ✅ 部署记录已生成")

            # Step 5: 验证上传
            cancel_check()
            self.progress_signal.emit(75, 'verify')
            ok, info = self._verify_remote(remote_jar, log)
            log(f"[5/6] {'✅ 服务器文件确认' if ok else '⚠️  验证'}: {info}")

            # Step 6: 执行脚本
            cancel_check()
            self.progress_signal.emit(90, 'script')
            log(f"[6/6] 🖥️  执行 {app['sh_name']} {script_args} ...")
            script_cmd = f"cd {script_dir} && sh {app['sh_name']} {script_args}"
            self._run_script(f"bash -l -c \"{script_cmd}\"", log, cancel_check)
            log("[6/6] ✅ 启动脚本执行完成")

            db.add_deploy_history(
                app_id=app.get('app_id', 0),
                app_name=app['name'],
                jar_name=app['jar_name'],
                server_ip=app['ip'],
                status='success'
            )
            self.progress_signal.emit(100, 'done')
            log("🎉 部署完成！")
            self.finished_ok.emit()

        except Exception as e:
            err_msg = str(e)
            if "用户取消" in err_msg:
                log("⚠️  部署已取消")
                db.add_deploy_history(
                    app_id=app.get('app_id', 0),
                    app_name=app['name'],
                    jar_name=app['jar_name'],
                    server_ip=app['ip'],
                    status='cancelled'
                )
                self.finished_err.emit("⚠️  部署已取消")
            else:
                log(f"❌ 部署失败: {err_msg}")
                db.add_deploy_history(
                    app_id=app.get('app_id', 0),
                    app_name=app['name'],
                    jar_name=app['jar_name'],
                    server_ip=app['ip'],
                    status='failed'
                )
                self.finished_err.emit(f"❌ 部署失败: {err_msg}")
        finally:
            self._cleanup()

    def _maven_package(self, project_path, log, cancel_check):
        if self.maven_home and os.path.isdir(self.maven_home):
            mvn_cmd = os.path.normpath(os.path.join(self.maven_home, "bin", "mvn.cmd"))
            if not os.path.exists(mvn_cmd):
                mvn_cmd = os.path.normpath(os.path.join(self.maven_home, "bin", "mvn"))
            if not os.path.exists(mvn_cmd):
                log(f"❌ Maven路径无效: {self.maven_home}")
                self.finished_err.emit(f"❌ Maven路径无效: {self.maven_home}")
                return False
        else:
            mvn_cmd = "mvn"

        env = os.environ.copy()
        if self.jdk_home and os.path.isdir(self.jdk_home):
            jdk_bin = os.path.join(self.jdk_home, "bin")
            env["JAVA_HOME"] = self.jdk_home
            env["PATH"] = jdk_bin + os.pathsep + env.get("PATH", "")
            log(f"   JDK: {self.jdk_home}")

        cmd = [mvn_cmd, "clean", "package", "-DskipTests"]
        if self.maven_repo:
            cmd.insert(3, "-Dmaven.repo.local=" + self.maven_repo)
        if self.app_info.get('maven_module'):
            cmd.extend(["-pl", self.app_info['maven_module'], "-am"])

        try:
            cwd = project_path if project_path else None
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=cwd,
                shell=True,
                env=env
            )
            for line in proc.stdout:
                if self._cancel:
                    proc.terminate()
                    raise Exception("⚠️  用户取消了部署")
                s = line.rstrip()
                if s:
                    keywords = ["Building", "Downloaded", "Downloading",
                                "Compiling", "Tests", "BUILD", "ERROR",
                                "WARN", "Reactor", "Installing", "SUCCESS", "FAILURE"]
                    color_line = any(k in s for k in keywords)
                    log(("   " + s) if color_line else f"   {s}")
            proc.wait()
            if proc.returncode != 0:
                self.finished_err.emit(f"❌ Maven 打包失败 (exit {proc.returncode})")
                return False
            return True
        except Exception as e:
            if "取消" not in str(e):
                self.finished_err.emit(f"❌ Maven 打包异常: {e}")
            raise

    def _find_jar(self, project_path, jar_name, log):
        search_dir = Path(project_path) / "target" if project_path else Path("target")
        if not search_dir.exists():
            self.finished_err.emit(f"❌ 未找到 target 目录: {search_dir}")
            return None
        candidate = search_dir / jar_name
        if candidate.exists():
            return str(candidate)
        for f in search_dir.glob("*.jar"):
            if "original" not in f.name and f.name.endswith(".jar"):
                return str(f)
        self.finished_err.emit(f"❌ 未找到 jar 包: {jar_name}")
        return None

    def _upload_file(self, local_path, remote_path, log, cancel_check=None):
        try:
            self._sftp = self._ssh.open_sftp()
            self._sftp.put(local_path, remote_path)
            self._sftp.close()
            self._sftp = None
            return True
        except Exception as e:
            self.finished_err.emit(f"❌ SFTP 上传失败: {e}")
            return False

    def _write_remote_file(self, remote_path, content, log):
        try:
            sftp = self._ssh.open_sftp()
            with sftp.file(remote_path, "w") as f:
                f.write(content)
            sftp.close()
        except Exception as e:
            log(f"   ⚠️  写入 {remote_path} 失败: {e}")

    def _verify_remote(self, remote_path, log):
        try:
            _, stdout, _ = self._ssh.exec_command(f"ls -lh {remote_path}", timeout=10)
            result = stdout.read().decode().strip()
            if result:
                return True, result
            return False, "文件未找到"
        except Exception as e:
            return False, str(e)

    def _run_script(self, cmd_str, log, cancel_check=None):
        try:
            stdin, stdout, stderr = self._ssh.exec_command(cmd_str, timeout=120)
            out = stdout.read().decode()
            err = stderr.read().decode()
            if err:
                for line in err.strip().split('\n')[-5:]:
                    if line.strip():
                        log(f"   stderr: {line}")
            if out:
                for line in out.strip().split('\n')[-15:]:
                    if line.strip():
                        log(f"   {line}")
        except Exception as e:
            log(f"   ⚠️  脚本执行异常: {e}")

    def _cleanup(self):
        try:
            if self._sftp:
                self._sftp.close()
        except Exception:
            pass
        try:
            if self._ssh:
                self._ssh.close()
        except Exception:
            pass


# ─── 数据库增强 ───────────────────────────────────────────────────────────────
def _init_history():
    try:
        db.cursor.execute("""
            CREATE TABLE IF NOT EXISTS deploy_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                app_id INTEGER,
                app_name TEXT,
                jar_name TEXT,
                server_ip TEXT,
                status TEXT,
                deployed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        db.conn.commit()
    except Exception:
        pass

_init_history()


# ─── 自定义确认删除弹窗 ───────────────────────────────────────────────────────
class ConfirmDialog(QDialog):
    def __init__(self, title, message, parent=None, danger=False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(400)
        self.setFont(QFont("Segoe UI", 10))
        self._build_ui(message, danger)

    def _build_ui(self, message, danger):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 20, 24, 12)

        # 图标
        icon_label = QLabel("⚠️")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("font-size: 36px;")
        layout.addWidget(icon_label)

        # 标题
        title_label = QLabel(self.windowTitle())
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet(f"font-size:15px; font-weight:700; color:{C['text']};")
        layout.addWidget(title_label)

        # 内容
        msg_label = QLabel(message)
        msg_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg_label.setWordWrap(True)
        msg_label.setStyleSheet(f"color:{C['text2']}; font-size:13px; line-height:1.6;")
        layout.addWidget(msg_label)

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("✖  取消")
        cancel_btn.setFixedSize(110, 40)
        cancel_btn.setStyleSheet(f"""
            QPushButton {{ background:{C['surface2']}; color:{C['text']};
                font-size:13px; border:1px solid {C['border']}; border-radius:8px; }}
            QPushButton:hover {{ background:{C['border']}; }}
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        ok_text = "🗑  确认删除" if danger else "✅  确定"
        ok_btn = QPushButton(ok_text)
        ok_btn.setFixedSize(110, 40)
        if danger:
            ok_btn.setStyleSheet(f"""
                QPushButton {{ background:{C['danger']}; color:#fff;
                    font-size:13px; font-weight:600; border-radius:8px; border:none; }}
                QPushButton:hover {{ background:#ef5555; }}
            """)
        else:
            ok_btn.setStyleSheet(f"""
                QPushButton {{ background:{C['accent']}; color:#fff;
                    font-size:13px; font-weight:600; border-radius:8px; border:none; }}
                QPushButton:hover {{ background:{C['accent']}cc; }}
            """)
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(ok_btn)

        layout.addLayout(btn_row)


# ─── 主窗口 ──────────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.deploy_thread = None
        self.current_app = None
        self._selected_server = None  # 当前选中的服务器（server dict）
        self._apply_style()
        self.init_ui()
        # 数据加载延迟到窗口显示后，不阻塞启动
        QTimer.singleShot(100, self._delayed_init)

    def _delayed_init(self):
        self.refresh_tree()
        self._load_history()

    def _apply_style(self):
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{ background: {C['bg']}; color: {C['text']};
                font-family: 'Segoe UI', 'Microsoft YaHei UI', sans-serif; }}
            QLabel {{ color: {C['text']}; background: transparent; }}
            QTreeWidget {{ background: {C['surface']}; border: 1px solid {C['border']};
                border-radius: 10px; color: {C['text']}; font-size: 13px; outline: none; }}
            QTreeWidget::item {{ padding: 8px 12px; border-radius: 6px; margin: 1px 4px; }}
            QTreeWidget::item:hover {{ background: {C['surface2']}; }}
            QTreeWidget::item:selected {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {C['accent']}, stop:1 {C['accent']}99);
                color: #fff; font-weight: 600;
                border: 1px solid {C['accent']}88;
            }}
            QTreeWidget::item:selected:active {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {C['accent']}ee, stop:1 {C['accent']}bb);
                color: #fff; font-weight: 600;
                border: 1px solid {C['accent']};
            }}
            QPushButton {{ border-radius: 8px; font-weight: 600; font-size: 13px; }}
            QPushButton:disabled {{ opacity: 0.4; }}
            QTextEdit {{ background: {C['surface']}; border: 1px solid {C['border']};
                border-radius: 10px; color: #93c5fd; font-family: 'Cascadia Code','Consolas',monospace;
                font-size: 12px; padding: 12px 12px 16px 12px; }}
            QLineEdit {{ background: {C['surface2']}; color: {C['text']};
                border: 1px solid {C['border']}; border-radius: 6px; padding: 7px 10px; font-size: 13px; }}
            QLineEdit:focus {{ border-color: {C['accent']}; }}
            QComboBox {{ background: {C['surface2']}; color: {C['text']};
                border: 1px solid {C['border']}; border-radius: 6px; padding: 7px 10px; }}
            QComboBox::dropDown {{ border: none; }}
            QComboBox QAbstractItemView {{ background: {C['surface2']}; color: {C['text']};
                border: 1px solid {C['border']}; selection-background-color: {C['accent']}44; }}
            QDialog {{ background: {C['bg']}; }}
            QMenu {{ background: {C['surface']}; color: {C['text']}; border: 1px solid {C['border']};
                border-radius: 8px; padding: 4px; }}
            QMenu::item {{ padding: 7px 14px; border-radius: 4px; }}
            QMenu::item:selected {{ background: {C['accent']}33; }}
            QMessageBox {{ background: {C['bg']}; }}
            QProgressBar {{ background: {C['surface2']}; border: none; border-radius: 6px; height: 8px; }}
            QProgressBar::chunk {{ background: {C['accent']}; border-radius: 6px; }}
            QStatusBar {{ background: {C['surface']}; color: {C['text2']}; font-size: 12px;
                border-top: 1px solid {C['border']}; }}
            QListWidget {{ background: {C['surface']}; border: 1px solid {C['border']};
                border-radius: 8px; color: {C['text']}; font-size: 12px; }}
            QListWidget::item {{ padding: 6px 10px; border-radius: 4px; }}
            QListWidget::item:selected {{ background: {C['accent']}33; }}
            QTabWidget::pane {{ border: 1px solid {C['border']}; border-radius: 8px;
                background: {C['surface']}; }}
            QTabBar::tab {{ background: {C['surface2']}; color: {C['text2']}; padding: 7px 16px;
                border-radius: 6px 6px 0 0; }}
            QTabBar::tab:selected {{ background: {C['accent']}; color: #fff; }}
            QScrollBar {{ background: transparent; width: 6px; }}
            QScrollBar::handle {{ background: {C['border']}; border-radius: 3px; }}
        """)

    def init_ui(self):
        self.setWindowTitle("🚀 一键部署工具")
        self.setMinimumSize(1180, 700)
        self.resize(1300, 820)

        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 8)
        root.setSpacing(12)

        # 左侧面板（self.tree 在这里创建）
        left = self._build_left_panel()
        root.addWidget(left, 1)

        # 拖拽支持：tree 已创建，补上配置
        self.tree.setDragEnabled(True)
        self.tree.setAcceptDrops(True)
        self.tree.setDropIndicatorShown(True)
        self.tree.setDragDropMode(QTreeWidget.DragDropMode.DragDrop)
        self.tree.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.tree.installEventFilter(self)

        # 右侧面板
        right = self._build_right_panel()
        root.addWidget(right, 3)

        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("✅ 就绪")

    def _build_left_panel(self):
        panel = QWidget()
        panel.setFixedWidth(310)
        panel.setStyleSheet(f"background:{C['surface']}; border-right: 1px solid {C['border']}; border-radius:0px;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # 标题
        title = QLabel("🖥️  服务器与应用")
        title.setStyleSheet(f"font-size:13px; font-weight:700; color:{C['accent']}; padding:2px 4px;")
        layout.addWidget(title)

        # 树（占据上方剩余空间）
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        self.tree.itemClicked.connect(self._on_tree_click)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_tree_menu)
        layout.addWidget(self.tree, 1)

        # 操作按钮行1
        r1 = QHBoxLayout()
        r1.setSpacing(8)
        for label, fn in [("+ 服务器", self._add_server), ("+ 应用", self._add_app)]:
            b = QPushButton(label)
            b.setFixedHeight(36)
            b.setStyleSheet(f"""
                QPushButton {{ background:{C['accent']}; color:#fff; font-size:13px;
                    font-weight:600; border-radius:8px; border:none; }}
                QPushButton:hover {{ background:{C['accent']}cc; }}
            """)
            b.clicked.connect(fn)
            r1.addWidget(b)
        layout.addLayout(r1)

        # 操作按钮行2
        r2 = QHBoxLayout()
        r2.setSpacing(8)
        for label, fn in [("✏️  编辑", self._edit_selected),
                           ("🗑  删除", self._delete_selected),
                           ("📋 复制", self._copy_app)]:
            b = QPushButton(label)
            b.setFixedHeight(32)
            b.setStyleSheet(f"""
                QPushButton {{ background:{C['surface2']}; color:{C['text']};
                    font-size:12px; border:1px solid {C['border']}; border-radius:7px; }}
                QPushButton:hover {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {C['accent']}, stop:1 #9b8bff);
                    color:#fff; border-color:{C['accent']}; font-weight:600; }}
            """)
            b.clicked.connect(fn)
            r2.addWidget(b)
        layout.addLayout(r2)

        # 全局设置 + 帮助（等宽平分占满整行）
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        for label, fn in [("⚙️  全局设置", self._open_settings), ("📖 帮助", self._show_help)]:
            b = QPushButton(label)
            b.setFixedHeight(36)
            b.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.Fixed)
            b.setStyleSheet(f"""
                QPushButton {{ background:{C['bg']}; color:{C['text2']}; font-size:13px;
                    font-weight:600; border:1px solid {C['border']}; border-radius:8px; }}
                QPushButton:hover {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {C['accent']}, stop:1 #9b8bff);
                    color:#fff; border-color:{C['accent']}; }}
            """)
            b.clicked.connect(fn)
            btn_row.addWidget(b, stretch=1)
        layout.addLayout(btn_row)

        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background:{C['border']}; margin:4px 0;")
        layout.addWidget(sep)

        # 历史记录
        hist_title = QLabel("📜 部署历史")
        hist_title.setStyleSheet(f"font-size:13px; font-weight:700; color:{C['accent2']}; padding:2px 4px;")
        layout.addWidget(hist_title)

        self.hist_list = QListWidget()
        self.hist_list.setMaximumHeight(145)
        self.hist_list.itemClicked.connect(self._on_hist_click)
        layout.addWidget(self.hist_list)

        return panel

    def _build_right_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # 应用信息卡片
        self.info_card = QLabel()
        self.info_card.setStyleSheet(f"""
            background:{C['surface']}; border:1px solid {C['border']};
            border-radius:12px; padding:14px 16px; font-size:13px; line-height:1.8;
        """)
        self.info_card.setText("👈 请选择左侧服务器或应用")
        layout.addWidget(self.info_card)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.phase_label = QLabel("")
        self.phase_label.setStyleSheet(f"color:{C['text3']}; font-size:11px; padding:0 4px;")
        self.phase_label.hide()
        layout.addWidget(self.phase_label)

        log_label = QLabel("📋  部署日志")
        log_label.setStyleSheet("font-weight:700; font-size:13px;")
        layout.addWidget(log_label)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setPlaceholderText("点击「🚀 部署」后，日志将实时显示在这里...")
        layout.addWidget(self.log_text, 1)

        # 按钮行
        btn_row = QHBoxLayout()

        self.deploy_btn = QPushButton("🚀  部署")
        self.deploy_btn.setFixedHeight(48)
        self.deploy_btn.setMinimumWidth(200)
        self.deploy_btn.setStyleSheet(f"""
            QPushButton {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 {C['accent']}, stop:1 #9b8bff);
                color:#fff; font-size:15px; font-weight:700;
                border-radius:10px; border:none; letter-spacing:1px; }}
            QPushButton:hover {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #9b8bff, stop:1 {C['accent']}); }}
            QPushButton:disabled {{ background:{C['surface2']}; color:{C['text3']};
                border-radius:10px; border:none; }}
        """)
        self.deploy_btn.clicked.connect(self._do_deploy)
        self.deploy_btn.setEnabled(False)

        self.cancel_btn = QPushButton("⛔ 取消")
        self.cancel_btn.setFixedHeight(46)
        self.cancel_btn.setFixedWidth(95)
        self.cancel_btn.setStyleSheet(f"""
            QPushButton {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 {C['accent']}, stop:1 #9b8bff);
                color:#fff; font-size:13px; font-weight:600;
                border-radius:10px; border:none; }}
            QPushButton:hover {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #9b8bff, stop:1 {C['accent']}); }}
            QPushButton:disabled {{ background:{C['surface2']}; color:{C['text3']};
                border-radius:10px; border:none; }}
        """)
        self.cancel_btn.clicked.connect(self._cancel_deploy)
        self.cancel_btn.setEnabled(False)

        self.clear_btn = QPushButton("🗑 清空")
        self.clear_btn.setFixedHeight(46)
        self.clear_btn.setFixedWidth(80)
        self.clear_btn.setStyleSheet(f"""
            QPushButton {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 {C['accent']}, stop:1 #9b8bff);
                color:#fff; font-size:12px; font-weight:600;
                border-radius:10px; border:none; }}
            QPushButton:hover {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #9b8bff, stop:1 {C['accent']}); }}
        """)
        self.clear_btn.clicked.connect(lambda: self.log_text.clear())

        btn_row.addWidget(self.deploy_btn)
        btn_row.addWidget(self.cancel_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.clear_btn)
        layout.addLayout(btn_row)

        return panel

    # ── 树刷新 ────────────────────────────────────────────────────────────────
    def refresh_tree(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        for srv in db.get_all_servers():
            srv_item = QTreeWidgetItem([f"🖥️  {srv['name']}"])
            srv_item.setData(0, Qt.ItemDataRole.UserRole, {'type': 'server', **srv})
            srv_item.setForeground(0, QColor(C['text']))
            for app in db.get_apps_by_server(srv['id']):
                app_item = QTreeWidgetItem([f"   📦  {app[2]}"])
                app_item.setData(0, Qt.ItemDataRole.UserRole, {
                    'type': 'app', 'server_id': app[1], 'app_id': app[0],
                    'name': app[2], 'jar_name': app[3], 'sh_name': app[4],
                    'sh_path': app[5] if len(app) > 5 else '',
                    'maven_module': app[6] if len(app) > 6 else '',
                    'local_project_path': app[7] if len(app) > 7 else '',
                    'script_args': app[8] if len(app) > 8 else 'restart',
                    'server': srv,
                })
                srv_item.addChild(app_item)
            self.tree.addTopLevelItem(srv_item)
            srv_item.setExpanded(True)
        self.tree.blockSignals(False)

    def _on_tree_click(self, item, col):
        d = item.data(0, Qt.ItemDataRole.UserRole)
        if not d:
            self._selected_server = None
            return
        if d['type'] == 'server':
            self.current_app = None
            self.tree._drag_src_data = None  # 清除拖拽残留
            # ── 关键修复：每次点击都重新设置，不再残留旧值 ──
            self._selected_server = {'id': d['id'], 'name': d['name'],
                                     'ip': d['ip'], 'username': d['username'],
                                     'password': d['password'],
                                     'server_path': d['server_path'],
                                     'remark': d.get('remark', '')}
            self.info_card.setText(
                f"<b style='color:{C['accent']}; font-size:15px;'>🖥 {d['name']}</b><br>"
                f"<span style='color:{C['text2']}'>IP：</span>{d['ip']}<br>"
                f"<span style='color:{C['text2']}'>用户：</span>{d['username']}<br>"
                f"<span style='color:{C['text2']}'>路径：</span>{d['server_path']}<br>"
                f"<span style='color:{C['text2']}'>备注：</span>{d.get('remark','无') or '无'}"
            )
            self.deploy_btn.setEnabled(False)
        else:
            self.current_app = d
            self._selected_server = d['server']
            # 拖拽开始时，记录被拖的应用数据
            self.tree._drag_src_data = d
            s = d['server']
            proj = d.get('local_project_path') or '（未设置）'
            jdk = db.get_setting('jdk_home', '') or '（未设置）'
            mvn = db.get_setting('maven_home', '') or '（未设置）'
            repo = db.get_setting('maven_repo', '') or '（未设置）'
            script_args = d.get('script_args', 'restart')
            sh_path_display = d.get('sh_path') or '（默认项目路径）'
            self.info_card.setText(
                f"<b style='color:{C['accent2']}; font-size:15px;'>📦 {d['name']}</b><br>"
                f"<span style='color:{C['text2']}'>Jar：</span>{d['jar_name']}<br>"
                f"<span style='color:{C['text2']}'>脚本：</span><b>{d['sh_name']}</b> {script_args}<br>"
                f"<span style='color:{C['text2']}'>脚本路径：</span>{sh_path_display}<br>"
                f"<span style='color:{C['text2']}'>服务器：</span>{s['name']} ({s['ip']})<br>"
                f"<span style='color:{C['text2']}'>项目路径：</span>{proj}<br>"
                f"<span style='color:{C['text2']}'>JDK：</span>{jdk}<br>"
                f"<span style='color:{C['text2']}'>Maven：</span>{mvn}<br>"
                f"<span style='color:{C['text2']}'>仓库：</span>{repo}"
            )
            self.deploy_btn.setEnabled(True)

    def _show_tree_menu(self, pos):
        from PyQt6.QtWidgets import QMenu
        item = self.tree.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        d = item.data(0, Qt.ItemDataRole.UserRole)
        if d['type'] == 'server':
            menu.addAction("➕ 新增应用到此服务器", self._add_app)
            menu.addAction("✏️  编辑服务器", self._edit_selected)
            menu.addAction("🗑  删除服务器", self._delete_selected)
        else:
            menu.addAction("🚀 部署此应用", self._do_deploy)
            menu.addAction("✏️  编辑应用", self._edit_selected)
            menu.addAction("📋 复制应用", self._copy_app)
            menu.addAction("🗑 删除应用", self._delete_selected)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _show_tree_menu(self, pos):
        from PyQt6.QtWidgets import QMenu
        item = self.tree.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        d = item.data(0, Qt.ItemDataRole.UserRole)
        if d['type'] == 'server':
            menu.addAction("➕ 新增应用到此服务器", self._add_app)
            menu.addAction("✏️  编辑服务器", self._edit_selected)
            menu.addAction("🗑  删除服务器", self._delete_selected)
        else:
            menu.addAction("🚀 部署此应用", self._do_deploy)
            menu.addAction("✏️  编辑应用", self._edit_selected)
            menu.addAction("📋 复制应用", self._copy_app)
            menu.addAction("🗑 删除应用", self._delete_selected)
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # ── 拖拽移动应用 ─────────────────────────────────────────────────────────
    def eventFilter(self, obj, event):
        """拦截树的拖拽释放事件"""
        if obj is self.tree:
            if event.type() == event.Type.DragLeave:
                return super().eventFilter(obj, event)
            if event.type() == event.Type.Drop:
                # 拖拽释放在 viewport 上，找下方的 server 节点
                pos = event.position().toPoint()
                item = self.tree.itemAt(pos)
                if item:
                    target_data = item.data(0, Qt.ItemDataRole.UserRole)
                    if target_data and target_data.get('type') == 'server':
                        src = getattr(self.tree, '_drag_src_data', None)
                        if src and src.get('type') == 'app':
                            target_server_id = target_data['id']
                            if src.get('server', {}).get('id') == target_server_id:
                                return super().eventFilter(obj, event)
                            from PyQt6.QtWidgets import QMessageBox
                            reply = QMessageBox.question(
                                self, "📋 确认移动应用",
                                f"确定把应用「{src['name']}」移动到服务器「{target_data['name']}」吗？",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                            )
                            if reply == QMessageBox.StandardButton.Yes:
                                db.update_app(
                                    app_id=src['app_id'],
                                    server_id=target_server_id,
                                    name=src['name'],
                                    jar_name=src['jar_name'],
                                    sh_name=src['sh_name'],
                                    maven_module=src.get('maven_module', ''),
                                    local_project_path=src.get('local_project_path', ''),
                                    script_args=src.get('script_args', 'restart'),
                                )
                                self.refresh_tree()
                            return super().eventFilter(obj, event)
        return super().eventFilter(obj, event)

    # ── 部署逻辑 ──────────────────────────────────────────────────────────────
    def _do_deploy(self):
        if not self.current_app:
            return
        self.log_text.clear()
        self.deploy_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.show()
        self.phase_label.show()
        self.phase_label.setText("准备中...")

        app_info = {
            'app_id': self.current_app['app_id'],
            'name': self.current_app['name'],
            'jar_name': self.current_app['jar_name'],
            'sh_name': self.current_app['sh_name'],
            'sh_path': self.current_app.get('sh_path', ''),
            'maven_module': self.current_app.get('maven_module', ''),
            'local_project_path': self.current_app.get('local_project_path', ''),
            'script_args': self.current_app.get('script_args', 'restart'),
            'ip': self.current_app['server']['ip'],
            'username': self.current_app['server']['username'],
            'password': self.current_app['server']['password'],
            'server_path': self.current_app['server']['server_path'],
        }

        self.deploy_thread = DeployThread(
            app_info,
            maven_home=db.get_setting('maven_home', ''),
            maven_repo=db.get_setting('maven_repo', ''),
            jdk_home=db.get_setting('jdk_home', ''),
        )
        self.deploy_thread.log_signal.connect(self._append_log)
        self.deploy_thread.progress_signal.connect(self._update_progress)
        self.deploy_thread.finished_ok.connect(self._on_deploy_ok)
        self.deploy_thread.finished_err.connect(self._on_deploy_err)
        self.deploy_thread.start()
        self.status_bar.showMessage("🚀 部署中...")

    def _cancel_deploy(self):
        if self.deploy_thread and self.deploy_thread.isRunning():
            self.deploy_thread.cancel()
            self._append_log("⛔ 正在取消部署...")

    def _update_progress(self, pct, phase):
        self.progress_bar.setValue(pct)
        labels = {
            'maven': '📦 Maven 打包中...',
            'find_jar': '🔍 查找 Jar 包...',
            'upload': '📤 上传 Jar 中...',
            'hello': '📝 生成部署记录...',
            'verify': '🔍 验证文件...',
            'script': '🖥 执行启动脚本...',
            'done': '🎉 部署完成！',
        }
        self.phase_label.setText(labels.get(phase, phase))

    def _append_log(self, msg):
        self.log_text.append(msg)
        self.log_text.verticalScrollBar().setValue(
            self.log_text.verticalScrollBar().maximum()
        )

    def _on_deploy_ok(self):
        self._deploy_finish(success=True)

    def _on_deploy_err(self, msg):
        self._deploy_finish(success=False)

    def _deploy_finish(self, success):
        self.progress_bar.hide()
        self.phase_label.hide()
        self.deploy_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        msg = "✅ 部署完成" if success else "❌ 部署失败"
        self.status_bar.showMessage(msg)
        self._load_history()

    # ── 历史记录 ──────────────────────────────────────────────────────────────
    def _load_history(self):
        self.hist_list.clear()
        try:
            rows = db.cursor.execute(
                "SELECT app_name, server_ip, status, deployed_at FROM deploy_history ORDER BY id DESC LIMIT 20"
            ).fetchall()
            if not rows:
                self.hist_list.addItem("（暂无记录）")
                return
            for r in rows:
                status_icon = {'success': '✅', 'failed': '❌', 'cancelled': '⏹️'}.get(r[2], '❓')
                ts = r[3] or ''
                if ts:
                    try:
                        # SQLite 时间是 UTC，解析后 +8 小时 = 北京时间
                        import re
                        m = re.match(r'(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})', ts)
                        if m:
                            from datetime import timedelta
                            gg = int(m[1]), int(m[2]), int(m[3]), int(m[4]), int(m[5]), int(m[6])
                            dt = datetime(*gg)
                            dt_bj = dt + timedelta(hours=8)
                            ts = dt_bj.strftime('%m/%d %H:%M')
                        else:
                            ts = ts[:16]
                    except Exception:
                        ts = ts[:16]
                self.hist_list.addItem(f"{status_icon} {r[0]} → {r[1]}  {ts}")
        except Exception:
            self.hist_list.addItem("（读取历史失败）")

    def _on_hist_click(self, item):
        pass  # 可扩展：点击历史显示详情

    # ── CRUD 弹窗 ─────────────────────────────────────────────────────────────
    def _open_settings(self):
        dlg = SettingsDialog(self)
        dlg.exec()

    def _show_help(self):
        if getattr(sys, 'frozen', False):
            help_path = os.path.join(sys._MEIPASS, "HELP.md")
        else:
            help_path = os.path.join(os.path.dirname(__file__), "HELP.md")
        if os.path.exists(help_path):
            with open(help_path, "r", encoding="utf-8") as f:
                content = f.read()
        else:
            content = "HELP.md 文件未找到，请确保文件存在于程序同目录下。"
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton
        dlg = QDialog(self)
        dlg.setWindowTitle("📖 使用说明")
        dlg.setMinimumSize(680, 600)
        dlg.setFont(QFont("Segoe UI", 10))
        layout = QVBoxLayout(dlg)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setMarkdown(content)
        text.setStyleSheet(f"""
            QTextEdit {{ background:{C['surface']}; color:{C['text']};
                border:1px solid {C['border']}; border-radius:8px; padding:12px;
                font-size:13px; line-height:1.7; }}
        """)
        layout.addWidget(text)
        btn = QPushButton("✅ 知道了")
        btn.setFixedSize(100, 36)
        btn.setStyleSheet(f"""
            QPushButton {{ background:{C['accent']}; color:#fff; font-size:13px;
                font-weight:600; border-radius:8px; border:none; }}
            QPushButton:hover {{ background:{C['accent']}cc; }}
        """)
        btn.clicked.connect(dlg.accept)
        layout.addWidget(btn)
        dlg.exec()

    def _add_server(self):
        dlg = ServerDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            db.add_server(**data)
            self.refresh_tree()

    def _add_app(self):
        servers = db.get_all_servers()
        if not servers:
            QMessageBox.warning(self, "提示", "请先添加服务器！")
            return
        # 优先用当前树选中节点的服务器（必须是真实存在的服务器），否则不预设
        preselected = None
        if self._selected_server and self._selected_server.get('id'):
            sel_id = self._selected_server['id']
            if any(s['id'] == sel_id for s in servers):
                preselected = sel_id
        dlg = AppDialog(self, servers=servers, preselected_server_id=preselected)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            data = dlg.get_data()
            db.add_app(**data)
            self.refresh_tree()

    def _edit_selected(self):
        item = self.tree.currentItem()
        if not item:
            QMessageBox.warning(self, "提示", "请先选择要编辑的服务器或应用")
            return
        d = item.data(0, Qt.ItemDataRole.UserRole)
        if d['type'] == 'server':
            dlg = ServerDialog(self, server=d)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                nd = dlg.get_data()
                db.update_server(d['id'], **nd)
                self.refresh_tree()
        else:
            servers = db.get_all_servers()
            dlg = AppDialog(self, app=d, servers=servers)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                nd = dlg.get_data()
                db.update_app(d['app_id'], **nd)
                self.refresh_tree()

    def _delete_selected(self):
        item = self.tree.currentItem()
        if not item:
            QMessageBox.warning(self, "提示", "请先选择要删除的服务器或应用")
            return
        d = item.data(0, Qt.ItemDataRole.UserRole)
        if d['type'] == 'server':
            dlg = ConfirmDialog(
                "🗑 确认删除服务器",
                f"确定删除服务器「{d['name']}」吗？\n\n"
                f"⚠️  该服务器下所有应用也会被一并删除！",
                self, danger=True
            )
            if dlg.exec() == QDialog.DialogCode.Accepted:
                db.delete_server(d['id'])
                self.refresh_tree()
        else:
            dlg = ConfirmDialog(
                "🗑 确认删除应用",
                f"确定删除应用「{d['name']}」吗？",
                self, danger=True
            )
            if dlg.exec() == QDialog.DialogCode.Accepted:
                db.delete_app(d['app_id'])
                self.refresh_tree()

    def _copy_app(self):
        item = self.tree.currentItem()
        if not item or item.data(0, Qt.ItemDataRole.UserRole).get('type') != 'app':
            QMessageBox.warning(self, "提示", "请先选中要复制的应用")
            return
        d = item.data(0, Qt.ItemDataRole.UserRole)
        servers = db.get_all_servers()
        if not servers:
            QMessageBox.warning(self, "提示", "没有可用服务器")
            return
        copy_data = {
            'name': d['name'] + '_copy',
            'jar_name': d['jar_name'],
            'sh_name': d['sh_name'],
            'maven_module': d.get('maven_module', ''),
            'local_project_path': d.get('local_project_path', ''),
            'script_args': d.get('script_args', 'restart'),
            'server_id': d['server']['id'],
        }
        dlg = AppDialog(self, app=copy_data, servers=servers,
                        preselected_server_id=d['server']['id'])
        if dlg.exec() == QDialog.DialogCode.Accepted:
            nd = dlg.get_data()
            if not nd['name'] or not nd['jar_name'] or not nd['server_id']:
                QMessageBox.warning(self, "提示", "名称、Jar包名和服务器不能为空")
                return
            db.add_app(**nd)
            self.refresh_tree()


# ─── 设置对话框 ───────────────────────────────────────────────────────────────
class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚙️  全局设置")
        self.setMinimumWidth(520)
        self.setFont(QFont("Segoe UI", 10))
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        info = QLabel("💡 设置仅需配置一次，保存后永久生效。不填则使用系统环境变量。")
        info.setStyleSheet(f"color:{C['text2']}; font-size:12px; padding:4px;")
        layout.addWidget(info)

        form = QFormLayout()
        self.jdk_le = QLineEdit(placeholderText="例如：C:/environments/java")
        self.jdk_le.setText(db.get_setting('jdk_home', ''))

        self.mvn_le = QLineEdit(placeholderText="例如：D:/Softwares/apache-maven-3.6.3")
        self.mvn_le.setText(db.get_setting('maven_home', ''))

        self.repo_le = QLineEdit(placeholderText="例如：D:/Softwares/maven-repo")
        self.repo_le.setText(db.get_setting('maven_repo', ''))

        self.realm_le = QLineEdit(placeholderText="例如：admin:password（私有仓库认证，可选）")
        self.realm_le.setText(db.get_setting('maven_realm', ''))
        self.realm_le.setEchoMode(QLineEdit.EchoMode.Password)

        form.addRow("JDK 路径：", self.jdk_le)
        form.addRow("Maven 路径：", self.mvn_le)
        form.addRow("Maven 仓库：", self.repo_le)
        form.addRow("私有仓库认证：", self.realm_le)
        layout.addLayout(form)

        hint = QLabel(
            "📌 JDK：编译用的 JDK，确保 bin 里有 javac\n"
            "📌 Maven：Maven 安装根目录\n"
            "📌 仓库：本地 Maven 仓库路径（可加速）\n"
            "📌 认证：私有仓库用户名:密码（可为空）"
        )
        hint.setStyleSheet(f"color:{C['text3']}; font-size:11px; padding:4px;")
        layout.addWidget(hint)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton("✅  确定")
        ok_btn.setFixedSize(100, 36)
        ok_btn.setStyleSheet(f"""
            QPushButton {{ background:{C['accent']}; color:#fff; font-size:13px;
                font-weight:600; border-radius:8px; border:none; }}
            QPushButton:hover {{ background:{C['accent']}cc; }}
        """)
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("✖  取消")
        cancel_btn.setFixedSize(100, 36)
        cancel_btn.setStyleSheet(f"""
            QPushButton {{ background:{C['surface2']}; color:{C['text']}; font-size:13px;
                border:1px solid {C['border']}; border-radius:8px; }}
            QPushButton:hover {{ background:{C['border']}; }}
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

    def accept(self):
        db.set_setting('jdk_home', self.jdk_le.text().strip())
        db.set_setting('maven_home', self.mvn_le.text().strip())
        db.set_setting('maven_repo', self.repo_le.text().strip())
        db.set_setting('maven_realm', self.realm_le.text().strip())
        super().accept()


# ─── 服务器对话框 ──────────────────────────────────────────────────────────────
class ServerDialog(QDialog):
    def __init__(self, parent=None, server=None):
        super().__init__(parent)
        self.server = server or {}
        self.setWindowTitle("✏️  编辑服务器" if server else "➕ 新增服务器")
        self.setMinimumWidth(460)
        self.setFont(QFont("Segoe UI", 10))
        self._build_ui()

    def _build_ui(self):
        layout = QFormLayout(self)

        self.name_le = QLineEdit(placeholderText="例如：测试环境服务器")
        self.name_le.setText(self.server.get('name', ''))
        self.ip_le = QLineEdit(placeholderText="例如：192.168.90.16")
        self.ip_le.setText(self.server.get('ip', ''))
        self.user_le = QLineEdit(placeholderText="用户名")
        self.user_le.setText(self.server.get('username', ''))
        self.pw_le = QLineEdit(placeholderText="密码", echoMode=QLineEdit.EchoMode.Password)
        self.pw_le.setText(self.server.get('password', ''))
        self.pw_toggle_btn = QPushButton("🙈")
        self.pw_toggle_btn.setFixedSize(36, 36)
        self.pw_toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pw_toggle_btn.setStyleSheet(f"""
            QPushButton {{ background:{C['surface2']}; color:{C['text']};
                font-size:15px; border:1px solid {C['border']}; border-radius:8px; }}
            QPushButton:hover {{ background:{C['border']}; }}
        """)
        self.pw_toggle_btn.clicked.connect(self._toggle_password)
        pw_layout = QHBoxLayout()
        pw_layout.addWidget(self.pw_le)
        pw_layout.addWidget(self.pw_toggle_btn)
        pw_layout.setSpacing(6)
        pw_layout.setContentsMargins(0, 0, 0, 0)
        self.path_le = QLineEdit(placeholderText="/home/wuyuan/server/jingzhu-imaster")
        self.path_le.setText(self.server.get('server_path', ''))
        self.remark_le = QLineEdit(placeholderText="备注（可选）")
        self.remark_le.setText(self.server.get('remark', ''))

        layout.addRow("服务器名称：", self.name_le)
        layout.addRow("IP 地址：", self.ip_le)
        layout.addRow("用户名：", self.user_le)
        layout.addRow("密码：", pw_layout)
        layout.addRow("项目路径：", self.path_le)
        layout.addRow("备注：", self.remark_le)

        btn_row = QHBoxLayout()
        test_btn = QPushButton("🔗 测试连接")
        test_btn.setFixedSize(100, 36)
        test_btn.setStyleSheet(f"""
            QPushButton {{ background:{C['surface2']}; color:{C['text']}; font-size:13px;
                border:1px solid {C['border']}; border-radius:8px; }}
            QPushButton:hover {{ background:{C['border']}; }}
        """)
        test_btn.clicked.connect(self._test_connection)
        btn_row.addWidget(test_btn)
        btn_row.addStretch()
        ok_btn = QPushButton("✅  确定")
        ok_btn.setFixedSize(100, 36)
        ok_btn.setStyleSheet(f"""
            QPushButton {{ background:{C['accent']}; color:#fff; font-size:13px;
                font-weight:600; border-radius:8px; border:none; }}
            QPushButton:hover {{ background:{C['accent']}cc; }}
        """)
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("✖  取消")
        cancel_btn.setFixedSize(100, 36)
        cancel_btn.setStyleSheet(f"""
            QPushButton {{ background:{C['surface2']}; color:{C['text']}; font-size:13px;
                border:1px solid {C['border']}; border-radius:8px; }}
            QPushButton:hover {{ background:{C['border']}; }}
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addRow(btn_row)

    def _toggle_password(self):
        if self.pw_le.echoMode() == QLineEdit.EchoMode.Password:
            self.pw_le.setEchoMode(QLineEdit.EchoMode.Normal)
            self.pw_toggle_btn.setText("🐵")
        else:
            self.pw_le.setEchoMode(QLineEdit.EchoMode.Password)
            self.pw_toggle_btn.setText("🙈")

    def accept(self):
        name = self.name_le.text().strip()
        ip = self.ip_le.text().strip()
        if not name or not ip:
            self._show_validation_msg("⚠️  必填项", "服务器名称和 IP 地址不能为空")
            return
        super().accept()

    def _show_validation_msg(self, title, text):
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setMinimumWidth(320)
        dlg.setFont(QFont("Segoe UI", 10))
        dlg.setStyleSheet(f"QDialog {{ background:{C['surface']}; }}")
        layout = QVBoxLayout(dlg)
        layout.setSpacing(14)
        icon_label = QLabel("⚠️")
        icon_label.setStyleSheet("font-size:36px;")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)
        msg = QLabel(text)
        msg.setStyleSheet(f"color:{C['text']}; font-size:13px; line-height:1.6;")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setWordWrap(True)
        layout.addWidget(msg)
        ok_btn = QPushButton("✅  知道了")
        ok_btn.setFixedSize(120, 36)
        ok_btn.setStyleSheet(f"""
            QPushButton {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 {C['accent']}, stop:1 #9b8bff);
                color:#fff; font-size:13px; font-weight:600;
                border-radius:9px; border:none; }}
            QPushButton:hover {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #9b8bff, stop:1 {C['accent']}); }}
        """)
        ok_btn.clicked.connect(dlg.accept)
        layout.addWidget(ok_btn, alignment=Qt.AlignmentFlag.AlignHCenter)
        dlg.exec()

    def _test_connection(self):
        import paramiko, socket
        ip = self.ip_le.text().strip()
        user = self.user_le.text().strip()
        pw = self.pw_le.text()
        if not ip or not user:
            self._show_msg("⚠️  请填写", "IP 地址和用户名不能为空", False)
            return
        btn = self.sender()
        btn.setText("🔄 连接中...")
        btn.setEnabled(False)
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(ip, username=user, password=pw, timeout=8,
                          banner_timeout=8, auth_timeout=8)
            client.close()
            self._show_msg("✅ 连接成功", f"服务器 {ip} 连接正常！", True)
        except paramiko.AuthenticationException:
            self._show_msg("❌ 认证失败", "用户名或密码错误", False)
        except socket.timeout:
            self._show_msg("❌ 连接超时", f"无法连接到 {ip}，请检查 IP 和网络", False)
        except Exception as e:
            self._show_msg("❌ 连接失败", f"连接 {ip} 失败：\n{str(e)}", False)
        finally:
            btn.setText("🔗 测试连接")
            btn.setEnabled(True)

    def _show_msg(self, title, text, success):
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setMinimumWidth(340)
        dlg.setFont(QFont("Segoe UI", 10))
        dlg.setStyleSheet(f"""
            QDialog {{ background:{C['surface']}; }}
        """)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(16)
        icon_label = QLabel("✅" if success else "❌")
        icon_label.setStyleSheet(f"font-size:40px;")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)
        msg = QLabel(text)
        msg.setStyleSheet(f"color:{C['text']}; font-size:13px; line-height:1.6;")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setWordWrap(True)
        layout.addWidget(msg)
        ok_btn = QPushButton("✅ 知道了")
        ok_btn.setFixedSize(120, 38)
        ok_btn.setStyleSheet(f"""
            QPushButton {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 {C['accent']}, stop:1 #9b8bff);
                color:#fff; font-size:13px; font-weight:600;
                border-radius:9px; border:none; }}
            QPushButton:hover {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #9b8bff, stop:1 {C['accent']}); }}
        """)
        ok_btn.clicked.connect(dlg.accept)
        layout.addWidget(ok_btn, alignment=Qt.AlignmentFlag.AlignHCenter)
        dlg.exec()

    def get_data(self):
        return {
            'name': self.name_le.text().strip(),
            'ip': self.ip_le.text().strip(),
            'username': self.user_le.text().strip(),
            'password': self.pw_le.text(),
            'server_path': self.path_le.text().strip(),
            'remark': self.remark_le.text().strip(),
        }


# ─── 应用对话框 ───────────────────────────────────────────────────────────────
class AppDialog(QDialog):
    def __init__(self, parent=None, app=None, servers=None, preselected_server_id=None):
        super().__init__(parent)
        self.app = app or {}
        self.servers = servers or []
        self.preselected = preselected_server_id
        self.setWindowTitle("✏️  编辑应用" if app else "➕ 新增应用")
        self.setMinimumWidth(510)
        self.setFont(QFont("Segoe UI", 10))
        self._build_ui()

    def _build_ui(self):
        layout = QFormLayout(self)

        self.name_le = QLineEdit(placeholderText="例如：industry")
        self.name_le.setText(self.app.get('name', ''))
        self.jar_le = QLineEdit(placeholderText="例如：industry-0.0.1-SNAPSHOT.jar")
        self.jar_le.setText(self.app.get('jar_name', ''))
        self.sh_le = QLineEdit(placeholderText="例如：uu-industry.sh")
        self.sh_le.setText(self.app.get('sh_name', ''))
        self.sh_path_le = QLineEdit(placeholderText="脚本所在目录，不填则使用项目路径（服务器上）")
        self.sh_path_le.setText(self.app.get('sh_path', ''))
        self.module_le = QLineEdit(placeholderText="多模块项目填子模块名（可选）")
        self.module_le.setText(self.app.get('maven_module', ''))
        self.local_le = QLineEdit(placeholderText="例如：D:/ideaProjects/companyProject/IMasterR/iMaster-Api")
        self.local_le.setText(self.app.get('local_project_path', ''))
        self.script_args_le = QLineEdit(placeholderText="start / stop / restart（默认 restart）")
        self.script_args_le.setText(self.app.get('script_args', 'restart'))

        self.server_cmb = QComboBox()
        self.server_cmb.addItems([s['name'] for s in self.servers])
        target = self.app.get('server_id') or self.preselected
        if target:
            for i, s in enumerate(self.servers):
                if s['id'] == target:
                    self.server_cmb.setCurrentIndex(i)
                    break

        layout.addRow("应用名称：", self.name_le)
        layout.addRow("Jar 包名：", self.jar_le)
        layout.addRow("启动脚本：", self.sh_le)
        layout.addRow("脚本路径：", self.sh_path_le)
        layout.addRow("脚本参数：", self.script_args_le)
        layout.addRow("Maven模块：", self.module_le)
        layout.addRow("本地项目路径：", self.local_le)
        layout.addRow("所属服务器：", self.server_cmb)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton("✅  确定")
        ok_btn.setFixedSize(100, 36)
        ok_btn.setStyleSheet(f"""
            QPushButton {{ background:{C['accent']}; color:#fff; font-size:13px;
                font-weight:600; border-radius:8px; border:none; }}
            QPushButton:hover {{ background:{C['accent']}cc; }}
        """)
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("✖  取消")
        cancel_btn.setFixedSize(100, 36)
        cancel_btn.setStyleSheet(f"""
            QPushButton {{ background:{C['surface2']}; color:{C['text']}; font-size:13px;
                border:1px solid {C['border']}; border-radius:8px; }}
            QPushButton:hover {{ background:{C['border']}; }}
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addRow(btn_row)

    def get_data(self):
        idx = self.server_cmb.currentIndex()
        server_id = self.servers[idx]['id'] if idx >= 0 and idx < len(self.servers) else None
        return {
            'name': self.name_le.text().strip(),
            'jar_name': self.jar_le.text().strip(),
            'sh_name': self.sh_le.text().strip(),
            'sh_path': self.sh_path_le.text().strip(),
            'script_args': self.script_args_le.text().strip() or 'restart',
            'maven_module': self.module_le.text().strip(),
            'local_project_path': self.local_le.text().strip(),
            'server_id': server_id,
        }

    def accept(self):
        idx = self.server_cmb.currentIndex()
        server_id = self.servers[idx]['id'] if idx >= 0 and idx < len(self.servers) else None
        if not self.name_le.text().strip() or not self.jar_le.text().strip() or not server_id:
            self._show_validation_msg("⚠️  必填项", "名称、Jar包名和服务器不能为空")
            return
        super().accept()

    def _show_validation_msg(self, title, text):
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setMinimumWidth(320)
        dlg.setFont(QFont("Segoe UI", 10))
        dlg.setStyleSheet(f"QDialog {{ background:{C['surface']}; }}")
        layout = QVBoxLayout(dlg)
        layout.setSpacing(14)
        icon_label = QLabel("⚠️")
        icon_label.setStyleSheet("font-size:36px;")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label)
        msg = QLabel(text)
        msg.setStyleSheet(f"color:{C['text']}; font-size:13px; line-height:1.6;")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setWordWrap(True)
        layout.addWidget(msg)
        ok_btn = QPushButton("✅  知道了")
        ok_btn.setFixedSize(120, 36)
        ok_btn.setStyleSheet(f"""
            QPushButton {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 {C['accent']}, stop:1 #9b8bff);
                color:#fff; font-size:13px; font-weight:600;
                border-radius:9px; border:none; }}
            QPushButton:hover {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #9b8bff, stop:1 {C['accent']}); }}
        """)
        ok_btn.clicked.connect(dlg.accept)
        layout.addWidget(ok_btn, alignment=Qt.AlignmentFlag.AlignHCenter)
        dlg.exec()


# ─── 入口 ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)

    # 设置窗口图标（任务栏 + 窗口左上角）
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后的 exe，图标在临时目录
        icon_path = os.path.join(sys._MEIPASS, "icon.ico")
    else:
        icon_path = os.path.join(os.path.dirname(__file__), "icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # Splash screen - 立即显示，不卡顿
    if getattr(sys, 'frozen', False):
        splash_img = os.path.join(sys._MEIPASS, "icon.jpg")
    else:
        splash_img = os.path.join(os.path.dirname(__file__), "icon.jpg")
    if os.path.exists(splash_img):
        splash_pix = QPixmap(splash_img).scaled(300, 300, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    else:
        splash_pix = QPixmap(400, 300)
        splash_pix.fill(QColor(C['surface']))

    splash = QSplashScreen(splash_pix, Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
    splash.setFont(QFont("Segoe UI", 11))
    loading_label = QLabel("正在启动...")
    loading_label.setStyleSheet(f"color:{C['text']}; font-weight:600; font-size:13px; margin-top:8px;")
    loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    sp_layout = QVBoxLayout()
    sp_layout.addStretch()
    sp_layout.addWidget(loading_label)
    sp_container = QWidget()
    sp_container.setLayout(sp_layout)
    sp_container.setStyleSheet(f"background:transparent;")

    # 用QLabel叠加文字
    splash.setStyleSheet(f"background:{C['surface']}; border:none; border-radius:16px;")
    splash.showMessage("正在启动...", Qt.AlignmentFlag.AlignCenter, QColor(C['text']))
    splash.show()

    def on_window_ready():
        w.show()
        splash.finish(w)

    w = MainWindow()
    # 窗口准备好后显示
    QTimer.singleShot(50, on_window_ready)

    sys.exit(app.exec())
