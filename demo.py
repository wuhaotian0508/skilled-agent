import json
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI()
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

# ── tool registry ──────────────────────────────────────────
registry = {}  # { "func_name": {"func": callable, "schema": dict} }

def register(func, description, parameters):
    """注册一个工具：把函数和它的 schema 统一存到 registry"""
    registry[func.__name__] = {
        "func": func,
        "schema": {
            "type": "function",
            "function": {
                "name": func.__name__,
                "description": description,
                "parameters": parameters,
            }
        }
    }

# ── 工具函数 ───────────────────────────────────────────────
def get_weather(city: str) -> str:
    data = {"北京": "晴天，25°C", "上海": "多云，22°C", "广州": "小雨，28°C"}
    return data.get(city, f"{city}：暂无数据")

def get_stock_price(symbol: str) -> str:
    data = {"AAPL": "$189.50", "TSLA": "$245.30", "GOOGL": "$178.20"}
    return data.get(symbol.upper(), f"{symbol}：暂无数据")

# ── 注册工具（只需改这里，tools 和 available_functions 自动同步）──
register(get_weather, "获取指定城市的天气信息", {
    "type": "object",
    "properties": {"city": {"type": "string", "description": "城市名称，如：北京"}},
    "required": ["city"]
})

register(get_stock_price, "获取指定股票的当前价格", {
    "type": "object",
    "properties": {"symbol": {"type": "string", "description": "股票代码，如：AAPL"}},
    "required": ["symbol"]
})

# ── 从 registry 自动派生出这两个变量（不用手动维护）──────────
tools = [v["schema"] for v in registry.values()]
available_functions = {k: v["func"] for k, v in registry.items()}

print("已注册的工具:", list(registry.keys()))
print()

# ── 主流程 ─────────────────────────────────────────────────
messages = [{"role": "user", "content": "北京今天天气怎么样？顺便查一下苹果(AAPL)的股价"}]

response = client.chat.completions.create(model=MODEL, messages=messages, tools=tools)
msg = response.choices[0].message

print("=== Round 1 返回 ===")
print(f"tool_calls 数量: {len(msg.tool_calls) if msg.tool_calls else 0}")
print()

if msg.tool_calls:
    messages.append(msg)
    for tool_call in msg.tool_calls:
        func_name = tool_call.function.name
        func_args = json.loads(tool_call.function.arguments)
        result = available_functions[func_name](**func_args)

        print(f"调用: {func_name}({func_args})")
        print(f"返回: {result}")
        print()

        messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})

    final_response = client.chat.completions.create(model=MODEL, messages=messages)
    print("=== 模型最终回答 ===")
    print(final_response.choices[0].message.content)
else:
    print(f"模型回答：{msg.content}")
