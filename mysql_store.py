"""新网页的唯一业务存储：MySQL；不读取或迁移旧教学数据库。"""
import hashlib
import secrets
from uuid import uuid4
from datetime import datetime, timezone
import pymysql


class QuotaExceeded(Exception):
    pass


class MySQLStore:
    def __init__(self, config):
        self.config = config

    def connection(self):
        return pymysql.connect(**self.config.connect_args(),
                               cursorclass=pymysql.cursors.DictCursor, autocommit=False)

    def setup(self):
        # Database must be created explicitly, so startup cannot alter old databases.
        schemas = [
            """CREATE TABLE IF NOT EXISTS web_visitors (
                owner_id CHAR(32) PRIMARY KEY, token_hash CHAR(64) UNIQUE NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL DEFAULT (CURRENT_TIMESTAMP + INTERVAL 7 DAY)
            ) ENGINE=InnoDB""",
            """CREATE TABLE IF NOT EXISTS web_tasks (
                task_id CHAR(32) PRIMARY KEY, owner_id CHAR(32) NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX(owner_id, created_at)
            ) ENGINE=InnoDB""",
            """CREATE TABLE IF NOT EXISTS web_orders (
                order_id VARCHAR(64) PRIMARY KEY, request_id VARCHAR(64) UNIQUE NOT NULL,
                owner_id CHAR(32) NOT NULL, room_id VARCHAR(32) NOT NULL,
                description TEXT NOT NULL, status VARCHAR(20) NOT NULL DEFAULT '待处理',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX(owner_id, created_at)
            ) ENGINE=InnoDB""",
            """CREATE TABLE IF NOT EXISTS demo_fees (
                room_id VARCHAR(32) PRIMARY KEY, amount DECIMAL(10,2) NOT NULL
            ) ENGINE=InnoDB""",
            """CREATE TABLE IF NOT EXISTS web_usage (
                scope VARCHAR(64) NOT NULL, day DATE NOT NULL, used INT NOT NULL,
                PRIMARY KEY(scope, day)
            ) ENGINE=InnoDB""",
        ]
        with self.connection() as conn:
            with conn.cursor() as cur:
                for sql in schemas:
                    cur.execute(sql)
                cur.executemany("INSERT IGNORE INTO demo_fees(room_id,amount) VALUES(%s,%s)",
                                [("A101", 100), ("B202", 200), ("C303", 0)])
            conn.commit()

    def ping(self):
        with self.connection() as conn:
            conn.ping(reconnect=False)

    def resolve_visitor(self, token):
        if not token or len(token) > 100:
            return None
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT owner_id FROM web_visitors WHERE token_hash=%s AND expires_at>NOW()", (digest,))
            row = cur.fetchone()
            return row["owner_id"] if row else None

    def new_visitor(self):
        owner, token = uuid4().hex, secrets.token_urlsafe(32)
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO web_visitors(owner_id,token_hash) VALUES(%s,%s)",
                        (owner, hashlib.sha256(token.encode()).hexdigest()))
            conn.commit()
        return owner, token

    def consume(self, owner):
        day = datetime.now(timezone.utc).date()
        # Lock in fixed order; rolled back together if either limit is exceeded.
        with self.connection() as conn, conn.cursor() as cur:
            try:
                for scope, limit in [("global", self.config.global_quota), (owner, self.config.session_quota)]:
                    cur.execute("INSERT IGNORE INTO web_usage(scope,day,used) VALUES(%s,%s,0)", (scope, day))
                    cur.execute("SELECT used FROM web_usage WHERE scope=%s AND day=%s FOR UPDATE", (scope, day))
                    if cur.fetchone()["used"] >= limit:
                        raise QuotaExceeded("今日演示额度已用完，请稍后再试")
                    cur.execute("UPDATE web_usage SET used=used+1 WHERE scope=%s AND day=%s", (scope, day))
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def register_task(self, owner, task_id):
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO web_tasks(task_id,owner_id) VALUES(%s,%s)", (task_id, owner))
            conn.commit()

    def owns_task(self, owner, task_id):
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT task_id FROM web_tasks WHERE task_id=%s AND owner_id=%s", (task_id, owner))
            return cur.fetchone() is not None

    def tasks(self, owner):
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT task_id,created_at FROM web_tasks WHERE owner_id=%s ORDER BY created_at DESC LIMIT 20", (owner,))
            return cur.fetchall()

    def fee(self, room):
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT room_id,amount FROM demo_fees WHERE room_id=%s", (room,))
            row = cur.fetchone()
            if row:
                row["amount"] = float(row["amount"])
            return row

    def orders(self, owner):
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT order_id,room_id,description,status,created_at FROM web_orders WHERE owner_id=%s ORDER BY created_at DESC LIMIT 20", (owner,))
            return cur.fetchall()

    def create_order(self, state, owner):
        if not owner or state.get("approved") is not True:
            raise ValueError("未经授权或确认的写入")
        for key in ("request_id", "room_id", "description"):
            if not isinstance(state.get(key), str) or not state[key].strip():
                raise ValueError("缺少有效字段")
        room = state["room_id"].strip().upper()
        if not self.fee(room):
            raise ValueError("仅支持演示房间A101/B202/C303")
        candidate = "WO-" + uuid4().hex
        with self.connection() as conn, conn.cursor() as cur:
            try:
                cur.execute("""INSERT INTO web_orders(order_id,request_id,owner_id,room_id,description)
                    VALUES(%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE request_id=request_id""",
                            (candidate, state["request_id"], owner, room, state["description"]))
                cur.execute("SELECT order_id,owner_id,room_id,description FROM web_orders WHERE request_id=%s FOR UPDATE", (state["request_id"],))
                row = cur.fetchone()
                if not row or (row["owner_id"], row["room_id"], row["description"]) != (owner, room, state["description"]):
                    raise ValueError("请求编号对应内容或访客不一致")
                conn.commit()
                return {"order_id": row["order_id"], "created": row["order_id"] == candidate}
            except Exception:
                conn.rollback()
                raise
