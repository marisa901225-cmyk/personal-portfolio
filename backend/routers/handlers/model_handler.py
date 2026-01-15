"""
LLM 모델 관련 명령어 핸들러
/model 목록, /model 교체 등
"""
import os
import logging

from ...integrations.telegram import send_telegram_message

logger = logging.getLogger(__name__)

# 모델 별칭 매핑
MODEL_ALIASES = {
    "K1.5": "Kanana-Nano-2.1B-Instruct-v1.5-Q8_0.gguf",
    "E4": "EXAONE-4.0-1.2B-BF16.gguf",
    "Q3": "Qwen3-1.7B-Instruct-f16.gguf",
    "G3": "gemma-3-4b-it-Q3_K_M.gguf",
    "G4": "gemma-3-4b-it-q4_k_m.gguf"
}


async def handle_model_command(parts: list) -> str:
    """/model 명령어 처리"""
    from ...services.llm_service import LLMService
    llm = LLMService.get_instance()
    
    subcmd = parts[0] if len(parts) > 0 else "목록"
    arg = parts[1] if len(parts) > 1 else ""
    
    if subcmd in ["list", "목록", "리스트"]:
        return _handle_list(llm)
    elif subcmd in ["switch", "교체", "변경", "선택"] and arg:
        return await _handle_switch(llm, arg)
    
    return "ℹ️ 사용법: /model 목록 또는 /model 교체 {별칭|파일명}"


def _handle_list(llm) -> str:
    """모델 목록 조회"""
    models = llm.list_available_models()
    current = llm.get_current_model()
    
    if not models:
        return "📁 사용 가능한 GGUF 모델이 없습니다. (backend/data 디렉토리 확인)"
    
    lines = ["<b>🤖 사용 가능한 모델 목록</b>"]
    rev_aliases = {v: k for k, v in MODEL_ALIASES.items()}
    
    for m in models:
        is_active = " (활성)" if m == current else ""
        fname = os.path.basename(m)
        alias = rev_aliases.get(fname)
        alias_str = f" [<b>{alias}</b>]" if alias else ""
        lines.append(f"• <code>{fname}</code>{alias_str}{is_active}")
    
    lines.append("\n💡 <code>/model 교체 별칭</code> 또는 <code>파일명</code>으로 교체")
    return "\n".join(lines)


async def _handle_switch(llm, arg: str) -> str:
    """모델 교체"""
    # 1. 별칭 우선 확인
    target_file = MODEL_ALIASES.get(arg)
    
    # 2. 별칭이 없으면 파일명 부분 일치 검색
    if not target_file:
        available_models = llm.list_available_models()
        for m in available_models:
            fname = os.path.basename(m)
            if arg.lower() in fname.lower():
                target_file = fname
                break
    
    if not target_file:
        target_file = arg
        
    # 파일 경로 구성
    full_path = target_file if target_file.startswith("backend/data/") else os.path.join("backend/data", target_file)
    if not full_path.endswith(".gguf") and "." not in target_file:
        full_path += ".gguf"
    
    # 모델 전환 전 로딩 메시지 전송
    await send_telegram_message(f"🔄 모델 변경 중: <code>{os.path.basename(full_path)}</code>\n<i>큰 모델은 로드에 수 분이 걸릴 수 있습니다...</i>")
        
    if llm.switch_model(full_path):
        return f"✅ 모델 교체 완료: <code>{os.path.basename(full_path)}</code>"
    else:
        if not os.path.exists(full_path):
            return f"❌ 모델 교체 실패: <code>{arg}</code>와 일치하는 모델을 찾을 수 없습니다."
        last_error = llm.get_last_error()
        if last_error:
            return f"❌ 모델 교체 실패: <code>{os.path.basename(full_path)}</code> 로드 오류 ({last_error})"
        return f"❌ 모델 교체 실패: <code>{os.path.basename(full_path)}</code> 로드에 실패했습니다."
