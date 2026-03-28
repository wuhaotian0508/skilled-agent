Step 1: 基础设施

 - 加载 .env 配置
 - Jina embedding 函数 (embed_texts(texts: list[str]) ->
 np.ndarray)
 - OpenAI LLM 调用函数
 - Cosine similarity 检索函数 (retrieve(query, chunks,
 embeddings, top_k))

 Step 2: Chunking

 - chunk_markdown(md_text) -> list[dict]：按 # 标题切分，每个
 chunk 带 {"text": ..., "section": ..., "index": ...}
 - 过长 section 按段落二次切分，保留上下文重叠

 Step 3: Phase 1 — 核心基因识别

 - 用通用 query 如 "core genes experimental results gene function
  metabolite" 检索 top 10 chunks
 - 发给 LLM，prompt 只要求返回核心基因名列表 (JSON array)

 Step 4: Phase 2 — 按组提取

 - 定义 5 个字段组，每组包含：字段名列表、query 模板、对应的
 schema 片段
 - 对每个基因 × 每组：构造 query → 检索 top 5 chunks → 发给 LLM
 提取该组字段
 - LLM 只返回该组字段的 JSON

 Step 5: Phase 3 — 合并输出

 - 合并每个基因的 5 组结果为完整 gene object
 - 组装顶层 JSON (Title, Journal, DOI, Genes)
 - 验证并写入文件

 关键文件路径

 - 输入: rag_test/Mol_Plant_2017_Zhu_processed.md
 - Schema: rag_test/nutri_gene_schema_v2.json
 - Prompt: rag_test/nutri_gene_prompt_v2.txt（Phase 1 参考其 Role
  定义）
 - 配置: simple-agent/.env
 - 输出: rag_test/rag_extract.py（代码）+ rag_test/output/ （结果
  JSON）
 - 复用: rag_test/text_utils.py 中的 chunking 逻辑可参考其
 _split_sections() 函数

 Verification

 1. python rag_test/rag_extract.py — 运行完整 pipeline
 2. 检查输出 JSON 结构是否符合 schema
 3. 比较 token 用量日志（脚本会打印每次调用的 token 数）
 4. 确认提取出的核心基因和字段值合理