import os
from zhipuai import ZhipuAI

# 从环境变量中读取 API Key，如果没有设置则报错退出
api_key = os.getenv("ZHIPUAI_API_KEY")
if not api_key:
    raise ValueError("请在环境变量中设置 ZHIPUAI_API_KEY")

# 初始化客户端
client = ZhipuAI(api_key=api_key)

# 构建对话消息
messages = [
    {"role": "system", "content": "你是一个有帮助的助手。"},
    {"role": "user", "content": "你好，请告诉我如何调用智谱AI的API？"}
]

try:
    response = client.chat.completions.create(
        model="glm-4.5-flash",
        messages=messages,
        temperature=0.9,
        top_p=0.7,
    )
    print(response.choices[0].message.content)
    if hasattr(response, "usage"):
        print(f"本次消耗Token: {response.usage.total_tokens}")
except Exception as e:
    print(f"调用失败: {e}")