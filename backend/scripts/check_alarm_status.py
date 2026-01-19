
import os
import json
from datetime import datetime

STATE_FILE = "backend/data/random_topic_state.json"

def check_status():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            data = json.load(f)
            print(f"마지막 전송: {data.get('last_sent_at')}")
    else:
        print("상태 파일 없음")

if __name__ == "__main__":
    check_status()
