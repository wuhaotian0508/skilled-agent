"""
rag_extract.py
RAG-based gene extraction pipeline:
  论文 MD → 按 section 分 chunk → Jina embedding → numpy 内存向量库
  Phase 1: 检索 + LLM 识别核心基因列表
  Phase 2: 按基因检索 + LLM 提取 24 字段
  Phase 3: 合并输出 JSON
"""

import os
import re
import json
import time
import numpy as np
import requests
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv
from text_utils import _split_sections

# ═══════════════════════════════════════════════════════════════════════════════
#  配置
# ═══════════════════════════════════════════════════════════════════════════════

# 从 simple-agent/.env 加载
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "Vendor2/Claude-4.6-opus")
JINA_API_KEY = os.getenv("JINA_API_KEY")
JINA_EMBED_MODEL = os.getenv("JINA_EMBED_MODEL", "jina-embeddings-v3")

client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

# 输入 / 输出路径
INPUT_FILE = Path(__file__).resolve().parent / "Mol_Plant_2017_Zhu_processed.md"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

SCHEMA_FILE = Path(__file__).resolve().parent / "nutri_gene_schema_v2.json"
PROMPT_FILE = Path(__file__).resolve().parent / "nutri_gene_prompt_v2.txt"


# ═══════════════════════════════════════════════════════════════════════════════
#  1. Chunking — 复用 text_utils._split_sections()
# ═══════════════════════════════════════════════════════════════════════════════

def estimate_tokens(text):
    """粗略估算 token 数（英文 ~4 chars/token）"""
    return len(text) // 4


def chunk_markdown(md_content, max_tokens=1000):
    """
    按 # 标题切分 section，过长的 section 按双换行进一步切分。
    返回: list of {"text": str, "section": str, "index": int}
    """
    preamble, sections = _split_sections(md_content)

    chunks = []
    idx = 0

    # preamble 作为第一个 chunk（通常包含标题、摘要等）
    if preamble.strip():
        chunks.append({"text": preamble.strip(), "section": "Preamble", "index": idx})
        idx += 1

    for heading, body in sections:
        full_text = heading + "\n" + body.strip()

        if estimate_tokens(full_text) <= max_tokens:
            chunks.append({"text": full_text, "section": heading, "index": idx})
            idx += 1
        else:
            # 按双换行切分为子段落
            paragraphs = re.split(r'\n\n+', body.strip())
            sub_chunk = heading  # 每个子 chunk 以 heading 开头
            for para in paragraphs:
                if estimate_tokens(sub_chunk + "\n\n" + para) > max_tokens and sub_chunk != heading:
                    chunks.append({"text": sub_chunk.strip(), "section": heading, "index": idx})
                    idx += 1
                    sub_chunk = heading + "\n\n" + para
                else:
                    sub_chunk += "\n\n" + para
            if sub_chunk.strip() and sub_chunk.strip() != heading:
                chunks.append({"text": sub_chunk.strip(), "section": heading, "index": idx})
                idx += 1

    return chunks


# ═══════════════════════════════════════════════════════════════════════════════
#  2. Embedding — Jina API
# ═══════════════════════════════════════════════════════════════════════════════

def embed_texts(texts, batch_size=64):
    """
    调用 Jina API 批量 embed，返回 np.ndarray (n, dim)。
    """
    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        resp = requests.post(
            "https://api.jina.ai/v1/embeddings",
            headers={
                "Authorization": f"Bearer {JINA_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": JINA_EMBED_MODEL,
                "input": batch,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        batch_embs = [item["embedding"] for item in data["data"]]
        all_embeddings.extend(batch_embs)
        token_usage = data.get("usage", {}).get("total_tokens", "?")
        print(f"  [embed] batch {i//batch_size + 1}: {len(batch)} texts, tokens={token_usage}")

    return np.array(all_embeddings, dtype=np.float32)


# ═══════════════════════════════════════════════════════════════════════════════
#  3. 检索 — cosine similarity
# ═══════════════════════════════════════════════════════════════════════════════

def retrieve(query, chunk_texts, chunk_embeddings, top_k=10):
    """
    query → embed → cosine similarity → top_k chunks
    返回: list of (chunk_text, score)
    """
    q_emb = embed_texts([query])  # (1, dim)
    # cosine similarity: dot product of normalized vectors
    norms_q = np.linalg.norm(q_emb, axis=1, keepdims=True)
    norms_c = np.linalg.norm(chunk_embeddings, axis=1, keepdims=True)
    q_normed = q_emb / (norms_q + 1e-9)
    c_normed = chunk_embeddings / (norms_c + 1e-9)
    scores = (c_normed @ q_normed.T).squeeze()  # (n,)

    top_indices = np.argsort(scores)[::-1][:top_k]
    results = [(chunk_texts[i], float(scores[i])) for i in top_indices]
    return results


# ═══════════════════════════════════════════════════════════════════════════════
#  4. LLM 调用辅助
# ═══════════════════════════════════════════════════════════════════════════════

def call_llm(system_prompt, user_prompt, temperature=0):
    """调用 LLM，返回文本响应和 token 使用量。"""
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=4096,
    )
    text = response.choices[0].message.content.strip()
    usage = response.usage
    print(f"  [LLM] prompt_tokens={usage.prompt_tokens}, completion_tokens={usage.completion_tokens}")
    return text


def extract_json_from_text(text):
    """从 LLM 输出中提取 JSON（兼容 ```json ``` 包裹）。"""
    # 先尝试 code block
    m = re.search(r'```(?:json)?\s*\n?(.*?)```', text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    # 尝试解析
    return json.loads(text)


# ═══════════════════════════════════════════════════════════════════════════════
#  5. Schema 字段描述提取
# ═══════════════════════════════════════════════════════════════════════════════

def load_field_descriptions():
    """
    从 nutri_gene_schema_v2.json 提取 CommonGene 的 field name + description，
    构建紧凑的字段说明文本。
    """
    with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
        schema = json.load(f)

    properties = schema["CommonGeneExtraction"]["$defs"]["CommonGene"]["properties"]
    lines = []
    for field_name, field_def in properties.items():
        desc = field_def.get("description", "")
        lines.append(f"- **{field_name}**: {desc}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
#  6. Phase 1 — 核心基因识别
# ═══════════════════════════════════════════════════════════════════════════════

def phase1_identify_genes(chunk_texts, chunk_embeddings):
    """
    检索与基因研究相关的 chunks，让 LLM 识别核心基因列表。
    同时提取论文元数据 (Title, Journal, DOI)。
    """
    print("\n" + "=" * 60)
    print("Phase 1: 核心基因识别")
    print("=" * 60)

    query = "core genes experimentally studied gene function metabolite biosynthesis"
    results = retrieve(query, chunk_texts, chunk_embeddings, top_k=10)

    print(f"  检索到 {len(results)} 个 chunks, 相似度范围: {results[-1][1]:.3f} ~ {results[0][1]:.3f}")

    context = "\n\n---\n\n".join([text for text, score in results])

    system_prompt = (
        "You are a plant molecular biology expert. Analyze the provided paper excerpts "
        "and identify the core genes that are experimentally studied in the Results section. "
        "Also extract the paper metadata."
    )

    user_prompt = f"""Based on the following excerpts from a scientific paper, please:

1. Identify ALL core genes that are primary subjects of experimentation in the Results section.
   - Include both transgenes and endogenous genes that are directly studied
   - Do NOT include genes only mentioned as background in Introduction/Discussion

2. Extract the paper metadata: Title, Journal, DOI

Return your answer as JSON in this exact format:
{{
  "Title": "paper title",
  "Journal": "journal name",
  "DOI": "doi string",
  "core_genes": ["Gene1", "Gene2", ...]
}}

Paper excerpts:
{context}"""

    response_text = call_llm(system_prompt, user_prompt)

    try:
        result = extract_json_from_text(response_text)
        genes = result.get("core_genes", [])
        metadata = {
            "Title": result.get("Title", "NA"),
            "Journal": result.get("Journal", "NA"),
            "DOI": result.get("DOI", "NA"),
        }
        print(f"  识别到 {len(genes)} 个核心基因: {genes}")
        print(f"  论文: {metadata['Title'][:60]}...")
        return genes, metadata
    except (json.JSONDecodeError, KeyError) as e:
        print(f"  JSON 解析失败: {e}")
        print(f"  LLM 原始输出:\n{response_text[:500]}")
        return [], {"Title": "NA", "Journal": "NA", "DOI": "NA"}


# ═══════════════════════════════════════════════════════════════════════════════
#  7. Phase 2 — 按基因提取 24 字段
# ═══════════════════════════════════════════════════════════════════════════════

def phase2_extract_gene(gene_name, chunk_texts, chunk_embeddings, field_descriptions, role_prompt):
    """
    对单个基因：检索相关 chunks → LLM 提取 24 字段。
    """
    print(f"\n  --- 提取基因: {gene_name} ---")

    query = f"{gene_name} function expression validation metabolite phenotype result"
    results = retrieve(query, chunk_texts, chunk_embeddings, top_k=8)

    print(f"  检索到 {len(results)} 个 chunks, 相似度: {results[-1][1]:.3f} ~ {results[0][1]:.3f}")

    context = "\n\n---\n\n".join([text for text, score in results])

    system_prompt = role_prompt

    user_prompt = f"""Extract structured information for the gene **{gene_name}** from the following paper excerpts.

Fill in ALL 24 fields below based on the paper content. If a field is not mentioned, use "NA".

**Fields to extract:**
{field_descriptions}

**Paper excerpts:**
{context}

Return ONLY a valid JSON object with exactly the 24 fields listed above. Do not include any explanation outside the JSON."""

    response_text = call_llm(system_prompt, user_prompt)

    try:
        gene_data = extract_json_from_text(response_text)
        # 确保 Gene_Name 字段正确
        gene_data["Gene_Name"] = gene_name
        filled = sum(1 for v in gene_data.values() if v and v != "NA")
        print(f"  填充字段: {filled}/24")
        return gene_data
    except (json.JSONDecodeError, KeyError) as e:
        print(f"  JSON 解析失败: {e}")
        print(f"  LLM 原始输出:\n{response_text[:500]}")
        return {"Gene_Name": gene_name}


# ═══════════════════════════════════════════════════════════════════════════════
#  8. Main — 完整流水线
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    start_time = time.time()

    # --- 读取输入 ---
    print(f"读取论文: {INPUT_FILE}")
    md_content = INPUT_FILE.read_text(encoding="utf-8")
    print(f"  原文长度: {len(md_content)} chars, ~{estimate_tokens(md_content)} tokens")

    # --- Chunking ---
    print("\nStep 1: Chunking")
    chunks = chunk_markdown(md_content)
    print(f"  切分为 {len(chunks)} 个 chunks")
    for c in chunks:
        print(f"    [{c['index']:2d}] {c['section'][:50]:50s} | {estimate_tokens(c['text']):5d} tokens")

    chunk_texts = [c["text"] for c in chunks]

    # --- Embedding ---
    print("\nStep 2: Embedding all chunks")
    chunk_embeddings = embed_texts(chunk_texts)
    print(f"  Embedding shape: {chunk_embeddings.shape}")

    # --- Phase 1: 核心基因识别 ---
    core_genes, metadata = phase1_identify_genes(chunk_texts, chunk_embeddings)

    if not core_genes:
        print("未识别到核心基因，退出。")
        return

    # --- 加载 schema 字段描述 & prompt ---
    field_descriptions = load_field_descriptions()
    role_prompt = PROMPT_FILE.read_text(encoding="utf-8")
    # 只取 <Role> 部分作为 system prompt
    role_match = re.search(r'<Role>(.*?)</Role>', role_prompt, re.DOTALL)
    if role_match:
        role_prompt = role_match.group(1).strip()
    else:
        # fallback: 取开头到 <Mission> 之前
        role_prompt = role_prompt.split("#### **`<Mission>`**")[0].strip()
        # 去掉 markdown 标记
        role_prompt = re.sub(r'[#*`<>/]', '', role_prompt).strip()

    # --- Phase 2: 按基因提取 ---
    print("\n" + "=" * 60)
    print("Phase 2: 按基因提取 24 字段")
    print("=" * 60)

    all_genes = []
    for gene_name in core_genes:
        gene_data = phase2_extract_gene(gene_name, chunk_texts, chunk_embeddings,
                                        field_descriptions, role_prompt)
        all_genes.append(gene_data)

    # --- Phase 3: 合并输出 ---
    print("\n" + "=" * 60)
    print("Phase 3: 合并输出")
    print("=" * 60)

    final_result = {
        "Title": metadata["Title"],
        "Journal": metadata["Journal"],
        "DOI": metadata["DOI"],
        "Genes": all_genes,
        "_metadata": {
            "source_file": INPUT_FILE.name,
            "model": OPENAI_MODEL,
            "method": "RAG (Jina embedding + cosine retrieval)",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "num_chunks": len(chunks),
            "num_genes_extracted": len(all_genes),
        }
    }

    output_file = OUTPUT_DIR / f"{INPUT_FILE.stem}_rag_result.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(final_result, f, ensure_ascii=False, indent=2)

    elapsed = time.time() - start_time
    print(f"\n  输出文件: {output_file}")
    print(f"  提取基因数: {len(all_genes)}")
    print(f"  总耗时: {elapsed:.1f}s")
    print("\nDone!")


if __name__ == "__main__":
    main()
