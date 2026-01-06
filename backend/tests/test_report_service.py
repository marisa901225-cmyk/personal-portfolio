
import unittest
from datetime import date
from backend.services.report_service import parse_report_query, resolve_period

class ReportServiceTests(unittest.TestCase):
    def test_parse_report_query_monthly(self):
        today = date(2026, 1, 6)
        # 2025년 6월 리포트
        year, month, quarter, half, error = parse_report_query("2025년 6월", today)
        self.assertEqual(year, 2025)
        self.assertEqual(month, 6)
        self.assertIsNone(quarter)
        self.assertIsNone(error)

    def test_parse_report_query_relative(self):
        today = date(2025, 12, 1)
        # 지난달
        year, month, quarter, half, error = parse_report_query("지난달 리포트", today)
        self.assertEqual(year, 2025)
        self.assertEqual(month, 11)
        self.assertIsNone(error)

    def test_resolve_period_quarterly(self):
        # 2025년 1분기
        period = resolve_period(2025, None, 1, None)
        self.assertEqual(period.start_date, date(2025, 1, 1))
        self.assertEqual(period.end_date, date(2025, 4, 1))

    def test_resolve_period_validation(self):
        # 월과 분기 중복 지정 시 오류
        with self.assertRaises(ValueError):
            resolve_period(2025, 1, 1, None)
