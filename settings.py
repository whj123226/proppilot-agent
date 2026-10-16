"""统一非敏感配置；密钥在使用时从环境变量读取。"""
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"
OPERATION_LOG_PATH = PROJECT_DIR / "logs" / "operations.jsonl"
ORDER_DB_PATH = DATA_DIR / "demo_work_orders.sqlite"
INTAKE_DB_PATH = DATA_DIR / "intake_checkpoints.sqlite"
APPROVAL_DB_PATH = DATA_DIR / "approval_checkpoints.sqlite"
CHROMA_DB_PATH = DATA_DIR / "chroma_db"
SOURCE_PATH = DATA_DIR / "property_guide.txt"
VECTOR_INDEX_PATH = DATA_DIR / "vector_index.json"


def _text(name, default):
    return os.getenv(name, "").strip() or default


def _positive_number(name, default):
    value = float(_text(name, str(default)))
    if not 0 < value < float("inf"):
        raise ValueError(f"{name}必须是大于0的有限数字")
    return value


CHAT_MODEL = _text("CHAT_MODEL", "qwen-plus")
MODEL_BASE_URL = _text("MODEL_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/")
EMBEDDING_URL = MODEL_BASE_URL + "/embeddings"
CHAT_URL = MODEL_BASE_URL + "/chat/completions"
MODEL_TIMEOUT = _positive_number("MODEL_TIMEOUT", 60)
MODEL_MAX_RETRIES = 1
ERP_BASE_URL = _text("ERP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
ERP_TIMEOUT = _positive_number("ERP_TIMEOUT", 5)
RERANK_MODEL = _text("RERANK_MODEL", "qwen3-rerank")


def get_api_key():
    return os.getenv("DASHSCOPE_API_KEY", "").strip()


def get_rerank_url():
    return os.getenv("RERANK_URL", "").strip()
