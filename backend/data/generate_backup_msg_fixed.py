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
from backend.services.alarm.sanitizer import clean_exaone_tokens

def generate_backup_message(file_size_mb: float, backup_time: str) -> str:
    """
    LLM을 사용하여 창의적인 DB 백업 완료 메시지 생성
    """
    llm = LLMService.get_instance()
    if not llm.is_loaded():
        return f"📦 DB 백업 완료!\n- 파일 크기: {file_size_mb:.2f}MB\n- {backup_time} 기준"
    
    # 모델 템플릿에 의존하지 않고 generate_chat 사용
    messages = [
        {
            "role": "user",
            "content": f"""
DB 백업 완료! 용량: {file_size_mb:.2f}MB. 사용자한테 알려줄 짧은 메시지 만들어줘.

[규칙]
- 반말로 친근하게
- 파일 크기({file_size_mb:.2f}MB) 반드시 포함
- 한두 문장으로 짧게
- 안심시키거나 재미있는 코멘트 추가
- 이모지 OK
- 한국어만

바로 메시지만 출력!
"""
        }
    ]
    
    try:
        creative_text = llm.generate_chat(
            messages, 
            max_tokens=128, 
            temperature=0.8,
            stop=["아이디어 완료", "Ok,", "사용자가", "지시사항을"]
        )
        creative_text = clean_exaone_tokens(creative_text)
        creative_text = creative_text.replace("아이디어 완료!", "").replace("아이디어 완료", "").strip()
        
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
