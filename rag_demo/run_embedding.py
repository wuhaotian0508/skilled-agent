"""
升级版 RAG 演示 —— 使用 Jina AI Embedding API 做语义检索

流程：
  1. 读取 knowledge/ 下的 .txt 文件作为知识库
  2. 对每个段落调用 Jina Embedding API 获取语义向量（构建时一次性完成）
  3. 用户提问 → 问题也转成 Embedding → 余弦相似度找最相关段落
  4. 把段落塞进 prompt → 调用 LLM 生成回答

优势：
  - 语义理解！"细胞分裂" 和 "有丝分裂" 能匹配，TF-IDF 做不到
  - Jina jina-embeddings-v3 多语言支持强，中英文混合效果更好
  - Embedding 使用 Jina AI，LLM 生成继续使用原有接口
"""

import math
import os
import re
import sys
import requests
from openai import OpenAI
from dotenv import load_dotenv

# 加载项目根目录的 .env
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


# ========== 1. 读取知识库 ==========

def load_knowledge(knowledge_dir: str) -> list[dict]:
    """读取目录下所有 .txt 文件，按段落切块"""
    chunks = []
    for filename in sorted(os.listdir(knowledge_dir)):
        if not filename.endswith(".txt"):
            continue
        filepath = os.path.join(knowledge_dir, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            text = f.read().strip()
        # 按空行切段落
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        for p in paragraphs:
            chunks.append({"source": filename, "text": p})
    return chunks


# ========== 2. 工具函数 ==========

def cosine_sim(v1: list[float], v2: list[float]) -> float:
    """计算两个向量的余弦相似度"""
    dot = sum(a * b for a, b in zip(v1, v2))
    n1 = math.sqrt(sum(a ** 2 for a in v1))
    n2 = math.sqrt(sum(b ** 2 for b in v2))
    return dot / (n1 * n2) if n1 and n2 else 0.0


def get_embedding(text: str, jina_api_key: str, embed_model: str) -> list[float]:
    """调用 Jina AI Embedding API 获取向量"""
    resp = requests.post(
        "https://api.jina.ai/v1/embeddings",
        headers={
            "Authorization": f"Bearer {jina_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": embed_model,
            "input": [text],
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["data"][0]["embedding"]


def get_embeddings_batch(texts: list[str], jina_api_key: str, embed_model: str) -> list[list[float]]:
    """批量调用 Jina AI Embedding API，一次性获取多个向量（更高效）"""
    resp = requests.post(
        "https://api.jina.ai/v1/embeddings",
        headers={
            "Authorization": f"Bearer {jina_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": embed_model,
            "input": texts,
        },
        timeout=60,
    )
    resp.raise_for_status()
    # 按 index 排序确保顺序正确
    data = sorted(resp.json()["data"], key=lambda x: x["index"])
    return [item["embedding"] for item in data]


# ========== 3. 语义检索引擎 ==========

class EmbeddingRetriever:
    def __init__(self, chunks: list[dict], jina_api_key: str, embed_model: str):
        self.chunks = chunks
        self.jina_api_key = jina_api_key
        self.embed_model = embed_model

        print(f"正在对 {len(chunks)} 个段落生成 Jina Embedding 向量（批量请求）...")
        texts = [chunk["text"] for chunk in chunks]
        self.vectors = get_embeddings_batch(texts, jina_api_key, embed_model)
        print(f"Embedding 构建完成！向量维度：{len(self.vectors[0])}\n")

    def search(self, query: str, top_k: int = 3) -> list[tuple[dict, float]]:
        """语义检索：将问题转为向量，与知识库做余弦相似度排序"""
        q_vec = get_embedding(query, self.jina_api_key, self.embed_model)
        scored = [
            (chunk, cosine_sim(q_vec, vec))
            for chunk, vec in zip(self.chunks, self.vectors)
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


# ========== 4. RAG：检索 + 生成 ==========

def rag(question: str, retriever: EmbeddingRetriever, client: OpenAI, model: str) -> str:
    # 检索
    results = retriever.search(question, top_k=3)

    print("\n--- 语义检索结果（Jina Embedding）---")
    for i, (chunk, score) in enumerate(results):
        print(f"  [{i+1}] 相似度={score:.4f} | 来源={chunk['source']}")
        print(f"      {chunk['text'][:60]}...")

    context = "\n\n".join(chunk["text"] for chunk, _ in results)

    # 生成
    prompt = f"""请根据下面的参考资料回答问题。如果资料里没有答案，就说"资料中未找到相关信息"。

【参考资料】
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
    # Jina AI 配置（用于 Embedding）
    jina_api_key = os.getenv("JINA_API_KEY")
    embed_model = os.getenv("JINA_EMBED_MODEL", "jina-embeddings-v3")

    # OpenAI 兼容接口配置（用于 LLM 生成）
    openai_api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.gpugeek.com/v1")
    model = os.getenv("OPENAI_MODEL", "Vendor2/GPT-5.2")

    if not jina_api_key:
        print("错误：.env 中未找到 JINA_API_KEY")
        sys.exit(1)

    if not openai_api_key:
        print("错误：.env 中未找到 OPENAI_API_KEY")
        sys.exit(1)

    client = OpenAI(api_key=openai_api_key, base_url=base_url)

    # 加载知识库
    knowledge_dir = os.path.join(os.path.dirname(__file__), "knowledge")
    chunks = load_knowledge(knowledge_dir)
    if not chunks:
        print(f"错误：{knowledge_dir} 下没有 .txt 文件")
        sys.exit(1)

    print("=" * 55)
    print("   升级版 RAG 演示（Jina AI Embedding 语义检索）")
    print("=" * 55)
    print(f"知识库：{len(chunks)} 个段落（来自 {knowledge_dir}）")
    print(f"Embedding 模型：{embed_model}（Jina AI）")
    print(f"生成模型：{model}\n")

    # 构建语义检索器（批量调用 Jina API 预计算所有向量）
    retriever = EmbeddingRetriever(chunks, jina_api_key, embed_model)

    print("输入问题开始提问，输入 quit 退出\n")

    while True:
        q = input("❓ 问题：").strip()
        if q.lower() in ("quit", "exit", "q"):
            break
        if not q:
            continue
        answer = rag(q, retriever, client, model)
        print(f"\n💡 回答：{answer}\n")


if __name__ == "__main__":
    main()
