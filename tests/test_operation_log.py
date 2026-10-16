"""验证日志关联、隐私边界、轮换与写入失败时的业务连续性。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import operation_log as log
from operation_result import OperationResult


class OperationLogTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "logs" / "operations.jsonl"
        path_patch = patch.object(log, "OPERATION_LOG_PATH", self.path)
        path_patch.start()
        self.addCleanup(path_patch.stop)

    def events(self):
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]

    async def test_result_fields_only_and_unique_trace(self):
        async def action():
            log.bind_task("repair-001")
            return OperationResult("waiting_confirmation", "private-message", "repair-001",
                                   {"user_text": "private-description", "answer": "private-answer",
                                    "api_key": "private-key", "request_id": "req-001"})
        first = await log.run_logged("repair_new", action)
        second = await log.run_logged("repair_resume", action)
        self.assertNotEqual(first.trace_id, second.trace_id)
        events = self.events()
        self.assertEqual([e["event"] for e in events[:3]], ["started", "task_selected", "finished"])
        self.assertEqual({e["trace_id"] for e in events[:3]}, {first.trace_id})
        self.assertEqual(events[2]["task_id"], "repair-001")
        self.assertEqual(events[2]["request_id"], "req-001")
        self.assertEqual(events[2]["status"], "waiting_confirmation")
        self.assertGreaterEqual(events[2]["duration_ms"], 0)
        self.assertNotIn("private-", self.path.read_text(encoding="utf-8"))

    async def test_exception_retains_task_without_logging_exception_text(self):
        async def broken():
            log.bind_task("repair-error")
            raise RuntimeError("private-token-in-url")
        result = await log.run_logged("repair_new", broken)
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.task_id, "repair-error")
        self.assertEqual(self.events()[-1]["exception_type"], "RuntimeError")
        self.assertNotIn("private-token", self.path.read_text(encoding="utf-8"))
        # 下一次操作不能继承上一次的报修编号。
        await log.run_logged("consult", AsyncMock(return_value=OperationResult("success", "ok")))
        self.assertIsNone(self.events()[-1]["task_id"])

    async def test_unwritable_log_does_not_repeat_or_fail_business(self):
        self.path.parent.mkdir(parents=True)
        self.path.mkdir()  # 模拟日志路径无法作为文件打开。
        action = AsyncMock(return_value=OperationResult("success", "created", data={"order_id": "WO-1"}))
        with patch("builtins.print") as output:
            result = await log.run_logged("repair_new", action)
        self.assertEqual(result.status, "success")
        self.assertEqual(result.data["order_id"], "WO-1")
        action.assert_awaited_once()
        self.assertEqual(output.call_count, 1)

    async def test_stream_write_failure_does_not_change_result(self):
        action = AsyncMock(return_value=OperationResult("success", "ok"))
        with patch("logging.StreamHandler.flush", side_effect=OSError("disk full")), patch("builtins.print"):
            result = await log.run_logged("consult", action)
        self.assertEqual(result.status, "success")
        action.assert_awaited_once()

    async def test_interruption_is_recorded_and_propagated(self):
        with self.assertRaises(EOFError):
            await log.run_logged("consult", AsyncMock(side_effect=EOFError()))
        self.assertEqual(self.events()[-1]["status"], "interrupted")
        self.assertIsNone(log._current.get())

    async def test_rotation_keeps_bounded_files(self):
        with patch.object(log, "LOG_MAX_BYTES", 500):
            for _ in range(12):
                await log.run_logged("consult", AsyncMock(return_value=OperationResult("success", "ok")))
        files = list(self.path.parent.iterdir())
        self.assertGreater(len(files), 1)
        self.assertLessEqual(len(files), 4)
        for path in files:
            for line in path.read_text(encoding="utf-8").splitlines():
                self.assertIn("trace_id", json.loads(line))
