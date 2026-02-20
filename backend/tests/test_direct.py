import requests
url = "http://127.0.0.1:8080/v1/chat/completions"
payload = {"model": "model", "messages": [{"role": "user", "content": "spam? [광고] 포인트!"}], "max_tokens": 10}
r = requests.post(url, json=payload)
print(r.json()["choices"][0]["message"]["content"])
