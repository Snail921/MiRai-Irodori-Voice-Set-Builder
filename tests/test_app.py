from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from app import (
    ARRANGE_JS,
    ARRANGE_REFRESH_START_JS,
    GENERATION_CSS,
    GENERATION_FINISH_JS,
    GENERATION_START_JS,
    OPEN_ARRANGE_TAB_JS,
    run_type_generation,
    select_generated_voice,
    render_arrange_board,
    split_filename_toggle_parts,
    persist_arrange_available_tags,
)


class ArrangeSelectionTests(unittest.TestCase):
    def test_filename_toggle_parts_split_sentence_endings_and_heart_boundaries(self) -> None:
        self.assertEqual(
            split_filename_toggle_parts("あー♡♡すごく楽しかった！_000.wav"),
            ("あー♡♡", "すごく楽しかった！"),
        )
        self.assertEqual(
            split_filename_toggle_parts("だめ！もう無理？本当に。_012.wav"),
            ("だめ！", "もう無理？", "本当に。"),
        )

    def test_filename_toggle_parts_keep_terminal_hearts_with_the_preceding_text(self) -> None:
        self.assertEqual(
            split_filename_toggle_parts("ありがとう♡♡_000.wav"),
            ("ありがとう♡♡",),
        )

    def test_filename_toggle_parts_keep_punctuation_on_the_previous_part(self) -> None:
        self.assertEqual(
            split_filename_toggle_parts("あー♡♡、すごく楽しかった！_000.wav"),
            ("あー♡♡、", "すごく楽しかった！"),
        )
        self.assertEqual(
            split_filename_toggle_parts("本当？』もう一度、お願い。_000.wav"),
            ("本当？』", "もう一度、", "お願い。"),
        )

    def test_filename_toggle_parts_never_drop_hearts(self) -> None:
        filenames = (
            "あー♡♡すごい！_000.wav",
            "イッてる…♡♡_000.wav",
            "本当？♡♡もう一度。_000.wav",
            "大好き！❤️もう一回。_000.wav",
        )
        expected = (
            ("あー♡♡", "すごい！"),
            ("イッてる…♡♡",),
            ("本当？♡♡", "もう一度。"),
            ("大好き！❤️", "もう一回。"),
        )
        for filename, parts in zip(filenames, expected):
            with self.subTest(filename=filename):
                actual = split_filename_toggle_parts(filename)
                self.assertEqual(actual, parts)
                stem_without_number = filename.removesuffix("_000.wav")
                self.assertEqual("".join(actual), stem_without_number)

    def test_generated_voice_is_selected_and_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output_root = Path(temp)
            (output_root / "Voice A" / "Default").mkdir(parents=True)
            clip = output_root / "Voice A" / "Default" / "[Continue]hello_000.wav"
            clip.write_bytes(b"RIFF" + b"\x00" * 40)
            (output_root / "Voice B").mkdir()

            with patch("app.OUTPUT_DIRECTORY", output_root):
                dropdown, board, status = select_generated_voice(
                    {"voice_set": "Voice A", "generation_id": "unique"}
                )

            self.assertEqual(dropdown.value, "Voice A")
            self.assertIn(("Voice A", "Voice A"), dropdown.choices)
            self.assertIn("hello_000.wav", board)
            self.assertIn('<span class="clip-name">hello_000.wav</span>', board)
            self.assertIn('prefix-continue', board)
            self.assertIn('value="Continue" selected', board)
            self.assertIn('class="trim-prefix"', board)
            self.assertIn("1クリップ", status)

    def test_generation_start_js_preserves_backend_inputs(self) -> None:
        self.assertIn("(...inputs)", GENERATION_START_JS)
        self.assertIn("return inputs", GENERATION_START_JS)

    def test_generation_shortcuts_share_state_and_open_arrange_tab(self) -> None:
        self.assertIn("querySelectorAll", GENERATION_START_JS)
        self.assertIn("querySelectorAll", GENERATION_FINISH_JS)
        self.assertIn("button.disabled = !succeeded", GENERATION_FINISH_JS)
        self.assertIn("#arrange-tab-rail", GENERATION_CSS)
        self.assertIn("position: fixed", GENERATION_CSS)
        self.assertIn("writing-mode: vertical-rl", GENERATION_CSS)
        self.assertIn("=== 'Arrange'", OPEN_ARRANGE_TAB_JS)

    def test_prefix_change_is_captured_before_a_card_can_be_replaced(self) -> None:
        self.assertIn("addEventListener('input'", ARRANGE_JS)
        self.assertIn("select.disabled = true", ARRANGE_JS)
        self.assertIn("arrange-refreshing", ARRANGE_REFRESH_START_JS)
        self.assertIn("return inputs", ARRANGE_REFRESH_START_JS)
        self.assertIn("synchronizePrefixSelects", ARRANGE_JS)
        self.assertIn("select.value = expected", ARRANGE_JS)
        self.assertIn("schedulePrefixSynchronization", ARRANGE_JS)
        self.assertIn("window.requestAnimationFrame", ARRANGE_JS)
        self.assertIn("editButton.dataset.prefix", ARRANGE_JS)

    def test_additional_tags_are_hidden_from_card_name_and_rendered_as_chips(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output_root = Path(temp)
            clip = output_root / "Voice A" / "Default" / "[Common][Nod][Blink]hello_000.wav"
            clip.parent.mkdir(parents=True)
            clip.write_bytes(b"RIFF" + b"\x00" * 40)

            with patch("app.OUTPUT_DIRECTORY", output_root), patch("app._arrange_available_tags", return_value=("Nod", "Blink")):
                board = render_arrange_board("Voice A")

            self.assertIn('<span class="clip-name">hello_000.wav</span>', board)
            self.assertNotIn('<span class="clip-name">hello_000[Nod]', board)
            self.assertIn('class="clip-tag-chip"', board)
            self.assertIn('data-tags="Nod/Blink"', board)
            self.assertIn('class="trim-tag-option"', board)
            self.assertIn('class="trim-filename-parts"', board)
            self.assertIn('data-filename-parts=', board)

    def test_filename_part_buttons_update_the_trim_filename(self) -> None:
        self.assertIn("splitFilenameForToggles", ARRANGE_JS)
        self.assertIn("trim-filename-part", ARRANGE_JS)
        self.assertIn("parts.filter((part) => part.enabled)", ARRANGE_JS)

    def test_trailing_tag_separator_is_saved_without_rewriting_the_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            settings_path = Path(temp) / "settings.json"
            with patch("app.SETTINGS_PATH", settings_path):
                result = persist_arrange_available_tags("Nod/", None)

            self.assertEqual(len(result), 2)
            self.assertEqual(json.loads(settings_path.read_text(encoding="utf-8"))["arrange_available_tags"], "Nod")

    def test_empty_steps_returns_a_clear_validation_error(self) -> None:
        status, log, files, _ = run_type_generation(
            "Default",
            "http://127.0.0.1:5000",
            "Voice A",
            None,
            "hello",
            "",
            1,
        )

        self.assertIn("ステップ数", status)
        self.assertNotIn("予期しないエラー", status)
        self.assertIn("ステップ数", log)
        self.assertEqual(files, [])


if __name__ == "__main__":
    unittest.main()
