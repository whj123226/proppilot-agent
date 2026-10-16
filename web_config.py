"""网页演示配置，凭证不进入代码或前端。"""
import os
import re
from dataclasses import dataclass


@dataclass
class WebConfig:
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "proppilot_showcase"
    mode: str = "fixture"
    secure_cookie: bool = False
    session_quota: int = 40
    global_quota: int = 300

    @classmethod
    def from_env(cls):
        cfg = cls(
            mysql_host=os.getenv("MYSQL_HOST", "127.0.0.1"),
            mysql_port=int(os.getenv("MYSQL_PORT", "3306")),
            mysql_user=os.getenv("MYSQL_USER", "root"),
            mysql_password=os.getenv("MYSQL_PASSWORD", ""),
            mysql_database=os.getenv("MYSQL_DATABASE", "proppilot_showcase"),
            mode=os.getenv("APP_MODE", "fixture"),
            secure_cookie=os.getenv("COOKIE_SECURE", "false").lower() == "true",
            session_quota=int(os.getenv("SESSION_DAILY_QUOTA", "40")),
            global_quota=int(os.getenv("GLOBAL_DAILY_QUOTA", "300")),
        )
        if not re.fullmatch(r"[a-zA-Z0-9_]+", cfg.mysql_database):
            raise ValueError("MYSQL_DATABASE只能包含字母、数字和下划线")
        if not cfg.mysql_password:
            raise ValueError("请在环境变量或项目.env中设置MYSQL_PASSWORD")
        if cfg.mode not in {"fixture", "live"}:
            raise ValueError("APP_MODE必须为fixture或live")
        if not (1 <= cfg.session_quota <= 1000 and 1 <= cfg.global_quota <= 10000):
            raise ValueError("演示额度配置超出范围")
        return cfg

    def connect_args(self):
        return dict(host=self.mysql_host, port=self.mysql_port, user=self.mysql_user,
                    password=self.mysql_password, db=self.mysql_database,
                    charset="utf8mb4", connect_timeout=5)
