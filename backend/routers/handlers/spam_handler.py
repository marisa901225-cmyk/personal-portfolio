"""
스팸 규칙 관리 명령어 핸들러
/add, /del, /list, /on, /off
"""
import logging

from sqlalchemy.orm import Session

from ...core.models import SpamRule
from ...core.time_utils import utcnow

logger = logging.getLogger(__name__)


async def handle_spam_command(cmd: str, arg: str, db: Session) -> str:
    """스팸 명령어 처리"""
    if cmd == "add" and arg:
        return _handle_add(arg, db)
    elif cmd == "del" and arg:
        return _handle_del(arg, db)
    elif cmd == "list":
        return _handle_list(db)
    elif cmd == "off" and arg:
        return _handle_toggle(arg, db, enabled=False)
    elif cmd == "on" and arg:
        return _handle_toggle(arg, db, enabled=True)
    else:
        return _get_help_text()


def _handle_add(arg: str, db: Session) -> str:
    """스팸 규칙 추가"""
    patterns = [p.strip() for p in arg.split(",") if p.strip()]
    added_ids = []
    for p in patterns:
        new_rule = SpamRule(
            rule_type="contains",
            pattern=p,
            category="general",
            note="텔레그램 추가",
            is_enabled=True,
            created_at=utcnow()
        )
        db.add(new_rule)
        db.commit()
        added_ids.append(f"#{new_rule.id}")
    
    patterns_str = ", ".join([f"<code>{p}</code>" for p in patterns])
    return f"✅ 스팸 규칙 {len(patterns)}개 추가됨: {patterns_str} ({', '.join(added_ids)})"


def _handle_del(arg: str, db: Session) -> str:
    """스팸 규칙 삭제"""
    try:
        rule_id = int(arg)
    except ValueError:
        return "❌ ID는 숫자여야 합니다 (예: /del 15)"
    
    rule = db.query(SpamRule).filter(SpamRule.id == rule_id).first()
    if not rule:
        return f"❌ 규칙 #{rule_id}를 찾을 수 없습니다"
    
    pattern = rule.pattern
    db.delete(rule)
    db.commit()
    return f"🗑️ 규칙 #{rule_id} 삭제됨: <code>{pattern}</code>"


def _handle_list(db: Session) -> str:
    """스팸 규칙 목록"""
    rules = db.query(SpamRule).order_by(SpamRule.id.desc()).limit(30).all()
    if not rules:
        return "📋 등록된 스팸 규칙이 없습니다"
    
    lines = ["<b>📋 스팸 규칙 목록 (최신 30개)</b>"]
    for r in rules:
        status_icon = "🟢" if r.is_enabled else "🔴"
        disp_pattern = (r.pattern[:20] + "..") if len(r.pattern) > 20 else r.pattern
        lines.append(f"{status_icon} #{r.id} [<code>{disp_pattern}</code>]")
    
    lines.append("\n💡 <code>/off ID</code>로 끄고 <code>/del ID</code>로 삭제")
    return "\n".join(lines)


def _handle_toggle(arg: str, db: Session, enabled: bool) -> str:
    """스팸 규칙 활성화/비활성화"""
    try:
        rule_id = int(arg)
    except ValueError:
        return "❌ ID는 숫자여야 합니다"
    
    rule = db.query(SpamRule).filter(SpamRule.id == rule_id).first()
    if not rule:
        return f"❌ 규칙 #{rule_id}를 찾을 수 없습니다"
    
    rule.is_enabled = enabled
    db.commit()
    
    if enabled:
        return f"▶️ 규칙 #{rule_id} 활성화됨"
    return f"⏸️ 규칙 #{rule_id} 비활성화됨"


def _get_help_text() -> str:
    """도움말 텍스트"""
    return """<b>ℹ️ 봇 명령어 도움말</b>
/help - 봇 명령어 도움말
/reset - 대화 내용(컨텍스트) 초기화
/model 목록 - 사용 가능한 LLM 모델 목록
/model 교체 {별칭|파일명} - 실시간 모델 교체

<b>스팸 규칙 관리</b>
/add {키워드} - 새 키워드 추가 (콤마 구분 가능)
/del {ID} - 규칙 완전 삭제
/list - 전체 목록 및 상태 보기
/on {ID} - 특정 규칙 활성화
/off {ID} - 특정 규칙 비활성화"""
