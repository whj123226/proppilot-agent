"""使用临时数据库和模拟提取器测试实际图的暂停与恢复。"""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from agent_tools import RepairInfo
from repair_flow import build_repair_graph


class RepairFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.checkpoints = Path(self.temp.name) / "checkpoints.sqlite"
        self.orders = Path(self.temp.name) / "orders.sqlite"
        self.config = {"configurable": {"thread_id": "intake:test"}, "recursion_limit": 12}
        self.extractor = AsyncMock()
        self.extractor.ainvoke.return_value = RepairInfo(room_id="C303", location="厨房", description="漏水")

    def initial(self):
        return dict(user_text="C303厨房漏水", room_id=None, location=None, description=None,
                    missing_fields=[], approved=False, request_id="req-test", order_id="",
                    created=False, supplement_count=0)

    def build(self, saver, **kwargs):
        return build_repair_graph(self.extractor, saver, order_db_path=self.orders, **kwargs)

    async def test_confirm_after_reopening_checkpoint_database(self):
        async with AsyncSqliteSaver.from_conn_string(str(self.checkpoints)) as saver:
            graph = self.build(saver)
            result = await graph.ainvoke(self.initial(), self.config)
            self.assertEqual(result["__interrupt__"][0].value["kind"], "confirm")
            self.assertFalse(self.orders.exists())
        async with AsyncSqliteSaver.from_conn_string(str(self.checkpoints)) as saver:
            graph = self.build(saver)
            snapshot = await graph.aget_state(self.config)
            self.assertEqual(snapshot.next, ("confirm_intake",))
            result = await graph.ainvoke(Command(resume=True), self.config)
            self.assertTrue(result["created"])
            self.assertTrue(result["order_id"])
            self.assertFalse((await graph.aget_state(self.config)).next)
        self.extractor.ainvoke.assert_awaited_once()

    async def test_missing_then_cancel(self):
        self.extractor.ainvoke.side_effect = [
            RepairInfo(room_id=None, location="厨房", description="漏水"),
            RepairInfo(room_id="C303", location="厨房", description="漏水"),
        ]
        async with AsyncSqliteSaver.from_conn_string(str(self.checkpoints)) as saver:
            graph = self.build(saver)
            result = await graph.ainvoke(self.initial(), self.config)
            self.assertEqual(result["__interrupt__"][0].value["missing_fields"], ["房间编号"])
            result = await graph.ainvoke(Command(resume="C303"), self.config)
            self.assertEqual(result["supplement_count"], 1)
            self.assertIn("C303", result["user_text"])
            self.assertEqual(result["__interrupt__"][0].value["kind"], "confirm")
            result = await graph.ainvoke(Command(resume=False), self.config)
            self.assertFalse(result["approved"])
            self.assertFalse((await graph.aget_state(self.config)).next)
        self.assertFalse(self.orders.exists())

    async def test_write_then_error_recovers_same_order_after_reopening(self):
        async with AsyncSqliteSaver.from_conn_string(str(self.checkpoints)) as saver:
            graph = self.build(saver, simulate_submit_error=True)
            await graph.ainvoke(self.initial(), self.config)
            with self.assertRaisesRegex(RuntimeError, "模拟故障"):
                await graph.ainvoke(Command(resume=True), self.config)
            snapshot = await graph.aget_state(self.config)
            self.assertEqual(snapshot.next, ("submit_intake",))
            self.assertTrue(snapshot.values["approved"])
        connection = sqlite3.connect(self.orders)
        try:
            original = connection.execute("SELECT order_id FROM demo_orders").fetchone()[0]
        finally:
            connection.close()
        async with AsyncSqliteSaver.from_conn_string(str(self.checkpoints)) as saver:
            graph = self.build(saver, simulate_submit_error=True)
            result = await graph.ainvoke(None, self.config)
            self.assertEqual(result["order_id"], original)
            self.assertFalse(result["created"])
            self.assertFalse((await graph.aget_state(self.config)).next)
        connection = sqlite3.connect(self.orders)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM demo_orders").fetchone()[0], 1)
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
