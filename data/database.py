import sqlite3
import os
import base64
import hashlib
from cryptography.fernet import Fernet

# 数据统一存在 D:\skills\deply\data\，与软件目录分离，升级软件不丢数据
DATA_DIR = r"D:\skills\deply\data"
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "deploy_tool.db")


def get_encryption_key():
    """生成一个稳定的加密key（基于固定种子）"""
    key_bytes = hashlib.sha256(b"jingzhu-deploy-tool-secret-key-2024").digest()
    return base64.urlsafe_b64encode(key_bytes)


class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.fernet = Fernet(get_encryption_key())
        self._migrate()
        self.init_tables()

    def _migrate(self):
        """迁移旧数据库，添加新增字段"""
        # apps 表新增 script_args 列
        try:
            self.cursor.execute("ALTER TABLE apps ADD COLUMN script_args TEXT DEFAULT 'restart'")
            self.conn.commit()
        except sqlite3.OperationalError:
            pass  # 列已存在
        # apps 表新增 sh_path 列
        try:
            self.cursor.execute("ALTER TABLE apps ADD COLUMN sh_path TEXT DEFAULT ''")
            self.conn.commit()
        except sqlite3.OperationalError:
            pass  # 列已存在

    def init_tables(self):
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS servers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                ip TEXT NOT NULL,
                username TEXT NOT NULL,
                password_encrypted TEXT NOT NULL,
                server_path TEXT NOT NULL,
                remark TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS apps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                jar_name TEXT NOT NULL,
                sh_name TEXT NOT NULL,
                sh_path TEXT DEFAULT '',
                maven_module TEXT DEFAULT '',
                local_project_path TEXT DEFAULT '',
                script_args TEXT DEFAULT 'restart',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE
            )
        """)
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        self.cursor.execute("""
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
        self.conn.commit()

    def encrypt_password(self, password: str) -> str:
        return self.fernet.encrypt(password.encode()).decode()

    def decrypt_password(self, encrypted: str) -> str:
        return self.fernet.decrypt(encrypted.encode()).decode()

    def get_setting(self, key: str, default: str = '') -> str:
        self.cursor.execute("SELECT value FROM settings WHERE key=?", (key,))
        row = self.cursor.fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str):
        self.cursor.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value)
        )
        self.conn.commit()

    # ── 服务器 CRUD ─────────────────────────────────────────────────────────
    def add_server(self, name, ip, username, password, server_path, remark=''):
        encrypted = self.encrypt_password(password)
        self.cursor.execute(
            "INSERT INTO servers (name, ip, username, password_encrypted, server_path, remark) VALUES (?, ?, ?, ?, ?, ?)",
            (name, ip, username, encrypted, server_path, remark)
        )
        self.conn.commit()
        return self.cursor.lastrowid

    def get_all_servers(self):
        self.cursor.execute(
            "SELECT id, name, ip, username, password_encrypted, server_path, remark FROM servers ORDER BY id"
        )
        rows = self.cursor.fetchall()
        result = []
        for r in rows:
            result.append({
                'id': r[0], 'name': r[1], 'ip': r[2], 'username': r[3],
                'password': self.decrypt_password(r[4]),
                'server_path': r[5], 'remark': r[6]
            })
        return result

    def update_server(self, server_id, name, ip, username, password, server_path, remark=''):
        encrypted = self.encrypt_password(password)
        self.cursor.execute(
            "UPDATE servers SET name=?, ip=?, username=?, password_encrypted=?, server_path=?, remark=? WHERE id=?",
            (name, ip, username, encrypted, server_path, remark, server_id)
        )
        self.conn.commit()

    def delete_server(self, server_id):
        self.cursor.execute("DELETE FROM servers WHERE id=?", (server_id,))
        self.cursor.execute("DELETE FROM apps WHERE server_id=?", (server_id,))
        self.conn.commit()

    # ── 应用 CRUD ───────────────────────────────────────────────────────────
    def add_app(self, server_id, name, jar_name, sh_name, sh_path='',
                maven_module='', local_project_path='', script_args='restart'):
        self.cursor.execute(
            "INSERT INTO apps (server_id, name, jar_name, sh_name, sh_path, maven_module, local_project_path, script_args) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (server_id, name, jar_name, sh_name, sh_path, maven_module, local_project_path, script_args)
        )
        self.conn.commit()
        return self.cursor.lastrowid

    def get_apps_by_server(self, server_id):
        self.cursor.execute(
            "SELECT id, server_id, name, jar_name, sh_name, sh_path, maven_module, local_project_path, script_args FROM apps WHERE server_id=?",
            (server_id,)
        )
        return self.cursor.fetchall()

    def get_all_apps(self):
        self.cursor.execute("""
            SELECT a.id, a.server_id, a.name, a.jar_name, a.sh_name, a.sh_path, a.maven_module,
                   a.local_project_path, a.script_args,
                   s.name as server_name, s.ip, s.username, s.password_encrypted, s.server_path
            FROM apps a
            JOIN servers s ON a.server_id = s.id
        """)
        rows = self.cursor.fetchall()
        result = []
        for r in rows:
            result.append({
                'id': r[0], 'server_id': r[1], 'name': r[2], 'jar_name': r[3],
                'sh_name': r[4], 'sh_path': r[5], 'maven_module': r[6], 'local_project_path': r[7],
                'script_args': r[8],
                'server_name': r[9], 'ip': r[10], 'username': r[11],
                'password': self.decrypt_password(r[12]), 'server_path': r[13]
            })
        return result

    def get_app_by_id(self, app_id):
        self.cursor.execute("""
            SELECT a.id, a.server_id, a.name, a.jar_name, a.sh_name, a.sh_path, a.maven_module,
                   a.local_project_path, a.script_args,
                   s.name as server_name, s.ip, s.username, s.password_encrypted, s.server_path
            FROM apps a
            JOIN servers s ON a.server_id = s.id
            WHERE a.id=?
        """, (app_id,))
        r = self.cursor.fetchone()
        if r:
            return {
                'id': r[0], 'server_id': r[1], 'name': r[2], 'jar_name': r[3],
                'sh_name': r[4], 'sh_path': r[5], 'maven_module': r[6], 'local_project_path': r[7],
                'script_args': r[8],
                'server_name': r[9], 'ip': r[10], 'username': r[11],
                'password': self.decrypt_password(r[12]), 'server_path': r[13]
            }
        return None

    def update_app(self, app_id, server_id, name, jar_name, sh_name, sh_path='',
                   maven_module='', local_project_path='', script_args='restart'):
        self.cursor.execute(
            "UPDATE apps SET server_id=?, name=?, jar_name=?, sh_name=?, sh_path=?, maven_module=?, local_project_path=?, script_args=? WHERE id=?",
            (server_id, name, jar_name, sh_name, sh_path, maven_module, local_project_path, script_args, app_id)
        )
        self.conn.commit()

    def delete_app(self, app_id):
        self.cursor.execute("DELETE FROM apps WHERE id=?", (app_id,))
        self.conn.commit()

    # ── 部署历史 ────────────────────────────────────────────────────────────
    def add_deploy_history(self, app_id, app_name, jar_name, server_ip, status):
        self.cursor.execute(
            "INSERT INTO deploy_history (app_id, app_name, jar_name, server_ip, status) VALUES (?, ?, ?, ?, ?)",
            (app_id, app_name, jar_name, server_ip, status)
        )
        self.conn.commit()


db = Database()
