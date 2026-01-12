#!/usr/bin/env python3
"""
DB 백업 완료 메시지를 LLM을 사용하여 생성합니다.
Usage: python3 generate_backup_msg.py <file_size_mb> <backup_time>
"""
import sys
import os
from datetime import datetime

# Add backend to path
sys.path.append(os.path.join(os.path.dirname(__file__), "../.."))

from backend.services.llm_service import LLMService

def generate_backup_message(file_size_mb: float, backup_time: str) -> str:
    """
    LLM을 사용하여 창의적인 DB 백업 완료 메시지 생성
    """
    llm = LLMService.get_instance()
    if not llm.is_loaded():
        return f"📦 DB 백업 완료!\n- 파일 크기: {file_size_mb:.2f}MB\n- {backup_time} 기준"
    
    prompt = f"""<start_of_turn>user
You are a reliable and witty database backup assistant. You just completed a successful database backup.

[Backup Info]
- File Size: {file_size_mb:.2f}MB
- Backup Time: {backup_time}

[Rules]
1. Inform the user that the backup is complete in Korean.
2. You MUST include the exact file size ({file_size_mb:.2f}MB). Do not hallucinate numbers.
3. Use a polite, friendly, and reassuring tone in Korean.
4. Be creative and varied in each response - celebrate the successful backup!
5. Keep it concise (2-3 sentences).
6. Use HTML tags (e.g., <b>, <i>) sparingly to style the Telegram message.
7. Start directly without introductory phrases.

Message (in Korean):<end_of_turn>
<start_of_turn>model
"""
    
    try:
        creative_text = llm.generate(prompt, max_tokens=256, temperature=0.8)
        
        # 파일 크기가 환각으로 바뀌었을 경우를 방지하기 위해 재검증
        if f"{file_size_mb:.2f}" not in creative_text and f"{file_size_mb:.1f}" not in creative_text:
            creative_text += f"\n\n(참고: 파일 크기 {file_size_mb:.2f}MB)"
        
        # 하단에 시간 정보 추가
        final_msg = f"{creative_text}\n\n🕒 {backup_time} 기준"
        return final_msg
    except Exception as e:
        print(f"ERROR: LLM generation failed: {e}", file=sys.stderr)
        return f"📦 DB 백업 완료!\n- 파일 크기: {file_size_mb:.2f}MB\n- {backup_time} 기준"

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 generate_backup_msg.py <file_size_mb> <backup_time>", file=sys.stderr)
        sys.exit(1)
    
    try:
        file_size_mb = float(sys.argv[1])
        backup_time = sys.argv[2]
        
        message = generate_backup_message(file_size_mb, backup_time)
        print(message)
    except ValueError:
        print("ERROR: Invalid file size", file=sys.stderr)
        sys.exit(1)
