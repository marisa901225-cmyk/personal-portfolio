import unittest
from unittest.mock import AsyncMock, MagicMock

from backend.services.alarm.alarm_summary_service import _AlarmSummaryDeps, _generate_alarm_summary_async


class AlarmSummaryServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_tokens_do_not_include_ellipsis(self):
        deps = _AlarmSummaryDeps(
            build_stop_tokens=MagicMock(return_value=["Okay", "let me", "\n\n\n", "aaaa", "----"]),
            resolve_llm_options=MagicMock(
                return_value=MagicMock(
                    max_tokens=512,
                    temperature=0.05,
                    enable_thinking=False,
                    extra_kwargs={},
                )
            ),
            generate_with_main_llm_async=AsyncMock(return_value="- 치지직에서 [민트초코용...님 라이브 시작!]"),
            dump_llm_draft=MagicMock(),
            sanitize_llm_output=MagicMock(side_effect=lambda items, text: text),
            postprocess_llm_text=MagicMock(side_effect=lambda text: text),
            get_korean_ratio=MagicMock(return_value=1.0),
        )

        items = [
            {
                "app_name": "치지직",
                "app_title": "민트초코용...님 라이브 시작!",
                "conversation": "",
                "text": "민트초코용...님이 방송을 시작했습니다",
            }
        ]

        result = await _generate_alarm_summary_async(
            items,
            "prompt",
            deps=deps,
        )

        self.assertEqual(result, "- 치지직에서 [민트초코용...님 라이브 시작!]")
        deps.build_stop_tokens.assert_called_once_with(extra=["\n\n\n", "aaaa", "----"])
        stop_tokens = deps.generate_with_main_llm_async.await_args.kwargs["stop"]
        self.assertNotIn("...", stop_tokens)


if __name__ == "__main__":
    unittest.main()
