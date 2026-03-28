import os
import json
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# 推荐做法：无论是否提取到结果，都返回统一 JSON 结构
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "extract_info",
            "description": "从文本中提取城市和天气信息；如果无法明确提取，也返回统一 JSON 结构",
            "parameters": {
                "type": "object",
                "properties": {
                    "success": {
                        "type": "boolean",
                        "description": "是否成功提取到完整信息"
                    },
                    "data": {
                        "type": ["object", "null"],
                        "description": "提取结果；若没有结果则为 null",
                        "properties": {
                            "城市": {
                                "type": "string",
                                "description": "文中提到的城市"
                            },
                            "天气": {
                                "type": "string",
                                "description": "文中提到的天气"
                            }
                        },
                        "required": ["城市", "天气"],
                        "additionalProperties": False
                    },
                    "reason": {
                        "type": "string",
                        "description": "未提取到结果时的原因；提取成功时可为空字符串"
                    }
                },
                "required": ["success", "data", "reason"],
                "additionalProperties": False
            }
        }
    }
]


def call_extract_info(client, model_name: str, text: str) -> dict:
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一个信息提取助手。"
                    "请调用 extract_info 函数。"
                    "无论能否提取到城市和天气，都必须返回合法 JSON："
                    "提取到时 success=true, data 为对象；"
                    "提取不到时 success=false, data=null, 并在 reason 中说明原因。"
                ),
            },
            {"role": "user", "content": text},
        ],
        tools=TOOLS,
        tool_choice={"type": "function", "function": {"name": "extract_info"}},
    )

    tool_call = response.choices[0].message.tool_calls[0]
    return json.loads(tool_call.function.arguments)


def main():
    api_key = os.getenv("OPENAI_API_KEY", os.getenv("ANTHROPIC_API_KEY"))
    raw_base_url = os.getenv(
        "OPENAI_BASE_URL",
        os.getenv("ANTHROPIC_BASE_URL", "https://api.gpugeek.com/"),
    )
    base_url = (
        raw_base_url
        if raw_base_url.endswith("/v1") or raw_base_url.endswith("/v1/")
        else f"{raw_base_url.rstrip('/')}/v1"
    )
    model_name = os.getenv(
        "OPENAI_MODEL",
        os.getenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "Vendor2/Claude-4.5-Sonnet"),
    )

    client = OpenAI(api_key=api_key, base_url=base_url)

    examples = [
        "上海通常是晴天，但今天下雨了",
        "今天天气不错，适合出去走走",
    ]

    for text in examples:
        result = call_extract_info(client, model_name, text)
        print(f"输入: {text}")
        print("输出:")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("-" * 40)


if __name__ == "__main__":
    main()