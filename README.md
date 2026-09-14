# MiRai Irodori Voice Set Builder

[English](README.en.md) | 日本語

起動済みの [MiRai Server for Irodori-TTS V4](https://github.com/Snail921/MiRai-Server-for-Irodori-TTS-V4) を利用して、タイプ別のボイスセットを一括生成・整理するWindows向けGradio GUIです。

Irodori-TTSのモデルやPythonコードを直接読み込まないため、TTSサーバーとBuilderを別々の環境で管理できます。

![Generation画面](docs/images/generation.png)

## 主な機能

- 9種類のボイスタイプを一括または個別に生成
- `/` 区切りの複数テキストと、テキストごとの生成数を指定
- タイプごとの任意Caption（声質・感情・スタイル）
- ボイスセットへ保存しないSampleプレビュー
- 生成結果を `output/<voice>/<type>/` へ自動整理
- 既存ファイルを上書きしない連番ファイル名
- クリップの再生、分類、タグ付け、トリミング、フェード、複製、移動、削除
- 削除・編集前データを `.trash` に保存する復旧可能な運用
- 入力内容と設定の自動保存

## 必要なもの

- Windows 10またはWindows 11
- [uv](https://docs.astral.sh/uv/)（PATHから `uv` を実行できること）
- セットアップ済みの [MiRai Server for Irodori-TTS V4](https://github.com/Snail921/MiRai-Server-for-Irodori-TTS-V4)
- Irodori-TTSサーバーで利用できる参照voice

Whisperサーバーは使用しません。

## クイックスタート

1. MiRai Server for Irodori-TTS V4を起動し、`http://127.0.0.1:5000/health` が応答するまで待ちます。
2. このリポジトリをダウンロードまたはcloneします。
3. `Start_IrodoriVoiceSetBuilder.bat` をダブルクリックします。
4. 自動的に開く `http://127.0.0.1:7860` で「接続確認」を押します。
5. 参照voice、テキスト、出力数を入力してGenerateを押します。

初回起動時はuvが専用仮想環境を作成し、ロックファイルに記録された依存関係を取得します。終了時はBuilderのコマンド画面で `Ctrl+C` を押してください。

## マニュアル

- [日本語マニュアル](docs/MANUAL.ja.md)
- [English manual](docs/MANUAL.en.md)

## データとプライバシー

生成した音声は `output/`、画面設定は `settings.json` にローカル保存されます。どちらも `.gitignore` の対象で、リポジトリにはコミットされません。Sample音声はOSの一時領域に保存され、ボイスセットには含まれません。

## 開発者向け

```powershell
uv run --locked python -m unittest discover -s tests -v
```

Builderのポートやブラウザー自動表示は環境変数で変更できます。

```powershell
$env:IRODORI_BUILDER_PORT = "7861"
$env:IRODORI_BUILDER_OPEN_BROWSER = "false"
uv run --locked python app.py
```

TTSサーバーのURLはGUIで変更でき、既定値は `http://127.0.0.1:5000` です。
