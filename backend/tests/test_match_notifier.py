import asyncio
import unittest
from datetime import datetime as DateTime

from backend.services.alarm.match_notifier import check_upcoming_matches


class _FakeQuery:
    def __init__(self):
        self.filter_args = None

    def filter(self, *args):
        self.filter_args = args
        return self

    def all(self):
        return []


class _FakeSession:
    def __init__(self):
        self._query = _FakeQuery()

    def query(self, _model):
        return self._query


class TestMatchNotifier(unittest.TestCase):
    def test_filter_does_not_receive_datetime_literal(self):
        db = _FakeSession()

        result = asyncio.run(check_upcoming_matches(db, catchphrases_file="/does/not/exist.json", window_minutes=5))
        self.assertFalse(result)

        self.assertIsNotNone(db._query.filter_args)
        self.assertFalse(any(isinstance(arg, DateTime) for arg in db._query.filter_args))

