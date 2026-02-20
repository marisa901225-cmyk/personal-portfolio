# Create new file: backend/tests/test_prompt_loader.py
import os
import tempfile
import unittest

from backend.services import prompt_loader


class PromptLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        prompt_loader.PROMPTS_DIR = self._tmp.name
        prompt_loader._prompt_cache.clear()
        prompt_loader._prompt_mtime.clear()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, name: str, content: str) -> str:
        path = os.path.join(self._tmp.name, f"{name}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_load_prompt_returns_empty_string_when_missing(self) -> None:
        self.assertEqual(prompt_loader.load_prompt("does_not_exist"), "")

    def test_load_prompt_formats_variables(self) -> None:
        self._write("hello", "Hi {name}!")
        self.assertEqual(prompt_loader.load_prompt("hello", name="Bob"), "Hi Bob!")

    def test_load_prompt_returns_template_when_missing_variable(self) -> None:
        self._write("hello", "Hi {name}!")
        self.assertEqual(prompt_loader.load_prompt("hello"), "Hi {name}!")

    def test_load_prompt_cache_uses_mtime(self) -> None:
        path = self._write("cached", "v1")
        v1 = prompt_loader.load_prompt("cached")
        self.assertEqual(v1, "v1")

        original_mtime = os.path.getmtime(path)

        with open(path, "w", encoding="utf-8") as f:
            f.write("v2")
        os.utime(path, (original_mtime, original_mtime))

        v_cached = prompt_loader.load_prompt("cached")
        self.assertEqual(v_cached, "v1")

        os.utime(path, None)
        v2 = prompt_loader.load_prompt("cached")
        self.assertEqual(v2, "v2")

    def test_list_prompts_lists_txt_files_without_extension(self) -> None:
        self._write("a", "x")
        self._write("b", "y")
        with open(os.path.join(self._tmp.name, "not_a_prompt.md"), "w", encoding="utf-8") as f:
            f.write("ignore")

        prompts = sorted(prompt_loader.list_prompts())
        self.assertEqual(prompts, ["a", "b"])
