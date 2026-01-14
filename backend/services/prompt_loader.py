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


def load_prompt(name: str, **kwargs) -> str:
    """
    프롬프트 템플릿을 로드하고 변수를 치환한다.
    
    Args:
        name: 프롬프트 파일 이름 (확장자 제외, 예: "random_topic")
        **kwargs: 템플릿 변수 (예: category="지식/과학")
    
    Returns:
        변수가 치환된 프롬프트 문자열
    """
    filepath = os.path.join(PROMPTS_DIR, f"{name}.txt")
    
    if not os.path.exists(filepath):
        logger.warning(f"Prompt file not found: {filepath}")
        return ""
    
    # 파일 수정 시간 체크 (핫 리로드)
    mtime = os.path.getmtime(filepath)
    if filepath in _prompt_cache and _prompt_mtime.get(filepath) == mtime:
        template = _prompt_cache[filepath]
    else:
        with open(filepath, "r", encoding="utf-8") as f:
            template = f.read()
        _prompt_cache[filepath] = template
        _prompt_mtime[filepath] = mtime
        logger.info(f"Prompt loaded/reloaded: {name}")
    
    # 변수 치환
    try:
        return template.format(**kwargs)
    except KeyError as e:
        logger.warning(f"Missing template variable in {name}: {e}")
        return template


def list_prompts() -> list:
    """사용 가능한 프롬프트 목록 반환"""
    if not os.path.exists(PROMPTS_DIR):
        return []
    return [f.replace(".txt", "") for f in os.listdir(PROMPTS_DIR) if f.endswith(".txt")]
