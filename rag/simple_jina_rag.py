"""
最简单的 Jina RAG 示例（不写函数）

目标：直接演示 Jina rerank 返回的 results 怎么看、怎么用。
"""

import os
import requests
from dotenv import load_dotenv


load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

api_key = os.getenv("JINA_API_KEY")
model = os.getenv("JINA_RERANK_MODEL", "jina-reranker-v2-base-multilingual")

documents = [
    "小明喜欢吃苹果",
    "小红喜欢吃栗子",
    "小明喜欢吃香蕉",
    "小明喜欢穿拖鞋",
]

query = "小明喜欢吃什么水果？"

for i, doc in enumerate(documents):
    print(f"{i}: {doc}")

resp = requests.post(
    "https://api.jina.ai/v1/rerank",
    headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    },
    json={
        "model": model,
        "query": query,
        "documents": documents,
        "top_n": 3,
    }
)

resp.raise_for_status()
results = resp.json()["results"]

print("\nJina 返回的 results：")
print(results)

print("\n把 results 对应回原文后：")
for item in results:
    idx = item["index"]
    score = item["relevance_score"]
    print(f"index={idx}, score={score:.4f}, text={documents[idx]}")

answer_docs = []
for item in results:
    text = documents[item["index"]]
    if "小明喜欢吃" in text:
        answer_docs.append(text.replace("小明喜欢吃", ""))

print("\n最终答案：")
if answer_docs:
    print("小明喜欢吃：" + "、".join(answer_docs))
else:
    print("没有找到答案")