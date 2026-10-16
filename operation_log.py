"""本地单进程操作日志：只写排查字段，写入失败不改变业务结果。"""
import asyncio
import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from threading import Lock
from time import perf_counter
from uuid import uuid4

from operation_result import OperationResult
from settings import OPERATION_LOG_PATH

_current = ContextVar("operation_context", default=None)
_write_lock = Lock()
LOG_MAX_BYTES = 1024 * 1024
LOG_BACKUPS = 3


class _FileHandler(RotatingFileHandler):
    def handleError(self, record):
        # 将写入失败交给外层处理，避免标准 logging 向屏幕倾倒错误内容。
        raise


def _write_event(event):
    with _write_lock:
        OPERATION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        handler = _FileHandler(OPERATION_LOG_PATH, maxBytes=LOG_MAX_BYTES,
                               backupCount=LOG_BACKUPS, encoding="utf-8")
        try:
            line = json.dumps(event, ensure_ascii=False)
            handler.handle(logging.LogRecord("proppilot.operations", logging.INFO,
                                             "", 0, line, (), None))
        finally:
            handler.close()


def _record(context, event, **fields):
    record = {
        "time": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "trace_id": context["trace_id"],
        "operation": context["operation"],
        "task_id": context.get("task_id"),
        **fields,
    }
    try:
        _write_event(record)
    except Exception:
        if not context.get("log_warning"):
            print("日志暂时无法保存，本次业务操作仍可继续。")
            context["log_warning"] = True


def bind_task(task_id):
    """收到报修编号立即关联；即使后续初始化失败，也能定位原任务。"""
    context = _current.get()
    if context is not None:
        context["task_id"] = task_id
        _record(context, "task_selected")


async def run_logged(operation, action, **kwargs):
    """包住一次菜单办理，耗时包括等待用户输入；不自动重试业务。"""
    context = {"trace_id": uuid4().hex, "operation": operation}
    token = _current.set(context)
    started = perf_counter()
    exception_type = None
    try:
        _record(context, "started")
        try:
            result = await action(**kwargs)
            if not isinstance(result, OperationResult):
                raise TypeError("操作没有返回统一结果")
        except (EOFError, KeyboardInterrupt, asyncio.CancelledError) as exc:
            _record(context, "finished", status="interrupted",
                    duration_ms=round((perf_counter() - started) * 1000),
                    exception_type=type(exc).__name__)
            raise
        except Exception as exc:
            exception_type = type(exc).__name__
            result = OperationResult(
                "failed", "本次操作未完成。如涉及报修，请沿用原任务编号从恢复入口检查。",
                task_id=context.get("task_id"), error_code="operation_exception")
        result.trace_id = context["trace_id"]
        context["task_id"] = result.task_id or context.get("task_id")
        # 不序列化整个 result，message/data 可能含业务正文或外部错误详情。
        _record(context, "finished", status=result.status,
                duration_ms=round((perf_counter() - started) * 1000),
                error_code=result.error_code, exception_type=exception_type,
                request_id=result.data.get("request_id"),
                order_id=result.data.get("order_id"))
        return result
    finally:
        _current.reset(token)
