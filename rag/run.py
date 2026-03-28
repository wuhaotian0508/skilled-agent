"""
论文问答 RAG —— 用 Jina Reranker 对 Markdown 论文做语义检索 + LLM 生成

流程：
  1. 读取同目录下的 .md 文件，按段落切块
  2. 用户提问 → 调用 Jina Reranker API 直接对段落排序
  3. 取 top-k 段落拼接 prompt → 调用 LLM 生成回答
"""

import os
import re
import sys
import requests
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


# ========== 1. 读取知识库 ==========

def load_markdown_files(knowledge_dir: str) -> list[dict]:
    """读取目录下所有 .md 文件，按段落切块"""
    chunks = []
    for filename in sorted(os.listdir(knowledge_dir)):
        if not filename.endswith(".md"):
            continue
        filepath = os.path.join(knowledge_dir, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            text = f.read().strip()
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        for p in paragraphs:
            if len(p) > 30:
                chunks.append({"source": filename, "text": p})
    return chunks


# ========== 2. Jina Reranker 检索 ==========

def rerank(query: str, documents: list[str], api_key: str, model: str, top_n: int = 3) -> list[dict]:
    """调用 Jina Reranker API，直接返回按相关性排序的结果"""
    resp = requests.post(
        "https://api.jina.ai/v1/rerank",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "query": query, "documents": documents, "top_n": top_n},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["results"]


class Retriever:
    def __init__(self, chunks: list[dict], api_key: str, model: str):
        self.chunks = chunks
        self.api_key = api_key
        self.model = model
        self.documents = [c["text"] for c in chunks]

    def search(self, query: str, top_k: int = 3) -> list[tuple[dict, float]]:
        results = rerank(query, self.documents, self.api_key, self.model, top_n=top_k)
        return [(self.chunks[r["index"]], r["relevance_score"]) for r in results]


# ========== 3. RAG ==========

def rag(question: str, retriever: Retriever, client: OpenAI, model: str) -> str:
    results = retriever.search(question, top_k=3)

    print("\n--- 检索到的相关段落 ---")
    for i, (chunk, score) in enumerate(results):
        preview = chunk["text"][:80].replace("\n", " ")
        print(f"  [{i+1}] 相关性={score:.4f}")
        print(f"      {preview}...")

    context = "\n\n".join(chunk["text"] for chunk, _ in results)

    prompt = f"""你是一个学术论文问答助手。请根据下面的论文内容回答问题。
如果内容中没有相关信息，就说"论文中未找到相关信息"。
回答请尽量准确，可以引用原文。

【论文内容】
{context}

【问题】
{question}"""

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return resp.choices[0].message.content


# ========== 主程序 ==========

def main():
    jina_api_key = os.getenv("JINA_API_KEY")
    rerank_model = os.getenv("JINA_RERANK_MODEL", "jina-reranker-v2-base-multilingual")
    openai_api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.gpugeek.com/v1")
    llm_model = os.getenv("OPENAI_MODEL", "Vendor2/GPT-5.2")

    if not jina_api_key:
        print("错误：.env 中未找到 JINA_API_KEY")
        sys.exit(1)
    if not openai_api_key:
        print("错误：.env 中未找到 OPENAI_API_KEY")
        sys.exit(1)

    client = OpenAI(api_key=openai_api_key, base_url=base_url)

    knowledge_dir = os.path.dirname(os.path.abspath(__file__))
    chunks = load_markdown_files(knowledge_dir)
    if not chunks:
        print(f"错误：{knowledge_dir} 下没有 .md 文件")
        sys.exit(1)

    print("=" * 50)
    print("   论文问答 RAG（Jina Reranker）")
    print("=" * 50)
    print(f"知识库：{len(chunks)} 个段落")
    print(f"Reranker：{rerank_model}")
    print(f"LLM：{llm_model}")
    print("输入问题开始提问，输入 quit 退出\n")

    retriever = Retriever(chunks, jina_api_key, rerank_model)

    while True:
        q = input("问题：").strip()
        if q.lower() in ("quit", "exit", "q"):
            break
        if not q:
            continue
        answer = rag(q, retriever, client, llm_model)
        print(f"\n回答：{answer}\n")


if __name__ == "__main__":
    main()
