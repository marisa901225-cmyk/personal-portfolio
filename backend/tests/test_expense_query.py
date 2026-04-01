import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.services.expenses.expense_query import build_user_expense_query


class TestExpenseQueryHelper(unittest.TestCase):
    def test_build_user_expense_query_applies_common_filters(self):
        db = MagicMock()
        query = MagicMock()
        db.query.return_value = query
        query.filter.side_effect = lambda *args, **kwargs: query
        with patch("backend.services.expenses.expense_query.get_or_create_single_user", return_value=SimpleNamespace(id=7)):
            result = build_user_expense_query(
                db,
                include_deleted=False,
                year=2026,
                month=4,
                category="식비",
            )

        self.assertIs(result, query)
        db.query.assert_called_once()
        self.assertEqual(query.filter.call_count, 5)

    def test_build_user_expense_query_ignores_month_without_year(self):
        db = MagicMock()
        query = MagicMock()
        db.query.return_value = query
        query.filter.side_effect = lambda *args, **kwargs: query

        with patch("backend.services.expenses.expense_query.get_or_create_single_user", return_value=SimpleNamespace(id=7)):
            result = build_user_expense_query(
                db,
                include_deleted=True,
                year=None,
                month=4,
                category=None,
            )

        self.assertIs(result, query)
        db.query.assert_called_once()
        query.filter.assert_called_once()


if __name__ == "__main__":
    unittest.main()
