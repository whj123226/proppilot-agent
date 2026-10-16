"""共享报修字段与只读工具；不包含交互入口或工单创建操作。"""

from langchain_core.tools import tool
from pydantic import BaseModel, Field
from erp_tools import query_fee as erp_query_fee
from rag import query_knowledge as rag_query_knowledge


# 1. 定义模型需要填写的表单
class RepairInfo(BaseModel):
    """从用户描述中提取报修信息。"""

    room_id: str | None = Field(
        description="用户明确提供的房间编号；未提供时为 null"
    )

    location: str | None = Field(
        description="故障位置，例如厨房、卧室；未提供时为 null"
    )

    description: str | None = Field(
        description="用户明确描述的故障，不添加猜测；未提供时为 null"
    )

@tool(args_schema=RepairInfo)
def check_repair_info(
    room_id: str | None,
    location: str | None,
    description: str | None
) -> dict:
    """检查报修信息是否包含房间编号、故障位置和故障描述。
    只检查字段是否填写，不验证房间是否存在，也不创建工单。
    """
    missing_fields = []

    for value, label in [
        (room_id, "房间编号"),
        (location, "故障位置"),
        (description, "故障描述")
    ]:
        if value is None or not value.strip():
            missing_fields.append(label)

    return {
        "complete": not missing_fields,
        "missing_fields": missing_fields,
        "created": False
    }
@tool
async def query_fee(room_id: str) -> dict:
    """根据用户明确提供的房间编号查询ERP欠费。
    例如 C303。仅查询，不缴费，也不修改数据。
    用户没有提供房间编号时，应先询问，不得猜测。
    """
    room_id = room_id.strip()

    if not room_id:
        return {
            "success": False,
            "error": "缺少房间编号"
        }

    return await erp_query_fee(room_id)
@tool
async def query_knowledge(question: str) -> dict:
    """查询物业知识库中的规定和办事指南。
    适用于报修所需材料、工单查询方法、停车登记等问题。
    不用于查询某个房间的实时欠费或实时工单状态。
    question 应保留用户的知识问题，不混入无关的业务查询。
    """
    question = question.strip()

    if not question:
        return {
            "success": False,
            "error": "知识库查询问题不能为空"
        }

    return await rag_query_knowledge(question)
