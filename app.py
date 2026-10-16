"""PropPilot 本地统一入口：运行 python app.py。"""
import asyncio

from agent_tools import query_fee
from langchain_demo import run_agent
from langgraph_demo import run_intake_demo
from operation_result import OperationResult
from operation_log import run_logged


def show_result(result):
    if not isinstance(result, OperationResult):
        raise TypeError("操作没有返回统一结果")
    labels = {"success": "成功", "failed": "未完成", "waiting_input": "待补充",
              "waiting_confirmation": "待确认", "cancelled": "已取消",
              "invalid_input": "输入无效", "not_found": "未找到",
              "conflict": "编号已存在", "not_started": "尚未开始"}
    print("\n办理状态：", labels[result.status])
    print(result.message)
    if result.trace_id:
        print("追踪编号：", result.trace_id)
    if result.task_id:
        print("任务编号：", result.task_id)
    if "answer" in result.data:
        print("回答：", result.data["answer"])
    if "amount" in result.data:
        print("房间编号：", result.data["room_id"])
        print("欠费金额：", result.data["amount"])
    if result.data.get("order_id"):
        print("工单编号：", result.data["order_id"])
    if result.error_code:
        print("问题代码：", result.error_code)


async def consult():
    question = input("请输入物业规定或办理指南问题：").strip()
    if not question:
        return OperationResult("invalid_input", "问题不能为空。")
    answer = await run_agent(question)
    if not answer or not answer.strip():
        return OperationResult("failed", "未获得回答，请检查模型连接后重试。", error_code="no_answer")
    return OperationResult("success", "咨询已返回回答，内容仍需按资料核实。", data={"answer": answer})


async def check_fee():
    room_id = input("请输入房间编号，例如 C303：").strip().upper()
    if not room_id:
        return OperationResult("invalid_input", "房间编号不能为空。")
    result = await query_fee.ainvoke({"room_id": room_id})
    if not result.get("success"):
        return OperationResult("failed", "欠费查询失败：" + str(result.get("error", "未获得有效结果")), error_code="fee_query_failed")
    data = result.get("data", {})
    if not isinstance(data, dict) or "amount" not in data or data["amount"] is None:
        return OperationResult("failed", "查询结果缺少有效欠费金额，请检查业务服务。", error_code="invalid_fee_response")
    return OperationResult("success", "欠费查询完成。", data={"room_id": data.get("room_id", room_id), "amount": data["amount"]})


async def main():
    print("PropPilot 物业助手（本地演示，报修创建模拟工单）")
    while True:
        print("\n1. 物业咨询\n2. 欠费查询\n3. 发起模拟报修\n4. 继续或查看报修任务\n0. 退出")
        try:
            choice = input("请选择：").strip()
            if choice == "0":
                print("已退出。")
                return
            if choice == "1":
                show_result(await run_logged("consult", consult))
            elif choice == "2":
                show_result(await run_logged("check_fee", check_fee))
            elif choice == "3":
                show_result(await run_logged("repair_new", run_intake_demo, mode="new", simulate_submit_error=False, continuous=True))
            elif choice == "4":
                show_result(await run_logged("repair_resume", run_intake_demo, mode="resume", simulate_submit_error=False, continuous=True))
            else:
                print("请输入0至4。")
        except (EOFError, KeyboardInterrupt):
            print("\n已退出，已经保存的任务可通过恢复入口继续。")
            return
        except Exception as exc:
            print("本次操作未完成：", type(exc).__name__, str(exc))
            show_result(OperationResult("failed", "如涉及报修，请保留原任务编号，通过恢复入口查看。",
                                        error_code="operation_exception"))


if __name__ == "__main__":
    asyncio.run(main())
