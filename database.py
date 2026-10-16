import os

import pymysql


def get_connection():
    password = os.getenv("MYSQL_PASSWORD")

    if password is None:
        raise RuntimeError("请先配置 MYSQL_PASSWORD")

    return pymysql.connect(
        host="localhost",
        port=3306,
        user="root",
        password=password,
        database="proppilot",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5
    )