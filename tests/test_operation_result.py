"""存档状态映射不依赖模型，不把暂停或失败当成取消。"""
import unittest
from types import SimpleNamespace as NS
from operation_result import repair_result


class ResultTests(unittest.TestCase):
    def test_failure_after_possible_write_is_not_cancelled(self):
        snapshot = NS(values={"approved": True, "request_id": "original"},
                      next=("submit_intake",), tasks=[NS(error="lost result", interrupts=[])])
        result = repair_result(snapshot, "repair-1")
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.data["request_id"], "original")
        self.assertIn("可能已有工单", result.message)

    def test_pause_with_false_approval_is_not_cancelled(self):
        snapshot = NS(values={"approved": False}, next=("confirm_intake",),
                      tasks=[NS(error=None, interrupts=[NS(value={"kind": "confirm"})])])
        self.assertEqual(repair_result(snapshot, "repair-1").status, "waiting_confirmation")

    def test_unfinished_without_pause_is_failure(self):
        snapshot = NS(values={"approved": False}, next=("extract",), tasks=[])
        self.assertEqual(repair_result(snapshot, "repair-1").status, "failed")
