from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from unittest.mock import patch


class TestKisConfigDir(unittest.TestCase):
    def test_import_has_no_makedirs_side_effect(self):
        try:
            import pydantic  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("pydantic not installed in this environment")
        with patch("os.makedirs") as makedirs:
            import backend.integrations.kis.open_trading.kis_auth_state as state  # noqa: F401

        makedirs.assert_not_called()

    def test_kis_config_dir_env_is_respected(self):
        try:
            import pydantic  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("pydantic not installed in this environment")
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"KIS_CONFIG_DIR": tmp}, clear=False):
                import backend.integrations.kis.open_trading.kis_auth_state as state

                importlib.reload(state)
                state.reload_paths()
                self.assertEqual(state.config_root, tmp)

    def test_no_env_means_default_storage_path(self):
        try:
            import pydantic  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("pydantic not installed in this environment")
        with patch.dict(os.environ, {}, clear=True):
            import backend.integrations.kis.open_trading.kis_auth_state as state
            from backend.integrations.kis.config_paths import DEFAULT_KIS_CONFIG_DIR

            importlib.reload(state)
            state.reload_paths()
            self.assertEqual(state.config_root, str(DEFAULT_KIS_CONFIG_DIR))
