"""直接调用业务操作，使用真实图、临时存档和模拟模型。"""
import asyncio
import sqlite3
import tempfile
import unittest
from contextlib import asynccontextmanager, closing
from pathlib import Path
from unittest.mock import AsyncMock, patch

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from agent_tools import RepairInfo
from repair_flow import build_repair_graph
from repair_service import RepairService


class RepairServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.checkpoints = Path(temp.name) / "checkpoints.sqlite"
        self.orders = Path(temp.name) / "orders.sqlite"
        self.extractor = AsyncMock()
        self.full = RepairInfo(room_id="C303", location="厨房", description="漏水")
        self.missing = RepairInfo(room_id=None, location="厨房", description="漏水")
        self.extractor.ainvoke.return_value = self.full

    @asynccontextmanager
    async def service(self, **kwargs):
        async with AsyncSqliteSaver.from_conn_string(str(self.checkpoints)) as saver:
            yield RepairService(build_repair_graph(self.extractor, saver,
                                                   order_db_path=self.orders, **kwargs))

    def rows(self):
        with closing(sqlite3.connect(self.orders)) as connection:
            return connection.execute("SELECT request_id, order_id FROM demo_orders").fetchall()

    async def test_edit_rechecks_preserves_ids_and_survives_reopen(self):
        fields = dict(room_id="b202", location="卧室", description="灯不亮")
        async with self.service() as service:
            before = await service.start("edit-one", "C303厨房漏水")
            updated = await service.edit("edit-one", fields)
            self.assertEqual(updated.status, "waiting_confirmation")
            self.assertFalse(updated.data["approved"])
            self.assertEqual(updated.data["request_id"], before.data["request_id"])
            self.assertEqual(updated.task_id, before.task_id)
            self.assertEqual(updated.data["room_id"], "B202")
            self.assertFalse(self.orders.exists())
        async with self.service() as service:
            restored = await service.get("edit-one")
            self.assertEqual(restored.data["location"], "卧室")
            done = await service.confirm("edit-one")
            self.assertEqual(done.status, "success")
            self.assertEqual((await service.edit("edit-one", fields)).status, "conflict")
            again = await service.confirm("edit-one")
            self.assertEqual(again.data["order_id"], done.data["order_id"])
        self.assertEqual(len(self.rows()), 1)
        self.extractor.ainvoke.assert_awaited_once()

    async def test_edit_invalid_cancelled_missing_and_repeat(self):
        fields = dict(room_id="B202", location="卧室", description="灯不亮")
        async with self.service() as service:
            await service.start("edit-two", "C303厨房漏水")
            for invalid in [None, {}, {**fields, "description": " "}, {**fields, "room_id": "X001"}]:
                self.assertEqual((await service.edit("edit-two", invalid)).status, "invalid_input")
            self.assertEqual((await service.get("edit-two")).data["room_id"], "C303")
            for room in ["B202", "A101"]:
                result = await service.edit("edit-two", {**fields, "room_id": room})
                self.assertEqual(result.status, "waiting_confirmation")
                self.assertEqual(result.data["room_id"], room)
            await service.cancel("edit-two")
            self.assertEqual((await service.edit("edit-two", fields)).status, "conflict")
            self.extractor.ainvoke.return_value = self.missing
            await service.start("edit-missing", "厨房漏水")
            self.assertEqual((await service.edit("edit-missing", fields)).status, "conflict")
        self.assertFalse(self.orders.exists())

    async def test_reopen_then_confirm_without_console_and_no_duplicate(self):
        with patch("builtins.input", side_effect=AssertionError("不能读取键盘")), patch("builtins.print") as output:
            async with self.service() as service:
                result = await service.start("task-1", "C303厨房漏水")
                self.assertEqual(result.status, "waiting_confirmation")
                request_id = result.data["request_id"]
                self.assertNotIn("user_text", result.data)
                self.assertFalse(self.orders.exists())
            async with self.service() as service:
                viewed = await service.get("task-1")
                self.assertEqual(viewed.data["request_id"], request_id)
                first, repeated = await asyncio.gather(service.confirm("task-1"), service.confirm("task-1"))
                self.assertEqual(first.status, "success")
                self.assertEqual(first.data["order_id"], repeated.data["order_id"])
                self.assertEqual((await service.cancel("task-1")).status, "conflict")
            output.assert_not_called()
        self.extractor.ainvoke.assert_awaited_once()
        self.assertEqual(len(self.rows()), 1)

    async def test_missing_cannot_confirm_then_supplement_and_cancel(self):
        self.extractor.ainvoke.side_effect = [self.missing, self.full]
        async with self.service() as service:
            self.assertEqual((await service.start("task-1", "厨房漏水")).status, "waiting_input")
            self.assertEqual((await service.confirm("task-1")).status, "conflict")
            self.assertEqual((await service.supplement("task-1", " ")).status, "invalid_input")
            self.assertEqual((await service.get("task-1")).data["supplement_count"], 0)
            result = await service.supplement("task-1", "C303")
            self.assertEqual(result.status, "waiting_confirmation")
            self.assertEqual((await service.cancel("task-1")).status, "cancelled")
            self.assertEqual((await service.cancel("task-1")).status, "cancelled")
            self.assertEqual((await service.confirm("task-1")).status, "conflict")
        self.assertFalse(self.orders.exists())

    async def test_supplement_limit_enforced_outside_console(self):
        self.extractor.ainvoke.return_value = self.missing
        async with self.service() as service:
            await service.start("task-1", "厨房漏水")
            for _ in range(3):
                await service.supplement("task-1", "还是漏水")
            result = await service.supplement("task-1", "C303")
            self.assertEqual(result.error_code, "supplement_limit")
            self.assertEqual(result.data["supplement_count"], 3)
            self.assertEqual((await service.get("task-1")).error_code, "supplement_limit")
        self.assertEqual(self.extractor.ainvoke.await_count, 4)
        self.assertFalse(self.orders.exists())

    async def test_unknown_and_duplicate_task_protection(self):
        async with self.service() as service:
            for action in (service.get, service.confirm, service.cancel, service.retry):
                self.assertEqual((await action("unknown")).status, "not_found")
            self.assertEqual((await service.start(" ", "漏水")).status, "invalid_input")
            self.assertEqual((await service.start("task-1", None)).status, "invalid_input")
            first = await service.start("task-1", "C303厨房漏水")
            self.assertEqual((await service.start("task-1", "B202卧室漏水")).status, "conflict")
            self.assertEqual((await service.get("task-1")).data["request_id"], first.data["request_id"])
        self.extractor.ainvoke.assert_awaited_once()

    async def test_write_then_failure_reopens_and_retries_same_request(self):
        async with self.service(simulate_submit_error=True) as service:
            await service.start("task-1", "C303厨房漏水")
            failed = await service.confirm("task-1")
            self.assertEqual(failed.status, "failed")
            self.assertEqual(failed.data["available_actions"], ["retry"])
            original = self.rows()
            self.assertEqual(len(original), 1)
            self.assertEqual((await service.cancel("task-1")).status, "conflict")
        async with self.service(simulate_submit_error=True) as service:
            await service.get("task-1")
            self.assertEqual(self.rows(), original)
            result = await service.retry("task-1")
            self.assertEqual(result.status, "success")
            self.assertEqual(result.data["request_id"], original[0][0])
            self.assertEqual(result.data["order_id"], original[0][1])
            self.assertEqual((await service.retry("task-1")).status, "conflict")
        self.assertEqual(self.rows(), original)

    async def test_extraction_failure_cannot_use_submit_retry(self):
        self.extractor.ainvoke.side_effect = RuntimeError("private error")
        async with self.service() as service:
            result = await service.start("task-1", "C303厨房漏水")
            self.assertEqual(result.status, "failed")
            self.assertEqual(result.task_id, "task-1")
            self.assertNotIn("private error", repr(result))
            self.assertEqual((await service.retry("task-1")).status, "conflict")
            self.assertEqual((await service.get("task-1")).status, "failed")
        self.extractor.ainvoke.assert_awaited_once()

    async def test_checkpoint_failure_returns_failed_with_task_id(self):
        graph = AsyncMock()
        graph.aget_state.side_effect = OSError("private path")
        result = await RepairService(graph).get("task-1")
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.task_id, "task-1")
        graph.ainvoke.assert_not_awaited()

    async def test_existing_graph_checkpoint_is_compatible(self):
        # 按原教学脚本的方式直接建存档，再由新业务层恢复。
        config = {"configurable": {"thread_id": "intake:legacy"}, "recursion_limit": 12}
        async with AsyncSqliteSaver.from_conn_string(str(self.checkpoints)) as saver:
            graph = build_repair_graph(self.extractor, saver, order_db_path=self.orders)
            await graph.ainvoke(dict(user_text="C303厨房漏水", room_id=None,
                                    location=None, description=None, missing_fields=[],
                                    approved=False, request_id="original-request",
                                    order_id="", created=False, supplement_count=0), config)
        async with self.service() as service:
            viewed = await service.get("legacy")
            self.assertEqual(viewed.status, "waiting_confirmation")
            result = await service.confirm("legacy")
            self.assertEqual(result.status, "success")
            self.assertEqual(result.data["request_id"], "original-request")
        self.extractor.ainvoke.assert_awaited_once()
