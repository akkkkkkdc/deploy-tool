import os
import subprocess
import threading
import paramiko
from pathlib import Path


class Deployer:
    def __init__(self, app_info: dict, log_callback=None):
        """
        app_info: {
            'jar_name': 'industry-0.0.1-SNAPSHOT.jar',
            'sh_name': 'uu-industry.sh',
            'maven_module': '',  # 可选
            'ip': '192.168.90.16',
            'username': 'root',
            'password': '123456',
            'server_path': '/home/wuyuan/server/jingzhu-imaster'
        }
        log_callback: 回调函数，用于实时输出日志
        """
        self.app = app_info
        self.log = log_callback or (lambda x: None)
        self._stop_flag = threading.Event()

    def log_msg(self, msg):
        self.log(f"[{self._timestamp()}] {msg}")

    def _timestamp(self):
        from datetime import datetime
        return datetime.now().strftime("%H:%M:%S")

    def run(self):
        """执行完整部署流程"""
        try:
            self.log_msg("=" * 50)
            self.log_msg("🚀 部署开始")
            self.log_msg("=" * 50)

            # Step 1: Maven 打包
            self._maven_package()

            # Step 2: 上传 jar
            jar_path = self._find_jar()
            self._upload_jar(jar_path)

            # Step 3: 执行启动脚本
            self._run_shell_script()

            self.log_msg("✅ 部署完成！")
        except Exception as e:
            self.log_msg(f"❌ 部署失败: {e}")

    def _maven_package(self):
        self.log_msg("📦 Maven 打包中 (mvn clean package -DskipTests)...")
        cmd = ["mvn", "clean", "package", "-DskipTests"]
        if self.app.get('maven_module'):
            cmd.extend(["-pl", self.app['maven_module'], "-am"])
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            universal_newlines=True
        )
        for line in proc.stdout:
            stripped = line.rstrip()
            if stripped:
                self.log_msg(f"   {stripped}")
        proc.wait()
        if proc.returncode != 0:
            raise Exception(f"Maven 打包失败 (exit code {proc.returncode})")
        self.log_msg("✅ Maven 打包完成")

    def _find_jar(self) -> str:
        """找到 target 目录下的 jar 文件"""
        jar_name = self.app['jar_name']
        # 优先精确匹配
        jar_path = os.path.join("target", jar_name)
        if os.path.exists(jar_path):
            self.log_msg(f"   找到 jar: {jar_path}")
            return jar_path
        # 否则模糊匹配
        target_dir = Path("target")
        for f in target_dir.rglob("*.jar"):
            if "original" not in f.name and f.name.endswith(".jar"):
                self.log_msg(f"   找到 jar: {f}")
                return str(f)
        raise Exception(f"未找到 jar 包: {jar_name}")

    def _upload_jar(self, jar_path: str):
        self.log_msg(f"📤 上传 jar 到 {self.app['ip']}...")
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname=self.app['ip'],
            username=self.app['username'],
            password=self.app['password'],
            timeout=10
        )
        sftp = ssh.open_sftp()
        remote_path = os.path.join(self.app['server_path'], os.path.basename(jar_path))
        sftp.put(jar_path, remote_path)
        sftp.close()
        ssh.close()
        self.log_msg("✅ jar 上传完成")

    def _run_shell_script(self):
        self.log_msg(f"🖥️  执行启动脚本 {self.app['sh_name']} ...")
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname=self.app['ip'],
            username=self.app['username'],
            password=self.app['password'],
            timeout=10
        )
        cmd = f"cd {self.app['server_path']} && sh {self.app['sh_name']}"
        stdin, stdout, stderr = ssh.exec_command(cmd)
        output = stdout.read().decode()
        error = stderr.read().decode()
        ssh.close()
        if error:
            self.log_msg(f"   脚本输出: {error}")
        if output:
            self.log_msg(f"   脚本输出: {output}")
        self.log_msg("✅ 启动脚本执行完成")
