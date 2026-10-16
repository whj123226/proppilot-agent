"""统一入口离线测试：模拟交互和业务函数。"""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch
import app
from operation_result import OperationResult


class AppTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        log_path = Path(temp.name) / "operations.jsonl"
        self.log_path = log_path
        log_patch = patch("operation_log.OPERATION_LOG_PATH", log_path)
        log_patch.start()
        self.addCleanup(log_patch.stop)

    async def test_menu_dispatch_and_return(self):
        with patch("builtins.input", side_effect=["9", "1", "2", "3", "4", "0"]), patch("builtins.print"), patch.object(app, "consult", new_callable=AsyncMock) as consult, patch.object(app, "check_fee", new_callable=AsyncMock) as fee, patch.object(app, "run_intake_demo", new_callable=AsyncMock) as intake:
            consult.return_value = OperationResult("success", "咨询已返回")
            fee.return_value = OperationResult("success", "查询已返回")
            intake.return_value = OperationResult("waiting_confirmation", "待确认", "test-task")
            await app.main()
        consult.assert_awaited_once()
        fee.assert_awaited_once()
        self.assertEqual(intake.await_count, 2)
        self.assertEqual(intake.await_args_list[0].kwargs, dict(mode="new", simulate_submit_error=False, continuous=True))
        self.assertEqual(intake.await_args_list[1].kwargs, dict(mode="resume", simulate_submit_error=False, continuous=True))
        import json
        events = [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines()]
        finished = [event for event in events if event["event"] == "finished"]
        self.assertEqual([event["operation"] for event in finished],
                         ["consult", "check_fee", "repair_new", "repair_resume"])

    async def test_failed_operation_returns_to_menu(self):
        with patch("builtins.input", side_effect=["1", "0"]), patch("builtins.print") as output, patch.object(app, "consult", new_callable=AsyncMock, side_effect=RuntimeError("test")):
            await app.main()
        self.assertTrue(any("本次操作未完成" in str(call) for call in output.call_args_list))

    async def test_zero_fee_is_displayed(self):
        with patch("builtins.input", return_value=" c303 "), patch("builtins.print") as output, patch.object(app, "query_fee") as query:
            query.ainvoke = AsyncMock(return_value=dict(success=True, data=dict(room_id="C303", amount=0)))
            result = await app.check_fee()
            app.show_result(result)
            self.assertEqual(result.status, "success")
        query.ainvoke.assert_awaited_once_with({"room_id": "C303"})
        output.assert_any_call("欠费金额：", 0)

    async def test_blank_fee_does_not_call_service(self):
        with patch("builtins.input", return_value=" "), patch.object(app, "query_fee") as query:
            result = await app.check_fee()
        self.assertEqual(result.status, "invalid_input")
        query.ainvoke.assert_not_called()

    async def test_consult_missing_answer_is_not_success(self):
        with patch("builtins.input", return_value="换车牌？"), patch.object(app, "run_agent", new_callable=AsyncMock, return_value=None):
            result = await app.consult()
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "no_answer")

    async def test_missing_fee_amount_is_not_success(self):
        with patch("builtins.input", return_value="C303"), patch.object(app, "query_fee") as query:
            query.ainvoke = AsyncMock(return_value={"success": True, "data": {"amount": None}})
            result = await app.check_fee()
        self.assertEqual(result.status, "failed")


if __name__ == "__main__":
    unittest.main()
