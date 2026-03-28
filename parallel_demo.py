"""
并行 vs 串行 API 调用演示
================================
场景：同时向 LLM 发 3 个独立问题

串行：问题1完成 → 问题2完成 → 问题3完成   总耗时 ≈ T1+T2+T3
并行：3个问题同时发出                        总耗时 ≈ max(T1,T2,T3)
"""

import time
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.gpugeek.com/v1"),
)
MODEL = os.getenv("OPENAI_MODEL", "Vendor2/GPT-5.2")

QUESTIONS = [
    "用一句话解释什么是机器学习",
    "用一句话解释什么是深度学习",
    "用一句话解释什么是强化学习",
]


# ========== 单次 API 调用 ==========
def call_api(question: str) -> str:
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": question}],
        temperature=0.3,
    )
    return resp.choices[0].message.content


# ========== 串行调用 ==========
def run_serial():
    print("\n【串行调用】")
    t0 = time.time()
    results = []
    for q in QUESTIONS:
        print(f"  发送: {q}")
        ans = call_api(q)
        results.append((q, ans))
        print(f"  完成: {ans[:40]}...")
    elapsed = time.time() - t0
    print(f"  ✅ 串行总耗时: {elapsed:.2f}s\n")
    return results


# ========== 并行调用 ==========
def run_parallel():
    print("\n【并行调用】")
    t0 = time.time()
    results = {}

    with ThreadPoolExecutor(max_workers=len(QUESTIONS)) as executor:
        # 同时提交所有任务
        future_to_q = {executor.submit(call_api, q): q for q in QUESTIONS}
        print(f"  已同时发出 {len(QUESTIONS)} 个请求，等待响应...")

        for future in as_completed(future_to_q):
            q = future_to_q[future]
            ans = future.result()
            results[q] = ans
            print(f"  完成: {ans[:40]}...")

    elapsed = time.time() - t0
    print(f"  ✅ 并行总耗时: {elapsed:.2f}s\n")
    return results


# ========== 主程序 ==========
if __name__ == "__main__":
    serial_results  = run_serial()
    parallel_results = run_parallel()
