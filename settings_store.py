from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from irodori_builder import DEFAULT_SERVER_URL, DEFAULT_STEPS, VOICE_TYPES


DEFAULT_ARRANGE_TAGS = (
    "vm/Nod/LeanBack/Shudder/Convulse/HeadShake/LookDown/TurnAway/"
    "HeadTilt/HeadBack/ChinTuck/tear"
)


def default_settings() -> dict[str, Any]:
    return {
        "server_url": DEFAULT_SERVER_URL,
        "voice_id": "",
        "num_steps": DEFAULT_STEPS,
        "arrange_skip_delete_confirm": False,
        "arrange_available_tags": DEFAULT_ARRANGE_TAGS,
        "types": {
            voice_type: {
                "enabled": True,
                "text": "",
                "caption": "",
                "count": 1,
            }
            for voice_type in VOICE_TYPES
        },
    }


def load_settings(path: Path) -> dict[str, Any]:
    settings = default_settings()
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return settings
    if not isinstance(loaded, dict):
        return settings

    if isinstance(loaded.get("server_url"), str):
        settings["server_url"] = loaded["server_url"]
    if isinstance(loaded.get("voice_id"), str):
        settings["voice_id"] = loaded["voice_id"]
    if isinstance(loaded.get("arrange_skip_delete_confirm"), bool):
        settings["arrange_skip_delete_confirm"] = loaded["arrange_skip_delete_confirm"]
    if isinstance(loaded.get("arrange_available_tags"), str):
        settings["arrange_available_tags"] = loaded["arrange_available_tags"]
    steps = loaded.get("num_steps")
    if isinstance(steps, (int, float)) and not isinstance(steps, bool):
        if float(steps).is_integer() and 1 <= int(steps) <= 120:
            settings["num_steps"] = int(steps)

    loaded_types = loaded.get("types")
    if not isinstance(loaded_types, dict):
        return settings
    for voice_type in VOICE_TYPES:
        loaded_type = loaded_types.get(voice_type)
        if not isinstance(loaded_type, dict):
            continue
        destination = settings["types"][voice_type]
        if isinstance(loaded_type.get("enabled"), bool):
            destination["enabled"] = loaded_type["enabled"]
        if isinstance(loaded_type.get("text"), str):
            destination["text"] = loaded_type["text"]
        if isinstance(loaded_type.get("caption"), str):
            destination["caption"] = loaded_type["caption"]
        count = loaded_type.get("count")
        if isinstance(count, (int, float)) and not isinstance(count, bool):
            if float(count).is_integer() and int(count) >= 0:
                destination["count"] = int(count)
    return settings


def save_settings(path: Path, settings: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(deepcopy(settings), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
