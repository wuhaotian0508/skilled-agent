import os
import json
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# 定义提取工具
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "extract_info",
            "description": "从文本中提取城市和天气信息",
            "parameters": {
                "type": "array",
                "items": {
                    "城市": {"type": "string", "description": "文中提到的城市"},
                    "天气": {"type": "string", "description": "文中提到当天的天气"}
                },
                "required": ["城市", "天气"]
            }
        }
    }
]

def main():
    # 初始化客户端
    api_key = os.getenv("OPENAI_API_KEY", os.getenv("ANTHROPIC_API_KEY"))
    raw_base_url = os.getenv("OPENAI_BASE_URL", os.getenv("ANTHROPIC_BASE_URL", "https://api.gpugeek.com/"))
    base_url = raw_base_url if raw_base_url.endswith("/v1") or raw_base_url.endswith("/v1/") else f"{raw_base_url.rstrip('/')}/v1"
    model_name = os.getenv("OPENAI_MODEL", os.getenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "Vendor2/Claude-4.5-Sonnet"))
    
    client = OpenAI(api_key=api_key, base_url=base_url)
    
    # 用户输入
    text = "上海通常是晴天，但今天下雨了"
    
    # 调用模型
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": "你是一个信息提取助手，请调用 extract_info 函数提取文本中的城市和天气信息。"},
            {"role": "user", "content": text}
        ],
        tools=TOOLS,
        tool_choice={"type": "function", "function": {"name": "extract_info"}}
    )
    
    # 提取结果
    tool_call = response.choices[0].message.tool_calls[0]
    result = json.loads(tool_call.function.arguments)
    
    print(f"输入: {text}")
    print(f"输出: {json.dumps(result, ensure_ascii=False, indent=2)}")

if __name__ == "__main__":
    main()
