from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from irodori_builder import VOICE_TYPES, make_groups
from settings_store import DEFAULT_ARRANGE_TAGS, default_settings, load_settings, save_settings


class TypeSelectionTests(unittest.TestCase):
    def test_types_use_requested_order(self) -> None:
        self.assertEqual(
            VOICE_TYPES,
            (
                "Default",
                "LowArousal",
                "MediumArousal",
                "HighArousal",
                "NearOrgasm",
                "Orgasm",
                "Hypersensitive",
                "Overdrive",
                "DeepOrgasm",
            ),
        )

    def test_disabled_types_are_skipped(self) -> None:
        groups = make_groups(
            ("default", "low", "medium", "high", "near", "orgasm", "hyper", "overdrive", "deep"),
            ("", "", "", "", "", "", "", "", ""),
            (1, 1, 1, 1, 1, 1, 1, 1, 1),
            (True, False, False, False, False, False, False, True, False),
        )
        self.assertEqual([group.voice_type for group in groups], ["Default", "Overdrive"])


class SettingsTests(unittest.TestCase):
    def test_defaults_include_standard_arrange_tags(self) -> None:
        self.assertEqual(
            default_settings()["arrange_available_tags"],
            "vm/Nod/LeanBack/Shudder/Convulse/HeadShake/LookDown/TurnAway/"
            "HeadTilt/HeadBack/ChinTuck/tear",
        )
        self.assertEqual(default_settings()["arrange_available_tags"], DEFAULT_ARRANGE_TAGS)

    def test_round_trip_preserves_all_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            settings = default_settings()
            settings["voice_id"] = "森岡凛"
            settings["num_steps"] = 55
            settings["arrange_skip_delete_confirm"] = True
            settings["arrange_available_tags"] = "Nod/Blink"
            settings["types"]["LowArousal"].update(
                {"enabled": False, "text": "おはよう/こんにちは", "caption": "静かな声", "count": 3}
            )

            save_settings(path, settings)
            loaded = load_settings(path)

            self.assertEqual(loaded, settings)

    def test_invalid_file_falls_back_to_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(load_settings(path), default_settings())

    def test_unknown_keys_do_not_replace_known_type_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            path.write_text(json.dumps({"types": {"Unknown": {"enabled": False}}}), encoding="utf-8")
            loaded = load_settings(path)
            self.assertTrue(all(loaded["types"][name]["enabled"] for name in VOICE_TYPES))
