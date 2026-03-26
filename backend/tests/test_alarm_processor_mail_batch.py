import unittest
from types import SimpleNamespace

from backend.services.alarm.processor import _collapse_mail_batch_notifications


class TestAlarmProcessorMailBatch(unittest.TestCase):
    def test_collapse_mail_batch_notifications_keeps_latest_per_app(self) -> None:
        items = [
            {"app_name": "Gmail", "sender": "새 메일 2개", "db_obj": SimpleNamespace(id=1)},
            {"app_name": "Gmail", "sender": "새 메일 3개", "db_obj": SimpleNamespace(id=2)},
            {"app_name": "카카오톡", "sender": "철수", "db_obj": SimpleNamespace(id=3)},
            {"app_name": "Gmail", "sender": "새 메일 5개", "db_obj": SimpleNamespace(id=4)},
        ]

        kept, dropped = _collapse_mail_batch_notifications(items)

        self.assertEqual([int(i["db_obj"].id) for i in kept], [3, 4])
        self.assertEqual([int(i["db_obj"].id) for i in dropped], [1, 2])
