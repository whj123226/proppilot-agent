"""固定样例用于无模型额度的演示；live模式使用真实模型及已有RAG。"""
import re
from agent_tools import RepairInfo

KNOWLEDGE = [
    ("DOC-001", "报修指南", "提交报修需要房屋编号、故障位置与故障描述。信息齐全后需要用户确认才会创建工单。"),
    ("DOC-002", "工单查询指南", "报修提交后可查看工单编号与处理状态。演示工单初始为待处理，演示不包含真实派单。"),
    ("DOC-003", "停车办理指南", "办理停车登记需要房屋编号和车牌号码；车辆信息变化后需要重新登记。"),
]


class FixtureExtractor:
    async def ainvoke(self, messages):
        text = messages[-1].content
        rooms = re.findall(r"\b([ABCabc]\d{3})\b", text)
        # Chinese adjacent characters do not form a regex word boundary.
        if not rooms:
            rooms = re.findall(r"([ABCabc]\d{3})", text)
        location = next((p for p in ["厨房", "卫生间", "卧室", "客厅", "阳台"] if p in text), None)
        fault = next((p for p in ["漏水", "损坏", "无法启动", "不亮", "堵塞"] if p in text), None)
        return RepairInfo(room_id=rooms[-1].upper() if rooms else None,
                          location=location, description=fault)


def fixture_consult(text):
    key = 2 if any(w in text for w in ["车牌", "停车", "车辆"]) else 1 if any(w in text for w in ["进度", "状态", "查询工单"]) else 0 if any(w in text for w in ["报修", "漏水", "材料"]) else None
    if key is None:
        return {"answer": "固定样例中没有这项规定，无法据此作出承诺。可试问：换车牌需要登记吗？报修需要哪些信息？", "sources": []}
    doc_id, title, content = KNOWLEDGE[key]
    return {"answer": content + f" [{doc_id}]", "sources": [{"id": doc_id, "title": title, "content": content}]}
