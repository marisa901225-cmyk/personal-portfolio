import json
import os
import random
import tempfile
from contextlib import contextmanager
from hashlib import sha1
from typing import Any, Optional

try:
    import fcntl  # Linux/Unix
except Exception:  # pragma: no cover
    fcntl = None  # type: ignore


def _stable_signature(phrases: list[str]) -> str:
    """
    입력 순서에 영향받지 않도록 정렬 후 서명 생성.
    같은 문구 집합이면 sig가 안정적으로 유지된다.
    """
    canonical = "\n".join(sorted(phrases)).encode("utf-8", errors="ignore")
    return sha1(canonical).hexdigest()


@contextmanager
def _file_lock(lock_path: str):
    """
    멀티 프로세스/멀티 인스턴스 환경에서 상태 파일 경쟁을 줄이기 위한 파일 락.
    fcntl이 없는 환경이면 no-op.
    """
    if fcntl is None:
        yield
        return

    os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
    with open(lock_path, "a", encoding="utf-8") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        except Exception:
            # 락 실패해도 동작은 하게 (최악: 중복 가능성 증가)
            pass
        try:
            yield
        finally:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass


def _read_state(path: str) -> dict[str, Any]:
    try:
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_state_atomic(path: str, data: dict[str, Any]) -> None:
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".catchphrase_state_", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp_path, path)
    finally:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def _dedupe_phrases(phrases: list[str]) -> list[str]:
    seen = set()
    out = []
    for phrase in phrases:
        p = (phrase or "").strip()
        if not p or p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def _shuffle_avoid_first_repeat(order: list[str], last: Optional[str]) -> None:
    """
    바퀴가 넘어가서 새로 셔플할 때, 첫 문구가 직전 문구와 같으면 살짝 교정.
    """
    if not order or not last or len(order) < 2:
        return
    if order[0] == last:
        # 1~끝 중 아무거나 하나와 swap
        j = random.randrange(1, len(order))
        order[0], order[j] = order[j], order[0]


def choose_phrase(phrases: list[str], state_path: str, key: str) -> Optional[str]:
    phrases = _dedupe_phrases(phrases)
    if not phrases:
        return None

    sig = _stable_signature(phrases)
    lock_path = state_path + ".lock"

    with _file_lock(lock_path):
        state = _read_state(state_path)
        entry = state.get(key)
        if not isinstance(entry, dict):
            entry = {}

        order = entry.get("order")
        idx = entry.get("idx")
        stored_sig = entry.get("sig")
        last = entry.get("last")

        valid = (
            stored_sig == sig
            and isinstance(order, list)
            and all(isinstance(x, str) for x in order)
            and isinstance(idx, int)
            and 0 <= idx < len(order)
            and len(order) == len(phrases)
            and set(order) == set(phrases)
        )

        if not valid:
            order = phrases[:]
            random.shuffle(order)
            _shuffle_avoid_first_repeat(order, last if isinstance(last, str) else None)
            idx = 0

        phrase = order[idx] if order else None

        next_idx = idx + 1
        if next_idx >= len(order):
            next_idx = 0
            order = phrases[:]
            random.shuffle(order)
            _shuffle_avoid_first_repeat(order, phrase)

        state[key] = {"sig": sig, "order": order, "idx": next_idx, "last": phrase}
        _write_state_atomic(state_path, state)

    return phrase
