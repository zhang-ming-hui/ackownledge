import requests
import json

url = "https://integrate.api.nvidia.com/v1/chat/completions"
api_key = "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"

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