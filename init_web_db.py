"""显式初始化独立演示数据库，不迁移旧数据。"""
import argparse
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env", override=False)
import pymysql
from web_config import WebConfig
from mysql_store import MySQLStore


def initialize(config, *, create_database=False):
    if create_database:
        args = config.connect_args()
        args.pop("db")
        with pymysql.connect(**args, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{config.mysql_database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_bin")
    MySQLStore(config).setup()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--create-database", action="store_true")
    args = parser.parse_args()
    try:
        initialize(WebConfig.from_env(), create_database=args.create_database)
        print("演示数据库初始化完成；未改动旧工单或检查点。")
    except Exception as exc:
        print("初始化失败：", type(exc).__name__, "请检查MySQL服务、环境变量和数据库权限。")
        raise SystemExit(1)
