from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path

from arrange_manager import (
    ArrangeError,
    delete_clip,
    delete_all_clips,
    delete_type_clips,
    duplicate_clip,
    list_clips,
    list_voice_sets,
    move_clip,
    normalize_available_tags,
    renumber_all_clips,
    set_clip_prefix,
    set_clip_tags,
    split_clip_tags,
    trim_wav_clip,
)
from irodori_builder import VOICE_TYPES


WAV = b"RIFF" + (b"\x00" * 40)


def make_clip(root: Path, voice: str, voice_type: str, filename: str) -> Path:
    path = root / voice / voice_type / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(WAV)
    return path


def make_pcm_wav(
    root: Path,
    voice: str,
    voice_type: str,
    filename: str,
    sample_value: int = 0,
) -> Path:
    path = root / voice / voice_type / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(8000)
        writer.writeframes(int(sample_value).to_bytes(2, "little", signed=True) * 8000)
    return path


class ArrangeManagerTests(unittest.TestCase):
    def test_parses_and_normalizes_additional_tags(self) -> None:
        self.assertEqual(normalize_available_tags(" Nod / Blink /nod "), ("Nod", "Blink"))
        self.assertEqual(split_clip_tags("voice_000[Nod][Blink].wav"), ("voice_000.wav", ("Nod", "Blink")))
        self.assertEqual(split_clip_tags("[Nod][Blink]voice_000.wav"), ("voice_000.wav", ("Nod", "Blink")))
        with self.assertRaises(ArrangeError):
            normalize_available_tags("Nod/bad?")

    def test_lists_voice_sets_and_all_types(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_clip(root, "森岡凛", "Default", "こんにちは_000.wav")
            (root / ".hidden").mkdir()

            self.assertEqual(list_voice_sets(root), ("森岡凛",))
            clips = list_clips(root, "森岡凛")
            self.assertEqual(tuple(clips), VOICE_TYPES)
            self.assertEqual(clips["Default"][0].name, "こんにちは_000.wav")

    def test_lists_cards_in_prefix_order_then_filename_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for filename in (
                "[Fawn]z_000.wav",
                "[Stop]z_000.wav",
                "[Change]z_000.wav",
                "[EaseUp]z_000.wav",
                "[Continue]b_000.wav",
                "[Continue]a_000.wav",
                "[Common]z_000.wav",
            ):
                make_clip(root, "森岡凛", "Default", filename)

            names = [path.name for path in list_clips(root, "森岡凛")["Default"]]

            self.assertEqual(
                names,
                [
                    "[Common]z_000.wav",
                    "[Continue]a_000.wav",
                    "[Continue]b_000.wav",
                    "[EaseUp]z_000.wav",
                    "[Change]z_000.wav",
                    "[Stop]z_000.wav",
                    "[Fawn]z_000.wav",
                ],
            )

    def test_fawn_prefix_is_available_after_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = make_clip(root, "森岡凛", "Default", "[Stop]voice_000.wav")

            result = set_clip_prefix(root, "森岡凛", "Default", source.name, "Fawn")

            self.assertEqual(result.destination.name, "[Fawn]voice_000.wav")

    def test_moves_clip_to_another_type(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = make_clip(root, "森岡凛", "Default", "こんにちは_000.wav")

            result = move_clip(root, "森岡凛", "Default", "LowArousal", source.name)

            self.assertFalse(source.exists())
            self.assertEqual(result.destination.parent.name, "LowArousal")
            self.assertEqual(result.destination.name, "こんにちは_000.wav")
            self.assertFalse(result.renamed)

    def test_collision_uses_next_available_number(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = make_clip(root, "森岡凛", "Default", "こんにちは_000.wav")
            make_clip(root, "森岡凛", "LowArousal", "こんにちは_000.wav")
            make_clip(root, "森岡凛", "LowArousal", "こんにちは_001.wav")

            result = move_clip(root, "森岡凛", "Default", "LowArousal", source.name)

            self.assertEqual(result.destination.name, "こんにちは_002.wav")
            self.assertTrue(result.renamed)

    def test_delete_moves_clip_to_recoverable_trash(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = make_clip(root, "森岡凛", "HighArousal", "はい_000.wav")

            destination = delete_clip(root, "森岡凛", "HighArousal", source.name)

            self.assertFalse(source.exists())
            self.assertTrue(destination.exists())
            self.assertEqual(destination.parent.parts[-2:], (".trash", "HighArousal"))

    def test_deletes_every_clip_in_one_type(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_clip(root, "森岡凛", "Default", "one_000.wav")
            make_clip(root, "森岡凛", "Default", "two_000.wav")
            other = make_clip(root, "森岡凛", "LowArousal", "keep_000.wav")

            deleted = delete_type_clips(root, "森岡凛", "Default")

            self.assertEqual(len(deleted), 2)
            self.assertEqual(list_clips(root, "森岡凛")["Default"], ())
            self.assertTrue(other.exists())

    def test_deletes_every_clip_across_all_types(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_clip(root, "森岡凛", "Default", "one_000.wav")
            make_clip(root, "森岡凛", "Orgasm", "two_000.wav")

            deleted = delete_all_clips(root, "森岡凛")

            self.assertEqual(len(deleted), 2)
            self.assertTrue(all(not clips for clips in list_clips(root, "森岡凛").values()))

    def test_duplicate_uses_next_available_number(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = make_clip(root, "森岡凛", "Default", "voice_000.wav")
            make_clip(root, "森岡凛", "Default", "voice_001.wav")

            result = duplicate_clip(root, "森岡凛", "Default", source.name)

            self.assertEqual(result.duplicate.name, "voice_002.wav")
            self.assertEqual(result.duplicate.read_bytes(), source.read_bytes())

    def test_duplicate_preserves_additional_tags(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = make_clip(root, "森岡凛", "Default", "[Common][Nod][Blink]voice_000.wav")

            result = duplicate_clip(root, "森岡凛", "Default", source.name)

            self.assertEqual(result.duplicate.name, "[Common][Nod][Blink]voice_001.wav")

    def test_renumbers_gaps_duplicate_suffixes_and_missing_suffixes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            type_directory = root / "森岡凛" / "Default"
            make_clip(root, "森岡凛", "Default", "voice_002.wav").write_bytes(b"two")
            make_clip(root, "森岡凛", "Default", "voice_005.wav").write_bytes(b"five")
            make_clip(root, "森岡凛", "Default", "voice_000_000.wav").write_bytes(b"nested")
            make_clip(root, "森岡凛", "Default", "other.wav").write_bytes(b"other")

            result = renumber_all_clips(root, "森岡凛")

            self.assertEqual(result.total, 4)
            self.assertEqual(result.renamed, 4)
            self.assertEqual(
                {path.name for path in type_directory.iterdir()},
                {
                    "[Common]voice_000.wav",
                    "[Common]voice_001.wav",
                    "[Common]voice_002.wav",
                    "[Common]other_000.wav",
                },
            )
            self.assertEqual(
                {path.read_bytes() for path in type_directory.iterdir()},
                {b"two", b"five", b"nested", b"other"},
            )

    def test_renumber_adds_common_to_untagged_contiguous_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_clip(root, "森岡凛", "Default", "voice_000.wav")
            make_clip(root, "森岡凛", "Default", "voice_001.wav")

            result = renumber_all_clips(root, "森岡凛")

            self.assertEqual(result.total, 2)
            self.assertEqual(result.renamed, 2)

    def test_renumber_keeps_tags_but_numbers_across_tag_types(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            type_directory = root / "森岡凛" / "Default"
            make_clip(root, "森岡凛", "Default", "[Continue]voice_004.wav")
            make_clip(root, "森岡凛", "Default", "[Stop]voice_009.wav")

            renumber_all_clips(root, "森岡凛")

            self.assertEqual(
                {path.name for path in type_directory.iterdir()},
                {"[Continue]voice_000.wav", "[Stop]voice_001.wav"},
            )

    def test_renumber_preserves_additional_tags_without_separate_number_groups(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            type_directory = root / "森岡凛" / "Default"
            make_clip(root, "森岡凛", "Default", "[Common]voice_004[Nod].wav")
            make_clip(root, "森岡凛", "Default", "[Common]voice_009[Blink].wav")

            renumber_all_clips(root, "森岡凛")

            self.assertEqual(
                {path.name for path in type_directory.iterdir()},
                {"[Common][Nod]voice_000.wav", "[Common][Blink]voice_001.wav"},
            )

    def test_changes_clip_prefix_without_touching_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = make_clip(root, "森岡凛", "Default", "[Common]voice_000.wav")
            source.write_bytes(b"audio")

            result = set_clip_prefix(root, "森岡凛", "Default", source.name, "EaseUp")

            self.assertFalse(source.exists())
            self.assertEqual(result.destination.name, "[EaseUp]voice_000.wav")
            self.assertEqual(result.destination.read_bytes(), b"audio")

    def test_changes_multiple_additional_tags_without_touching_audio_or_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = make_clip(root, "森岡凛", "Default", "[Stop]voice_000[Nod].wav")
            source.write_bytes(b"audio")

            result = set_clip_tags(root, "森岡凛", "Default", source.name, ("Blink", "Smile"))

            self.assertEqual(result.destination.name, "[Stop][Blink][Smile]voice_000.wav")
            self.assertEqual(result.destination.read_bytes(), b"audio")

    def test_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_clip(root, "森岡凛", "Default", "safe_000.wav")
            with self.assertRaises(ArrangeError):
                move_clip(root, "森岡凛", "Default", "LowArousal", "../safe_000.wav")

    def test_trims_pcm_wav_and_backs_up_original(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            clip = make_pcm_wav(root, "森岡凛", "Default", "trim_000.wav")

            result = trim_wav_clip(root, "森岡凛", "Default", clip.name, 0.25, 0.75)

            with wave.open(str(clip), "rb") as trimmed:
                self.assertEqual(trimmed.getnframes(), 4000)
                self.assertEqual(trimmed.getframerate(), 8000)
            with wave.open(str(result.backup), "rb") as backup:
                self.assertEqual(backup.getnframes(), 8000)
            self.assertAlmostEqual(result.original_duration, 1.0)
            self.assertAlmostEqual(result.trimmed_duration, 0.5)
            self.assertEqual(result.backup.parent.parts[-3:], (".trash", "edits", "Default"))

    def test_rejects_invalid_trim_range_without_changing_clip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            clip = make_pcm_wav(root, "森岡凛", "Default", "trim_000.wav")
            original = clip.read_bytes()

            with self.assertRaises(ArrangeError):
                trim_wav_clip(root, "森岡凛", "Default", clip.name, 0.8, 0.2)

            self.assertEqual(clip.read_bytes(), original)

    def test_trim_can_rename_clip_and_preserves_original_backup_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            clip = make_pcm_wav(root, "森岡凛", "Default", "before_000.wav")

            result = trim_wav_clip(
                root,
                "森岡凛",
                "Default",
                clip.name,
                0.25,
                0.75,
                new_filename="after_000",
            )

            self.assertFalse(clip.exists())
            self.assertEqual(result.clip.name, "after_000.wav")
            self.assertTrue(result.clip.exists())
            self.assertEqual(result.backup.name, "before_000.wav")

    def test_trim_rename_preserves_hidden_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            clip = make_pcm_wav(root, "森岡凛", "Default", "[Stop]before_000.wav")

            result = trim_wav_clip(
                root,
                "森岡凛",
                "Default",
                clip.name,
                0.25,
                0.75,
                new_filename="after_000.wav",
            )

            self.assertEqual(result.clip.name, "[Stop]after_000.wav")
            self.assertEqual(result.backup.name, "[Stop]before_000.wav")

    def test_trim_can_change_prefix_and_filename_together(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            clip = make_pcm_wav(root, "森岡凛", "Default", "[Common]before_000.wav")

            result = trim_wav_clip(
                root,
                "森岡凛",
                "Default",
                clip.name,
                0.25,
                0.75,
                new_filename="after_000.wav",
                new_prefix="Stop",
            )

            self.assertEqual(result.clip.name, "[Stop]after_000.wav")
            self.assertEqual(result.backup.name, "[Common]before_000.wav")

    def test_trim_can_change_additional_tags(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            clip = make_pcm_wav(root, "森岡凛", "Default", "[Common]before_000[Nod].wav")

            result = trim_wav_clip(
                root, "森岡凛", "Default", clip.name, 0.25, 0.75,
                new_filename="after_000.wav", new_tags=("Blink", "Smile"),
            )

            self.assertEqual(result.clip.name, "[Common][Blink][Smile]after_000.wav")
            self.assertEqual(result.backup.name, "[Common]before_000[Nod].wav")

    def test_trim_rejects_duplicate_rename_without_changing_clip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            clip = make_pcm_wav(root, "森岡凛", "Default", "before_000.wav")
            make_pcm_wav(root, "森岡凛", "Default", "existing_000.wav")
            original = clip.read_bytes()

            with self.assertRaisesRegex(ArrangeError, r"推奨ファイル名: existing_001\.wav"):
                trim_wav_clip(
                    root,
                    "森岡凛",
                    "Default",
                    clip.name,
                    0.25,
                    0.75,
                    new_filename="existing_000.wav",
                )

            self.assertEqual(clip.read_bytes(), original)
            self.assertTrue(clip.exists())

    def test_trim_rejects_invalid_rename_without_changing_clip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            clip = make_pcm_wav(root, "森岡凛", "Default", "before_000.wav")
            original = clip.read_bytes()

            with self.assertRaises(ArrangeError):
                trim_wav_clip(
                    root,
                    "森岡凛",
                    "Default",
                    clip.name,
                    0.25,
                    0.75,
                    new_filename="invalid?.wav",
                )

            self.assertEqual(clip.read_bytes(), original)

    def test_applies_linear_fade_in_and_out(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            clip = make_pcm_wav(root, "森岡凛", "Default", "fade_000.wav", sample_value=10000)

            trim_wav_clip(root, "森岡凛", "Default", clip.name, 0, 1, 0.25, 0.25)

            with wave.open(str(clip), "rb") as reader:
                frames = reader.readframes(reader.getnframes())
            samples = [int.from_bytes(frames[i : i + 2], "little", signed=True) for i in range(0, len(frames), 2)]
            self.assertEqual(samples[0], 0)
            self.assertGreaterEqual(samples[1999], 9990)
            self.assertEqual(samples[4000], 10000)
            self.assertGreaterEqual(samples[6000], 9990)
            self.assertEqual(samples[-1], 0)

    def test_rejects_fade_longer_than_trimmed_clip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            clip = make_pcm_wav(root, "森岡凛", "Default", "fade_000.wav", sample_value=10000)
            original = clip.read_bytes()

            with self.assertRaises(ArrangeError):
                trim_wav_clip(root, "森岡凛", "Default", clip.name, 0.2, 0.4, 0.3, 0)

            self.assertEqual(clip.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
