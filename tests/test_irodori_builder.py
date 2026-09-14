from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from irodori_builder import (
    CLIP_PREFIXES,
    GenerationGroup,
    generate_sample_clip,
    generate_voice_set,
    next_output_path,
    safe_path_component,
    split_clip_prefix,
    split_texts,
)


WAV_BYTES = b"RIFF" + (b"\x00" * 40)


class FakeClient:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, int, str | None]] = []

    def ensure_voice(self, voice_id: str) -> str:
        return voice_id.strip()

    def synthesize(
        self,
        *,
        text: str,
        voice_id: str,
        num_steps: int,
        caption: str | None = None,
    ) -> bytes:
        self.requests.append((text, voice_id, num_steps, caption))
        return WAV_BYTES


class TextParsingTests(unittest.TestCase):
    def test_splits_each_phrase_used_for_tts(self) -> None:
        self.assertEqual(
            split_texts("こんにちは。/ おはよう、元気？/ありがとう！"),
            ("こんにちは。", "おはよう、元気？", "ありがとう！"),
        )

    def test_ignores_empty_parts(self) -> None:
        self.assertEqual(split_texts("//first/// second//"), ("first", "second"))

    def test_punctuation_and_newlines_are_not_separators(self) -> None:
        value = "こんにちは、元気ですか。\nはい、元気です！"
        self.assertEqual(split_texts(value), (value,))

    def test_only_windows_invalid_characters_are_replaced(self) -> None:
        self.assertEqual(safe_path_component("しのさわひろ", fallback="voice"), "しのさわひろ")
        self.assertEqual(safe_path_component("a/b:c", fallback="clip"), "a_b_c")


class OutputTests(unittest.TestCase):
    def test_fawn_is_the_last_clip_prefix(self) -> None:
        self.assertEqual(CLIP_PREFIXES[-2:], ("Stop", "Fawn"))

    def test_generated_filename_keeps_emoji_and_readable_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)

            path = next_output_path(directory, "こんにちは😀❤️♡_声🎉")

            self.assertEqual(path.name, "[Common]こんにちは😀❤️♡_声🎉_000.wav")

    def test_emoji_only_filename_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(
                next_output_path(Path(temp), "😀❤️").name,
                "[Common]😀❤️_000.wav",
            )

    def test_next_path_starts_at_zero_and_skips_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            self.assertEqual(next_output_path(directory, "こんにちは").name, "[Common]こんにちは_000.wav")
            (directory / "こんにちは_000.wav").write_bytes(WAV_BYTES)
            self.assertEqual(next_output_path(directory, "こんにちは").name, "[Common]こんにちは_001.wav")

    def test_prefix_parser_returns_tag_and_display_name(self) -> None:
        self.assertEqual(
            split_clip_prefix("[Continue]こんにちは_000.wav"),
            ("Continue", "こんにちは_000.wav"),
        )
        self.assertEqual(split_clip_prefix("こんにちは_000.wav"), (None, "こんにちは_000.wav"))

    def test_generation_uses_phrase_filename_and_expected_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            client = FakeClient()
            result = generate_voice_set(
                client=client,
                output_root=Path(temp),
                voice_id="しのさわひろ",
                num_steps=40,
                groups=(GenerationGroup("Default", ("こんにちは",), 2, "明るい声"),),
            )

            self.assertEqual(
                [path.name for path in result.files],
                ["[Common]こんにちは_000.wav", "[Common]こんにちは_001.wav"],
            )
            self.assertEqual(result.files[0].parent.name, "Default")
            self.assertEqual(result.files[0].parent.parent.name, "しのさわひろ")
            self.assertEqual(
                client.requests,
                [
                    ("こんにちは", "しのさわひろ", 40, "明るい声"),
                    ("こんにちは", "しのさわひろ", 40, "明るい声"),
                ],
            )

    def test_generation_keeps_original_emoji_in_text_and_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            client = FakeClient()
            result = generate_voice_set(
                client=client,
                output_root=Path(temp),
                voice_id="しのさわひろ",
                num_steps=40,
                groups=(GenerationGroup("Default", ("こんにちは😀",), 1),),
            )

            self.assertEqual(result.files[0].name, "[Common]こんにちは😀_000.wav")
            self.assertEqual(client.requests[0][0], "こんにちは😀")

    def test_generation_keeps_text_hearts_in_filename_and_tts_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            client = FakeClient()
            result = generate_voice_set(
                client=client,
                output_root=Path(temp),
                voice_id="ユウカ",
                num_steps=40,
                groups=(GenerationGroup("HighArousal", ("んあ...。♡",), 2),),
            )

            self.assertEqual(
                [path.name for path in result.files],
                ["[Common]んあ...。♡_000.wav", "[Common]んあ...。♡_001.wav"],
            )
            self.assertEqual([request[0] for request in client.requests], ["んあ...。♡", "んあ...。♡"])

    def test_generation_without_caption_forwards_none(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            client = FakeClient()
            generate_voice_set(
                client=client,
                output_root=Path(temp),
                voice_id="しのさわひろ",
                num_steps=40,
                groups=(GenerationGroup("Default", ("こんにちは",), 1),),
            )

            self.assertEqual(client.requests, [("こんにちは", "しのさわひろ", 40, None)])

    def test_sample_cycles_slash_separated_candidates_without_voice_set_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            sample_root = Path(temp) / "temporary_samples"
            client = FakeClient()

            first = generate_sample_clip(
                client=client,
                sample_root=sample_root,
                voice_id="森岡凛",
                voice_type="Orgasm",
                text_value="one/two/three",
                caption="sample caption",
                num_steps=40,
                index=0,
            )
            second = generate_sample_clip(
                client=client,
                sample_root=sample_root,
                voice_id="森岡凛",
                voice_type="Orgasm",
                text_value="one/two/three",
                caption="sample caption",
                num_steps=40,
                index=first.next_index,
            )

            self.assertEqual((first.text, second.text), ("one", "two"))
            self.assertEqual((first.next_index, second.next_index), (1, 2))
            self.assertEqual(first.path.parent, sample_root.resolve())
            self.assertTrue(first.path.is_file())
            self.assertTrue(second.path.is_file())
            self.assertEqual(
                client.requests,
                [
                    ("one", "森岡凛", 40, "sample caption"),
                    ("two", "森岡凛", 40, "sample caption"),
                ],
            )

    def test_sample_index_wraps_to_first_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = generate_sample_clip(
                client=FakeClient(),
                sample_root=Path(temp),
                voice_id="森岡凛",
                voice_type="Default",
                text_value="first/second",
                caption=None,
                num_steps=40,
                index=3,
            )
            self.assertEqual(result.text, "second")
            self.assertEqual(result.next_index, 0)


if __name__ == "__main__":
    unittest.main()
