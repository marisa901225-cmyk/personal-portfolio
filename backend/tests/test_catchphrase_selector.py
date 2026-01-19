import os
import tempfile
import unittest

from backend.services.alarm.catchphrase_selector import choose_phrase


class TestCatchphraseSelector(unittest.TestCase):
    def test_shuffle_then_cycle_no_repeat_until_exhausted(self):
        phrases = ["a", "b", "c"]
        with tempfile.TemporaryDirectory() as td:
            state_path = os.path.join(td, "state.json")
            key = "k"

            picked = [choose_phrase(phrases, state_path=state_path, key=key) for _ in range(3)]
            self.assertEqual(set(picked), set(phrases))

            fourth = choose_phrase(phrases, state_path=state_path, key=key)
            self.assertIn(fourth, phrases)

    def test_persists_progress(self):
        phrases = ["a", "b", "c", "d"]
        with tempfile.TemporaryDirectory() as td:
            state_path = os.path.join(td, "state.json")
            key = "k2"

            first = choose_phrase(phrases, state_path=state_path, key=key)
            second = choose_phrase(phrases, state_path=state_path, key=key)
            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            self.assertNotEqual(first, second)

    def test_resets_when_phrase_list_changes(self):
        phrases1 = ["a", "b", "c"]
        phrases2 = ["a", "b", "c", "d"]
        with tempfile.TemporaryDirectory() as td:
            state_path = os.path.join(td, "state.json")
            key = "k3"

            _ = choose_phrase(phrases1, state_path=state_path, key=key)
            picked = [choose_phrase(phrases2, state_path=state_path, key=key) for _ in range(4)]
            self.assertEqual(set(picked), set(phrases2))


if __name__ == "__main__":
    unittest.main()

