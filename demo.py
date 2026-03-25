import json
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI()
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

# 定义工具函数
def get_weather(city: str) -> str:
    weather_data = {
        "北京": "晴天，25°C",
        "上海": "多云，22°C",
        "广州": "小雨，28°C",
    }
    return weather_data.get(city, f"{city}：暂无数据")

def get_stock_price(symbol: str) -> str:
    stock_data = {
        "AAPL": "$189.50",
        "TSLA": "$245.30",
        "GOOGL": "$178.20",
    }
    return stock_data.get(symbol.upper(), f"{symbol}：暂无数据")

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取指定城市的天气信息",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "城市名称，如：北京"}
                },
                "required": ["city"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_stock_price",
            "description": "获取指定股票的当前价格",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "股票代码，如：AAPL"}
                },
                "required": ["symbol"]
            }
        }
    }
]

available_functions = {
    "get_weather": get_weather,
    "get_stock_price": get_stock_price,
}

# 同时触发两个工具的 query
messages = [{"role": "user", "content": "苹果(AAPL)的天气怎么样"}]

# Round 1
response = client.chat.completions.create(
    model=MODEL,
    messages=messages,
    tools=tools,
)

msg = response.choices[0].message
print("=== Round 1 返回 ===")
print(f"tool_calls 数量: {len(msg.tool_calls) if msg.tool_calls else 0}")
print()

# 执行所有 tool_calls（并行）
if msg.tool_calls:
    messages.append(msg)
    for tool_call in msg.tool_calls:
        func_name = tool_call.function.name
        func_args = json.loads(tool_call.function.arguments)
        result = available_functions[func_name](**func_args)

        print(f"调用: {func_name}({func_args})")
        print(f"返回: {result}")
        print()

        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": result,
        })

    # Round 2
    final_response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
    )
    print("=== 模型最终回答 ===")
    print(final_response.choices[0].message.content)
else:
    print(f"模型回答：{msg.content}")
