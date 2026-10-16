"""只使用临时SQLite数据库，不接触项目data目录。"""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from order_store import DEFAULT_DB_PATH, create_demo_order


class OrderStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "orders.sqlite"
        self.state = dict(approved=True, request_id="test-001", room_id="C303", description="厨房漏水")

    def create(self, **changes):
        return create_demo_order({**self.state, **changes}, db_path=self.db)

    def row_count(self):
        connection = sqlite3.connect(self.db)
        try:
            return connection.execute("SELECT COUNT(*) FROM demo_orders").fetchone()[0]
        finally:
            connection.close()

    def test_new_order(self):
        result = self.create()
        self.assertTrue(result["created"])
        self.assertTrue(result["order_id"].startswith("DEMO-WO-"))
        self.assertEqual(self.row_count(), 1)

    def test_repeat_request_returns_existing_order(self):
        first = self.create()
        second = self.create()
        self.assertEqual(first["order_id"], second["order_id"])
        self.assertFalse(second["created"])
        self.assertEqual(self.row_count(), 1)

    def test_different_request_creates_separate_order(self):
        first = self.create()
        second = self.create(request_id="test-002")
        self.assertNotEqual(first["order_id"], second["order_id"])
        self.assertEqual(self.row_count(), 2)

    def test_changed_content_is_rejected(self):
        first = self.create()
        for changes in ({"description": "其他故障"}, {"room_id": "B202"}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    self.create(**changes)
        self.assertEqual(self.create()["order_id"], first["order_id"])
        self.assertEqual(self.row_count(), 1)

    def test_unapproved_does_not_open_database(self):
        for approved in (False, None, 1):
            with self.subTest(approved=approved):
                with self.assertRaises(ValueError):
                    self.create(approved=approved)
        self.assertFalse(self.db.exists())

    def test_missing_request_does_not_open_database(self):
        with self.assertRaises(ValueError):
            self.create(request_id="")
        self.assertFalse(self.db.exists())

    def test_retry_after_caller_failure(self):
        first = self.create()
        # 存储函数已提交成功，但调用方没有保存结果，然后重新调用。
        recovered = self.create()
        self.assertEqual(recovered["order_id"], first["order_id"])
        self.assertFalse(recovered["created"])
        self.assertEqual(self.row_count(), 1)

    def test_compatible_import_and_path(self):
        import langgraph_demo
        self.assertIs(langgraph_demo.create_demo_order, create_demo_order)
        self.assertEqual(DEFAULT_DB_PATH, Path(langgraph_demo.__file__).resolve().parent / "data" / "demo_work_orders.sqlite")


if __name__ == "__main__":
    unittest.main()
