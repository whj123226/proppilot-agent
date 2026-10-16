"""知识库更新入口：运行一次完成读取、切分、向量化和导入 Chroma。"""
import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

import chromadb
import httpx
from settings import SOURCE_PATH, VECTOR_INDEX_PATH, CHROMA_DB_PATH, EMBEDDING_URL, MODEL_TIMEOUT, get_api_key


# 一、文本切分
def split_text(text, chunk_size=8, overlap=2):
    if chunk_size <= 0:
        raise ValueError("每块长度必须大于0")

    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("重叠长度必须大于等于0，并小于每块长度")

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size

        chunk = text[start:end]
        chunks.append(chunk)

        # 已经取到末尾，就结束
        if end >= len(text):
            break

        # 下一块向前保留 overlap 个字符
        start = end - overlap

    return chunks


# 二、读取物业资料
def load_documents(chunk_size=300, overlap=50):
    base_dir = Path(__file__).resolve().parent
    file_path = SOURCE_PATH

    text = file_path.read_text(encoding="utf-8")
    sections = text.strip().split("\n\n")

    documents = []

    for section in sections:
        content = section.strip()

        if not content:
            continue

        lines = content.splitlines()
        title = lines[0].strip("【】")
        body = "\n".join(lines[1:]).strip()

        if not body:
            continue

        # 将当前章节正文按长度进一步切分
        body_chunks = split_text(
            body,
            chunk_size=chunk_size,
            overlap=overlap
        )

        for chunk_index, chunk in enumerate(body_chunks, start=1):
            document = {
                "id": f"DOC-{len(documents) + 1:03d}",
                "title": title,
                "source": file_path.name,
                "chunk_index": chunk_index,
                "content": chunk
            }

            documents.append(document)

    return documents


# 三、分批生成向量，保留 JSON 作为中间文件
async def build_vectors():
    api_key = get_api_key()

    if not api_key:
        print("请先配置 DASHSCOPE_API_KEY")
        return

    documents = load_documents()

    if not documents:
        print("没有可建立索引的资料")
        return

    model = "text-embedding-v4"
    dimensions = 1024

    url = EMBEDDING_URL

    headers = {
        "Authorization": f"Bearer {api_key}"
    }

    records = []

    async with httpx.AsyncClient(
        timeout=MODEL_TIMEOUT,
        trust_env=False
    ) as client:
        try:
            # 每批最多处理10段资料
            for start in range(0, len(documents), 10):
                batch = documents[start:start + 10]

                texts = [
                    f"{doc['title']}\n{doc['content']}"
                    for doc in batch
                ]

                response = await client.post(
                    url,
                    headers=headers,
                    json={
                        "model": model,
                        "input": texts,
                        "dimensions": dimensions,
                        "encoding_format": "float"
                    }
                )
                response.raise_for_status()

                items = sorted(
                    response.json()["data"],
                    key=lambda item: item["index"]
                )

                if (
                    len(items) != len(batch)
                    or [item["index"] for item in items]
                    != list(range(len(batch)))
                    or any(
                        len(item["embedding"]) != dimensions
                        for item in items
                    )
                ):
                    print("向量结果不完整，本次不更新索引")
                    return

                for document, item in zip(batch, items):
                    records.append({
                        "document": document,
                        "vector": item["embedding"]
                    })

            index_data = {
                "model": model,
                "dimensions": dimensions,
                "records": records
            }

            index_path = VECTOR_INDEX_PATH

            index_path.write_text(
                json.dumps(
                    index_data,
                    ensure_ascii=False,
                    indent=2
                ),
                encoding="utf-8"
            )

            print("索引更新成功")
            print("资料块数量：", len(records))
            print("保存位置：", index_path)
            return True

        except httpx.RequestError as exc:
            print("向量请求失败：", repr(exc))

        except httpx.HTTPStatusError as exc:
            print("接口错误：", exc.response.status_code)
            print(exc.response.text)


# 四、导入本地 Chroma；upsert 不会自动删除旧编号
def import_index():
    base_dir = Path(__file__).resolve().parent
    index_path = VECTOR_INDEX_PATH

    if not index_path.exists():
        print("找不到向量文件，请先运行 build_index.py")
        return

    # 1. 读取已有文档和向量
    index_data = json.loads(
        index_path.read_text(encoding="utf-8")
    )
    records = index_data["records"]

    if not records:
        print("向量文件中没有资料")
        return

    # 2. 打开本地向量数据库
    client = chromadb.PersistentClient(
        path=str(CHROMA_DB_PATH)
    )

    # 使用新集合，不与之前的三维演示数据混用
    collection = client.get_or_create_collection(
        name="property_knowledge_v1",
        embedding_function=None,
        metadata={
            "embedding_model": index_data["model"],
            "dimensions": index_data["dimensions"]
        }
    )

    # 3. 检查已有集合使用的模型和维度
    metadata = collection.metadata or {}

    if (
        metadata.get("embedding_model") != index_data["model"]
        or metadata.get("dimensions") != index_data["dimensions"]
    ):
        print("集合的模型或维度不匹配，停止导入")
        return
    # 本次只同步这一个资料文件
    source_name = "property_guide.txt"

    # 防止误把其他来源的数据混入本次同步
    if any(
        record["document"]["source"] != source_name
        for record in records
    ):
        print("发现其他来源的资料，停止同步")
        return

    # 获取数据库中这个来源已有的记录编号
    old_data = collection.get(
        where={"source": source_name},
        include=["metadatas"]
    )
    old_ids = set(old_data["ids"])

    # 获取这次准备写入的记录编号
    new_ids = {
        record["document"]["id"]
        for record in records
    }

    # 旧资料中存在、但新资料中已经没有的编号
    stale_ids = sorted(old_ids - new_ids)
    # 4. 分批写入文档、向量及来源信息
    for start in range(0, len(records), 100):
        batch = records[start:start + 100]

        collection.upsert(
            ids=[
                record["document"]["id"]
                for record in batch
            ],
            documents=[
                record["document"]["content"]
                for record in batch
            ],
            embeddings=[
                record["vector"]
                for record in batch
            ],
            metadatas=[
                {
                    "title": record["document"]["title"],
                    "source": record["document"]["source"],
                    "chunk_index": record["document"].get(
                        "chunk_index", 1
                    )
                }
                for record in batch
            ]
        )
    # 所有批次写入成功后，再清理失效记录
    if stale_ids:
        collection.delete(ids=stale_ids)

    print("清理旧记录数量：", len(stale_ids))
    print("导入完成")
    print("本次导入数量：", len(records))
    print("集合内记录数量：", collection.count())


async def main():
    if await build_vectors():
        import_index()


if __name__ == "__main__":
    asyncio.run(main())
