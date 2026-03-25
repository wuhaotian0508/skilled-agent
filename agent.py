import os
import yaml
import json
import subprocess
from dotenv import load_dotenv
from openai import OpenAI

# 加载 .env 文件中的环境变量
load_dotenv()

# ==========================================
# 1. 技能加载系统 (Progressive Disclosure)
# ==========================================
def load_skills(skills_dir: str) -> str:
    if not os.path.exists(skills_dir):
        return ""
    
    skill_xml = ""
    for name in os.listdir(skills_dir):
        skill_path = os.path.join(skills_dir, name, "SKILL.md")
        if os.path.isfile(skill_path):
            with open(skill_path, "r", encoding="utf-8") as f:
                content = f.read()
            parts = content.split("---", 2)
            if len(parts) >= 3:
                meta = yaml.safe_load(parts[1])
                skill_xml += f"""
  <skill>
    <name>{meta.get('name', name)}</name>
    <description>{meta.get('description', '')}</description>
    <path>{skill_path}</path>
  </skill>"""
    return skill_xml

# ==========================================
# 2. 定义工具菜单 (OpenAI 格式)
# ==========================================
# 注意：OpenAI 需要外层包裹 type="function" 和 function={...}
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取指定路径的文件内容",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "文件绝对或相对路径"}},
                "required": ["path"],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "向指定路径写入文件。注意：这会覆盖原文件！",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件保存路径"},
                    "content": {"type": "string", "description": "要写入的完整文件内容"}
                },
                "required": ["path", "content"],
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_shell",
            "description": "在本地终端中执行 shell 命令并返回输出结果。用于查看目录、运行脚本等。",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string", "description": "要执行的 bash/shell 命令"}},
                "required": ["command"],
            }
        }
    }
]

# ==========================================
# 3. 本地执行逻辑 (Tool Handlers)
# ==========================================
def handle_tool_call(tool_name: str, tool_input: dict) -> str:
    try:
        if tool_name == "read_file":
            path = tool_input["path"]
            print(f"  [动作] 读取文件: {path}")
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
                
        elif tool_name == "write_file":
            path = tool_input["path"]
            print(f"  [动作] 写入文件: {path}")
            with open(path, "w", encoding="utf-8") as f:
                f.write(tool_input["content"])
            return f"文件 {path} 写入成功。"
            
        elif tool_name == "execute_shell":
            cmd = tool_input["command"]
            print(f"\n⚠️  [警告] AI 请求执行命令: \033[93m{cmd}\033[0m")
            
            # 安全锁：人工确认环节
            confirm = input("允许执行吗? (y/n/直接回车代表y): ").strip().lower()
            if confirm not in ['', 'y', 'yes']:
                return "用户拒绝了此命令的执行。"
            
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            output = result.stdout if result.returncode == 0 else f"Error:\n{result.stderr}"
            return output if output.strip() else "命令执行成功，无输出内容。"
            
    except Exception as e:
        return f"工具执行发生错误: {str(e)}"
        
    return "未知工具调用"

# ==========================================
# 4. 主循环 (Agent Loop - OpenAI 版本)
# ==========================================
def main():
    # 兼容读取你的环境变量 (优先读 OPENAI_ 开头，读不到就读 ANTHROPIC_ 开头)
    api_key = os.getenv("OPENAI_API_KEY", os.getenv("ANTHROPIC_API_KEY"))
    
    # 关键点：OpenAI 官方兼容接口通常需要以 /v1 结尾
    raw_base_url = os.getenv("OPENAI_BASE_URL", os.getenv("ANTHROPIC_BASE_URL", "https://api.gpugeek.com/"))
    base_url = raw_base_url if raw_base_url.endswith("/v1") or raw_base_url.endswith("/v1/") else f"{raw_base_url.rstrip('/')}/v1"
    
    model_name = os.getenv("OPENAI_MODEL", os.getenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "Vendor2/Claude-4.5-Sonnet"))

    if not api_key:
        print("❌ 错误：未找到 API_KEY，请检查环境变量。")
        return

    # 初始化 OpenAI 客户端
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
    )
    
    print(f"✅ OpenAI API 初始化成功 -> [BaseURL: {base_url}] [Model: {model_name}]")
    
    # 构建系统提示词
    skills_xml = load_skills("skills")
    system_prompt = f"""你是一个高级 AI 代理。你拥有一些强大的技能和工具。
遇到复杂任务时，先调用 `read_file` 阅读 <available_skills> 中对应技能的 <path> 文件，学习该技能的 SOP。
绝不猜测系统环境，充分利用 `execute_shell` 来获取信息。如果写入代码请务必写完整。

【核心行为准则】（必须严格遵守）：
1. 目标导向：如果用户的需求包含多个步骤（例如“创建文件并写入内容”），你必须连续调用工具，或者在一次回复中「并行调用」多个工具，直到任务彻底完成。
2. 禁止半途而废：在所有必须的动作执行完毕之前，绝对不要向用户输出普通的纯文本回复！
3. 工具常识：`write_file` 工具不仅能覆盖写入，也能直接创建新文件。不需要提前调用 shell 命令去创建。

<available_skills>{skills_xml}
</available_skills>"""

    print("🚀 OpenAI Agent 启动成功！输入 quit 退出。\n")
    
    # OpenAI 把 System Prompt 放在 messages 数组的第一项
    messages = [{"role": "system", "content": system_prompt}]

    while True:
        user_input = input("\n👨‍💻 你: ")
        if user_input.lower() in ("quit", "exit"):
            break
            
        messages.append({"role": "user", "content": user_input})

        while True:
            # 调用 OpenAI 模型
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                tools=TOOLS,
                temperature=0.7,
            )

            # 提取助手的回复消息对象
            response_message = response.choices[0].message

            # 将助手的回复原样存入上下文 (必须保留 tool_calls 结构，如果存在的话)
            messages.append(response_message.model_dump(exclude_unset=True))

            # 判断 AI 是否想要调用工具
            if response_message.tool_calls:
                # OpenAI 支持并行工具调用，所以需要遍历 tool_calls 列表
                for tool_call in response_message.tool_calls:
                    func_name = tool_call.function.name
                    # OpenAI 返回的参数是一个 JSON 字符串，需要解析为字典
                    try:
                        func_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        func_args = {}
                        
                    # 执行真正的物理代码
                    result = handle_tool_call(func_name, func_args)
                    
                    # OpenAI 的规范：执行结果必须以 role="tool" 传回去，并且带上对应的 tool_call_id
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": func_name,
                        "content": str(result)
                    })
                # 循环继续，把执行结果发给 AI 让他继续思考
            el
                # 任务完成，没有工具调用了，打印最终文字回复
                if response_message.content:
                    print(f"\n🤖 AI: {response_message.content}")
                break

if __name__ == "__main__":
    main()