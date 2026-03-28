"""
RAG 记忆与说明书检索演示

两大功能：
  1. MemoryStore  — 对话记忆持久化，跨会话"记住"用户说过的话
  2. ManualRetriever — 产品说明书的智能检索问答

技术栈：
  - Jina AI Embedding（语义向量）
  - OpenAI 兼容 LLM（生成回答 + 提取记忆）
  - 余弦相似度 top-k 检索
"""

import json
import math
import os
import re
import sys
import time
import requests
from openai import OpenAI
from dotenv import load_dotenv

# 加载项目根目录的 .env
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


# ============================
#  工具函数
# ============================

def cosine_sim(v1: list[float], v2: list[float]) -> float:
    """余弦相似度"""
    dot = sum(a * b for a, b in zip(v1, v2))
    n1 = math.sqrt(sum(a * a for a in v1))
    n2 = math.sqrt(sum(b * b for b in v2))
    return dot / (n1 * n2) if n1 and n2 else 0.0


def get_embedding(text: str, jina_api_key: str, model: str) -> list[float]:
    """调用 Jina AI Embedding API 获取单条向量"""
    resp = requests.post(
        "https://api.jina.ai/v1/embeddings",
        headers={
            "Authorization": f"Bearer {jina_api_key}",
            "Content-Type": "application/json",
        },
        json={"model": model, "input": [text]},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["data"][0]["embedding"]


def get_embeddings_batch(texts: list[str], jina_api_key: str, model: str) -> list[list[float]]:
    """批量获取 Embedding 向量"""
    resp = requests.post(
        "https://api.jina.ai/v1/embeddings",
        headers={
            "Authorization": f"Bearer {jina_api_key}",
            "Content-Type": "application/json",
        },
        json={"model": model, "input": texts},
        timeout=60,
    )
    resp.raise_for_status()
    data = sorted(resp.json()["data"], key=lambda x: x["index"])
    return [item["embedding"] for item in data]


# ============================
#  MemoryStore — 对话记忆
# ============================

class MemoryStore:
    """
    对话记忆持久化存储。

    - 每条记忆 = {"text": ..., "timestamp": ..., "embedding": [...]}
    - 以 JSONL 格式保存到 memories/chat_memory.jsonl
    - 启动时加载已有记忆，支持语义检索
    """

    def __init__(self, memory_path: str, jina_api_key: str, embed_model: str):
        self.memory_path = memory_path
        self.jina_api_key = jina_api_key
        self.embed_model = embed_model
        self.memories: list[dict] = []  # {"text", "timestamp", "embedding"}

        self._load()

    def _load(self):
        """从 JSONL 文件加载已有记忆"""
        if not os.path.exists(self.memory_path):
            return
        with open(self.memory_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    self.memories.append(json.loads(line))
        if self.memories:
            print(f"  已加载 {len(self.memories)} 条历史记忆")

    def add(self, text: str):
        """添加一条新记忆"""
        embedding = get_embedding(text, self.jina_api_key, self.embed_model)
        entry = {
            "text": text,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "embedding": embedding,
        }
        self.memories.append(entry)

        # 追加写入文件
        os.makedirs(os.path.dirname(self.memory_path), exist_ok=True)
        with open(self.memory_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        print(f"  [记忆已保存] {text}")

    def search(self, query: str, top_k: int = 3) -> list[tuple[str, float]]:
        """语义检索最相关的记忆"""
        if not self.memories:
            return []
        q_vec = get_embedding(query, self.jina_api_key, self.embed_model)
        scored = [
            (m["text"], cosine_sim(q_vec, m["embedding"]))
            for m in self.memories
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        # 只返回相似度 > 0.5 的记忆
        return [(text, score) for text, score in scored[:top_k] if score > 0.5]


# ============================
#  ManualRetriever — 说明书检索
# ============================

class ManualRetriever:
    """
    产品说明书检索器。

    - 加载 knowledge/ 下 .txt 文件，按段落切块 + Embedding
    - 支持语义 top-k 检索
    """

    def __init__(self, knowledge_dir: str, jina_api_key: str, embed_model: str):
        self.jina_api_key = jina_api_key
        self.embed_model = embed_model
        self.chunks: list[dict] = []   # {"source", "text"}
        self.vectors: list[list[float]] = []

        self._build_index(knowledge_dir)

    def _build_index(self, knowledge_dir: str):
        """读取说明书并构建 Embedding 索引"""
        for filename in sorted(os.listdir(knowledge_dir)):
            if not filename.endswith(".txt"):
                continue
            filepath = os.path.join(knowledge_dir, filename)
            with open(filepath, "r", encoding="utf-8") as f:
                text = f.read().strip()
            paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
            for p in paragraphs:
                self.chunks.append({"source": filename, "text": p})

        if not self.chunks:
            print("  警告：说明书目录为空，说明书检索不可用")
            return

        print(f"  正在为 {len(self.chunks)} 个说明书段落构建 Embedding 索引...")
        texts = [c["text"] for c in self.chunks]
        self.vectors = get_embeddings_batch(texts, self.jina_api_key, self.embed_model)
        print(f"  说明书索引构建完成（向量维度 {len(self.vectors[0])}）")

    def search(self, query: str, top_k: int = 3) -> list[tuple[dict, float]]:
        """语义检索最相关的说明书段落"""
        if not self.vectors:
            return []
        q_vec = get_embedding(query, self.jina_api_key, self.embed_model)
        scored = [
            (chunk, cosine_sim(q_vec, vec))
            for chunk, vec in zip(self.chunks, self.vectors)
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


# ============================
#  记忆提取（LLM 判断）
# ============================

def extract_memories(user_input: str, assistant_reply: str, client: OpenAI, model: str) -> list[str]:
    """
    用 LLM 判断本轮对话中是否有值得记忆的用户信息。

    返回要存储的记忆列表（可能为空）。
    """
    prompt = f"""请分析下面这轮对话，提取用户透露的**个人信息、偏好或重要事实**。

规则：
- 只提取用户主动透露的信息（姓名、职业、喜好、习惯等）
- 不要提取用户的提问内容本身
- 每条信息用一句简短的陈述句表达
- 如果没有值得记忆的信息，返回空 JSON 数组 []

用户说：{user_input}
助手回复：{assistant_reply}

请以 JSON 数组格式返回，例如：["用户叫小明", "用户喜欢吃辣"]"""

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        content = resp.choices[0].message.content.strip()
        # 提取 JSON 数组
        match = re.search(r"\[.*?\]", content, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        print(f"  [记忆提取失败] {e}")
    return []


# ============================
#  主对话循环
# ============================

def chat(
    user_input: str,
    memory_store: MemoryStore,
    manual_retriever: ManualRetriever,
    client: OpenAI,
    model: str,
) -> str:
    """
    处理一轮对话：
      1. 检索相关记忆
      2. 检索说明书
      3. 合并 context → LLM 生成回答
    """

    # --- 1. 检索记忆 ---
    memory_results = memory_store.search(user_input, top_k=3)
    memory_context = ""
    if memory_results:
        print("\n  --- 相关记忆 ---")
        for text, score in memory_results:
            print(f"    [{score:.3f}] {text}")
        memory_context = "你记得关于这位用户的信息：\n" + "\n".join(
            f"- {text}" for text, _ in memory_results
        )

    # --- 2. 检索说明书 ---
    manual_results = manual_retriever.search(user_input, top_k=3)
    manual_context = ""
    if manual_results:
        # 只取相似度较高的结果
        relevant = [(c, s) for c, s in manual_results if s > 0.5]
        if relevant:
            print("\n  --- 说明书检索结果 ---")
            for i, (chunk, score) in enumerate(relevant):
                print(f"    [{i+1}] 相似度={score:.4f} | {chunk['text'][:50]}...")
            manual_context = "以下是产品说明书的相关内容：\n\n" + "\n\n".join(
                chunk["text"] for chunk, _ in relevant
            )

    # --- 3. 构建 prompt 并生成回答 ---
    system_parts = ["你是一个友好的智能助手。"]
    if memory_context:
        system_parts.append(memory_context)
    if manual_context:
        system_parts.append(
            "用户可能在问产品使用问题，请参考说明书内容回答。"
            "如果说明书中有答案就据此回答，不要编造不在说明书中的信息。"
        )
        system_parts.append(manual_context)

    system_prompt = "\n\n".join(system_parts)

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ],
        temperature=0.5,
    )
    return resp.choices[0].message.content


def main():
    # --- 配置 ---
    jina_api_key = os.getenv("JINA_API_KEY")
    embed_model = os.getenv("JINA_EMBED_MODEL", "jina-embeddings-v3")

    openai_api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.gpugeek.com/v1")
    model = os.getenv("OPENAI_MODEL", "Vendor2/Claude-4.6-opus")

    if not jina_api_key:
        print("错误：.env 中未找到 JINA_API_KEY")
        sys.exit(1)
    if not openai_api_key:
        print("错误：.env 中未找到 OPENAI_API_KEY")
        sys.exit(1)

    client = OpenAI(api_key=openai_api_key, base_url=base_url)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    memory_path = os.path.join(base_dir, "memories", "chat_memory.jsonl")
    knowledge_dir = os.path.join(base_dir, "knowledge")

    # --- 初始化 ---
    print("=" * 55)
    print("   RAG 记忆 + 说明书检索 演示")
    print("=" * 55)
    print(f"  Embedding 模型：{embed_model}（Jina AI）")
    print(f"  生成模型：{model}")
    print()

    print("[1/2] 加载对话记忆...")
    memory_store = MemoryStore(memory_path, jina_api_key, embed_model)

    print("[2/2] 构建说明书索引...")
    manual_retriever = ManualRetriever(knowledge_dir, jina_api_key, embed_model)

    print("\n" + "-" * 55)
    print("准备就绪！你可以：")
    print("  - 聊天并告诉我你的信息（我会跨会话记住）")
    print("  - 问微波炉使用问题（我会从说明书中检索）")
    print("  - 输入 quit 退出")
    print("-" * 55 + "\n")

    while True:
        try:
            user_input = input("你：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if user_input.lower() in ("quit", "exit", "q"):
            print("再见！")
            break
        if not user_input:
            continue

        # 生成回答
        answer = chat(user_input, memory_store, manual_retriever, client, model)
        print(f"\n助手：{answer}\n")

        # 提取并保存记忆
        new_memories = extract_memories(user_input, answer, client, model)
        for mem in new_memories:
            memory_store.add(mem)
        if new_memories:
            print()


if __name__ == "__main__":
    main()
