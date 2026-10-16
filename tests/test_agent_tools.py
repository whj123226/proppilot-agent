"""离线回归测试：不调用模型、ERP或数据库。"""
import unittest
from unittest.mock import AsyncMock, patch
import agent_tools as tools


class ValidationTests(unittest.TestCase):
    def test_complete(self):
        result = tools.check_repair_info.invoke(dict(room_id="C303", location="厨房", description="漏水"))
        self.assertEqual(result, dict(complete=True, missing_fields=[], created=False))

    def test_missing(self):
        result = tools.check_repair_info.invoke(dict(room_id=None, location="  ", description="漏水"))
        self.assertEqual(result, dict(complete=False, missing_fields=["房间编号", "故障位置"], created=False))

    def test_shared_imports(self):
        import langchain_demo
        import langgraph_demo
        for name in ("RepairInfo", "check_repair_info", "query_fee", "query_knowledge"):
            self.assertIs(getattr(langchain_demo, name), getattr(tools, name))
            self.assertIs(getattr(langgraph_demo, name), getattr(tools, name))


class ToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_blank_inputs(self):
        for tool, key, service in ((tools.query_fee, "room_id", "erp_query_fee"), (tools.query_knowledge, "question", "rag_query_knowledge")):
            with patch.object(tools, service, new_callable=AsyncMock) as backend:
                result = await tool.ainvoke({key: "  "})
                self.assertFalse(result["success"])
                backend.assert_not_awaited()

    async def test_forwarding(self):
        for tool, key, service, value in ((tools.query_fee, "room_id", "erp_query_fee", "C303"), (tools.query_knowledge, "question", "rag_query_knowledge", "停车登记")):
            with patch.object(tools, service, new_callable=AsyncMock) as backend:
                backend.return_value = {"success": True, "data": []}
                result = await tool.ainvoke({key: " " + value + " "})
                backend.assert_awaited_once_with(value)
                self.assertEqual(result, backend.return_value)


if __name__ == "__main__":
    unittest.main()
