from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable
from uuid import uuid4

import requests


VOICE_TYPES = (
    "Default",
    "LowArousal",
    "MediumArousal",
    "HighArousal",
    "NearOrgasm",
    "Orgasm",
    "Hypersensitive",
    "Overdrive",
    "DeepOrgasm",
)
CLIP_PREFIXES = ("Common", "Continue", "EaseUp", "Change", "Stop", "Fawn")
DEFAULT_CLIP_PREFIX = "Common"

DEFAULT_SERVER_URL = "http://127.0.0.1:5000"
DEFAULT_STEPS = 40
TEXT_SEPARATOR = re.compile(r"/+")
WINDOWS_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
CLIP_PREFIX_PATTERN = re.compile(
    rf"^\[({'|'.join(re.escape(prefix) for prefix in CLIP_PREFIXES)})\]"
)


class BuilderError(RuntimeError):
    """An error that can be shown directly in the Builder UI."""


@dataclass(frozen=True)
class GenerationGroup:
    voice_type: str
    texts: tuple[str, ...]
    count: int
    caption: str | None = None

    @property
    def clip_count(self) -> int:
        return len(self.texts) * self.count


@dataclass(frozen=True)
class GenerationResult:
    files: tuple[Path, ...]
    log_lines: tuple[str, ...]


@dataclass(frozen=True)
class SampleResult:
    path: Path
    text: str
    next_index: int


def split_texts(value: str) -> tuple[str, ...]:
    """Split a type's input into the exact phrases sent to the TTS endpoint."""
    if not value:
        return ()
    return tuple(part.strip() for part in TEXT_SEPARATOR.split(value) if part.strip())


def safe_path_component(value: str, *, fallback: str) -> str:
    """Keep readable text while replacing characters Windows cannot use in names."""
    cleaned = WINDOWS_INVALID.sub("_", value).strip().rstrip(". ")
    if not cleaned:
        cleaned = fallback
    if cleaned.upper() in WINDOWS_RESERVED:
        cleaned = f"_{cleaned}"
    # Leave room for the counter suffix and extension under Windows' limits.
    return cleaned[:180].rstrip(". ") or fallback


def split_clip_prefix(filename: str) -> tuple[str | None, str]:
    match = CLIP_PREFIX_PATTERN.match(filename)
    if not match:
        return None, filename
    return match.group(1), filename[match.end() :]


def add_clip_prefix(filename: str, prefix: str = DEFAULT_CLIP_PREFIX) -> str:
    if prefix not in CLIP_PREFIXES:
        raise BuilderError("不正なクリッププレフィックスです。")
    _, bare_filename = split_clip_prefix(filename)
    return f"[{prefix}]{bare_filename}"


def parse_count(value: object, voice_type: str) -> int:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise BuilderError(f"{voice_type} の出力数を整数で指定してください。") from exc
    count = int(numeric)
    if numeric != count or count < 0:
        raise BuilderError(f"{voice_type} の出力数は0以上の整数で指定してください。")
    return count


def make_groups(
    text_values: Iterable[str],
    caption_values: Iterable[str],
    count_values: Iterable[object],
    enabled_values: Iterable[object] | None = None,
) -> tuple[GenerationGroup, ...]:
    groups: list[GenerationGroup] = []
    enabled_items = enabled_values if enabled_values is not None else (True for _ in VOICE_TYPES)
    for voice_type, enabled, raw_text, raw_caption, raw_count in zip(
        VOICE_TYPES,
        enabled_items,
        text_values,
        caption_values,
        count_values,
        strict=True,
    ):
        if not enabled:
            continue
        count = parse_count(raw_count, voice_type)
        texts = split_texts(raw_text)
        if texts and count:
            caption = raw_caption.strip() or None
            groups.append(GenerationGroup(voice_type, texts, count, caption))
    if not groups:
        raise BuilderError("生成対象のテキストと、1以上の出力数を指定してください。")
    return tuple(groups)


def next_output_path(directory: Path, phrase: str) -> Path:
    stem = safe_path_component(phrase, fallback="clip")
    used_indices: set[int] = set()
    if directory.is_dir():
        numbered = re.compile(rf"^{re.escape(stem)}_([0-9]{{3,}})\.wav(?:\.part)?$", re.IGNORECASE)
        for path in directory.iterdir():
            _, bare_name = split_clip_prefix(path.name)
            match = numbered.fullmatch(bare_name)
            if match:
                used_indices.add(int(match.group(1)))
    index = 0
    while True:
        candidate = directory / add_clip_prefix(f"{stem}_{index:03d}.wav")
        if index not in used_indices and not candidate.exists() and not candidate.with_suffix(".wav.part").exists():
            return candidate
        index += 1


class IrodoriServerClient:
    def __init__(self, base_url: str, *, session: requests.Session | None = None) -> None:
        clean_url = base_url.strip().rstrip("/")
        if not clean_url:
            raise BuilderError("TTSサーバーURLを指定してください。")
        self.base_url = clean_url
        self.session = session or requests.Session()

    def _get_json(self, path: str) -> dict[str, object]:
        try:
            response = self.session.get(f"{self.base_url}{path}", timeout=(5, 30))
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise BuilderError(f"TTSサーバーに接続できません: {exc}") from exc
        except ValueError as exc:
            raise BuilderError("TTSサーバーから不正な応答を受信しました。") from exc
        if not isinstance(payload, dict):
            raise BuilderError("TTSサーバーから不正な応答を受信しました。")
        return payload

    def health(self) -> dict[str, object]:
        return self._get_json("/health")

    def ensure_voice(self, voice_id: str) -> str:
        requested = voice_id.strip()
        if not requested:
            raise BuilderError("参照voiceを指定してください。")
        payload = self._get_json("/voices")
        voices = payload.get("voices")
        if not isinstance(voices, list):
            raise BuilderError("TTSサーバーのvoice一覧を取得できませんでした。")
        for entry in voices:
            if isinstance(entry, dict) and str(entry.get("id", "")).casefold() == requested.casefold():
                return str(entry["id"])
        raise BuilderError(f"参照voice「{requested}」がTTSサーバーに見つかりません。")

    def synthesize(
        self,
        *,
        text: str,
        voice_id: str,
        num_steps: int,
        caption: str | None = None,
    ) -> bytes:
        fields = {
            "text": text,
            "speaker_id": voice_id,
            "num_steps": str(num_steps),
            "cfg_scale_text": "3.0",
            "cfg_scale_speaker": "5.0",
            "cfg_guidance_mode": "independent",
            "format": "wav",
        }
        if caption:
            fields["caption"] = caption
        try:
            response = self.session.post(
                f"{self.base_url}/tts",
                data=fields,
                timeout=(10, 900),
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            detail = ""
            response_value = getattr(exc, "response", None)
            if response_value is not None:
                try:
                    detail = str(response_value.json().get("detail", ""))
                except (ValueError, AttributeError):
                    detail = response_value.text[:300]
            suffix = f" ({detail})" if detail else ""
            raise BuilderError(f"「{text}」の生成に失敗しました: {exc}{suffix}") from exc

        if response.headers.get("X-Irodori-Voice-Fallback", "false").casefold() == "true":
            raise BuilderError(
                f"参照voice「{voice_id}」が使用されず、no-referenceへフォールバックしました。"
            )
        if "audio/wav" not in response.headers.get("Content-Type", "").casefold():
            raise BuilderError(f"「{text}」に対してWAV以外の応答を受信しました。")
        if not response.content.startswith(b"RIFF"):
            raise BuilderError(f"「{text}」に対して不正なWAVデータを受信しました。")
        return response.content


def generate_voice_set(
    *,
    client: IrodoriServerClient,
    output_root: Path,
    voice_id: str,
    num_steps: int,
    groups: Iterable[GenerationGroup],
    progress: Callable[[int, int, str], None] | None = None,
) -> GenerationResult:
    if num_steps < 1 or num_steps > 120:
        raise BuilderError("ステップ数は1～120で指定してください。")

    resolved_voice = client.ensure_voice(voice_id)
    group_list = tuple(groups)
    total = sum(group.clip_count for group in group_list)
    completed = 0
    files: list[Path] = []
    logs: list[str] = []
    voice_directory = output_root / safe_path_component(resolved_voice, fallback="voice")

    for group in group_list:
        type_directory = voice_directory / group.voice_type
        type_directory.mkdir(parents=True, exist_ok=True)
        for phrase in group.texts:
            for _ in range(group.count):
                label = f"{group.voice_type}: {phrase}"
                if progress:
                    progress(completed, total, label)
                wav = client.synthesize(
                    text=phrase,
                    voice_id=resolved_voice,
                    num_steps=num_steps,
                    caption=group.caption,
                )
                output_path = next_output_path(type_directory, phrase)
                temporary_path = output_path.with_suffix(".wav.part")
                temporary_path.write_bytes(wav)
                temporary_path.replace(output_path)
                files.append(output_path.resolve())
                completed += 1
                logs.append(f"[{completed}/{total}] {output_path}")

    if progress:
        progress(total, total, "完了")
    return GenerationResult(tuple(files), tuple(logs))


def generate_sample_clip(
    *,
    client: IrodoriServerClient,
    sample_root: Path,
    voice_id: str,
    voice_type: str,
    text_value: str,
    caption: str | None,
    num_steps: int,
    index: int,
) -> SampleResult:
    if voice_type not in VOICE_TYPES:
        raise BuilderError("不正なタイプが指定されました。")
    if num_steps < 1 or num_steps > 120:
        raise BuilderError("ステップ数は1～120で指定してください。")
    texts = split_texts(text_value)
    if not texts:
        raise BuilderError(f"{voice_type} のテキストを指定してください。")
    resolved_voice = client.ensure_voice(voice_id)
    selected_index = max(0, int(index)) % len(texts)
    selected_text = texts[selected_index]
    wav = client.synthesize(
        text=selected_text,
        voice_id=resolved_voice,
        num_steps=num_steps,
        caption=(caption or "").strip() or None,
    )
    sample_root.mkdir(parents=True, exist_ok=True)
    type_stem = safe_path_component(voice_type, fallback="sample")
    text_stem = safe_path_component(selected_text, fallback="clip")
    output_path = sample_root / f"{type_stem}_{text_stem}_{uuid4().hex}.wav"
    temporary_path = output_path.with_suffix(".wav.part")
    temporary_path.write_bytes(wav)
    temporary_path.replace(output_path)
    return SampleResult(output_path.resolve(), selected_text, (selected_index + 1) % len(texts))
