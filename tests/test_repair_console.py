"""模拟用户输入与提取结果，验证连续交互和退出恢复。"""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from agent_tools import RepairInfo
from repair_flow import build_repair_graph
import langgraph_demo as console


class RepairConsoleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.checkpoints = Path(self.temp.name) / "checkpoints.sqlite"
        self.orders = Path(self.temp.name) / "orders.sqlite"
        self.extractor = AsyncMock()
        self.full = RepairInfo(room_id="C303", location="厨房", description="漏水")
        self.extractor.ainvoke.return_value = self.full
        self.model = Mock()
        self.model.with_structured_output.return_value = self.extractor

    async def run_console(self, inputs, mode):
        def build(extractor, saver, **kwargs):
            return build_repair_graph(extractor, saver, order_db_path=self.orders, **kwargs)
        with patch.object(console, "INTAKE_DB_PATH", self.checkpoints), patch.object(console, "get_api_key", return_value="test"), patch.object(console, "ChatQwen", return_value=self.model), patch.object(console, "build_repair_graph", side_effect=build), patch("builtins.input", side_effect=inputs) as user_input, patch("builtins.print"):
            result = await console.run_intake_demo(mode=mode, continuous=True, simulate_submit_error=False)
            self.assertEqual(user_input.call_count, len(inputs))
            return result

    def rows(self):
        connection = sqlite3.connect(self.orders)
        try:
            return connection.execute("SELECT order_id FROM demo_orders").fetchall()
        finally:
            connection.close()

    async def test_complete_in_one_visit(self):
        result = await self.run_console(["task-one", "C303厨房漏水", "确认"], "new")
        self.assertEqual(result.status, "success")
        self.assertTrue(result.data["order_id"])
        self.assertTrue(self.orders.exists())
        self.assertEqual(len(self.rows()), 1)

    async def test_supplement_then_confirm_in_one_visit(self):
        self.extractor.ainvoke.side_effect = [RepairInfo(room_id=None, location="厨房", description="漏水"), self.full]
        await self.run_console(["task-one", "厨房漏水", "C303", "确认"], "new")
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.extractor.ainvoke.await_count, 2)

    async def test_back_then_resume_and_view_without_duplicate(self):
        result = await self.run_console(["task-one", "C303厨房漏水", "/back"], "new")
        self.assertEqual(result.status, "waiting_confirmation")
        self.assertEqual(result.task_id, "task-one")
        self.assertFalse(self.orders.exists())
        await self.run_console(["task-one", "确认"], "resume")
        original = self.rows()
        await self.run_console(["task-one"], "resume")
        self.assertEqual(self.rows(), original)
        self.extractor.ainvoke.assert_awaited_once()

    async def test_back_at_missing_then_resume_and_cancel(self):
        self.extractor.ainvoke.side_effect = [RepairInfo(room_id=None, location="厨房", description="漏水"), self.full]
        waiting = await self.run_console(["task-one", "厨房漏水", "/back"], "new")
        cancelled = await self.run_console(["task-one", "C303", "取消"], "resume")
        self.assertEqual(waiting.status, "waiting_input")
        self.assertEqual(cancelled.status, "cancelled")
        self.assertFalse(self.orders.exists())

    async def test_entry_modes_reject_wrong_task_without_write(self):
        result = await self.run_console(["unknown"], "resume")
        self.assertEqual(result.status, "not_found")
        self.extractor.ainvoke.assert_not_awaited()
        await self.run_console(["task-one", "C303厨房漏水", "/back"], "new")
        result = await self.run_console(["task-one"], "new")
        self.assertEqual(result.status, "conflict")
        self.extractor.ainvoke.assert_awaited_once()
        self.assertFalse(self.orders.exists())

    async def test_extraction_failure_preserves_task_id(self):
        self.extractor.ainvoke.side_effect = RuntimeError("model offline")
        result = await self.run_console(["task-error", "厨房漏水"], "new")
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.task_id, "task-error")
        self.assertFalse(self.orders.exists())


if __name__ == "__main__":
    unittest.main()
