"""报修业务操作：调用者提供图；此层不读取键盘，也不打印。

实例内操作串行执行。当前本地程序仅使用一个实例；多进程API需另加任务锁。
"""
import asyncio
from uuid import uuid4
import re

from langgraph.types import Command
from operation_result import OperationResult, repair_result


class RepairService:
    def __init__(self, graph):
        self.graph = graph
        self._lock = asyncio.Lock()

    async def start(self, task_id, text):
        return await self._execute("start", task_id, text)

    async def get(self, task_id):
        return await self._execute("get", task_id)

    async def supplement(self, task_id, text):
        return await self._execute("supplement", task_id, text)

    async def confirm(self, task_id):
        return await self._execute("confirm", task_id)

    async def edit(self, task_id, fields):
        return await self._execute("edit", task_id, fields)

    async def cancel(self, task_id):
        return await self._execute("cancel", task_id)

    async def retry(self, task_id):
        return await self._execute("retry", task_id)

    @staticmethod
    def _describe(snapshot, task_id):
        result = repair_result(snapshot, task_id)
        values = snapshot.values or {}
        # 对外只返回办理需要的字段，不把原始输入和内部异常全文传出去。
        result.data = {key: values[key] for key in (
            "room_id", "location", "description", "missing_fields", "approved",
            "request_id", "order_id", "created", "supplement_count"
        ) if key in values}
        pending = [item for task in snapshot.tasks for item in task.interrupts]
        retryable = (bool(values) and not pending
                     and tuple(snapshot.next) == ("submit_intake",)
                     and values.get("approved") is True and bool(values.get("request_id")))
        actions = []
        if len(pending) == 1 and result.status == "waiting_input":
            if values.get("supplement_count", 0) >= 3:
                result.status = "failed"
                result.error_code = "supplement_limit"
                result.message = "已达到3次补充上限，未创建工单。请重新整理信息后使用新任务编号。"
            else:
                actions = ["supplement"]
        elif len(pending) == 1 and result.status == "waiting_confirmation":
            actions = ["edit", "confirm", "cancel"]
        elif retryable:
            actions = ["retry"]
        result.data["available_actions"] = actions
        return result

    async def _execute(self, action, task_id, text=None):
        if not isinstance(task_id, str) or not task_id.strip():
            return OperationResult("invalid_input", "任务编号不能为空。")
        task_id = task_id.strip()
        if action == "edit":
            keys = {"room_id", "location", "description"}
            if (not isinstance(text, dict) or set(text) != keys
                    or any(not isinstance(text[k], str) or not text[k].strip() for k in keys)):
                return OperationResult("invalid_input", "请填写完整的房间编号、位置和故障描述。", task_id)
            text = {key: value.strip() for key, value in text.items()}
            text["room_id"] = text["room_id"].upper()
            if (not re.fullmatch(r"[ABC]\d{3}", text["room_id"])
                    or len(text["location"]) > 100 or len(text["description"]) > 1000):
                return OperationResult("invalid_input", "房间编号格式或字段长度不正确，原任务未修改。", task_id)
        if action in {"start", "supplement"} and (not isinstance(text, str) or not text.strip()):
            return OperationResult("invalid_input", "报修描述或补充内容不能为空，原任务进度保留。", task_id)
        config = {"configurable": {"thread_id": f"intake:{task_id}"}, "recursion_limit": 12}
        async with self._lock:
            try:
                snapshot = await self.graph.aget_state(config)
                if action == "start":
                    if snapshot.values:
                        return OperationResult("conflict", "任务编号已存在，请查看原任务。", task_id,
                                               error_code="task_exists")
                    await self.graph.ainvoke(dict(
                        user_text=text.strip(), room_id=None, location=None, description=None,
                        missing_fields=[], approved=False, request_id=uuid4().hex,
                        order_id="", created=False, supplement_count=0,
                    ), config=config)
                else:
                    if not snapshot.values:
                        return OperationResult("not_found", "未找到任务，请检查编号。", task_id)
                    current = self._describe(snapshot, task_id)
                    if action == "get":
                        return current
                    # 完成后的重复确认返回原工单，不重新执行创建节点。
                    if action == "confirm" and current.status == "success":
                        return current
                    if action == "cancel" and current.status == "cancelled":
                        return current
                    if action not in current.data["available_actions"]:
                        if current.error_code == "supplement_limit":
                            return current
                        return OperationResult("conflict", "当前任务状态不允许此操作，请先查看任务。",
                                               task_id, current.data, "invalid_task_state")
                    if action == "edit":
                        await self.graph.ainvoke(Command(resume={"action": "edit", "fields": text}), config=config)
                    elif action == "retry":
                        # 节点失败恢复；沿用检查点中原request_id，不重新初始化。
                        await self.graph.ainvoke(None, config=config)
                    else:
                        value = text.strip() if action == "supplement" else action == "confirm"
                        await self.graph.ainvoke(Command(resume=value), config=config)
                return self._describe(await self.graph.aget_state(config), task_id)
            except Exception as exc:
                # 尽力返回最新存档，不能把执行异常解释成“肯定没有创建”。
                data = {}
                try:
                    latest = await self.graph.aget_state(config)
                    data = self._describe(latest, task_id).data
                except Exception:
                    pass
                data["exception_type"] = type(exc).__name__
                return OperationResult("failed", "报修操作未完成，请保留原任务编号检查；数据库可能已有工单。",
                                       task_id, data, "repair_execution_failed")
