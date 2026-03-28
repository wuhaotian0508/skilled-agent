"""
text_utils.py
文本预处理工具：去除论文 Markdown 中的无用内容，减少 token 消耗。

对外只暴露一个入口函数 preprocess_md()，内部调用各子函数。
以后新增预处理规则只需改这一个文件。

当前预处理步骤：
    1. strip_images        — 去除图片标签（两种格式）
    2. strip_urls          — 去除括号内的 URL（http/https 链接）
    3. strip_references    — 去除 References / Literature Cited 引用列表
    4. strip_acknowledgments — 去除 Acknowledgments 段落
    5. strip_extra_blanks  — 合并多余空行
    6. extract_relevant_sections — 调用 LLM 判断各 section 标题，
       只保留 Results + Materials & Methods 相关部分（以及标题/摘要）
"""

import re
import os
import json


# ═══════════════════════════════════════════════════════════════════════════════
#  对外入口
# ═══════════════════════════════════════════════════════════════════════════════

def preprocess_md(md_content):
    """
    一站式 Markdown 预处理：去除 MinerU 转换产生的所有无用内容。

    调用方只需：
        from text_utils import preprocess_md
        content = preprocess_md(raw_md)

    Args:
        md_content: MinerU 转换后的 Markdown 全文

    Returns:
        清理后的文本（图片、引用列表、致谢 已去除，多余空行已合并，
        且只保留 Results + Materials & Methods 相关 section）
    """
    content = strip_images(md_content)
    content = strip_urls(content)
    content = strip_extra_blanks(content)
    content = extract_relevant_sections(content)
    return content


# ═══════════════════════════════════════════════════════════════════════════════
#  子函数
# ═══════════════════════════════════════════════════════════════════════════════

def strip_images(md_content):
    """
    去除 Markdown 图片标签。

    MinerU 有两种图片格式：
        1. ![image](https://cdn-mineru.openxlab.org.cn/result/...)   — CDN 链接
        2. ![](images/e2f35d9768aa228bf59dd00ff6e7ddcf...)           — 本地路径

    统一用一条正则匹配：![ 任意alt ]( 任意路径 )
    """
    result = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', md_content)
    return result


def strip_urls(md_content):
    """
    去除括号内的 URL 链接。

    MinerU 转换的论文中常包含大量括号内 URL，如：
        (https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE147589)
        (https://doi.org/10.5281/zenodo.5237316)
        (http://www.plantcell.org)

    这些对基因信息提取无用，且浪费 token。
    匹配 (http://...) 或 (https://...) 整体替换为空。
    """
    return re.sub(r'\(https?://[^)]*\)', '', md_content)


def strip_references(md_content):
    """
    去除 References / Literature Cited 引用列表，保留后面有用的 section。

    匹配的标题变体：
        # References / # REFERENCES / # References and Notes
        # LITERATURE CITED / # Literature Cited

    规则：
        - 从匹配的标题开始删除
        - 遇到下一个 `# ` + 大写字母开头的标题则停止删除，保留该标题及之后内容
        - 如果后面没有其他标题，直接截断
    """
    ref_pattern = re.compile(
        r'^#{1,2}\s+'
        r'(?:'
        r'References?\s*(?:and\s*notes)?'
        r'|'
        r'Literature\s+Cited'
        r')\s*$',
        re.MULTILINE | re.IGNORECASE
    )
    ref_match = ref_pattern.search(md_content)

    if not ref_match:
        return md_content

    ref_start = ref_match.start()
    after_ref = md_content[ref_match.end():]

    # 找下一个 `# ` + 大写字母开头的标题
    next_heading = re.search(r'^#\s+[A-Z]', after_ref, re.MULTILINE)

    if next_heading:
        kept_after = after_ref[next_heading.start():]
        return md_content[:ref_start].rstrip() + "\n\n" + kept_after
    else:
        return md_content[:ref_start].rstrip()


def strip_acknowledgments(md_content):
    """
    去除 Acknowledgments 段落。

    匹配的标题变体：
        # ACKNOWLEDGMENTS / # Acknowledgments / # Acknowledgements（英式拼写）
        ## ACKNOWLEDGMENTS（二级标题也匹配）

    规则同 strip_references：删到下一个 # 大写标题为止。
    """
    ack_pattern = re.compile(
        r'^#{1,2}\s+Acknowledg[e]?ments?\s*$',
        re.MULTILINE | re.IGNORECASE
    )
    ack_match = ack_pattern.search(md_content)

    if not ack_match:
        return md_content

    ack_start = ack_match.start()
    after_ack = md_content[ack_match.end():]

    next_heading = re.search(r'^#\s+[A-Z]', after_ack, re.MULTILINE)

    if next_heading:
        kept_after = after_ack[next_heading.start():]
        return md_content[:ack_start].rstrip() + "\n\n" + kept_after
    else:
        return md_content[:ack_start].rstrip()


def strip_extra_blanks(md_content):
    """合并 3 个以上连续空行为 2 个空行。"""
    return re.sub(r'\n{3,}', '\n\n', md_content)


# ═══════════════════════════════════════════════════════════════════════════════
#  Section 过滤：只保留 Results + Materials & Methods
# ═══════════════════════════════════════════════════════════════════════════════

def _split_sections(md_content):
    """
    按 '# ' 开头的行将 Markdown 拆分为多个 section。

    Returns:
        preamble: 第一个 '# ' 标题之前的内容（通常为空或 metadata）
        sections: list of (heading, body) 元组
                  heading 是 '# ...' 那一行（不含换行符）
                  body 是该标题到下一个 '# ' 标题之间的全部内容
    """
    # 找到所有以 '# ' 开头的行的位置（只匹配一级标题 '# '，不匹配 '## '）
    heading_pattern = re.compile(r'^# ', re.MULTILINE)
    matches = list(heading_pattern.finditer(md_content))

    if not matches:
        return md_content, []

    preamble = md_content[:matches[0].start()]
    sections = []

    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md_content)
        chunk = md_content[start:end]

        # 提取标题行（第一行）
        newline_pos = chunk.find('\n')
        if newline_pos == -1:
            heading = chunk.strip()
            body = ''
        else:
            heading = chunk[:newline_pos].strip()
            body = chunk[newline_pos:]

        sections.append((heading, body))

    return preamble, sections


def _classify_headings_with_llm(headings):
    """
    调用 LLM API 判断哪些标题需要被去除（反向逻辑）。

    Args:
        headings: list of str，论文中所有 '# ' 标题

    Returns:
        set of int，需要去除的标题索引（0-based）
    """
    from openai import OpenAI
    from dotenv import load_dotenv
    load_dotenv()

    client = OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL"),
    )
    model = os.getenv("MODEL", "Vendor2/Claude-4.6-opus")

    # 构建标题编号列表
    heading_list = "\n".join(f"{i}: {h}" for i, h in enumerate(headings))

    prompt = f"""Below is a numbered list of section headings from a scientific paper.
Please identify which headings should be REMOVED because they are NOT relevant to experimental results or methods.

Remove these types of sections:
- Introduction / Background
- References / References and Notes / Literature Cited
- Acknowledgments / Acknowledgements
- Author Contributions / Authors Contributions
- Funding / Financial Support
- Competing Interests / Conflict of Interest
- Additional Information
- Resource Distribution

Keep everything else (including Results, Methods, Discussion, paper title sections with content, Supplementary Materials, Accession Numbers etc.)

Headings:
{heading_list}

Return ONLY a JSON array of the index numbers that should be REMOVED.
Example: [0, 2, 4]
If nothing should be removed, return: []"""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant that identifies irrelevant sections in scientific papers. Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=200,
        )
        answer = response.choices[0].message.content.strip()

        # 提取 JSON 数组
        json_match = re.search(r'\[[\d\s,]*\]', answer)
        if json_match:
            indices = json.loads(json_match.group())
            return set(int(i) for i in indices if 0 <= i < len(headings))
        else:
            print(f"    ⚠️  [text_utils] LLM 返回无法解析的结果: {answer}")
            return None

    except Exception as e:
        print(f"    ❌ [text_utils] LLM section 分类调用失败: {e}")
        return None


def extract_relevant_sections(md_content):
    """
    去除论文中不相关的 section（Introduction、References、Acknowledgments 等），
    保留其余所有内容。

    流程：
        1. 按 '# ' 拆分所有 section
        2. 收集所有标题，一次性调用 LLM 判断哪些需要去除
        3. 拼接：preamble + 未被去除的 section
        4. 如果 LLM 调用失败，返回原始全文（fallback）

    Args:
        md_content: 经过基础清洗后的 Markdown 文本

    Returns:
        去除无关 section 后的文本
    """
    preamble, sections = _split_sections(md_content)

    if not sections:
        # 没有找到任何 '# ' 标题，返回原文
        return md_content

    headings = [h for h, _ in sections]
    print(f"    📑 [text_utils] 发现 {len(headings)} 个 section 标题，调用 LLM 分类...")

    remove_indices = _classify_headings_with_llm(headings)

    if remove_indices is None:
        print(f"    ⚠️  [text_utils] LLM 调用失败，使用全文 (fallback)")
        return md_content

    # 打印每个 section 的处理结果
    for i, h in enumerate(headings):
        mark = "❌ 去除" if i in remove_indices else "✅ 保留"
        print(f"        {mark}  {h}")

    # 拼接：preamble + 未被去除的 sections
    parts = [preamble.rstrip()]
    for i, (heading, body) in enumerate(sections):
        if i not in remove_indices:
            parts.append(heading + body)

    result = "\n\n".join(p for p in parts if p.strip())

    kept_len = len(result)
    orig_len = len(md_content)
    removed_count = len(remove_indices)
    kept_count = len(sections) - removed_count
    print(f"    📊 [text_utils] 去除 {removed_count} 个 section，保留 {kept_count} 个")
    print(f"    📊 [text_utils] 文本从 {orig_len} → {kept_len} 字符 "
          f"(保留 {kept_len * 100 // max(orig_len, 1)}%)")

    return result
