from uuid import uuid4

import httpx
from settings import ERP_BASE_URL, ERP_TIMEOUT
async def query_fee(room_id):
    async with httpx.AsyncClient(
        timeout=ERP_TIMEOUT,
        trust_env=False
    ) as client:
        try:
            response = await client.get(
                f"{ERP_BASE_URL}/fees",
                params={"room_id": room_id}
            )
            response.raise_for_status()
            return response.json()

        except httpx.TimeoutException:
            return {
                "success": False,
                "error": "ERP查询超时"
            }

        except httpx.RequestError:
            return {
                "success": False,
                "error": "无法连接ERP服务"
            }

        except httpx.HTTPStatusError as exc:
            return {
                "success": False,
                "error": f"ERP返回状态码{exc.response.status_code}"
            }
async def query_work_orders(room_id):
    async with httpx.AsyncClient(
        timeout=ERP_TIMEOUT,
        trust_env=False
    ) as client:
        try:
            response = await client.get(
                f"{ERP_BASE_URL}/work-orders",
                params={"room_id": room_id}
            )
            response.raise_for_status()
            return response.json()

        except httpx.TimeoutException:
            return {
                "success": False,
                "error": "工单查询超时"
            }

        except httpx.RequestError:
            return {
                "success": False,
                "error": "无法连接ERP服务"
            }

        except httpx.HTTPStatusError as exc:
            return {
                "success": False,
                "error": f"ERP返回状态码{exc.response.status_code}"
            }


async def create_work_order(room_id, description, request_id):
    async with httpx.AsyncClient(
        timeout=ERP_TIMEOUT,
        trust_env=False
    ) as client:
        try:
            response = await client.post(
                f"{ERP_BASE_URL}/work-orders",
                json={
                    "request_id": request_id,
                    "room_id": room_id,
                    "description": description
                }
            )
            response.raise_for_status()
            return response.json()

        except httpx.TimeoutException:
            return {
                "success": False,
                "error": "创建工单超时"
            }

        except httpx.RequestError:
            return {
                "success": False,
                "error": "无法连接ERP服务"
            }

        except httpx.HTTPStatusError as exc:
            return {
                "success": False,
                "error": f"ERP返回状态码{exc.response.status_code}"
            }

async def create_and_verify_work_order(room_id, description):
    # 每次新操作生成一次；同一次操作的网络重试必须沿用此编号。
    request_id = f"REQ-{uuid4().hex}"
    # 第一步：创建
    create_result = await create_work_order(
        room_id,
        description,
        request_id
    )

    if not create_result["success"]:
        return create_result

    # 第二步：查询
    new_order_id = create_result["data"]["order_id"]
    query_result = await query_work_orders(room_id)

    if not query_result["success"]:
        create_result["verified"] = False
        create_result["verification_error"] = "创建接口返回成功，但查询失败"
        return create_result

    # 第三步：核对编号
    orders = query_result["data"]["work_orders"]
    found = False

    for order in orders:
        if order["order_id"] == new_order_id:
            found = True
            break

    create_result["verified"] = found

    if not found:
        create_result["verification_error"] = "查询结果中未找到新工单"

    return create_result
