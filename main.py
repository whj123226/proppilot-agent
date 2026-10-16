from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from uuid import uuid4
import pymysql
from database import get_connection
from qwen_client import run_agent
app = FastAPI()
fees = {
    "A101":100,
    "B202":200,
    "C303":0
}
work_orders = {
    "A101": [
        {
            "order_id": "WO-001",
            "description": "卫生间水龙头漏水",
            "status": "处理中"
        }
    ],
    "B202": [
        {
            "order_id": "WO-002",
            "description": "厨房灯具损坏",
            "status": "待处理"
        },
        {
            "order_id": "WO-003",
            "description": "门锁故障",
            "status": "已完成"
        }
    ],
    "C303": []
}
class RepairRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=64)
    room_id: str
    description: str
class AgentRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


@app.post("/agent")
async def ask_agent(request: AgentRequest):
    answer = await run_agent(request.question)

    return {
        "answer": answer
    }
@app.get("/")
async def home():
    return {"message": "PropPilot ERP服务已启动"}

@app.get("/fees")
async def get_fees(room_id:str):
    if room_id not in fees:
        raise HTTPException(
            status_code=404,
            detail="房屋不存在"
        )
    return{
        "success":True,
        "data":{
            "room_id": room_id,
            "amount": fees[room_id]
        },
        "error":None
    }
@app.post("/work-orders")
def create_work_order(repair: RepairRequest):
    # 暂时使用已有的房屋编号检查
    if repair.room_id not in fees:
        raise HTTPException(
            status_code=404,
            detail="房屋不存在"
        )

    new_order = {
        "order_id": f"WO-{uuid4().hex}",
        "request_id": repair.request_id,
        "room_id": repair.room_id,
        "description": repair.description,
        "status": "待处理"
    }

    connection = get_connection()

    try:
        with connection.cursor() as cursor:
            sql = """
                INSERT INTO work_orders (
                    order_id, request_id, room_id, description, status
                )
                VALUES (%s, %s, %s, %s, %s)
            """

            cursor.execute(
                sql,
                (
                    new_order["order_id"],
                    new_order["request_id"],
                    new_order["room_id"],
                    new_order["description"],
                    new_order["status"]
                )
            )

        connection.commit()

        return {
            "success": True,
            "data": new_order,
            "error": None
        }

    except pymysql.MySQLError as exc:
        connection.rollback()
        raise HTTPException(
            status_code=500,
            detail="数据库保存失败"
        ) from exc

    finally:
        connection.close()


@app.get("/work-orders")
def get_work_orders(room_id: str):
    if room_id not in fees:
        raise HTTPException(
            status_code=404,
            detail="房屋不存在"
        )

    connection = get_connection()

    try:
        with connection.cursor() as cursor:
            sql = """
                SELECT order_id, room_id, description, status
                FROM work_orders
                WHERE room_id = %s
            """

            cursor.execute(sql, (room_id,))
            orders = cursor.fetchall()

        return {
            "success": True,
            "data": {
                "room_id": room_id,
                "work_orders": orders
            },
            "error": None
        }

    except pymysql.MySQLError as exc:
        raise HTTPException(
            status_code=500,
            detail="数据库查询失败"
        ) from exc

    finally:
        connection.close()
