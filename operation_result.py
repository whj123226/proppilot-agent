"""入口统一结果；状态描述操作进度，不代表模型回答已经人工核实。"""
from dataclasses import dataclass, field
from typing import Any, Literal

Status = Literal["success", "failed", "waiting_input", "waiting_confirmation",
                 "cancelled", "invalid_input", "not_found", "conflict", "not_started"]


@dataclass
class OperationResult:
    status: Status
    message: str
    task_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    trace_id: str | None = None


def repair_result(snapshot, task_id: str) -> OperationResult:
    """从真实存档判断结果；暂停不等于取消，节点失败不等于未写入。"""
    values = dict(snapshot.values or {})
    if any(task.error is not None for task in snapshot.tasks):
        return OperationResult("failed", "任务未完成，请沿用原任务编号检查；数据库可能已有工单。",
                               task_id, values, "node_failed")
    if not values:
        return OperationResult("not_started", "尚未开始报修。", task_id)
    pauses = [item for task in snapshot.tasks for item in task.interrupts]
    if pauses:
        kind = pauses[0].value.get("kind")
        if kind == "missing":
            return OperationResult("waiting_input", "进度已保存，请从恢复入口补充信息。", task_id, values)
        if kind == "confirm":
            return OperationResult("waiting_confirmation", "进度已保存，请从恢复入口确认或取消。", task_id, values)
    if not snapshot.next:
        if values.get("order_id"):
            return OperationResult("success", "本地模拟工单已完成，未提交真实ERP。", task_id, values)
        if values.get("approved") is False:
            return OperationResult("cancelled", "报修已取消，未创建工单。", task_id, values)
    return OperationResult("failed", "任务未完成，请保留原任务编号检查，不要重复提交。",
                           task_id, values, "incomplete_state")
