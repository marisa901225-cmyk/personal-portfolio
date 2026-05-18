import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "backend" / "scripts" / "shell" / "llm_fan_guard.sh"


class TestLlmFanGuard(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.actions_log = self.tmp_path / "actions.log"
        self.state_file = self.tmp_path / "llm_fan_guard_state.json"
        self.log_file = self.tmp_path / "llm_fan_guard.log"
        self.lock_file = self.tmp_path / "llm_fan_guard.lock"
        self.sensors_bin = self.tmp_path / "fake-sensors.sh"
        self.xpu_smi_bin = self.tmp_path / "fake-xpu-smi.sh"
        self.schedule_script = self.tmp_path / "fake-llm-schedule.sh"

        self._write_executable(
            self.sensors_bin,
            """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "${FAKE_SENSORS_OUTPUT:-}"
""",
        )
        self._write_executable(
            self.xpu_smi_bin,
            """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "${FAKE_XPU_SMI_OUTPUT:-}"
""",
        )
        self._write_executable(
            self.schedule_script,
            """#!/usr/bin/env bash
set -euo pipefail
printf '%s|%s\n' "${1:-}" "${LLM_SCHEDULE_ALLOW_WEEKEND_START:-0}" >> "${ACTIONS_LOG:?}"
""",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_executable(self, path: Path, content: str) -> None:
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)

    def _run_guard(
        self,
        *,
        sensors_output: str,
        now_epoch: int,
        threshold_rpm: int = 1600,
        stop_delay_sec: int = 0,
        cooldown_sec: int = 3600,
        sensor_pattern: str = "",
        start_max_temp_c: str = "88",
        start_retry_sec: int = 300,
        startup_grace_sec: int = 600,
        temp_sensor_pattern: str = "",
        critical_threshold_rpm: int = 2000,
        critical_stop_delay_sec: int = 0,
        day_relax_enabled: int = 0,
        day_relax_require_trading_day: int = 0,
        now_date: str = "20260514",
        now_weekday: str = "4",
        now_hhmm: str = "12:00",
        xpu_smi_output: str = "",
        stop_temp_c: str = "86",
        critical_stop_temp_c: str = "92",
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(
            {
                "ACTIONS_LOG": str(self.actions_log),
                "FAKE_SENSORS_OUTPUT": textwrap.dedent(sensors_output).strip(),
                "LLM_FAN_GUARD_STATE_FILE": str(self.state_file),
                "LLM_FAN_GUARD_LOG_FILE": str(self.log_file),
                "LLM_FAN_GUARD_LOCK_FILE": str(self.lock_file),
                "LLM_FAN_GUARD_SCHEDULE_SCRIPT": str(self.schedule_script),
                "LLM_FAN_GUARD_SENSORS_BIN": str(self.sensors_bin),
                "LLM_FAN_GUARD_XPU_SMI_BIN": str(self.xpu_smi_bin),
                "FAKE_XPU_SMI_OUTPUT": textwrap.dedent(xpu_smi_output).strip(),
                "LLM_FAN_GUARD_THRESHOLD_RPM": str(threshold_rpm),
                "LLM_FAN_GUARD_COOLDOWN_SEC": str(cooldown_sec),
                "LLM_FAN_GUARD_NOW_EPOCH": str(now_epoch),
                "LLM_FAN_GUARD_SENSOR_PATTERN": sensor_pattern,
                "LLM_FAN_GUARD_STOP_DELAY_SEC": str(stop_delay_sec),
                "LLM_FAN_GUARD_START_MAX_TEMP_C": str(start_max_temp_c),
                "LLM_FAN_GUARD_STOP_TEMP_C": str(stop_temp_c),
                "LLM_FAN_GUARD_CRITICAL_STOP_TEMP_C": str(critical_stop_temp_c),
                "LLM_FAN_GUARD_START_RETRY_SEC": str(start_retry_sec),
                "LLM_FAN_GUARD_STARTUP_GRACE_SEC": str(startup_grace_sec),
                "LLM_FAN_GUARD_TEMP_SENSOR_PATTERN": temp_sensor_pattern,
                "LLM_FAN_GUARD_CRITICAL_THRESHOLD_RPM": str(critical_threshold_rpm),
                "LLM_FAN_GUARD_CRITICAL_STOP_DELAY_SEC": str(critical_stop_delay_sec),
                "LLM_FAN_GUARD_DAY_RELAX_ENABLED": str(day_relax_enabled),
                "LLM_FAN_GUARD_DAY_RELAX_REQUIRE_TRADING_DAY": str(day_relax_require_trading_day),
                "LLM_FAN_GUARD_NOW_DATE": now_date,
                "LLM_FAN_GUARD_NOW_WEEKDAY": now_weekday,
                "LLM_FAN_GUARD_NOW_HHMM": now_hhmm,
            }
        )
        return subprocess.run(
            ["bash", str(SCRIPT_PATH)],
            cwd=PROJECT_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def _read_actions(self) -> list[str]:
        if not self.actions_log.exists():
            return []
        return self.actions_log.read_text(encoding="utf-8").splitlines()

    def test_initial_high_fan_rpm_observes_without_stopping(self) -> None:
        result = self._run_guard(
            sensors_output="""
                xe-pci-0300
                Adapter: PCI adapter
                fan1:        1750 RPM
                fan2:           0 RPM
            """,
            now_epoch=1_000,
            stop_delay_sec=30,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._read_actions(), [])
        state_text = self.state_file.read_text(encoding="utf-8")
        self.assertIn('"cooldown_active": 0', state_text)
        self.assertIn('"last_seen_rpm": 1750', state_text)
        self.assertIn('"high_rpm_started_epoch": 1000', state_text)
        self.assertIn('"last_action": "observe_high_rpm"', state_text)

    def test_initial_high_fan_rpm_stops_immediately_by_default(self) -> None:
        result = self._run_guard(
            sensors_output="""
                xe-pci-0300
                Adapter: PCI adapter
                fan1:        1750 RPM
            """,
            now_epoch=1_000,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._read_actions(), ["stop|0"])
        state_text = self.state_file.read_text(encoding="utf-8")
        self.assertIn('"last_trigger_rpm": 1750', state_text)
        self.assertIn('"last_action": "stop"', state_text)

    def test_sustained_high_fan_rpm_enters_cooldown_and_stops_llm_services(self) -> None:
        self.state_file.write_text(
            textwrap.dedent(
                """
                {
                  "cooldown_active": 0,
                  "cooldown_started_epoch": 0,
                  "cooldown_until_epoch": 0,
                  "last_trigger_rpm": 0,
                  "last_seen_rpm": 1750,
                  "high_rpm_started_epoch": 880,
                  "last_action": "observe_high_rpm",
                  "updated_at_epoch": 880
                }
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )

        result = self._run_guard(
            sensors_output="""
                xe-pci-0300
                Adapter: PCI adapter
                fan1:        1750 RPM
                fan2:           0 RPM
            """,
            now_epoch=1_000,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._read_actions(), ["stop|0"])
        state_text = self.state_file.read_text(encoding="utf-8")
        self.assertIn('"cooldown_active": 1', state_text)
        self.assertIn('"cooldown_started_epoch": 1000', state_text)
        self.assertIn('"cooldown_until_epoch": 4600', state_text)
        self.assertIn('"last_trigger_rpm": 1750', state_text)
        self.assertIn('"high_rpm_started_epoch": 0', state_text)
        self.assertIn('"last_action": "stop"', state_text)

    def test_sustained_high_fan_rpm_keeps_observing_before_delay_expires(self) -> None:
        self.state_file.write_text(
            textwrap.dedent(
                """
                {
                  "cooldown_active": 0,
                  "cooldown_started_epoch": 0,
                  "cooldown_until_epoch": 0,
                  "last_trigger_rpm": 0,
                  "last_seen_rpm": 1750,
                  "high_rpm_started_epoch": 980,
                  "last_action": "observe_high_rpm",
                  "updated_at_epoch": 900
                }
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )

        result = self._run_guard(
            sensors_output="""
                xe-pci-0300
                Adapter: PCI adapter
                fan1:        1750 RPM
            """,
            now_epoch=1_000,
            stop_delay_sec=30,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._read_actions(), [])
        state_text = self.state_file.read_text(encoding="utf-8")
        self.assertIn('"cooldown_active": 0', state_text)
        self.assertIn('"last_seen_rpm": 1750', state_text)
        self.assertIn('"high_rpm_started_epoch": 980', state_text)
        self.assertIn('"last_action": "observe_high_rpm"', state_text)

    def test_does_not_retrigger_while_cooldown_is_active(self) -> None:
        self.state_file.write_text(
            textwrap.dedent(
                """
                {
                  "cooldown_active": 1,
                  "cooldown_started_epoch": 1000,
                  "cooldown_until_epoch": 4600,
                  "last_trigger_rpm": 2350,
                  "last_seen_rpm": 2350,
                  "last_action": "stop",
                  "updated_at_epoch": 1000
                }
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )

        result = self._run_guard(
            sensors_output="""
                xe-pci-0300
                Adapter: PCI adapter
                fan1:        2800 RPM
            """,
            now_epoch=2_000,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._read_actions(), [])

    def test_restarts_llm_services_after_cooldown_expires(self) -> None:
        self.state_file.write_text(
            textwrap.dedent(
                """
                {
                  "cooldown_active": 1,
                  "cooldown_started_epoch": 1000,
                  "cooldown_until_epoch": 4600,
                  "last_trigger_rpm": 2350,
                  "last_seen_rpm": 2350,
                  "last_action": "stop",
                  "updated_at_epoch": 1000
                }
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )

        result = self._run_guard(
            sensors_output="""
                xe-pci-0300
                Adapter: PCI adapter
                fan1:          90 RPM
            """,
            now_epoch=5_000,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._read_actions(), ["start|1"])
        state_text = self.state_file.read_text(encoding="utf-8")
        self.assertIn('"cooldown_active": 0', state_text)
        self.assertIn('"cooldown_until_epoch": 0', state_text)
        self.assertIn('"last_start_epoch": 5000', state_text)
        self.assertIn('"last_action": "start"', state_text)

    def test_startup_grace_defers_stop_after_restart(self) -> None:
        self.state_file.write_text(
            textwrap.dedent(
                """
                {
                  "cooldown_active": 0,
                  "cooldown_started_epoch": 0,
                  "cooldown_until_epoch": 0,
                  "last_trigger_rpm": 2350,
                  "last_seen_rpm": 0,
                  "high_rpm_started_epoch": 0,
                  "last_start_epoch": 1000,
                  "last_action": "start",
                  "updated_at_epoch": 1000
                }
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )

        result = self._run_guard(
            sensors_output="""
                xe-pci-0300
                Adapter: PCI adapter
                fan1:        1750 RPM
            """,
            now_epoch=1_300,
            startup_grace_sec=600,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._read_actions(), [])
        state_text = self.state_file.read_text(encoding="utf-8")
        self.assertIn('"cooldown_active": 0', state_text)
        self.assertIn('"last_seen_rpm": 1750', state_text)
        self.assertIn('"high_rpm_started_epoch": 0', state_text)
        self.assertIn('"last_start_epoch": 1000', state_text)
        self.assertIn('"last_action": "startup_grace"', state_text)

    def test_critical_fan_rpm_stops_immediately_even_during_startup_grace(self) -> None:
        self.state_file.write_text(
            textwrap.dedent(
                """
                {
                  "cooldown_active": 0,
                  "cooldown_started_epoch": 0,
                  "cooldown_until_epoch": 0,
                  "last_trigger_rpm": 0,
                  "last_seen_rpm": 0,
                  "high_rpm_started_epoch": 0,
                  "last_start_epoch": 1000,
                  "last_action": "start",
                  "updated_at_epoch": 1000
                }
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )

        result = self._run_guard(
            sensors_output="""
                xe-pci-0300
                Adapter: PCI adapter
                fan1:        2050 RPM
            """,
            now_epoch=1_060,
            cooldown_sec=3600,
            startup_grace_sec=600,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._read_actions(), ["stop|0"])
        state_text = self.state_file.read_text(encoding="utf-8")
        self.assertIn('"cooldown_active": 1', state_text)
        self.assertIn('"cooldown_until_epoch": 4660', state_text)
        self.assertIn('"last_trigger_rpm": 2050', state_text)
        self.assertIn('"last_action": "stop"', state_text)

    def test_defers_restart_when_temperature_is_still_high(self) -> None:
        self.state_file.write_text(
            textwrap.dedent(
                """
                {
                  "cooldown_active": 1,
                  "cooldown_started_epoch": 1000,
                  "cooldown_until_epoch": 4600,
                  "last_trigger_rpm": 2350,
                  "last_seen_rpm": 2350,
                  "last_action": "stop",
                  "updated_at_epoch": 1000
                }
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )

        result = self._run_guard(
            sensors_output="""
                xe-pci-0300
                Adapter: PCI adapter
                fan1:          90 RPM
                pkg:         +68.0 C
                vram:        +72.5 C
            """,
            now_epoch=5_000,
            start_max_temp_c="70",
            start_retry_sec=600,
            temp_sensor_pattern="xe-pci-0300",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._read_actions(), [])
        state_text = self.state_file.read_text(encoding="utf-8")
        self.assertIn('"cooldown_active": 1', state_text)
        self.assertIn('"cooldown_until_epoch": 5600', state_text)
        self.assertIn('"last_action": "start_deferred_hot"', state_text)

    def test_sensor_pattern_limits_which_fan_section_is_used(self) -> None:
        result = self._run_guard(
            sensors_output="""
                chassis-fan
                Adapter: ISA adapter
                fan1:        2600 RPM

                xe-pci-0300
                Adapter: PCI adapter
                fan1:        1200 RPM
            """,
            now_epoch=1_000,
            sensor_pattern="xe-pci-0300",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._read_actions(), [])

    def test_day_relax_window_keeps_llm_services_running_despite_high_rpm(self) -> None:
        result = self._run_guard(
            sensors_output="""
                xe-pci-0300
                Adapter: PCI adapter
                fan1:        1810 RPM
            """,
            now_epoch=1_000,
            day_relax_enabled=1,
            now_weekday="4",
            now_hhmm="08:30",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._read_actions(), [])
        state_text = self.state_file.read_text(encoding="utf-8")
        self.assertIn('"last_seen_rpm": 1810', state_text)
        self.assertIn('"high_rpm_started_epoch": 0', state_text)
        self.assertIn('"last_action": "day_relax"', state_text)

    def test_xpu_smi_temperature_stops_llm_even_when_fan_rpm_is_low(self) -> None:
        result = self._run_guard(
            sensors_output="""
                xe-pci-0300
                Adapter: PCI adapter
                fan1:         900 RPM
                pkg:          +45.0 C
            """,
            xpu_smi_output="""
                {
                    "device_id": 0,
                    "device_level": [
                        {
                            "metrics_type": "XPUM_STATS_GPU_CORE_TEMPERATURE",
                            "value": 84.0
                        },
                        {
                            "metrics_type": "XPUM_STATS_MEMORY_TEMPERATURE",
                            "value": 88.0
                        }
                    ]
                }
            """,
            now_epoch=1_000,
            stop_temp_c="86",
            critical_stop_temp_c="92",
            day_relax_enabled=1,
            now_weekday="4",
            now_hhmm="08:30",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._read_actions(), ["stop|0"])
        state_text = self.state_file.read_text(encoding="utf-8")
        self.assertIn('"last_action": "stop"', state_text)
        log_text = self.log_file.read_text(encoding="utf-8")
        self.assertIn("temp=88", log_text)
        self.assertIn("temp; LLM중지", log_text)

    def test_day_relax_window_does_not_apply_before_8am(self) -> None:
        result = self._run_guard(
            sensors_output="""
                xe-pci-0300
                Adapter: PCI adapter
                fan1:        1810 RPM
            """,
            now_epoch=1_000,
            day_relax_enabled=1,
            now_weekday="4",
            now_hhmm="07:59",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._read_actions(), ["stop|0"])


if __name__ == "__main__":
    unittest.main()
