import requests

def send_webhook(webhook: str, content: str):
    return requests.post(webhook, json={'msgtype': 'text', 'text': {'content': content}}, timeout=5).json()
