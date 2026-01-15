"""
프롬프트 로더 유틸리티
외부 .txt 파일에서 프롬프트 템플릿을 불러온다.
"""
import os
import logging

logger = logging.getLogger(__name__)

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "..", "prompts")

# 캐시 (파일 수정 시간 기반)
_prompt_cache = {}
_prompt_mtime = {}


def load_prompt(prompt_name: str, **kwargs) -> str:
    """
    프롬프트 템플릿을 로드하고 변수를 치환한다.
    
    Args:
        prompt_name: 프롬프트 파일 이름 (확장자 제외, 예: "random_topic")
        **kwargs: 템플릿 변수 (예: category="지식/과학")
    
    Returns:
        변수가 치환된 프롬프트 문자열
    """
    filepath = os.path.join(PROMPTS_DIR, f"{prompt_name}.txt")
    
    if not os.path.exists(filepath):
        logger.warning(f"Prompt file not found: {filepath}")
        return ""
    
    # 파일 수정 시간 체크 (정각에만 갱신 반영)
    from datetime import datetime
    current_minute = datetime.now().minute
    
    # 캐시가 있고, 정각이 아니라면 파일 시스템 체크 없이 즉시 반환 (성능 최적화)
    if filepath in _prompt_cache and current_minute != 0:
        return _prompt_cache[filepath].format(**kwargs)
    
    # 정각이거나 캐시가 없는 경우에만 파일 시스템에서 로드/수정시간 체크
    mtime = os.path.getmtime(filepath)
    if filepath in _prompt_cache and _prompt_mtime.get(filepath) == mtime:
        template = _prompt_cache[filepath]
    else:
        with open(filepath, "r", encoding="utf-8") as f:
            template = f.read()
        _prompt_cache[filepath] = template
        _prompt_mtime[filepath] = mtime
        logger.info(f"Prompt loaded/reloaded (Hourly Sync): {prompt_name}")
    
    # 변수 치환
    try:
        return template.format(**kwargs)
    except KeyError as e:
        logger.warning(f"Missing template variable in {prompt_name}: {e}")
        return template


def list_prompts() -> list:
    """사용 가능한 프롬프트 목록 반환"""
    if not os.path.exists(PROMPTS_DIR):
        return []
    return [f.replace(".txt", "") for f in os.listdir(PROMPTS_DIR) if f.endswith(".txt")]
