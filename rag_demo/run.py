"""
最简 RAG 演示 —— 能直接跑起来的完整版本

流程：
  1. 读取 knowledge/ 下的 .txt 文件作为知识库
  2. 用户提问 → TF-IDF 余弦相似度检索最相关的段落
  3. 把段落塞进 prompt → 调用 LLM 生成回答
"""

import math
import os
import re
import sys
from collections import Counter
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


# ========== 2. 检索引擎（纯手写 TF-IDF） ==========

def tokenize(text: str) -> list[str]:
    """中文按单字切，英文按单词切"""
    return re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+", text.lower())


def build_idf(doc_token_lists: list[list[str]]) -> dict[str, float]:
    n = len(doc_token_lists)
    idf = {}
    for tokens in doc_token_lists:
        for word in set(tokens):
            idf[word] = idf.get(word, 0) + 1
    return {word: math.log(n / count) for word, count in idf.items()}


def tfidf_vector(tokens: list[str], idf: dict[str, float]) -> dict[str, float]:
    tf = Counter(tokens)
    total = len(tokens)
    return {w: (c / total) * idf.get(w, 0) for w, c in tf.items()}


def cosine_sim(v1: dict, v2: dict) -> float:
    common = set(v1) & set(v2)
    dot = sum(v1[k] * v2[k] for k in common)
    n1 = math.sqrt(sum(v ** 2 for v in v1.values()))
    n2 = math.sqrt(sum(v ** 2 for v in v2.values()))
    return dot / (n1 * n2) if n1 and n2 else 0.0


class Retriever:
    def __init__(self, chunks: list[dict]):
        self.chunks = chunks
        self.token_lists = [tokenize(c["text"]) for c in chunks]
        self.idf = build_idf(self.token_lists)
        self.vectors = [tfidf_vector(t, self.idf) for t in self.token_lists]

    def search(self, query: str, top_k: int = 3) -> list[tuple[dict, float]]:
        q_vec = tfidf_vector(tokenize(query), self.idf)
        scored = [(c, cosine_sim(q_vec, v)) for c, v in zip(self.chunks, self.vectors)]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


# ========== 3. RAG：检索 + 生成 ==========

def rag(question: str, retriever: Retriever, client: OpenAI, model: str) -> str:
    # 检索
    results = retriever.search(question, top_k=3)

    print("\n--- 检索结果 ---")
    for i, (chunk, score) in enumerate(results):
        print(f"  [{i+1}] 相似度={score:.3f} | 来源={chunk['source']}")
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
    # 初始化 API
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.gpugeek.com/v1")
    model = os.getenv("OPENAI_MODEL", "Vendor2/GPT-5.2")

    if not api_key:
        print("错误：.env 中未找到 OPENAI_API_KEY")
        sys.exit(1)

    client = OpenAI(api_key=api_key, base_url=base_url)

    # 加载知识库
    knowledge_dir = os.path.join(os.path.dirname(__file__), "knowledge")
    chunks = load_knowledge(knowledge_dir)
    if not chunks:
        print(f"错误：{knowledge_dir} 下没有 .txt 文件")
        sys.exit(1)

    retriever = Retriever(chunks)

    print("=" * 45)
    print("   最简 RAG 演示")
    print("=" * 45)
    print(f"知识库：{len(chunks)} 个段落（来自 {knowledge_dir}）")
    print(f"模型：{model}")
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
