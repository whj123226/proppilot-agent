"""本地模拟工单存储，与流程编排和控制台交互无关。"""

import sqlite3
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4
from settings import ORDER_DB_PATH

DEFAULT_DB_PATH = ORDER_DB_PATH


def create_demo_order(
    state: Mapping[str, Any], *, db_path: str | Path | None = None
) -> dict:
    """保存已确认的模拟报修；同一请求及内容返回原工单。

    db_path 仅用于显式选择存储位置，测试必须传入临时数据库。
    不导入LangGraph，也不调用真实ERP。
    """
    # 程序层面检查确认状态
    if state.get("approved") is not True:
        raise ValueError("用户尚未确认，禁止创建模拟工单")

    request_id = state.get("request_id")
    if not request_id:
        raise ValueError("缺少请求编号，请用新的任务编号开始测试")

    db_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(str(db_path), timeout=10)

    try:
        with connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS demo_orders (
                    request_id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL UNIQUE,
                    room_id TEXT NOT NULL,
                    description TEXT NOT NULL
                )
            """)

            candidate_order_id = f"DEMO-WO-{uuid4().hex}"

            cursor = connection.execute(
                """
                INSERT INTO demo_orders (
                    request_id, order_id, room_id, description
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(request_id) DO NOTHING
                """,
                (
                    request_id,
                    candidate_order_id,
                    state["room_id"],
                    state["description"],
                ),
            )

            created = cursor.rowcount == 1

            row = connection.execute(
                """
                SELECT order_id, room_id, description
                FROM demo_orders
                WHERE request_id = ?
                """,
                (request_id,),
            ).fetchone()

            if row is None:
                raise RuntimeError("未找到模拟工单")

            # 同一请求编号不能拿来提交另一份内容
            if (
                row[1] != state["room_id"]
                or row[2] != state["description"]
            ):
                raise ValueError("同一请求编号对应的报修内容不一致")

            return {
                "order_id": row[0],
                "created": created,
            }

    finally:
        connection.close()
