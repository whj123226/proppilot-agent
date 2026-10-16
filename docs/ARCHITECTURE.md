# 架构与代码阅读路线

## 一句话

模型负责理解输入，程序负责校验与执行，MySQL负责保存业务记录和流程进度。

```text
浏览器 static/
    ↓ HTTP / HttpOnly访客Cookie
FastAPI web_app.py —— 访客隔离、输入限制、调用额度
    ├─ 咨询 → fixture样例 / live RAG → 引用答案
    ├─ 欠费 → MySQL模拟欠费记录（只读）
    └─ 报修 → RepairService → LangGraph
                          提取 → 校验
                                  ├─ 缺项 → interrupt补充 → 再提取
                                  └─ 完整 → interrupt确认
                                              ├─ 取消 → 结束
                                              └─ 同意 → 写入MySQL → 结束
MySQL：访客、任务、工单、额度、checkpoint_*检查点
Chroma：live知识向量索引，与关系数据库分工
```

## 依次读这些代码

1. `web_models.py`：先看无需模型的输入输出，理解演示边界。
2. `agent_tools.py`：RepairInfo字段和校验工具，不要先读大段框架API。
3. `repair_flow.py`：extract、validate、ask_missing、confirm_intake、submit_intake五个节点。
4. `repair_service.py`：start/get/supplement/confirm/cancel/retry如何限制允许操作。
5. `mysql_store.py`：工单唯一约束、事务、访客所有权及额度。
6. `web_app.py`：把上述服务暴露为HTTP接口，并注入模型、检查点与存储。
7. `rag.py`与`build_index.py`：live检索与索引维护；不是每次启动都重新建索引。
8. `tests/test_web_mysql.py`：从断言理解真实MySQL链路应当满足什么。

`app.py`、`main.py`、`langchain_demo.py`、`langgraph_demo.py`等属于兼容教学入口，并非新版网页入口。保留它们是因为旧测试仍有依赖；没有为了目录好看直接删除。

## 三种编号不要混淆

- task_id：一次报修任务及其恢复入口。
- request_id：这次业务写入的稳定标识，重试不能换号。
- trace_id：一次HTTP操作的排查标识，不用于业务去重。

## 关键设计与限制

为什么需要LangGraph：报修会暂停等待补充和确认，需要明确分支与检查点；单次问答不必强行建图。

为什么确认后才写入：模型提取可能有误，确认前只保存流程状态，不产生工单。

为什么不能失败就换编号：写入可能成功但返回失败。用原request_id重试才能识别已有记录；业务表唯一约束是最后一道防线。

为什么还保留服务层：HTTP是交互协议，RepairService控制状态允许哪些动作，图只组织业务步骤，存储负责数据库一致性。

为什么混合检索：向量候选用于语义匹配，BM25补充关键词匹配，候选按文档合并去重后由rerank重排；不直接相加不同量纲分数。小知识库上的成功例子不能证明大规模效果。

限制：单worker/单副本；进程锁不是分布式锁；访客Cookie隔离不是企业身份权限；欠费与工单为模拟业务；未接真实ERP。并发扩展需要额外设计跨进程任务锁、检查点连接与故障处理。
