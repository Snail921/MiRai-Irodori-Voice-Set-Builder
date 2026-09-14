from __future__ import annotations

import re
import shutil
import sys
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from irodori_builder import (
    CLIP_PREFIXES,
    DEFAULT_CLIP_PREFIX,
    VOICE_TYPES,
    add_clip_prefix,
    split_clip_prefix,
)


AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac"}
NUMBERED_STEM = re.compile(r"^(.*)_([0-9]{3,})$")
WINDOWS_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_RESERVED_STEMS = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
CLIP_PREFIX_ORDER = {prefix: index for index, prefix in enumerate(CLIP_PREFIXES)}


class ArrangeError(RuntimeError):
    """A safe, user-facing Arrange operation error."""


@dataclass(frozen=True)
class MoveResult:
    source: Path
    destination: Path
    renamed: bool


@dataclass(frozen=True)
class TrimResult:
    clip: Path
    backup: Path
    original_duration: float
    trimmed_duration: float


@dataclass(frozen=True)
class DuplicateResult:
    source: Path
    duplicate: Path


@dataclass(frozen=True)
class RenumberResult:
    total: int
    renamed: int


@dataclass(frozen=True)
class PrefixResult:
    source: Path
    destination: Path
    prefix: str


@dataclass(frozen=True)
class TagsResult:
    source: Path
    destination: Path
    tags: tuple[str, ...]


ADDITIONAL_TAG_PREFIX = re.compile(r"^(?:\[([^\[\]]+)\])+")
ADDITIONAL_TAG_SUFFIX = re.compile(r"(?:\[([^\[\]]+)\])+$")
ADDITIONAL_TAG_ITEM = re.compile(r"\[([^\[\]]+)\]")
INVALID_ADDITIONAL_TAG = re.compile(r'[\[\]/\\<>:"|?*\x00-\x1f]')


def normalize_available_tags(value: str) -> tuple[str, ...]:
    tags: list[str] = []
    seen: set[str] = set()
    for raw_tag in str(value or "").split("/"):
        tag = raw_tag.strip()
        if tag.startswith("[") and tag.endswith("]"):
            tag = tag[1:-1].strip()
        if not tag:
            continue
        if len(tag) > 40 or INVALID_ADDITIONAL_TAG.search(tag):
            raise ArrangeError(f"追加タグ「{tag}」に使用できない文字が含まれています。")
        key = tag.casefold()
        if key not in seen:
            tags.append(tag)
            seen.add(key)
    return tuple(tags)


def split_clip_tags(filename: str) -> tuple[str, tuple[str, ...]]:
    path = Path(filename)
    stem = path.stem
    tags: list[str] = []
    prefix_match = ADDITIONAL_TAG_PREFIX.match(stem)
    if prefix_match:
        tags.extend(ADDITIONAL_TAG_ITEM.findall(prefix_match.group(0)))
        stem = stem[prefix_match.end() :]
    suffix_match = ADDITIONAL_TAG_SUFFIX.search(stem)
    if suffix_match:
        tags.extend(ADDITIONAL_TAG_ITEM.findall(suffix_match.group(0)))
        stem = stem[: suffix_match.start()]
    if not tags:
        return filename, ()
    normalized_tags = normalize_available_tags("/".join(tags))
    bare_stem = stem
    return f"{bare_stem}{path.suffix}", normalized_tags


def add_clip_tags(filename: str, tags: tuple[str, ...] | list[str]) -> str:
    bare_name, _ = split_clip_tags(filename)
    normalized = normalize_available_tags("/".join(tags))
    path = Path(bare_name)
    prefix = "".join(f"[{tag}]" for tag in normalized)
    return f"{prefix}{path.stem}{path.suffix}"


def _natural_key(value: str) -> tuple[object, ...]:
    return tuple(int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", value))


def _clip_sort_key(path: Path) -> tuple[object, ...]:
    prefix, bare_name = split_clip_prefix(path.name)
    display_name, tags = split_clip_tags(bare_name)
    return (
        CLIP_PREFIX_ORDER.get(prefix or DEFAULT_CLIP_PREFIX, 0),
        *_natural_key(display_name),
        *_natural_key("/".join(tags)),
    )


def list_voice_sets(output_root: Path) -> tuple[str, ...]:
    if not output_root.is_dir():
        return ()
    return tuple(
        path.name
        for path in sorted(output_root.iterdir(), key=lambda item: _natural_key(item.name))
        if path.is_dir() and not path.name.startswith(".")
    )


def resolve_voice_directory(output_root: Path, voice_set: str) -> Path:
    clean_name = str(voice_set or "").strip()
    if not clean_name:
        raise ArrangeError("ボイスセットを選択してください。")
    root = output_root.resolve()
    candidate = (root / clean_name).resolve()
    if candidate.parent != root or not candidate.is_dir():
        raise ArrangeError(f"ボイスセット「{clean_name}」が見つかりません。")
    return candidate


def list_clips(output_root: Path, voice_set: str) -> dict[str, tuple[Path, ...]]:
    voice_directory = resolve_voice_directory(output_root, voice_set)
    result: dict[str, tuple[Path, ...]] = {}
    for voice_type in VOICE_TYPES:
        directory = voice_directory / voice_type
        if not directory.is_dir():
            result[voice_type] = ()
            continue
        result[voice_type] = tuple(
            path.resolve()
            for path in sorted(directory.iterdir(), key=_clip_sort_key)
            if path.is_file() and path.suffix.casefold() in AUDIO_EXTENSIONS
        )
    return result


def _resolve_clip(voice_directory: Path, voice_type: str, filename: str) -> Path:
    if voice_type not in VOICE_TYPES:
        raise ArrangeError("不正なタイプが指定されました。")
    if not filename or Path(filename).name != filename:
        raise ArrangeError("不正なファイル名が指定されました。")
    type_directory = (voice_directory / voice_type).resolve()
    clip = (type_directory / filename).resolve()
    if clip.parent != type_directory or not clip.is_file():
        raise ArrangeError(f"クリップ「{filename}」が見つかりません。")
    if clip.suffix.casefold() not in AUDIO_EXTENSIONS:
        raise ArrangeError("音声ファイル以外は操作できません。")
    return clip


def _available_destination(directory: Path, filename: str) -> Path:
    requested = directory / filename
    if not requested.exists():
        return requested
    prefix, without_prefix = split_clip_prefix(filename)
    without_tags, tags = split_clip_tags(without_prefix)
    source_name = Path(without_tags)
    match = NUMBERED_STEM.fullmatch(source_name.stem)
    base = match.group(1) if match else source_name.stem
    index = 0
    while True:
        candidate_name = add_clip_tags(
            f"{base}_{index:03d}{source_name.suffix}", tags
        )
        if prefix:
            candidate_name = add_clip_prefix(candidate_name, prefix)
        candidate = directory / candidate_name
        if not candidate.exists():
            return candidate
        index += 1


def _resolve_renamed_wav(
    source: Path,
    new_filename: str | None,
    new_prefix: str | None = None,
    new_tags: tuple[str, ...] | list[str] | None = None,
) -> Path:
    source_prefix, source_bare_name = split_clip_prefix(source.name)
    source_display_name, source_tags = split_clip_tags(source_bare_name)
    if new_prefix is not None and new_prefix not in CLIP_PREFIXES:
        raise ArrangeError("不正なプレフィックスが指定されました。")
    destination_prefix = new_prefix if new_prefix is not None else source_prefix
    requested = str(new_filename or source_display_name).strip()
    _, requested = split_clip_prefix(requested)
    requested, requested_tags = split_clip_tags(requested)
    destination_tags = (
        normalize_available_tags("/".join(new_tags))
        if new_tags is not None
        else (requested_tags or source_tags)
    )
    if not requested:
        raise ArrangeError("ファイル名を入力してください。")
    if Path(requested).name != requested or WINDOWS_INVALID_FILENAME.search(requested):
        raise ArrangeError("ファイル名に使用できない文字が含まれています。")
    if requested.endswith((" ", ".")):
        raise ArrangeError("ファイル名の末尾に空白やピリオドは使用できません。")
    requested_path = Path(requested)
    if not requested_path.suffix:
        requested_path = requested_path.with_suffix(".wav")
    if requested_path.suffix.casefold() != ".wav":
        raise ArrangeError("トリミング後の拡張子は .wav にしてください。")
    if requested_path.stem.upper() in WINDOWS_RESERVED_STEMS:
        raise ArrangeError("Windowsで予約されているファイル名は使用できません。")
    tagged_name = add_clip_tags(requested_path.name, destination_tags)
    destination_name = (
        add_clip_prefix(tagged_name, destination_prefix)
        if destination_prefix
        else tagged_name
    )
    destination = source.with_name(destination_name)
    if destination != source and destination.exists():
        suggestion = _available_destination(source.parent, destination.name)
        _, suggested_name = split_clip_prefix(suggestion.name)
        raise ArrangeError(
            f"同名のクリップが既に存在します。推奨ファイル名: {suggested_name}"
        )
    return destination


def move_clip(
    output_root: Path,
    voice_set: str,
    source_type: str,
    target_type: str,
    filename: str,
) -> MoveResult:
    voice_directory = resolve_voice_directory(output_root, voice_set)
    source = _resolve_clip(voice_directory, source_type, filename)
    if target_type not in VOICE_TYPES:
        raise ArrangeError("移動先タイプが不正です。")
    if source_type == target_type:
        return MoveResult(source, source, False)
    target_directory = voice_directory / target_type
    target_directory.mkdir(parents=True, exist_ok=True)
    destination = _available_destination(target_directory, source.name)
    shutil.move(str(source), str(destination))
    return MoveResult(source, destination.resolve(), destination.name != source.name)


def delete_clip(output_root: Path, voice_set: str, voice_type: str, filename: str) -> Path:
    voice_directory = resolve_voice_directory(output_root, voice_set)
    source = _resolve_clip(voice_directory, voice_type, filename)
    trash_directory = voice_directory / ".trash" / voice_type
    trash_directory.mkdir(parents=True, exist_ok=True)
    destination = _available_destination(trash_directory, source.name)
    shutil.move(str(source), str(destination))
    return destination.resolve()


def delete_type_clips(output_root: Path, voice_set: str, voice_type: str) -> tuple[Path, ...]:
    if voice_type not in VOICE_TYPES:
        raise ArrangeError("不正なタイプが指定されました。")
    clips = list_clips(output_root, voice_set)[voice_type]
    return tuple(delete_clip(output_root, voice_set, voice_type, clip.name) for clip in clips)


def delete_all_clips(output_root: Path, voice_set: str) -> tuple[Path, ...]:
    deleted: list[Path] = []
    clips_by_type = list_clips(output_root, voice_set)
    for voice_type in VOICE_TYPES:
        for clip in clips_by_type[voice_type]:
            deleted.append(delete_clip(output_root, voice_set, voice_type, clip.name))
    return tuple(deleted)


def duplicate_clip(output_root: Path, voice_set: str, voice_type: str, filename: str) -> DuplicateResult:
    voice_directory = resolve_voice_directory(output_root, voice_set)
    source = _resolve_clip(voice_directory, voice_type, filename)
    duplicate = _available_destination(source.parent, source.name)
    shutil.copy2(source, duplicate)
    return DuplicateResult(source.resolve(), duplicate.resolve())


def set_clip_prefix(
    output_root: Path,
    voice_set: str,
    voice_type: str,
    filename: str,
    prefix: str,
) -> PrefixResult:
    if prefix not in CLIP_PREFIXES:
        raise ArrangeError("不正なプレフィックスが指定されました。")
    voice_directory = resolve_voice_directory(output_root, voice_set)
    source = _resolve_clip(voice_directory, voice_type, filename)
    current_prefix, bare_name = split_clip_prefix(source.name)
    destination = source.with_name(add_clip_prefix(bare_name, prefix))
    if current_prefix == prefix:
        return PrefixResult(source.resolve(), source.resolve(), prefix)
    if destination.exists():
        raise ArrangeError(f"同名のクリップ「{destination.name}」が既に存在します。")
    source.rename(destination)
    return PrefixResult(source.resolve(), destination.resolve(), prefix)


def set_clip_tags(
    output_root: Path,
    voice_set: str,
    voice_type: str,
    filename: str,
    tags: tuple[str, ...] | list[str],
) -> TagsResult:
    voice_directory = resolve_voice_directory(output_root, voice_set)
    source = _resolve_clip(voice_directory, voice_type, filename)
    prefix, bare_name = split_clip_prefix(source.name)
    destination_bare = add_clip_tags(bare_name, tags)
    destination_name = add_clip_prefix(destination_bare, prefix) if prefix else destination_bare
    destination = source.with_name(destination_name)
    normalized = split_clip_tags(destination_bare)[1]
    if destination == source:
        return TagsResult(source.resolve(), source.resolve(), normalized)
    if destination.exists():
        raise ArrangeError(f"同名のクリップ「{destination.name}」が既に存在します。")
    source.rename(destination)
    return TagsResult(source.resolve(), destination.resolve(), normalized)


def _base_stem_for_renumber(stem: str) -> str:
    base = stem
    while match := NUMBERED_STEM.fullmatch(base):
        base = match.group(1)
    return base or "clip"


def renumber_all_clips(output_root: Path, voice_set: str) -> RenumberResult:
    clips_by_type = list_clips(output_root, voice_set)
    total = sum(len(clips) for clips in clips_by_type.values())
    renamed = 0

    for voice_type in VOICE_TYPES:
        groups: dict[tuple[str, str], list[Path]] = {}
        group_names: dict[tuple[str, str], tuple[str, str]] = {}
        for clip in clips_by_type[voice_type]:
            _, bare_name = split_clip_prefix(clip.name)
            bare_name, tags = split_clip_tags(bare_name)
            bare_path = Path(bare_name)
            base = _base_stem_for_renumber(bare_path.stem)
            key = (base.casefold(), clip.suffix.casefold())
            groups.setdefault(key, []).append(clip)
            group_names.setdefault(key, (base, clip.suffix))

        plan: list[tuple[Path, Path]] = []
        for key in sorted(groups, key=lambda item: _natural_key(item[0])):
            base, suffix = group_names[key]
            for index, source in enumerate(sorted(groups[key], key=lambda item: _natural_key(item.name))):
                prefix, source_bare_name = split_clip_prefix(source.name)
                _, tags = split_clip_tags(source_bare_name)
                destination_name = add_clip_prefix(
                    add_clip_tags(f"{base}_{index:03d}{suffix}", tags),
                    prefix or DEFAULT_CLIP_PREFIX,
                )
                destination = source.with_name(destination_name)
                if destination.name != source.name:
                    plan.append((source, destination))

        if not plan:
            continue

        staged: list[tuple[Path, Path, Path]] = []
        completed: list[tuple[Path, Path, Path]] = []
        try:
            for source, destination in plan:
                temporary = source.with_name(f".{uuid4().hex}.renumber.tmp")
                source.rename(temporary)
                staged.append((source, temporary, destination))
            for source, temporary, destination in staged:
                temporary.rename(destination)
                completed.append((source, temporary, destination))
        except OSError as exc:
            for source, temporary, destination in reversed(staged):
                current = destination if (source, temporary, destination) in completed else temporary
                if current.exists() and not source.exists():
                    current.rename(source)
            raise ArrangeError(f"連番の振り直しに失敗しました: {exc}") from exc
        renamed += len(plan)

    return RenumberResult(total=total, renamed=renamed)


def _apply_pcm16_fades(
    frame_bytes: bytes,
    *,
    channels: int,
    frame_rate: int,
    fade_in_seconds: float,
    fade_out_seconds: float,
) -> bytes:
    samples = array("h")
    samples.frombytes(frame_bytes)
    if sys.byteorder != "little":
        samples.byteswap()
    frame_count = len(samples) // channels
    fade_in_frames = min(frame_count, round(fade_in_seconds * frame_rate))
    fade_out_frames = min(frame_count, round(fade_out_seconds * frame_rate))

    if fade_in_frames:
        denominator = max(1, fade_in_frames - 1)
        for frame in range(fade_in_frames):
            gain = frame / denominator
            offset = frame * channels
            for channel in range(channels):
                samples[offset + channel] = round(samples[offset + channel] * gain)
    if fade_out_frames:
        denominator = max(1, fade_out_frames - 1)
        first_frame = frame_count - fade_out_frames
        for position, frame in enumerate(range(first_frame, frame_count)):
            gain = (fade_out_frames - 1 - position) / denominator
            offset = frame * channels
            for channel in range(channels):
                samples[offset + channel] = round(samples[offset + channel] * gain)

    if sys.byteorder != "little":
        samples.byteswap()
    return samples.tobytes()


def trim_wav_clip(
    output_root: Path,
    voice_set: str,
    voice_type: str,
    filename: str,
    start_seconds: float,
    end_seconds: float,
    fade_in_seconds: float = 0.0,
    fade_out_seconds: float = 0.0,
    new_filename: str | None = None,
    new_prefix: str | None = None,
    new_tags: tuple[str, ...] | list[str] | None = None,
) -> TrimResult:
    voice_directory = resolve_voice_directory(output_root, voice_set)
    source = _resolve_clip(voice_directory, voice_type, filename)
    if source.suffix.casefold() != ".wav":
        raise ArrangeError("トリミングできるのはWAVクリップだけです。")
    destination = _resolve_renamed_wav(source, new_filename, new_prefix, new_tags)
    try:
        start = float(start_seconds)
        end = float(end_seconds)
        fade_in = float(fade_in_seconds)
        fade_out = float(fade_out_seconds)
    except (TypeError, ValueError) as exc:
        raise ArrangeError("開始・終了位置を秒数で指定してください。") from exc
    if start < 0 or end <= start:
        raise ArrangeError("終了位置は開始位置より後にしてください。")
    if fade_in < 0 or fade_out < 0:
        raise ArrangeError("フェード秒数は0以上にしてください。")

    try:
        with wave.open(str(source), "rb") as reader:
            parameters = reader.getparams()
            frame_rate = reader.getframerate()
            frame_count = reader.getnframes()
            frame_width = reader.getnchannels() * reader.getsampwidth()
            frames = reader.readframes(frame_count)
    except (OSError, EOFError, wave.Error) as exc:
        raise ArrangeError(f"WAVクリップを読み込めません: {exc}") from exc
    if parameters.comptype != "NONE":
        raise ArrangeError("圧縮WAVのトリミングには対応していません。")

    duration = frame_count / frame_rate
    if start >= duration:
        raise ArrangeError("開始位置がクリップの長さを超えています。")
    if end > duration + 0.01:
        raise ArrangeError("終了位置がクリップの長さを超えています。")
    end = min(end, duration)
    start_frame = max(0, min(frame_count, round(start * frame_rate)))
    end_frame = max(start_frame + 1, min(frame_count, round(end * frame_rate)))
    if end_frame - start_frame < max(1, round(frame_rate * 0.01)):
        raise ArrangeError("トリミング範囲は0.01秒以上にしてください。")
    trimmed_duration = (end_frame - start_frame) / frame_rate
    if fade_in > trimmed_duration + 0.001 or fade_out > trimmed_duration + 0.001:
        raise ArrangeError("フェード秒数はトリミング後の長さ以下にしてください。")
    if (fade_in or fade_out) and parameters.sampwidth != 2:
        raise ArrangeError("フェードに対応しているのは16-bit PCM WAVだけです。")

    trash_directory = voice_directory / ".trash" / "edits" / voice_type
    trash_directory.mkdir(parents=True, exist_ok=True)
    backup = _available_destination(trash_directory, source.name)
    shutil.copy2(source, backup)

    temporary = source.with_suffix(source.suffix + ".trim.part")
    try:
        output_frames = frames[start_frame * frame_width : end_frame * frame_width]
        if fade_in or fade_out:
            output_frames = _apply_pcm16_fades(
                output_frames,
                channels=parameters.nchannels,
                frame_rate=frame_rate,
                fade_in_seconds=fade_in,
                fade_out_seconds=fade_out,
            )
        with wave.open(str(temporary), "wb") as writer:
            writer.setparams(parameters)
            writer.writeframes(output_frames)
        temporary.replace(source)
        if destination != source:
            source.rename(destination)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise

    return TrimResult(destination.resolve(), backup.resolve(), duration, trimmed_duration)
