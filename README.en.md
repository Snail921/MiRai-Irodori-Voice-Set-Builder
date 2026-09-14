# MiRai Irodori Voice Set Builder

English | [日本語](README.md)

A Windows Gradio GUI for generating and organizing type-based voice sets through a running [MiRai Server for Irodori-TTS V4](https://github.com/Snail921/MiRai-Server-for-Irodori-TTS-V4).

The Builder does not import the Irodori-TTS model or its Python code directly, so the TTS server and the Builder can be maintained in separate environments.

![Generation screen](docs/images/generation.png)

## Features

- Generate nine voice types in a batch or one type at a time
- Enter multiple phrases separated by `/` and choose the output count per phrase
- Add an optional per-type caption describing voice, emotion, or style
- Preview temporary samples without adding them to the voice set
- Organize output automatically under `output/<voice>/<type>/`
- Allocate numbered filenames without overwriting existing clips
- Play, classify, tag, trim, fade, duplicate, move, and delete clips
- Keep deleted clips and pre-edit originals under `.trash` for recovery
- Save and restore form inputs automatically

## Requirements

- Windows 10 or Windows 11
- [uv](https://docs.astral.sh/uv/) available on `PATH`
- A working [MiRai Server for Irodori-TTS V4](https://github.com/Snail921/MiRai-Server-for-Irodori-TTS-V4) installation
- At least one reference voice available to the Irodori-TTS server

The Whisper server is not used.

## Quick start

1. Start MiRai Server for Irodori-TTS V4 and wait until `http://127.0.0.1:5000/health` responds.
2. Download or clone this repository.
3. Double-click `Start_IrodoriVoiceSetBuilder.bat`.
4. In the automatically opened `http://127.0.0.1:7860` page, click **接続確認** (Check connection).
5. Enter a reference voice, text, and output count, then click **Generate**.

On the first launch, uv creates a dedicated virtual environment and installs the dependencies recorded in the lock file. To stop the Builder, press `Ctrl+C` in its command window.

## Manuals

- [日本語マニュアル](docs/MANUAL.ja.md)
- [English manual](docs/MANUAL.en.md)

## Data and privacy

Generated audio is stored locally in `output/`, while UI settings are stored in `settings.json`. Both paths are excluded by `.gitignore` and are not committed. Sample audio is written to an operating-system temporary directory and is not included in a voice set.

## Development

```powershell
uv run --locked python -m unittest discover -s tests -v
```

The Builder port and automatic browser launch can be changed with environment variables:

```powershell
$env:IRODORI_BUILDER_PORT = "7861"
$env:IRODORI_BUILDER_OPEN_BROWSER = "false"
uv run --locked python app.py
```

The TTS server URL can be changed in the GUI. Its default is `http://127.0.0.1:5000`.
