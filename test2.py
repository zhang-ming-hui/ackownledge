import os
import requests
import json

# 从环境变量中读取 NVIDIA API Key，如果没有设置则报错退出
api_key = os.getenv("NVIDIA_API_KEY")
if not api_key:
    raise ValueError("请在环境变量中设置 NVIDIA_API_KEY")

url = "https://integrate.api.nvidia.com/v1/chat/completions"

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

payload = {
    "model": "z-ai/glm-5.1",
    "messages": [{"role": "user", "content": "你好，请介绍一下你自己。"}],
    "temperature": 0.9,
    "top_p": 0.7,
    "max_tokens": 1024,
    "stream": False
}

# 关键：强制绕过任何系统代理
proxies = {
    "http": None,
    "https": None,
}

response = requests.post(url, headers=headers, data=json.dumps(payload), proxies=proxies)

if response.status_code == 200:
    result = response.json()
    print(result['choices'][0]['message']['content'])
else:
    print(f"请求失败: {response.status_code} - {response.text}")