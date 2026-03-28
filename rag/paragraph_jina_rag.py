"""
稍微复杂一点的 Jina RAG 示例（按段落切分 + LLM，不写函数）

目标：演示一篇文章如何先分段，再交给 Jina rerank 排序，最后把检索结果交给 LLM 生成答案。
"""

import os
import requests
from openai import OpenAI
from dotenv import load_dotenv


load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

api_key = os.getenv("JINA_API_KEY")
model = os.getenv("JINA_RERANK_MODEL", "jina-reranker-v2-base-multilingual")
openai_api_key = os.getenv("OPENAI_API_KEY")
base_url = os.getenv("OPENAI_BASE_URL", "https://api.gpugeek.com/v1")
llm_model = os.getenv("OPENAI_MODEL", "Vendor2/GPT-5.2")

if not api_key:
    print("错误：请先在 .env 中设置 JINA_API_KEY")
    raise SystemExit(1)

if not openai_api_key:
    print("错误：请先在 .env 中设置 OPENAI_API_KEY")
    raise SystemExit(1)

client = OpenAI(api_key=openai_api_key, base_url=base_url)

article = """
小明今年上小学三年级，他平时最喜欢吃苹果和香蕉。每天放学回家以后，他常常会先洗手，然后吃一点水果。

小红是小明的同学。她不太喜欢香蕉，但是很喜欢吃栗子和葡萄。她周末常常和妈妈一起去超市买零食。

除了喜欢吃水果以外，小明平时还喜欢穿拖鞋，也很喜欢踢足球。只要一到体育课，他就会特别开心。

他们的班主任老师平时喜欢喝茶，也喜欢看书。老师经常提醒大家，要养成健康饮食和按时运动的好习惯。
""".strip()

query = "小明喜欢吃什么水果？"

paragraphs = [p.strip() for p in article.split("\n\n") if p.strip()]

print("问题：", query)
print("\n整篇文章：")
print(article)

print("\n分段后的 documents：")
for i, p in enumerate(paragraphs):
    print(f"\n[{i}] {p}")

resp = requests.post(
    "https://api.jina.ai/v1/rerank",
    headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    },
    json={
        "model": model,
        "query": query,
        "documents": paragraphs,
        "top_n": 3,
    },
    timeout=30,
)

resp.raise_for_status()
results = resp.json()["results"]

print("\nJina 返回的 results：")
print(results)

print("\n把 results 对应回原段落后：")
for item in results:
    idx = item["index"]
    score = item["relevance_score"]
    print(f"\nindex={idx}, score={score:.4f}")
    print(paragraphs[idx])

context = "\n\n".join(paragraphs[item["index"]] for item in results)
print(context)

prompt = f"""你是一个问答助手。请严格根据给定内容回答问题。
如果内容里没有答案，就回答“未找到相关信息”。
回答尽量简洁。

【内容】
{context}

【问题】
{query}
"""

llm_resp = client.chat.completions.create(
    model=llm_model,
    messages=[{"role": "user", "content": prompt}],
    temperature=0.3,
)

answer = llm_resp.choices[0].message.content

print("\n最终答案：")
print(answer)
