"""真实MySQL集成测试；无凭证时显式跳过，不能称已验收。"""
import asyncio
import os
import unittest
from uuid import uuid4
from unittest.mock import patch
from dataclasses import replace
import pymysql
from fastapi.testclient import TestClient
from web_config import WebConfig
from web_app import create_app, OWNER
from web_models import FixtureExtractor
from mysql_store import MySQLStore, QuotaExceeded
from init_web_db import initialize
from repair_flow import build_repair_graph
from repair_service import RepairService
from langgraph.checkpoint.mysql.aio import AIOMySQLSaver
import aiomysql


@unittest.skipUnless(os.getenv("MYSQL_PASSWORD"), "需要MYSQL_PASSWORD才能验收真实MySQL")
class WebMySQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = replace(WebConfig.from_env(), mysql_database="proppilot_test_" + uuid4().hex[:12], mode="fixture")
        initialize(cls.cfg, create_database=True)

    @classmethod
    def tearDownClass(cls):
        # Only the exact database created by this test class may be removed.
        name = cls.cfg.mysql_database
        if not name.startswith("proppilot_test_") or len(name) != 27:
            raise RuntimeError("拒绝删除非测试数据库")
        args = cls.cfg.connect_args(); args.pop("db")
        with pymysql.connect(**args, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(f"DROP DATABASE `{name}`")

    def test_edit_api_isolation_validation_and_mysql_persistence(self):
        fields = {"room_id": "B202", "location": "卧室", "description": "灯不亮"}
        with TestClient(create_app(self.cfg)) as c:
            c.get("/api/session")
            original = c.post("/api/tasks", json={"text": "A101厨房漏水"}).json()
            task_id = original["task_id"]
            route = f"/api/tasks/{task_id}/edit"
            cookie = c.cookies.get("visitor")
            c.cookies.clear(); c.get("/api/session")
            self.assertEqual(c.post(route, json=fields).status_code, 404)
            c.cookies.set("visitor", cookie)
            self.assertEqual(c.post(route, json={**fields, "room_id": "X001"}).status_code, 422)
            edited = c.post(route, json=fields).json()
            self.assertEqual(edited["status"], "waiting_confirmation")
            self.assertEqual(edited["data"]["request_id"], original["data"]["request_id"])
            self.assertFalse(edited["data"]["approved"])
            self.assertEqual(c.get("/api/orders").json()["orders"], [])
        with TestClient(create_app(self.cfg)) as c:
            c.cookies.set("visitor", cookie)
            restored = c.get(f"/api/tasks/{task_id}").json()
            self.assertEqual(restored["data"]["room_id"], "B202")
            self.assertEqual(c.post(f"/api/tasks/{task_id}/confirm", json={}).json()["status"], "success")
            order = c.get("/api/orders").json()["orders"][0]
            self.assertEqual(order["room_id"], "B202")
            self.assertIn("灯不亮", order["description"])
            self.assertEqual(c.post(route, json=fields).json()["status"], "conflict")

    def test_web_complete_duplicate_and_owner_isolation(self):
        app = create_app(self.cfg)
        with TestClient(app) as c:
            self.assertEqual(c.get("/health").json()["storage"], "mysql")
            self.assertEqual(c.post("/api/tasks", json={"text": "厨房漏水"}).status_code, 401)
            c.get("/api/session")
            self.assertEqual(c.post("/api/fees", json={"room_id": "C303"}).json()["data"]["amount"], 0)
            self.assertIn("DOC-003", c.post("/api/consult", json={"text": "换车牌需要登记吗"}).json()["answer"])
            task = c.post("/api/tasks", json={"text": "厨房水管漏水"}).json()
            self.assertEqual(task["status"], "waiting_input")
            task_id = task["task_id"]
            self.assertEqual(c.post(f"/api/tasks/{task_id}/confirm", json={}).json()["status"], "conflict")
            self.assertEqual(c.get("/api/orders").json()["orders"], [])
            updated = c.post(f"/api/tasks/{task_id}/supplement", json={"text": "C303"}).json()
            self.assertEqual(updated["status"], "waiting_confirmation")
            first = c.post(f"/api/tasks/{task_id}/confirm", json={}).json()
            again = c.post(f"/api/tasks/{task_id}/confirm", json={}).json()
            self.assertEqual(first["status"], "success")
            self.assertEqual(first["data"]["order_id"], again["data"]["order_id"])
            self.assertEqual(len(c.get("/api/orders").json()["orders"]), 1)
            cookie = c.cookies.get("visitor")
            c.cookies.clear(); c.get("/api/session")
            self.assertEqual(c.get(f"/api/tasks/{task_id}").status_code, 404)
            self.assertEqual(c.post(f"/api/tasks/{task_id}/confirm", json={}).status_code, 404)
            self.assertEqual(c.get("/api/orders").json()["orders"], [])
        # Reopening application reconnects to MySQL checkpoints, no memory saver.
        with TestClient(create_app(self.cfg)) as c:
            c.cookies.set("visitor", cookie)
            restored = c.get(f"/api/tasks/{task_id}").json()
            self.assertEqual(restored["status"], "success")
            self.assertEqual(restored["data"]["order_id"], first["data"]["order_id"])

    def test_cancel_origin_and_validation(self):
        with TestClient(create_app(self.cfg)) as c:
            c.get("/api/session")
            self.assertEqual(c.post("/api/tasks",json={"text":" "}).status_code,422)
            self.assertEqual(c.post("/api/tasks",json={"text":"C303厨房漏水"},headers={"Origin":"https://other.example"}).status_code,403)
            t=c.post("/api/tasks",json={"text":"C303厨房漏水"}).json()["task_id"]
            self.assertEqual(c.post(f"/api/tasks/{t}/cancel",json={}).json()["status"],"cancelled")
            self.assertEqual(c.post(f"/api/tasks/{t}/confirm",json={}).json()["status"],"conflict")
            self.assertEqual(c.get("/api/orders").json()["orders"],[])

    def test_quota_survives_reopening(self):
        cfg=replace(self.cfg,session_quota=1,global_quota=1000)
        store=MySQLStore(cfg); who,_=store.new_visitor(); store.consume(who)
        with self.assertRaises(QuotaExceeded):MySQLStore(cfg).consume(who)
        # A new visitor cannot bypass an already exhausted global budget.
        other,_=store.new_visitor()
        exhausted=MySQLStore(replace(cfg,global_quota=1))
        with self.assertRaises(QuotaExceeded):exhausted.consume(other)

    def test_mysql_store_duplicate_content_conflict(self):
        store=MySQLStore(self.cfg); who,_=store.new_visitor()
        state=dict(request_id=uuid4().hex,room_id="C303",description="厨房漏水",approved=True)
        a=store.create_order(state,who); b=store.create_order(state,who)
        self.assertTrue(a["created"]);self.assertFalse(b["created"])
        self.assertEqual(a["order_id"],b["order_id"])
        with self.assertRaises(ValueError):store.create_order({**state,"description":"其他故障"},who)
        with self.assertRaises(ValueError):store.create_order(state,uuid4().hex)
        self.assertEqual(len(store.orders(who)),1)

    def test_mysql_checkpoint_pending_and_write_then_error_recovery(self):
        async def run():
            store=MySQLStore(self.cfg); who,_=store.new_visitor()
            task=uuid4().hex
            async def service_run(action):
                async with aiomysql.connect(**self.cfg.connect_args(),autocommit=True) as conn:
                    saver=AIOMySQLSaver(conn);await saver.setup()
                    graph=build_repair_graph(FixtureExtractor(),saver,
                        order_writer=lambda s:store.create_order(s,who),simulate_submit_error=True)
                    service=RepairService(graph)
                    if action=="start":return await service.start(task,"C303厨房漏水")
                    return await getattr(service,action)(task)
            self.assertEqual((await service_run("start")).status,"waiting_confirmation")
            self.assertEqual((await service_run("get")).status,"waiting_confirmation")
            self.assertEqual((await service_run("confirm")).status,"failed")
            self.assertEqual(len(store.orders(who)),1)
            resumed=await service_run("retry")
            self.assertEqual(resumed.status,"success")
            self.assertEqual(resumed.data["order_id"],store.orders(who)[0]["order_id"])
            self.assertEqual(len(store.orders(who)),1)
        asyncio.run(run())
