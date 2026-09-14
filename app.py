from __future__ import annotations

import os
import json
import re
import tempfile
import threading
from functools import partial
from html import escape
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

import gradio as gr

from arrange_manager import (
    ArrangeError,
    delete_all_clips,
    delete_clip,
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

from irodori_builder import (
    DEFAULT_SERVER_URL,
    DEFAULT_STEPS,
    CLIP_PREFIXES,
    DEFAULT_CLIP_PREFIX,
    VOICE_TYPES,
    BuilderError,
    IrodoriServerClient,
    generate_voice_set,
    generate_sample_clip,
    make_groups,
    parse_count,
    split_texts,
    split_clip_prefix,
    GenerationGroup,
)
from settings_store import load_settings, save_settings


APP_DIRECTORY = Path(__file__).resolve().parent
OUTPUT_DIRECTORY = APP_DIRECTORY / "output"
SAMPLE_TEMP_DIRECTORY = tempfile.TemporaryDirectory(prefix="irodori_voice_samples_")
SAMPLE_DIRECTORY = Path(SAMPLE_TEMP_DIRECTORY.name).resolve()
SETTINGS_PATH = APP_DIRECTORY / "settings.json"
SETTINGS_LOCK = threading.Lock()

GENERATION_CSS = """
.generation-type-text label > span {
  color: #000 !important;
  font-weight: 700 !important;
}
.arrange-tab-shortcut {
  min-width: 190px !important;
  min-height: 44px !important;
  padding: 9px 18px !important;
  font-size: 15px !important;
  font-weight: 700 !important;
}
.arrange-tab-shortcut.shortcut-running,
.arrange-tab-shortcut:disabled {
  color: #fff !important;
  background: #9ca3af !important;
  border-color: #9ca3af !important;
  cursor: wait !important;
  opacity: .8 !important;
}
.arrange-tab-shortcut.shortcut-ready {
  color: #fff !important;
  background: #15803d !important;
  border-color: #15803d !important;
}
.type-generate {
  color: #fff !important;
  background: #15803d !important;
  border-color: #15803d !important;
}
"""

ARRANGE_CSS = """
.arrange-board { display: grid; grid-template-columns: repeat(auto-fit, minmax(255px, 1fr)); gap: 12px; align-items: start; }
.arrange-refreshing { pointer-events: none; opacity: .62; transition: opacity .12s; }
.arrange-bulk-tools { display: flex; justify-content: flex-end; gap: 8px; margin: 0 0 10px; }
.arrange-renumber { border: 0; border-radius: 6px; cursor: pointer; color: #fff; background: #2563eb; padding: 7px 12px; font-weight: 600; }
.arrange-renumber:disabled { cursor: default; opacity: .4; }
.arrange-delete-all, .arrange-type-delete { border: 0; border-radius: 6px; cursor: pointer; color: #fff; background: #b42318; }
.arrange-delete-all { padding: 7px 12px; font-weight: 600; }
.arrange-type-delete { padding: 2px 6px; font-size: 11px; }
.arrange-type-delete:disabled { cursor: default; opacity: .4; }
.arrange-type { min-height: 150px; border: 2px dashed var(--border-color-primary); border-radius: 10px; padding: 9px; background: var(--background-fill-secondary); transition: border-color .15s, background .15s; }
.arrange-type.drag-over { border-color: var(--color-accent); background: var(--background-fill-primary); }
.arrange-type-title { display: flex; justify-content: space-between; gap: 8px; margin-bottom: 8px; font-weight: 700; }
.arrange-count { opacity: .7; font-size: .85em; }
.arrange-empty { opacity: .55; padding: 24px 6px; text-align: center; }
.clip-card { margin: 7px 0; padding: 7px; border: 1px solid var(--border-color-primary); border-radius: 8px; background: var(--block-background-fill); box-shadow: var(--block-shadow); }
.clip-prefix-row { display: flex; align-items: center; gap: 6px; margin: 0 0 5px 3px; }
.clip-prefix-mark { width: 9px; height: 9px; flex: 0 0 9px; border: 1px solid rgba(0,0,0,.35); border-radius: 50%; box-shadow: 0 0 0 1px rgba(255,255,255,.4); }
.clip-prefix-mark.prefix-common { background: #fff; }
.clip-prefix-mark.prefix-continue { background: #38bdf8; }
.clip-prefix-mark.prefix-easeup { background: #facc15; }
.clip-prefix-mark.prefix-change { background: #f97316; }
.clip-prefix-mark.prefix-stop { background: #ef4444; }
.clip-prefix-mark.prefix-fawn { background: #a855f7; }
.clip-prefix-select { max-width: 125px; padding: 2px 5px; border: 1px solid var(--border-color-primary); border-radius: 5px; background: var(--input-background-fill); color: var(--body-text-color); font-size: 11px; }
.clip-header { display: flex; align-items: center; gap: 6px; margin-bottom: 5px; }
.clip-handle { cursor: grab; user-select: none; font-size: 18px; line-height: 1; padding: 4px; }
.clip-handle:active { cursor: grabbing; }
.clip-name { min-width: 0; flex: 1; overflow-wrap: anywhere; font-size: .85em; }
.clip-edit, .clip-delete { border: 0; border-radius: 6px; padding: 3px 7px; cursor: pointer; color: #fff; font-size: 12px; }
.clip-edit { background: #2563eb; }
.clip-delete { background: #b42318; }
.clip-duplicate { border: 0; border-radius: 6px; padding: 3px 7px; cursor: pointer; color: #fff; background: #7c3aed; font-size: 12px; }
.clip-card.card-recent-play { border: 2px solid #16a34a; background: rgba(22,163,74,.12); box-shadow: 0 0 0 2px rgba(22,163,74,.16); }
.clip-card.card-recent-edit { border: 2px solid #2563eb; background: rgba(37,99,235,.12); box-shadow: 0 0 0 2px rgba(37,99,235,.16); }
.clip-card.card-recent-delete { border: 2px solid #f97316; background: rgba(249,115,22,.14); box-shadow: 0 0 0 2px rgba(249,115,22,.18); }
.clip-card.card-recent-duplicate { border: 2px solid #7c3aed; background: rgba(124,58,237,.12); box-shadow: 0 0 0 2px rgba(124,58,237,.16); }
.clip-card audio { width: 100%; height: 32px; display: block; }
.clip-tags-area { position: relative; margin-top: 7px; padding-top: 2px; }
.clip-tags-heading { display: flex; align-items: center; justify-content: space-between; gap: 7px; margin-bottom: 5px; color: var(--body-text-color-subdued); font-size: 11px; }
.clip-tag-add, .trim-tag-add { border: 1px solid var(--border-color-primary); border-radius: 5px; padding: 2px 7px; cursor: pointer; background: var(--button-secondary-background-fill); color: var(--button-secondary-text-color); font-size: 11px; }
.clip-tag-list, .trim-tag-chips { display: flex; flex-wrap: wrap; gap: 5px; min-height: 22px; }
.clip-tag-empty { color: var(--body-text-color-subdued); font-size: 11px; }
.clip-tag-chip, .trim-tag-chip { position: relative; display: inline-flex; align-items: center; min-height: 22px; padding: 3px 21px 3px 8px; border: 1px solid #93c5fd; border-radius: 999px; background: rgba(59,130,246,.12); color: var(--body-text-color); font-size: 11px; }
.clip-tag-remove, .trim-tag-remove { position: absolute; top: 1px; right: 3px; width: 16px; height: 16px; border: 0; padding: 0; cursor: pointer; background: transparent; color: #dc2626; font-size: 13px; font-weight: 700; line-height: 16px; }
.clip-tag-picker, .trim-tag-picker { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; padding: 7px; border: 1px solid var(--border-color-primary); border-radius: 7px; background: var(--background-fill-secondary); color: var(--body-text-color-subdued); font-size: 11px; }
.clip-tag-picker[hidden], .trim-tag-picker[hidden] { display: none; }
.clip-tag-option, .trim-tag-option { border: 1px solid #60a5fa; border-radius: 999px; padding: 3px 9px; cursor: pointer; background: rgba(59,130,246,.12); color: var(--body-text-color); font-size: 11px; }
.clip-tag-option:disabled, .trim-tag-option:disabled { cursor: default; opacity: .4; }
.trim-overlay { display: none; position: fixed; inset: 0; z-index: 10000; padding: 18px; align-items: center; justify-content: center; background: rgba(0,0,0,.58); }
.trim-overlay.open { display: flex; }
.trim-panel { width: min(680px, 95vw); max-height: 90vh; overflow: auto; padding: 18px; border-radius: 12px; background: var(--block-background-fill); box-shadow: 0 20px 60px rgba(0,0,0,.35); }
.trim-title { margin: 0 0 12px; font-size: 1.15rem; font-weight: 700; overflow-wrap: anywhere; }
.trim-waveform-wrap { position: relative; width: 100%; height: 132px; margin-bottom: 8px; overflow: hidden; border: 1px solid #374151; border-radius: 8px; background: #111827; cursor: crosshair; }
.trim-waveform { display: block; width: 100%; height: 100%; }
.trim-waveform-label { position: absolute; left: 8px; bottom: 5px; pointer-events: none; color: #d1d5db; font-size: 11px; text-shadow: 0 1px 2px #000; }
.trim-panel audio { width: 100%; margin-bottom: 14px; }
.trim-metadata { display: grid; grid-template-columns: minmax(0, 1fr) 150px; gap: 10px; margin: 0 0 12px; }
.trim-filename-field, .trim-prefix-field { display: grid; gap: 5px; font-weight: 600; }
.trim-filename { width: 100%; padding: 8px; border: 1px solid var(--border-color-primary); border-radius: 6px; background: var(--input-background-fill); color: var(--body-text-color); font-weight: 400; }
.trim-filename-parts { display: flex; flex-wrap: wrap; gap: 5px; min-height: 27px; margin-top: 2px; }
.trim-filename-part { border: 1px solid #16a34a; border-radius: 999px; padding: 3px 9px; cursor: pointer; background: rgba(22,163,74,.14); color: var(--body-text-color); font-size: 11px; }
.trim-filename-part.part-disabled { border-color: #9ca3af; background: rgba(156,163,175,.12); color: var(--body-text-color-subdued); text-decoration: line-through; opacity: .7; }
.trim-filename-parts-hint { color: var(--body-text-color-subdued); font-size: 10px; font-weight: 400; }
.trim-prefix { width: 100%; padding: 8px; border: 1px solid var(--border-color-primary); border-radius: 6px; background: var(--input-background-fill); color: var(--body-text-color); font-weight: 400; }
.trim-tags-editor { margin: 0 0 12px; padding: 8px; border: 1px solid var(--border-color-primary); border-radius: 7px; }
.trim-tags-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 6px; font-weight: 600; }
.trim-control { display: grid; grid-template-columns: 70px 1fr 100px; gap: 9px; align-items: center; margin: 10px 0; }
.trim-control input[type=range] { width: 100%; }
.trim-control input[type=number] { width: 100%; padding: 6px; border: 1px solid var(--border-color-primary); border-radius: 6px; background: var(--input-background-fill); color: var(--body-text-color); }
.trim-fades { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 12px 0; }
.trim-fades label { display: grid; grid-template-columns: 1fr 100px; gap: 8px; align-items: center; }
.trim-fades input { width: 100%; padding: 6px; border: 1px solid var(--border-color-primary); border-radius: 6px; background: var(--input-background-fill); color: var(--body-text-color); }
.trim-message { min-height: 1.5em; margin: 8px 0; color: var(--body-text-color-subdued); }
.trim-actions { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 8px; }
.trim-actions button { border: 0; border-radius: 7px; padding: 7px 12px; cursor: pointer; }
.trim-preview { background: var(--button-secondary-background-fill); color: var(--button-secondary-text-color); }
.trim-cancel { background: var(--button-secondary-background-fill); color: var(--button-secondary-text-color); }
.trim-apply { background: #15803d; color: #fff; }
"""

ARRANGE_JS = """
let dragged = null;
let trimWaveformData = null;
let trimWaveformLoadId = 0;
let lastArrangeAction = null;
const splitFilenameForToggles = (filename) => {
  const value = String(filename || '');
  const extensionMatch = value.match(/(\.[^.]*)$/);
  const extension = extensionMatch ? extensionMatch[1] : '';
  let stem = extension ? value.slice(0, -extension.length) : value;
  const numberMatch = stem.match(/(_[0-9]{3,})$/);
  const numberSuffix = numberMatch ? numberMatch[1] : '';
  if (numberSuffix) stem = stem.slice(0, -numberSuffix.length);
  const parts = [];
  let current = '';
  const characters = Array.from(stem);
  const isBoundaryMark = (character) => /[。、，,.．!！?？…:：;；]/.test(character);
  const isTrailingMark = (character) => /[。、，,.．!！?？…:：;；」』）)】〕〉》]/.test(character);
  const isHeart = (character) => /[♡♥❤❣💕💗💖💓💘💝💞💟]/u.test(character);
  const isHeartContinuation = (character) => isHeart(character) || character === '\uFE0F';
  for (let index = 0; index < characters.length; index += 1) {
    current += characters[index];
    if (isBoundaryMark(characters[index])) {
      while (index + 1 < characters.length && isTrailingMark(characters[index + 1])) {
        current += characters[index + 1];
        index += 1;
      }
      while (index + 1 < characters.length && isHeartContinuation(characters[index + 1])) {
        current += characters[index + 1];
        index += 1;
      }
      while (index + 1 < characters.length && isTrailingMark(characters[index + 1])) {
        current += characters[index + 1];
        index += 1;
      }
      if (current) parts.push(current);
      current = '';
      continue;
    }
    if (isHeart(characters[index])) {
      while (index + 1 < characters.length && isHeartContinuation(characters[index + 1])) {
        current += characters[index + 1];
        index += 1;
      }
      while (index + 1 < characters.length && isTrailingMark(characters[index + 1])) {
        current += characters[index + 1];
        index += 1;
      }
      const next = characters[index + 1];
      if (next) {
        parts.push(current);
        current = '';
      }
    }
  }
  if (current) parts.push(current);
  if (!parts.length && stem) parts.push(stem);
  return {parts, suffix: `${numberSuffix}${extension}`};
};
const renderFilenameParts = (updateFilename = true) => {
  const modal = element.querySelector('.trim-overlay');
  const container = element.querySelector('.trim-filename-parts');
  if (!modal || !container) return;
  const parts = modal._filenameParts || [];
  container.replaceChildren();
  parts.forEach((part, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `trim-filename-part${part.enabled ? '' : ' part-disabled'}`;
    button.dataset.index = String(index);
    button.setAttribute('aria-pressed', part.enabled ? 'true' : 'false');
    button.title = part.enabled ? 'クリックしてファイル名から除外' : 'クリックしてファイル名へ復帰';
    button.textContent = part.text;
    container.appendChild(button);
  });
  if (updateFilename) {
    element.querySelector('.trim-filename').value =
      parts.filter((part) => part.enabled).map((part) => part.text).join('') + (modal.dataset.filenameSuffix || '');
  }
};
const initializeFilenameParts = (filename, suppliedParts = null) => {
  const modal = element.querySelector('.trim-overlay');
  const split = splitFilenameForToggles(filename);
  const parts = Array.isArray(suppliedParts) && suppliedParts.length ? suppliedParts : split.parts;
  modal._filenameParts = parts.map((text) => ({text, enabled: true}));
  modal.dataset.filenameSuffix = split.suffix;
  renderFilenameParts(false);
};
const applyRecentAction = () => {
  element.querySelectorAll('.clip-card').forEach((card) => {
    card.classList.remove('card-recent-play', 'card-recent-edit', 'card-recent-delete', 'card-recent-duplicate');
  });
  if (!lastArrangeAction) return;
  const typeZone = Array.from(element.querySelectorAll('.arrange-type')).find(
    (zone) => zone.dataset.type === lastArrangeAction.type
  );
  if (!typeZone) return;
  const cards = Array.from(typeZone.querySelectorAll('.clip-card'));
  let target = null;
  if (lastArrangeAction.action === 'delete') {
    if (cards.length) target = cards[Math.min(lastArrangeAction.index, cards.length - 1)];
  } else {
    target = cards.find((card) => card.dataset.filename === lastArrangeAction.filename);
  }
  if (target) target.classList.add(`card-recent-${lastArrangeAction.action}`);
};
const markRecentAction = (card, action, indexOffset = 0) => {
  if (!card) return;
  const zone = card.closest('.arrange-type');
  const cards = Array.from(zone.querySelectorAll('.clip-card'));
  lastArrangeAction = {
    action,
    type: card.dataset.type,
    filename: card.dataset.filename,
    index: Math.max(0, cards.indexOf(card) + indexOffset)
  };
  applyRecentAction();
};
const synchronizePrefixSelects = () => {
  const currentElement = document.querySelector('#arrange-board-component') || element;
  currentElement.querySelectorAll('.clip-prefix-select').forEach((select) => {
    const expected = select.dataset.prefix || 'Common';
    select.value = expected;
    select.disabled = false;
    delete select.dataset.submittedPrefix;
    const marker = select.closest('.clip-card')?.querySelector('.clip-prefix-mark');
    if (marker) {
      marker.className = `clip-prefix-mark prefix-${expected.toLowerCase()}`;
      marker.title = expected;
    }
  });
};
let prefixSynchronizationFrame = 0;
const schedulePrefixSynchronization = () => {
  if (prefixSynchronizationFrame) window.cancelAnimationFrame(prefixSynchronizationFrame);
  prefixSynchronizationFrame = window.requestAnimationFrame(() => {
    prefixSynchronizationFrame = window.requestAnimationFrame(() => {
      prefixSynchronizationFrame = 0;
      synchronizePrefixSelects();
    });
  });
};
const predictedDuplicateName = (card) => {
  const filename = card.dataset.filename;
  const extensionAt = filename.lastIndexOf('.');
  const extension = extensionAt >= 0 ? filename.slice(extensionAt) : '';
  let stem = extensionAt >= 0 ? filename.slice(0, extensionAt) : filename;
  const leadingTags = stem.match(/^(?:\[[^\[\]]+\])+/)?.[0] || '';
  if (leadingTags) stem = stem.slice(leadingTags.length);
  const trailingTags = stem.match(/(?:\[[^\[\]]+\])+$/)?.[0] || '';
  if (trailingTags) stem = stem.slice(0, -trailingTags.length);
  const tagHeader = `${leadingTags}${trailingTags}`;
  const match = stem.match(/^(.*)_([0-9]{3,})$/);
  const base = match ? match[1] : stem;
  const existing = new Set(
    Array.from(card.closest('.arrange-type').querySelectorAll('.clip-card')).map((item) => item.dataset.filename)
  );
  let index = 0;
  while (true) {
    const candidate = `${tagHeader}${base}_${String(index).padStart(3, '0')}${extension}`;
    if (!existing.has(candidate)) return candidate;
    index += 1;
  }
};
const readAdditionalTags = (value) => String(value || '').split('/').map((tag) => tag.trim()).filter(Boolean);
const renderTrimTags = () => {
  const modal = element.querySelector('.trim-overlay');
  if (!modal) return;
  const tags = readAdditionalTags(modal.dataset.tags);
  const chips = modal.querySelector('.trim-tag-chips');
  chips.replaceChildren();
  if (!tags.length) {
    const empty = document.createElement('span');
    empty.className = 'clip-tag-empty';
    empty.textContent = '追加タグなし';
    chips.appendChild(empty);
  }
  tags.forEach((tag) => {
    const chip = document.createElement('span');
    chip.className = 'trim-tag-chip';
    const label = document.createElement('span');
    label.textContent = tag;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'trim-tag-remove';
    remove.dataset.tag = tag;
    remove.title = `${tag} を削除`;
    remove.setAttribute('aria-label', `${tag} を削除`);
    remove.textContent = '×';
    chip.append(label, remove);
    chips.appendChild(chip);
  });
  modal.querySelectorAll('.trim-tag-option').forEach((button) => {
    button.disabled = tags.some((tag) => tag.toLowerCase() === button.dataset.tag.toLowerCase());
  });
};
const drawTrimWaveform = () => {
  const canvas = element.querySelector('.trim-waveform');
  if (!canvas) return;
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(1, Math.floor(canvas.clientWidth * ratio));
  const height = Math.max(1, Math.floor(canvas.clientHeight * ratio));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  const context = canvas.getContext('2d');
  context.clearRect(0, 0, width, height);
  context.fillStyle = '#111827';
  context.fillRect(0, 0, width, height);
  if (!trimWaveformData || !trimWaveformData.samples.length) return;
  const samples = trimWaveformData.samples;
  const center = height / 2;
  const samplesPerPixel = Math.max(1, Math.floor(samples.length / width));
  context.strokeStyle = '#60a5fa';
  context.lineWidth = Math.max(1, ratio);
  context.beginPath();
  for (let x = 0; x < width; x++) {
    const from = x * samplesPerPixel;
    const to = Math.min(samples.length, from + samplesPerPixel);
    let minimum = 1;
    let maximum = -1;
    for (let index = from; index < to; index++) {
      const value = samples[index];
      if (value < minimum) minimum = value;
      if (value > maximum) maximum = value;
    }
    context.moveTo(x, center - maximum * center * 0.9);
    context.lineTo(x, center - minimum * center * 0.9);
  }
  context.stroke();

  const duration = trimWaveformData.duration || 1;
  const start = Number(element.querySelector('.trim-start-number').value || 0);
  const end = Number(element.querySelector('.trim-end-number').value || duration);
  const fadeIn = Number(element.querySelector('.trim-fade-in').value || 0);
  const fadeOut = Number(element.querySelector('.trim-fade-out').value || 0);
  const startX = Math.max(0, Math.min(width, start / duration * width));
  const endX = Math.max(0, Math.min(width, end / duration * width));
  context.fillStyle = 'rgba(0, 0, 0, .62)';
  context.fillRect(0, 0, startX, height);
  context.fillRect(endX, 0, width - endX, height);
  context.strokeStyle = '#fbbf24';
  context.lineWidth = Math.max(1, 2 * ratio);
  context.strokeRect(startX, 1, Math.max(1, endX - startX), height - 2);

  const audio = element.querySelector('.trim-audio');
  const playheadX = Math.max(0, Math.min(width, (audio.currentTime || 0) / duration * width));
  context.strokeStyle = '#f43f5e';
  context.lineWidth = Math.max(1, 2 * ratio);
  context.beginPath();
  context.moveTo(playheadX, 0);
  context.lineTo(playheadX, height);
  context.stroke();

  context.save();
  context.setLineDash([5 * ratio, 4 * ratio]);
  context.strokeStyle = '#22d3ee';
  context.lineWidth = Math.max(1, ratio);
  for (const seconds of [start + fadeIn, end - fadeOut]) {
    if (seconds > start && seconds < end) {
      const x = seconds / duration * width;
      context.beginPath();
      context.moveTo(x, 0);
      context.lineTo(x, height);
      context.stroke();
    }
  }
  context.restore();
};
const loadTrimWaveform = async (url, loadId) => {
  trimWaveformData = null;
  drawTrimWaveform();
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const bytes = await response.arrayBuffer();
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    const audioContext = new AudioContextClass();
    const decoded = await audioContext.decodeAudioData(bytes);
    if (loadId !== trimWaveformLoadId) {
      await audioContext.close();
      return;
    }
    const source = decoded.getChannelData(0);
    trimWaveformData = {samples: new Float32Array(source), duration: decoded.duration};
    await audioContext.close();
    drawTrimWaveform();
  } catch (error) {
    if (loadId === trimWaveformLoadId) {
      element.querySelector('.trim-message').textContent = `波形を読み込めませんでした: ${error.message}`;
    }
  }
};
element.addEventListener('dragstart', (event) => {
  if (event.target.closest('.clip-prefix-select, .clip-tags-area')) {
    event.preventDefault();
    return;
  }
  const card = event.target.closest('.clip-card');
  if (!card) return;
  dragged = { source_type: card.dataset.type, filename: card.dataset.filename };
  event.dataTransfer.effectAllowed = 'move';
  event.dataTransfer.setData('text/plain', card.dataset.filename);
});
element.addEventListener('dragover', (event) => {
  const zone = event.target.closest('.arrange-type');
  if (!zone || !dragged) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = 'move';
  zone.classList.add('drag-over');
});
element.addEventListener('dragleave', (event) => {
  const zone = event.target.closest('.arrange-type');
  if (zone && !zone.contains(event.relatedTarget)) zone.classList.remove('drag-over');
});
element.addEventListener('drop', (event) => {
  const zone = event.target.closest('.arrange-type');
  if (!zone || !dragged) return;
  event.preventDefault();
  element.querySelectorAll('.drag-over').forEach((item) => item.classList.remove('drag-over'));
  trigger('click', {
    action: 'move',
    source_type: dragged.source_type,
    target_type: zone.dataset.type,
    filename: dragged.filename
  });
  dragged = null;
});
element.addEventListener('dragend', () => {
  element.querySelectorAll('.drag-over').forEach((item) => item.classList.remove('drag-over'));
  dragged = null;
});
element.addEventListener('input', (event) => {
  const select = event.target.closest('.clip-prefix-select');
  if (!select) return;
  if (select.dataset.submittedPrefix === select.value) return;
  select.dataset.submittedPrefix = select.value;
  const card = select.closest('.clip-card');
  const marker = card.querySelector('.clip-prefix-mark');
  if (marker) {
    marker.className = `clip-prefix-mark prefix-${select.value.toLowerCase()}`;
    marker.title = select.value;
  }
  select.disabled = true;
  trigger('click', {
    action: 'set_prefix',
    source_type: card.dataset.type,
    filename: card.dataset.filename,
    prefix: select.value
  });
});
element.addEventListener('click', (event) => {
  const filenamePart = event.target.closest('.trim-filename-part');
  if (filenamePart) {
    event.preventDefault();
    const modal = element.querySelector('.trim-overlay');
    const part = modal._filenameParts?.[Number(filenamePart.dataset.index)];
    if (!part) return;
    if (part.enabled && modal._filenameParts.filter((item) => item.enabled).length === 1) {
      element.querySelector('.trim-message').textContent = 'ファイル名には少なくとも1つのテキスト部分が必要です。';
      return;
    }
    part.enabled = !part.enabled;
    renderFilenameParts(true);
    return;
  }
  const cardTagAdd = event.target.closest('.clip-tag-add');
  if (cardTagAdd) {
    event.preventDefault();
    const picker = cardTagAdd.closest('.clip-tags-area').querySelector('.clip-tag-picker');
    picker.hidden = !picker.hidden;
    return;
  }
  const cardTagOption = event.target.closest('.clip-tag-option');
  if (cardTagOption) {
    event.preventDefault();
    if (cardTagOption.disabled) return;
    const card = cardTagOption.closest('.clip-card');
    const tags = readAdditionalTags(card.dataset.tags);
    if (!tags.some((tag) => tag.toLowerCase() === cardTagOption.dataset.tag.toLowerCase())) {
      tags.push(cardTagOption.dataset.tag);
    }
    trigger('click', {action: 'set_tags', source_type: card.dataset.type, filename: card.dataset.filename, tags: tags.join('/')});
    return;
  }
  const cardTagRemove = event.target.closest('.clip-tag-remove');
  if (cardTagRemove) {
    event.preventDefault();
    const card = cardTagRemove.closest('.clip-card');
    const tags = readAdditionalTags(card.dataset.tags).filter(
      (tag) => tag.toLowerCase() !== cardTagRemove.dataset.tag.toLowerCase()
    );
    trigger('click', {action: 'set_tags', source_type: card.dataset.type, filename: card.dataset.filename, tags: tags.join('/')});
    return;
  }
  const trimTagAdd = event.target.closest('.trim-tag-add');
  if (trimTagAdd) {
    event.preventDefault();
    const picker = trimTagAdd.closest('.trim-tags-editor').querySelector('.trim-tag-picker');
    picker.hidden = !picker.hidden;
    return;
  }
  const trimTagOption = event.target.closest('.trim-tag-option');
  if (trimTagOption) {
    event.preventDefault();
    if (trimTagOption.disabled) return;
    const modal = element.querySelector('.trim-overlay');
    const tags = readAdditionalTags(modal.dataset.tags);
    tags.push(trimTagOption.dataset.tag);
    modal.dataset.tags = tags.join('/');
    renderTrimTags();
    return;
  }
  const trimTagRemove = event.target.closest('.trim-tag-remove');
  if (trimTagRemove) {
    event.preventDefault();
    const modal = element.querySelector('.trim-overlay');
    modal.dataset.tags = readAdditionalTags(modal.dataset.tags).filter(
      (tag) => tag.toLowerCase() !== trimTagRemove.dataset.tag.toLowerCase()
    ).join('/');
    renderTrimTags();
    return;
  }
  const renumberButton = event.target.closest('.arrange-renumber');
  if (renumberButton) {
    event.preventDefault();
    const count = element.querySelectorAll('.clip-card').length;
    if (!count) return;
    if (!window.confirm(`選択中ボイスセットの全タイプを対象に、${count}クリップの連番を振り直しますか？`)) return;
    lastArrangeAction = null;
    trigger('click', {action: 'renumber_all'});
    return;
  }
  const deleteAllButton = event.target.closest('.arrange-delete-all');
  if (deleteAllButton) {
    event.preventDefault();
    const count = element.querySelectorAll('.clip-card').length;
    if (!count) return;
    if (!window.confirm(`選択中ボイスセットの全 ${count} クリップを削除しますか？`)) return;
    lastArrangeAction = null;
    trigger('click', {action: 'delete_all'});
    return;
  }
  const deleteTypeButton = event.target.closest('.arrange-type-delete');
  if (deleteTypeButton) {
    event.preventDefault();
    const zone = deleteTypeButton.closest('.arrange-type');
    const count = zone.querySelectorAll('.clip-card').length;
    if (!count) return;
    if (!window.confirm(`${deleteTypeButton.dataset.type} の全 ${count} クリップを削除しますか？`)) return;
    lastArrangeAction = null;
    trigger('click', {action: 'delete_type', source_type: deleteTypeButton.dataset.type});
    return;
  }
  const editButton = event.target.closest('.clip-edit');
  if (editButton) {
    event.preventDefault();
    const modal = element.querySelector('.trim-overlay');
    const audio = element.querySelector('.trim-audio');
    const card = editButton.closest('.clip-card');
    markRecentAction(card, 'edit');
    trimWaveformLoadId += 1;
    const loadId = trimWaveformLoadId;
    trimWaveformData = null;
    delete element.dataset.trimPreviewEnd;
    audio.pause();
    audio.currentTime = 0;
    element.querySelector('.trim-start-range').max = '1';
    element.querySelector('.trim-end-range').max = '1';
    element.querySelector('.trim-start-range').value = '0';
    element.querySelector('.trim-start-number').value = '0';
    element.querySelector('.trim-end-range').value = '1';
    element.querySelector('.trim-end-number').value = '1';
    element.querySelector('.trim-fade-in').value = '0';
    element.querySelector('.trim-fade-out').value = '0';
    modal.dataset.type = editButton.dataset.type;
    modal.dataset.filename = editButton.dataset.filename;
    modal.dataset.tags = editButton.dataset.tags || '';
    const currentPrefix = editButton.dataset.prefix || 'Common';
    element.querySelector('.trim-title').textContent = `トリミング: ${editButton.dataset.displayName}`;
    element.querySelector('.trim-filename').value = editButton.dataset.displayName;
    let suppliedFilenameParts = null;
    try { suppliedFilenameParts = JSON.parse(editButton.dataset.filenameParts || 'null'); } catch (_) {}
    initializeFilenameParts(editButton.dataset.displayName, suppliedFilenameParts);
    element.querySelector('.trim-prefix').value = currentPrefix;
    element.querySelector('.trim-tag-picker').hidden = true;
    renderTrimTags();
    element.querySelector('.trim-message').textContent = '音声情報を読み込んでいます…';
    audio.src = editButton.dataset.audioUrl;
    audio.load();
    modal.classList.add('open');
    window.requestAnimationFrame(() => {
      drawTrimWaveform();
      loadTrimWaveform(audio.src, loadId);
    });
    return;
  }
  const cancelButton = event.target.closest('.trim-cancel');
  if (cancelButton || (event.target.classList && event.target.classList.contains('trim-overlay'))) {
    const modal = element.querySelector('.trim-overlay');
    const audio = element.querySelector('.trim-audio');
    audio.pause();
    modal.classList.remove('open');
    trimWaveformLoadId += 1;
    trimWaveformData = null;
    return;
  }
  const previewButton = event.target.closest('.trim-preview');
  if (previewButton) {
    const audio = element.querySelector('.trim-audio');
    const start = Number(element.querySelector('.trim-start-number').value);
    const end = Number(element.querySelector('.trim-end-number').value);
    if (!(end > start)) {
      element.querySelector('.trim-message').textContent = '終了位置は開始位置より後にしてください。';
      return;
    }
    element.dataset.trimPreviewEnd = String(end);
    audio.currentTime = start;
    audio.play();
    return;
  }
  const applyButton = event.target.closest('.trim-apply');
  if (applyButton) {
    const modal = element.querySelector('.trim-overlay');
    const start = Number(element.querySelector('.trim-start-number').value);
    const end = Number(element.querySelector('.trim-end-number').value);
    const fadeIn = Number(element.querySelector('.trim-fade-in').value);
    const fadeOut = Number(element.querySelector('.trim-fade-out').value);
    const newPrefix = element.querySelector('.trim-prefix').value;
    let newFilename = element.querySelector('.trim-filename').value.trim();
    if (!newFilename) {
      element.querySelector('.trim-message').textContent = 'ファイル名を入力してください。';
      return;
    }
    if (!newFilename.includes('.')) newFilename += '.wav';
    const sourceFilename = modal.dataset.filename;
    const prefixText = `[${newPrefix}]`;
    const additionalTags = readAdditionalTags(modal.dataset.tags);
    const tagHeader = additionalTags.map((tag) => `[${tag}]`).join('');
    const requestedFullName = `${prefixText}${tagHeader}${newFilename}`;
    const typeZone = Array.from(element.querySelectorAll('.arrange-type')).find(
      (zone) => zone.dataset.type === modal.dataset.type
    );
    const existingNames = new Set(
      Array.from(typeZone?.querySelectorAll('.clip-card') || []).map((card) => card.dataset.filename)
    );
    if (requestedFullName !== sourceFilename && existingNames.has(requestedFullName)) {
      const extensionAt = newFilename.lastIndexOf('.');
      const extension = extensionAt >= 0 ? newFilename.slice(extensionAt) : '.wav';
      let base = extensionAt >= 0 ? newFilename.slice(0, extensionAt) : newFilename;
      while (/_[0-9]{3,}$/.test(base)) base = base.replace(/_[0-9]{3,}$/, '');
      base = base || 'clip';
      let index = 0;
      let suggestion = '';
      do {
        suggestion = `${base}_${String(index).padStart(3, '0')}${extension}`;
        index += 1;
      } while (existingNames.has(`${prefixText}${tagHeader}${suggestion}`));
      element.querySelector('.trim-filename').value = suggestion;
      initializeFilenameParts(suggestion);
      element.querySelector('.trim-message').textContent =
        `同名のクリップが存在します。推奨ファイル名「${suggestion}」を入力しました。確認後、もう一度「適用」を押してください。`;
      return;
    }
    if (!(start >= 0 && end > start && fadeIn >= 0 && fadeOut >= 0)) {
      element.querySelector('.trim-message').textContent = '有効な開始・終了位置を指定してください。';
      return;
    }
    element.querySelector('.trim-audio').pause();
    element.querySelector('.trim-message').textContent = 'トリミングを適用しています…';
    trigger('click', {
      action: 'trim',
      source_type: modal.dataset.type,
      filename: modal.dataset.filename,
      new_filename: newFilename,
      new_prefix: newPrefix,
      new_tags: additionalTags.join('/'),
      start_seconds: start,
      end_seconds: end,
      fade_in_seconds: fadeIn,
      fade_out_seconds: fadeOut
    });
    return;
  }
  const button = event.target.closest('.clip-delete');
  if (!button) return;
  event.preventDefault();
  const skipConfirm = document.querySelector('#arrange-skip-delete-confirm input[type="checkbox"]')?.checked;
  if (!skipConfirm && !window.confirm(`「${button.dataset.filename}」を削除しますか？`)) return;
  markRecentAction(button.closest('.clip-card'), 'delete');
  trigger('click', {
    action: 'delete',
    source_type: button.dataset.type,
    filename: button.dataset.filename
  });
});
element.addEventListener('click', (event) => {
  const button = event.target.closest('.clip-duplicate');
  if (!button) return;
  event.preventDefault();
  const card = button.closest('.clip-card');
  lastArrangeAction = {
    action: 'duplicate',
    type: card.dataset.type,
    filename: predictedDuplicateName(card),
    index: 0
  };
  applyRecentAction();
  trigger('click', {
    action: 'duplicate',
    source_type: button.dataset.type,
    filename: button.dataset.filename
  });
});
element.addEventListener('play', (event) => {
  const card = event.target.closest('.clip-card');
  if (card) markRecentAction(card, 'play');
}, true);
element.addEventListener('loadedmetadata', (event) => {
  if (!event.target.classList.contains('trim-audio')) return;
  const duration = Number(event.target.duration || 0);
  const startRange = element.querySelector('.trim-start-range');
  const endRange = element.querySelector('.trim-end-range');
  const startNumber = element.querySelector('.trim-start-number');
  const endNumber = element.querySelector('.trim-end-number');
  [startRange, endRange].forEach((input) => input.max = String(duration));
  startRange.value = '0';
  startNumber.value = '0';
  endRange.value = String(duration);
  endNumber.value = duration.toFixed(3);
  element.querySelector('.trim-message').textContent = `長さ: ${duration.toFixed(3)} 秒`;
}, true);
element.addEventListener('timeupdate', (event) => {
  if (!event.target.classList.contains('trim-audio')) return;
  drawTrimWaveform();
  const previewEnd = Number(element.dataset.trimPreviewEnd || 'NaN');
  if (Number.isFinite(previewEnd) && event.target.currentTime >= previewEnd) {
    event.target.pause();
    delete element.dataset.trimPreviewEnd;
  }
}, true);
element.addEventListener('input', (event) => {
  if (event.target.classList.contains('trim-filename')) {
    initializeFilenameParts(event.target.value);
    return;
  }
  if (event.target.classList.contains('trim-start-range')) {
    element.querySelector('.trim-start-number').value = Number(event.target.value).toFixed(3);
  } else if (event.target.classList.contains('trim-end-range')) {
    element.querySelector('.trim-end-number').value = Number(event.target.value).toFixed(3);
  } else if (event.target.classList.contains('trim-start-number')) {
    element.querySelector('.trim-start-range').value = event.target.value;
  } else if (event.target.classList.contains('trim-end-number')) {
    element.querySelector('.trim-end-range').value = event.target.value;
  }
  if (event.target.matches('.trim-start-range, .trim-end-range, .trim-start-number, .trim-end-number, .trim-fade-in, .trim-fade-out')) {
    drawTrimWaveform();
  }
});
element.addEventListener('click', (event) => {
  const canvas = event.target.closest('.trim-waveform');
  if (!canvas || !trimWaveformData) return;
  const bounds = canvas.getBoundingClientRect();
  const position = Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width));
  const audio = element.querySelector('.trim-audio');
  audio.currentTime = position * trimWaveformData.duration;
  drawTrimWaveform();
});
window.addEventListener('resize', drawTrimWaveform);
synchronizePrefixSelects();
if (window.__irodoriPrefixSelectObserver) window.__irodoriPrefixSelectObserver.disconnect();
window.__irodoriPrefixSelectObserver = new MutationObserver(() => {
  synchronizePrefixSelects();
  schedulePrefixSynchronization();
  applyRecentAction();
});
window.__irodoriPrefixSelectObserver.observe(document.body, {childList: true, subtree: true});
"""

GENERATION_START_JS = """(...inputs) => {
  const button = document.querySelector('button.arrange-tab-shortcut');
  if (button) {
    button.disabled = true;
    button.classList.remove('shortcut-ready');
    button.classList.add('shortcut-running');
  }
  return inputs;
}"""

GENERATION_FINISH_JS = """(status) => {
  const button = document.querySelector('button.arrange-tab-shortcut');
  if (!button) return;
  button.disabled = false;
  button.classList.remove('shortcut-running');
  button.classList.toggle('shortcut-ready', String(status || '').trim().startsWith('✅'));
}"""

ARRANGE_REFRESH_START_JS = """(...inputs) => {
  const board = document.querySelector('#arrange-board-component');
  if (board) {
    board.classList.add('arrange-refreshing');
    board.setAttribute('aria-busy', 'true');
  }
  return inputs;
}"""

ARRANGE_REFRESH_FINISH_JS = """() => {
  const board = document.querySelector('#arrange-board-component');
  if (board) {
    board.classList.remove('arrange-refreshing');
    board.removeAttribute('aria-busy');
  }
}"""


def check_server(server_url: str) -> str:
    try:
        client = IrodoriServerClient(server_url)
        health = client.health()
        voices = client._get_json("/voices").get("voices", [])
        voice_count = len(voices) if isinstance(voices, list) else health.get("voices", "?")
        loaded = "読込済み" if health.get("runtime_loaded") else "未読込"
        return f"✅ 接続成功 — voices: {voice_count} / runtime: {loaded}"
    except BuilderError as exc:
        return f"❌ {exc}"


def parse_steps(value: object) -> int:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise BuilderError("ステップ数を1～120の整数で指定してください。") from exc
    steps = int(numeric)
    if numeric != steps or not 1 <= steps <= 120:
        raise BuilderError("ステップ数を1～120の整数で指定してください。")
    return steps


def run_generation(
    server_url: str,
    voice_id: str,
    num_steps: object,
    *type_values: object,
    progress: gr.Progress = gr.Progress(track_tqdm=False),
) -> tuple[str, str, list[str], object]:
    try:
        steps = parse_steps(num_steps)
        enabled = type_values[0::4]
        texts = tuple(str(value or "") for value in type_values[1::4])
        captions = tuple(str(value or "") for value in type_values[2::4])
        counts = type_values[3::4]
        groups = make_groups(texts, captions, counts, enabled)
        total = sum(group.clip_count for group in groups)

        def report(done: int, all_clips: int, label: str) -> None:
            ratio = done / all_clips if all_clips else 0
            progress(ratio, desc=f"{done}/{all_clips} {label}")

        result = generate_voice_set(
            client=IrodoriServerClient(server_url),
            output_root=OUTPUT_DIRECTORY,
            voice_id=voice_id,
            num_steps=steps,
            groups=groups,
            progress=report,
        )
        status = f"✅ {total}クリップを生成しました。出力先: {result.files[0].parents[1]}"
        voice_set = result.files[0].parents[1].name
        selection_event = {"voice_set": voice_set, "generation_id": uuid4().hex}
        return status, "\n".join(result.log_lines), [str(path) for path in result.files], selection_event
    except (BuilderError, ValueError) as exc:
        return f"❌ {exc}", str(exc), [], gr.skip()
    except Exception as exc:  # Keep unexpected failures visible without killing Gradio.
        return f"❌ 予期しないエラー: {exc}", repr(exc), [], gr.skip()


def run_type_generation(
    voice_type: str,
    server_url: str,
    voice_id: str,
    num_steps: object,
    text_value: str,
    caption_value: str,
    count_value: object,
    progress: gr.Progress = gr.Progress(track_tqdm=False),
) -> tuple[str, str, list[str], object]:
    try:
        steps = parse_steps(num_steps)
        count = parse_count(count_value, voice_type)
        texts = split_texts(str(text_value or ""))
        if not texts or not count:
            raise BuilderError(f"{voice_type} のテキストと、1以上の出力数を指定してください。")
        group = GenerationGroup(
            voice_type=voice_type,
            texts=texts,
            count=count,
            caption=str(caption_value or "").strip() or None,
        )
        total = group.clip_count

        def report(done: int, all_clips: int, label: str) -> None:
            progress(done / all_clips if all_clips else 0, desc=f"{done}/{all_clips} {label}")

        result = generate_voice_set(
            client=IrodoriServerClient(server_url),
            output_root=OUTPUT_DIRECTORY,
            voice_id=voice_id,
            num_steps=steps,
            groups=(group,),
            progress=report,
        )
        status = f"✅ {voice_type}: {total}クリップを生成しました。"
        voice_set = result.files[0].parents[1].name
        selection_event = {"voice_set": voice_set, "generation_id": uuid4().hex}
        return status, "\n".join(result.log_lines), [str(path) for path in result.files], selection_event
    except (BuilderError, ValueError) as exc:
        return f"❌ {exc}", str(exc), [], gr.skip()
    except Exception as exc:
        return f"❌ 予期しないエラー: {exc}", repr(exc), [], gr.skip()


def _remove_previous_sample(path_value: object) -> None:
    if not path_value:
        return
    try:
        path = Path(str(path_value)).resolve()
        if path.parent == SAMPLE_DIRECTORY and path.is_file():
            path.unlink()
    except OSError:
        pass


def run_sample_generation(
    voice_type: str,
    server_url: str,
    voice_id: str,
    num_steps: object,
    text_value: str,
    caption_value: str,
    sample_state: dict[str, object] | None,
) -> tuple[str | None, str, dict[str, object]]:
    state = sample_state if isinstance(sample_state, dict) else {}
    try:
        steps = parse_steps(num_steps)
        candidates = split_texts(str(text_value or ""))
        current_index = int(state.get("index", 0) or 0)
        result = generate_sample_clip(
            client=IrodoriServerClient(server_url),
            sample_root=SAMPLE_DIRECTORY,
            voice_id=voice_id,
            voice_type=voice_type,
            text_value=str(text_value or ""),
            caption=str(caption_value or ""),
            num_steps=steps,
            index=current_index,
        )
        _remove_previous_sample(state.get("path"))
        selected_position = current_index % len(candidates) + 1
        next_state = {"index": result.next_index, "path": str(result.path)}
        status = (
            f"✅ Sample {voice_type} [{selected_position}/{len(candidates)}]: "
            f"{result.text}（一時生成・未保存）"
        )
        return str(result.path), status, next_state
    except (BuilderError, TypeError, ValueError) as exc:
        return None, f"❌ {exc}", state
    except Exception as exc:
        return None, f"❌ 予期しないエラー: {exc}", state


def reset_sample_sequence(sample_state: dict[str, object] | None) -> dict[str, object]:
    state = sample_state if isinstance(sample_state, dict) else {}
    return {"index": 0, "path": state.get("path", "")}


def persist_inputs(server_url: str, voice_id: str, num_steps: object, *type_values: object) -> None:
    try:
        steps = int(float(num_steps))
    except (TypeError, ValueError):
        steps = DEFAULT_STEPS
    type_settings: dict[str, object] = {}
    for index, voice_type in enumerate(VOICE_TYPES):
        offset = index * 4
        type_settings[voice_type] = {
            "enabled": bool(type_values[offset]),
            "text": str(type_values[offset + 1] or ""),
            "caption": str(type_values[offset + 2] or ""),
            "count": type_values[offset + 3],
        }
    with SETTINGS_LOCK:
        settings = load_settings(SETTINGS_PATH)
        settings["server_url"] = str(server_url or "")
        settings["voice_id"] = str(voice_id or "")
        settings["num_steps"] = steps
        settings["types"] = type_settings
        save_settings(SETTINGS_PATH, settings)


def persist_arrange_skip_delete_confirm(value: bool) -> None:
    with SETTINGS_LOCK:
        settings = load_settings(SETTINGS_PATH)
        settings["arrange_skip_delete_confirm"] = bool(value)
        save_settings(SETTINGS_PATH, settings)


def persist_arrange_available_tags(value: str, voice_set: str | None) -> tuple[str, str]:
    try:
        normalized = "/".join(normalize_available_tags(value))
    except ArrangeError as exc:
        return render_arrange_board(voice_set), f"❌ 追加タグ設定: {exc}"
    with SETTINGS_LOCK:
        settings = load_settings(SETTINGS_PATH)
        settings["arrange_available_tags"] = normalized
        save_settings(SETTINGS_PATH, settings)
    return render_arrange_board(voice_set), "✅ 利用可能な追加タグを保存しました。"


def _arrange_available_tags() -> tuple[str, ...]:
    try:
        return normalize_available_tags(load_settings(SETTINGS_PATH)["arrange_available_tags"])
    except (ArrangeError, KeyError, TypeError):
        return ()


def _render_clip_tags(tags: tuple[str, ...], available_tags: tuple[str, ...]) -> str:
    chips = "".join(
        '<span class="clip-tag-chip">'
        f'<span>{escape(tag)}</span><button class="clip-tag-remove" type="button" '
        f'data-tag="{escape(tag, quote=True)}" title="{escape(tag, quote=True)} を削除" '
        f'aria-label="{escape(tag, quote=True)} を削除">×</button></span>'
        for tag in tags
    )
    options = "".join(
        f'<button class="clip-tag-option" type="button" data-tag="{escape(tag, quote=True)}"'
        + (" disabled" if tag.casefold() in {item.casefold() for item in tags} else "")
        + f'>{escape(tag)}</button>'
        for tag in available_tags
    )
    if not chips:
        chips = '<span class="clip-tag-empty">追加タグなし</span>'
    if not options:
        options = "利用可能な追加タグが未設定です。"
    return (
        '<div class="clip-tags-area"><div class="clip-tags-heading"><span>追加タグ</span>'
        '<button class="clip-tag-add" type="button">＋ 追加タグ</button></div>'
        f'<div class="clip-tag-list">{chips}</div>'
        f'<div class="clip-tag-picker" hidden>{options}</div></div>'
    )


def split_filename_toggle_parts(filename: str) -> tuple[str, ...]:
    path = Path(str(filename or ""))
    stem = path.stem
    number_match = re.search(r"_[0-9]{3,}$", stem)
    if number_match:
        stem = stem[: number_match.start()]
    parts: list[str] = []
    current: list[str] = []
    characters = list(stem)
    boundary_marks = set("。、，,.．!！?？…:：;；")
    trailing_marks = boundary_marks | set("」』）)】〕〉》")
    hearts = set("♡♥❤❣💕💗💖💓💘💝💞💟")
    heart_continuations = hearts | {"\ufe0f"}
    index = 0
    while index < len(characters):
        character = characters[index]
        current.append(character)
        if character in boundary_marks:
            while index + 1 < len(characters) and characters[index + 1] in trailing_marks:
                index += 1
                current.append(characters[index])
            while index + 1 < len(characters) and characters[index + 1] in heart_continuations:
                index += 1
                current.append(characters[index])
            while index + 1 < len(characters) and characters[index + 1] in trailing_marks:
                index += 1
                current.append(characters[index])
            parts.append("".join(current))
            current = []
        elif character in hearts:
            while index + 1 < len(characters) and characters[index + 1] in heart_continuations:
                index += 1
                current.append(characters[index])
            while index + 1 < len(characters) and characters[index + 1] in trailing_marks:
                index += 1
                current.append(characters[index])
            next_character = characters[index + 1] if index + 1 < len(characters) else ""
            if next_character:
                parts.append("".join(current))
                current = []
        index += 1
    if current:
        parts.append("".join(current))
    return tuple(part for part in parts if part) or ((stem,) if stem else ())


def render_arrange_board(voice_set: str | None) -> str:
    if not voice_set:
        return '<div class="arrange-empty">ボイスセットを選択してください。</div>'
    try:
        clips_by_type = list_clips(OUTPUT_DIRECTORY, voice_set)
    except ArrangeError as exc:
        return f'<div class="arrange-empty">{escape(str(exc))}</div>'

    available_tags = _arrange_available_tags()
    total_clips = sum(len(clips) for clips in clips_by_type.values())
    render_token = uuid4().hex
    columns: list[str] = [
        '<div class="arrange-bulk-tools">'
        f'<button class="arrange-renumber" data-count="{total_clips}"'
        + (" disabled" if not total_clips else "")
        + '>連番を振り直す</button>'
        f'<button class="arrange-delete-all" data-count="{total_clips}"'
        + (" disabled" if not total_clips else "")
        + '>全タイプを一括削除</button></div><div class="arrange-board">'
    ]
    for voice_type in VOICE_TYPES:
        clips = clips_by_type[voice_type]
        columns.append(
            f'<section class="arrange-type" data-type="{escape(voice_type, quote=True)}">'
            f'<div class="arrange-type-title"><span>{escape(voice_type)}</span>'
            f'<span class="arrange-count">{len(clips)} clips</span>'
            f'<button class="arrange-type-delete" data-type="{escape(voice_type, quote=True)}"'
            + (" disabled" if not clips else "")
            + '>全削除</button></div>'
        )
        if not clips:
            columns.append('<div class="arrange-empty">ここへドロップ</div>')
        for clip in clips:
            filename_attr = escape(clip.name, quote=True)
            prefix, tagged_display_name = split_clip_prefix(clip.name)
            display_name, additional_tags = split_clip_tags(tagged_display_name)
            tags_attr = escape("/".join(additional_tags), quote=True)
            filename_parts_attr = escape(
                json.dumps(split_filename_toggle_parts(display_name), ensure_ascii=False),
                quote=True,
            )
            selected_prefix = prefix or DEFAULT_CLIP_PREFIX
            prefix_class = selected_prefix.casefold()
            prefix_options = "".join(
                f'<option value="{escape(item, quote=True)}"'
                + (" selected" if item == selected_prefix else "")
                + f'>{escape(item)}</option>'
                for item in CLIP_PREFIXES
            )
            file_info = clip.stat()
            cache_version = f"{file_info.st_mtime_ns}-{file_info.st_size}"
            audio_url = (
                "/gradio_api/file="
                + quote(clip.as_posix(), safe="/:")
                + f"?v={cache_version}"
            )
            columns.append(
                f'<article class="clip-card" draggable="true" data-type="{escape(voice_type, quote=True)}" '
                f'data-filename="{filename_attr}" data-tags="{tags_attr}">'
                '<div class="clip-prefix-row">'
                f'<span class="clip-prefix-mark prefix-{prefix_class}" title="{escape(selected_prefix, quote=True)}"></span>'
                f'<select class="clip-prefix-select" data-prefix="{escape(selected_prefix, quote=True)}" '
                f'name="prefix-{render_token}-{escape(clip.name, quote=True)}" autocomplete="off" '
                f'aria-label="{escape(display_name, quote=True)} のプレフィックス">{prefix_options}</select>'
                '</div>'
                '<div class="clip-header">'
                '<span class="clip-handle" title="別タイプへドラッグ">⠿</span>'
                f'<span class="clip-name">{escape(display_name)}</span>'
                f'<button class="clip-edit" data-type="{escape(voice_type, quote=True)}" '
                f'data-filename="{filename_attr}" data-display-name="{escape(display_name, quote=True)}" '
                f'data-prefix="{escape(selected_prefix, quote=True)}" '
                f'data-tags="{tags_attr}" '
                f'data-filename-parts="{filename_parts_attr}" '
                f'data-audio-url="{escape(audio_url, quote=True)}" '
                'title="トリミング">編集</button>'
                f'<button class="clip-duplicate" data-type="{escape(voice_type, quote=True)}" '
                f'data-filename="{filename_attr}" title="複製">複製</button>'
                f'<button class="clip-delete" data-type="{escape(voice_type, quote=True)}" '
                f'data-filename="{filename_attr}" title="削除">削除</button>'
                '</div>'
                f'<audio controls preload="none" src="{escape(audio_url, quote=True)}"></audio>'
                + _render_clip_tags(additional_tags, available_tags)
                + '</article>'
            )
        columns.append("</section>")
    columns.append("</div>")
    trim_prefix_options = "".join(
        f'<option value="{escape(prefix, quote=True)}">{escape(prefix)}</option>'
        for prefix in CLIP_PREFIXES
    )
    trim_tag_options = "".join(
        f'<button class="trim-tag-option" type="button" data-tag="{escape(tag, quote=True)}">{escape(tag)}</button>'
        for tag in available_tags
    )
    columns.append(
        '<div class="trim-overlay">'
        '<div class="trim-panel" role="dialog" aria-modal="true" aria-label="音声トリミング">'
        '<div class="trim-title">トリミング</div>'
        '<div class="trim-metadata">'
        '<label class="trim-filename-field">ファイル名<input class="trim-filename" type="text" autocomplete="off">'
        '<div class="trim-filename-parts" aria-label="ファイル名のテキスト部分"></div>'
        '<span class="trim-filename-parts-hint">ボタンをクリックすると、その部分をファイル名から除外／復帰できます。</span></label>'
        f'<label class="trim-prefix-field">プレフィックス<select class="trim-prefix">{trim_prefix_options}</select></label>'
        '</div>'
        '<div class="trim-tags-editor"><div class="trim-tags-heading"><span>追加タグ</span>'
        '<button class="trim-tag-add" type="button">＋ 追加タグ</button></div>'
        '<div class="trim-tag-chips"></div>'
        f'<div class="trim-tag-picker" hidden>{trim_tag_options or "利用可能な追加タグが未設定です。"}</div></div>'
        '<div class="trim-waveform-wrap"><canvas class="trim-waveform"></canvas>'
        '<span class="trim-waveform-label">青: 波形　黄: 選択範囲　赤: 再生位置　水色: フェード境界</span></div>'
        '<audio class="trim-audio" controls preload="metadata"></audio>'
        '<div class="trim-control"><label>開始</label><input class="trim-start-range" type="range" min="0" max="1" step="0.001" value="0">'
        '<input class="trim-start-number" type="number" min="0" step="0.001" value="0"></div>'
        '<div class="trim-control"><label>終了</label><input class="trim-end-range" type="range" min="0" max="1" step="0.001" value="1">'
        '<input class="trim-end-number" type="number" min="0" step="0.001" value="1"></div>'
        '<div class="trim-fades"><label>フェードイン（秒）<input class="trim-fade-in" type="number" min="0" step="0.001" value="0"></label>'
        '<label>フェードアウト（秒）<input class="trim-fade-out" type="number" min="0" step="0.001" value="0"></label></div>'
        '<div class="trim-message"></div>'
        '<div class="trim-actions"><button class="trim-preview">範囲を再生</button>'
        '<button class="trim-cancel">キャンセル</button><button class="trim-apply">適用</button></div>'
        '</div></div>'
    )
    return "".join(columns)


def load_arrange_voice(voice_set: str | None) -> tuple[str, str]:
    if not voice_set:
        return render_arrange_board(None), "ボイスセットがありません。Generationでクリップを生成してください。"
    try:
        total = sum(len(items) for items in list_clips(OUTPUT_DIRECTORY, voice_set).values())
        return render_arrange_board(voice_set), f"✅ {voice_set}: {total}クリップを読み込みました。"
    except ArrangeError as exc:
        return render_arrange_board(None), f"❌ {exc}"


def refresh_arrange_voices(current: str | None) -> tuple[gr.Dropdown, str, str]:
    choices = list(list_voice_sets(OUTPUT_DIRECTORY))
    selected = current if current in choices else (choices[0] if choices else None)
    board, status = load_arrange_voice(selected)
    return gr.Dropdown(choices=choices, value=selected), board, status


def select_generated_voice(generation_event: object) -> tuple[gr.Dropdown, str, str]:
    voice_set = (
        str(generation_event.get("voice_set") or "")
        if isinstance(generation_event, dict)
        else ""
    )
    choices = list(list_voice_sets(OUTPUT_DIRECTORY))
    selected = voice_set if voice_set in choices else (choices[0] if choices else None)
    board, status = load_arrange_voice(selected)
    return gr.Dropdown(choices=choices, value=selected), board, status


def handle_arrange_action(voice_set: str | None, evt: gr.EventData) -> tuple[str, str]:
    if not voice_set:
        return render_arrange_board(None), "❌ ボイスセットを選択してください。"
    action = str(getattr(evt, "action", ""))
    source_type = str(getattr(evt, "source_type", ""))
    filename = str(getattr(evt, "filename", ""))
    try:
        if action == "move":
            target_type = str(getattr(evt, "target_type", ""))
            result = move_clip(OUTPUT_DIRECTORY, voice_set, source_type, target_type, filename)
            if result.source == result.destination:
                message = f"ℹ️ {filename} はすでに {target_type} にあります。"
            elif result.renamed:
                message = f"✅ {filename} → {target_type}/{result.destination.name}（重複のため自動改名）"
            else:
                message = f"✅ {filename} → {target_type}"
        elif action == "delete":
            destination = delete_clip(OUTPUT_DIRECTORY, voice_set, source_type, filename)
            message = f"✅ {filename} を削除しました（復旧先: .trash/{source_type}/{destination.name}）。"
        elif action == "delete_type":
            deleted = delete_type_clips(OUTPUT_DIRECTORY, voice_set, source_type)
            message = f"✅ {source_type} の全 {len(deleted)}クリップを削除しました（`.trash` から復旧可能です）。"
        elif action == "delete_all":
            deleted = delete_all_clips(OUTPUT_DIRECTORY, voice_set)
            message = f"✅ 全タイプの {len(deleted)}クリップを削除しました（`.trash` から復旧可能です）。"
        elif action == "renumber_all":
            result = renumber_all_clips(OUTPUT_DIRECTORY, voice_set)
            if result.renamed:
                message = f"✅ 全 {result.total}クリップを確認し、{result.renamed}件の連番を振り直しました。"
            else:
                message = f"ℹ️ 全 {result.total}クリップの連番は既に整っています。"
        elif action == "set_prefix":
            prefix = str(getattr(evt, "prefix", ""))
            result = set_clip_prefix(OUTPUT_DIRECTORY, voice_set, source_type, filename, prefix)
            _, display_name = split_clip_prefix(result.destination.name)
            if result.source == result.destination:
                message = f"ℹ️ {display_name} は既に [{prefix}] です。"
            else:
                message = f"✅ {display_name} のプレフィックスを [{prefix}] に変更しました。"
        elif action == "set_tags":
            tags = normalize_available_tags(str(getattr(evt, "tags", "")))
            result = set_clip_tags(OUTPUT_DIRECTORY, voice_set, source_type, filename, tags)
            _, tagged_name = split_clip_prefix(result.destination.name)
            display_name, _ = split_clip_tags(tagged_name)
            tag_text = "".join(f"[{tag}]" for tag in result.tags) or "なし"
            message = f"✅ {display_name} の追加タグを {tag_text} に変更しました。"
        elif action == "duplicate":
            result = duplicate_clip(OUTPUT_DIRECTORY, voice_set, source_type, filename)
            message = f"✅ {filename} を {result.duplicate.name} として複製しました。"
        elif action == "trim":
            fade_in = float(getattr(evt, "fade_in_seconds", 0))
            fade_out = float(getattr(evt, "fade_out_seconds", 0))
            result = trim_wav_clip(
                OUTPUT_DIRECTORY,
                voice_set,
                source_type,
                filename,
                float(getattr(evt, "start_seconds", "nan")),
                float(getattr(evt, "end_seconds", "nan")),
                fade_in,
                fade_out,
                str(getattr(evt, "new_filename", "")),
                str(getattr(evt, "new_prefix", "")),
                normalize_available_tags(str(getattr(evt, "new_tags", ""))),
            )
            fade_note = ""
            if fade_in or fade_out:
                fade_note = f"（Fade In {fade_in:.3f}秒 / Fade Out {fade_out:.3f}秒）"
            old_prefix, old_tagged_name = split_clip_prefix(filename)
            old_display_name, old_tags = split_clip_tags(old_tagged_name)
            new_prefix, new_tagged_name = split_clip_prefix(result.clip.name)
            new_display_name, new_tags = split_clip_tags(new_tagged_name)
            change_note = ""
            if old_display_name != new_display_name or old_prefix != new_prefix or old_tags != new_tags:
                change_note = f" → [{new_prefix or DEFAULT_CLIP_PREFIX}]{new_display_name}"
            message = (
                f"✅ {old_display_name}{change_note} を {result.original_duration:.3f}秒から "
                f"{result.trimmed_duration:.3f}秒へトリミングしました。{fade_note}"
            )
        else:
            raise ArrangeError("不明な操作です。")
        return render_arrange_board(voice_set), message
    except (ArrangeError, OSError, TypeError, ValueError) as exc:
        return render_arrange_board(voice_set), f"❌ 操作に失敗しました: {exc}"


def build_ui() -> gr.Blocks:
    saved = load_settings(SETTINGS_PATH)
    with gr.Blocks(title="Irodori VoiceSetBuilder") as demo:
        gr.Markdown(
            "# Irodori VoiceSetBuilder\n"
            "起動済みのIrodori-TTSサーバーを利用して、タイプ別のボイスセットを生成します。"
        )
        with gr.Tab("Generation"):
            with gr.Row():
                server_url = gr.Textbox(
                    label="TTSサーバーURL",
                    value=os.getenv("IRODORI_TTS_SERVER_URL", str(saved["server_url"])),
                    scale=3,
                )
                check_button = gr.Button("接続確認", scale=1)
            server_status = gr.Markdown("サーバーを起動してから接続確認してください。")

            with gr.Row():
                voice_id = gr.Textbox(
                    label="参照voice",
                    value=str(saved["voice_id"]),
                    placeholder="例: 森岡凛",
                    scale=3,
                )
                num_steps = gr.Number(
                    label="ステップ数",
                    value=saved["num_steps"],
                    precision=0,
                    minimum=1,
                    maximum=120,
                    scale=1,
                )

            inputs: list[gr.Component] = []
            type_buttons: list[
                tuple[str, gr.Button, gr.Button, list[gr.Component], gr.State]
            ] = []
            for voice_type in VOICE_TYPES:
                type_saved = saved["types"][voice_type]
                with gr.Row():
                    enabled_input = gr.Checkbox(
                        label="有効",
                        value=type_saved["enabled"],
                        scale=0,
                        min_width=55,
                    )
                    text_input = gr.Textbox(
                        label=voice_type,
                        placeholder="/ で複数指定（例: こんにちは/おはよう）",
                        value=type_saved["text"],
                        lines=2,
                        scale=4,
                        elem_classes="generation-type-text",
                    )
                    caption_input = gr.Textbox(
                        label=f"{voice_type} Caption（任意）",
                        placeholder="このタイプの声質・スタイル指定",
                        value=type_saved["caption"],
                        lines=2,
                        scale=4,
                    )
                    count_input = gr.Number(
                        label="各テキストの出力数",
                        value=type_saved["count"],
                        precision=0,
                        minimum=0,
                        scale=1,
                    )
                    with gr.Column(scale=0, min_width=90):
                        sample_button = gr.Button("Sample", size="sm", min_width=90)
                        type_button = gr.Button(
                            "Generate",
                            size="sm",
                            min_width=90,
                            elem_classes="type-generate",
                        )
                    sample_state = gr.State({"index": 0, "path": ""})
                row_inputs = [text_input, caption_input, count_input]
                inputs.extend((enabled_input, *row_inputs))
                type_buttons.append(
                    (voice_type, type_button, sample_button, row_inputs, sample_state)
                )

            sample_preview = gr.Audio(
                label="Sample Preview（一時生成・未保存）",
                autoplay=True,
                interactive=False,
                buttons=[],
            )
            generate_button = gr.HTML(
                value='<button class="bulk-generate">Generate</button>',
                html_template="${value}",
                css_template=(
                    ".bulk-generate { width: 100%; border: 0; border-radius: 8px; padding: 10px 16px; "
                    "cursor: pointer; color: white; background: var(--button-primary-background-fill); "
                    "font-weight: 600; font-size: 16px; }"
                ),
                js_on_load=(
                    "element.querySelector('.bulk-generate').addEventListener('click', () => { "
                    "if (window.confirm('有効な全タイプのクリップを一括生成します。よろしいですか？')) "
                    "trigger('click'); });"
                ),
                container=False,
            )
            with gr.Row():
                arrange_shortcut = gr.Button(
                    "Arrangeタブへ",
                    size="lg",
                    scale=0,
                    min_width=190,
                    elem_classes="arrange-tab-shortcut",
                )
            generation_status = gr.Markdown()
            generation_log = gr.Textbox(label="生成ログ", lines=10, interactive=False)
            generated_files = gr.File(label="生成ファイル", file_count="multiple")
            generated_voice_set = gr.State({})

            check_button.click(check_server, inputs=server_url, outputs=server_status)
            bulk_generation_event = generate_button.click(
                run_generation,
                inputs=[server_url, voice_id, num_steps, *inputs],
                outputs=[generation_status, generation_log, generated_files, generated_voice_set],
                js=GENERATION_START_JS,
                concurrency_limit=1,
            )
            bulk_generation_event.then(
                fn=None,
                inputs=generation_status,
                js=GENERATION_FINISH_JS,
            )
            arrange_shortcut.click(
                fn=None,
                js="""() => {
                  const target = Array.from(document.querySelectorAll('button[role="tab"]'))
                    .find((button) => button.textContent.trim() === 'Arrange');
                  if (target) target.click();
                }""",
            )
            for voice_type, type_button, sample_button, row_inputs, sample_state in type_buttons:
                type_generation_event = type_button.click(
                    partial(run_type_generation, voice_type),
                    inputs=[server_url, voice_id, num_steps, *row_inputs],
                    outputs=[generation_status, generation_log, generated_files, generated_voice_set],
                    js=GENERATION_START_JS,
                    concurrency_limit=1,
                )
                type_generation_event.then(
                    fn=None,
                    inputs=generation_status,
                    js=GENERATION_FINISH_JS,
                )
                sample_button.click(
                    partial(run_sample_generation, voice_type),
                    inputs=[server_url, voice_id, num_steps, row_inputs[0], row_inputs[1], sample_state],
                    outputs=[sample_preview, generation_status, sample_state],
                    concurrency_limit=1,
                )
                row_inputs[0].change(
                    reset_sample_sequence,
                    inputs=sample_state,
                    outputs=sample_state,
                    show_progress="hidden",
                )

            persistent_inputs = [server_url, voice_id, num_steps, *inputs]
            for component in persistent_inputs:
                component.change(
                    persist_inputs,
                    inputs=persistent_inputs,
                    outputs=None,
                    show_progress="hidden",
                )
            gr.Markdown("入力内容と各タイプの有効状態は自動保存され、次回起動時に復元されます。")

        with gr.Tab("Arrange") as arrange_tab:
            initial_voice_sets = list(list_voice_sets(OUTPUT_DIRECTORY))
            initial_voice = initial_voice_sets[0] if initial_voice_sets else None
            with gr.Row():
                arrange_voice = gr.Dropdown(
                    label="ボイスセット名",
                    choices=initial_voice_sets,
                    value=initial_voice,
                    interactive=True,
                    scale=4,
                )
                arrange_refresh = gr.Button("一覧を更新", size="sm", scale=0, min_width=110)
                arrange_skip_delete_confirm = gr.Checkbox(
                    label="確認をスキップ",
                    info="個別削除のみ",
                    value=bool(saved["arrange_skip_delete_confirm"]),
                    elem_id="arrange-skip-delete-confirm",
                    scale=0,
                    min_width=145,
                )
            arrange_available_tags = gr.Textbox(
                label="利用可能な追加タグ",
                value=str(saved["arrange_available_tags"]),
                placeholder="Nod/Blink/Smile",
                info="/ 区切りで指定します。保存後、各カードとトリミング画面の「追加タグ」から選択できます。",
            )
            arrange_status = gr.Markdown(
                load_arrange_voice(initial_voice)[1] if initial_voice else "Generationでボイスセットを生成してください。"
            )
            arrange_board = gr.HTML(
                value=render_arrange_board(initial_voice),
                html_template="${value}",
                css_template=ARRANGE_CSS,
                js_on_load=ARRANGE_JS,
                elem_id="arrange-board-component",
                container=False,
            )
            gr.Markdown(
                "クリップ左側の ⠿ を別タイプへドラッグできます。「追加タグ」はカードまたは編集画面から複数指定できます。"
                "「編集」ではトリミングとフェード、「複製」では同タイプへのコピーが可能です。削除したクリップと編集前の原音は `.trash` に保存されます。"
            )

            arrange_voice.change(
                load_arrange_voice,
                inputs=arrange_voice,
                outputs=[arrange_board, arrange_status],
                show_progress="hidden",
            )
            arrange_refresh.click(
                refresh_arrange_voices,
                inputs=arrange_voice,
                outputs=[arrange_voice, arrange_board, arrange_status],
                show_progress="hidden",
            )
            arrange_board.click(
                handle_arrange_action,
                inputs=arrange_voice,
                outputs=[arrange_board, arrange_status],
                show_progress="hidden",
                concurrency_limit=1,
            )
            arrange_tab_refresh_event = arrange_tab.select(
                refresh_arrange_voices,
                inputs=arrange_voice,
                outputs=[arrange_voice, arrange_board, arrange_status],
                js=ARRANGE_REFRESH_START_JS,
                show_progress="hidden",
            )
            arrange_tab_refresh_event.then(
                fn=None,
                js=ARRANGE_REFRESH_FINISH_JS,
            )
            arrange_skip_delete_confirm.change(
                persist_arrange_skip_delete_confirm,
                inputs=arrange_skip_delete_confirm,
                outputs=None,
                show_progress="hidden",
            )
            arrange_available_tags.change(
                persist_arrange_available_tags,
                inputs=[arrange_available_tags, arrange_voice],
                outputs=[arrange_board, arrange_status],
                show_progress="hidden",
            )
            generated_voice_set.change(
                select_generated_voice,
                inputs=generated_voice_set,
                outputs=[arrange_voice, arrange_board, arrange_status],
                show_progress="hidden",
            )
    return demo


if __name__ == "__main__":
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    port = int(os.getenv("IRODORI_BUILDER_PORT", "7860"))
    open_browser = os.getenv("IRODORI_BUILDER_OPEN_BROWSER", "true").strip().casefold() not in {
        "0",
        "false",
        "no",
        "off",
    }
    build_ui().queue(default_concurrency_limit=1).launch(
        server_name="127.0.0.1",
        server_port=port,
        inbrowser=open_browser,
        show_error=True,
        css=GENERATION_CSS,
        allowed_paths=[str(OUTPUT_DIRECTORY), str(SAMPLE_DIRECTORY)],
    )
