from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from backend.core.models import Trade
from backend.services.crud_helpers import commit_or_rollback, commit_with_refresh, get_owned_row_or_404


def test_get_owned_row_or_404_raises_consistent_404():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    with pytest.raises(HTTPException) as exc:
        get_owned_row_or_404(db, Trade, 1, 2, detail="Trade not found")

    assert exc.value.status_code == 404
    assert exc.value.detail == "Trade not found"


def test_commit_with_refresh_rolls_back_on_error():
    db = MagicMock()
    db.commit.side_effect = RuntimeError("boom")
    row = MagicMock()

    with pytest.raises(RuntimeError):
        commit_with_refresh(db, row)

    db.rollback.assert_called_once()
    db.refresh.assert_not_called()


def test_commit_or_rollback_rolls_back_on_error():
    db = MagicMock()
    db.commit.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError):
        commit_or_rollback(db)

    db.rollback.assert_called_once()
