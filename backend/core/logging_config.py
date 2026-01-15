from __future__ import annotations
import re
import logging
import os

class SensitiveDataFormatter(logging.Formatter):
    """
    민감 정보를 마스킹하는 전역 로깅 포맷터.
    - API Key (sk-...)
    - Telegram Bot Token
    - Authorization Bearer 토큰
    - 데이터베이스 연결 정보 (비밀번호 등)
    """
    
    PATTERNS = [
        # OpenAI API Key 패턴
        (r'sk-[a-zA-Z0-9]{20,}', 'sk-[MASKED]'),
        # Telegram Bot Token 패턴
        (r'[0-9]{9,12}:[a-zA-Z0-9_-]{32,}', '[TELEGRAM_TOKEN_MASKED]'),
        # Bearer 토큰 패턴
        (r'(?i)bearer\s+[a-zA-Z0-9.\-_]{20,}', 'Bearer [MASKED]'),
        # 일반적인 API Key 키워드 매칭 (JSON 및 텍스트)
        (r'(?i)("api[-_]key"|"secret"|"token")\s*:\s*"[^"]{10,}"', r'\1: "[MASKED]"'),
        (r'(?i)(api[-_]key|secret|token)\s*[:=]\s*[a-zA-Z0-9]{10,}', r'\1: [MASKED]'),
        # DB 연결 문자열 내 비밀번호 마스킹
        (r'://([^:]+):([^@]+)@', r'://\1:***@'),
    ]

    def format(self, record):
        msg = super().format(record)
        for pattern, replacement in self.PATTERNS:
            msg = re.sub(pattern, replacement, msg)
        return msg

def setup_global_logging(level=logging.INFO, log_file: str | None = None):
    """애플리케이션 전역 로깅 설정을 초기화하고 마스킹 포맷터를 적용한다."""
    formatter = SensitiveDataFormatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        # 로그 디렉토리 자동 생성
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding='utf-8'))

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # 기존 핸들러 제거 (중복 방지)
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)
    
    for handler in handlers:
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
    
    # 외부 라이브러리 로깅 레벨 조정
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    
    return root_logger
