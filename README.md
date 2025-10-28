# llm-generic-bot

プラットフォーム非依存の **LLM 汎用 BOT**。Discord / Misskey などへ自律投稿・応答。

## 主な機能

- **アーキテクチャ**: ドメインロジックと I/O を完全分離（Ports & Adapters）。
- **送信制御**: 適応型クールタイム、ジョブ優先度アービタ、近傍重複デデュープでスパムを抑制。
- **自動配信**: 天気（30℃/35℃アイコン・前日比 ΔT アラート）、ニュース、おみくじ、DM ダイジェストを定期生成。
- **レポート**: 週次サマリとメトリクス連携（登録は `src/llm_generic_bot/runtime/setup/__init__.py`、検証は `tests/integration/runtime_weekly_report/`）。

## 実装概要

### 実行フロー
- `src/llm_generic_bot/main.py` で依存性を解決し、`runtime.providers.bootstrap_runtime` からアプリケーションを起動。
- `core.scheduler.Scheduler` がジョブをポーリングし、`core.orchestrator.ExecutionOrchestrator` へハンドオフ。
- オーケストレータは `core.cooldown.AdaptiveCooldown`、`core.arbiter.PriorityArbiter`、`core.dedupe.NearDuplicateDetector` を組み合わせて送信可否を判定。
- 許可されたペイロードは `runtime.setup.sender.SenderRunner` を経由し、各アダプタ (`adapters.discord`, `adapters.misskey` など) が最終的な API 呼び出しを実行。

### 機能モジュール
- 天気・ニュース等の定期ジョブは `runtime.jobs.*` でスケジュールされ、共通ロジックは `runtime.jobs.common.JobContext` を介して再利用。
- 個々のフィーチャは `features/` 以下に実装され、`core.formatting` で共通のメッセージ整形を行う。
- メトリクス集計は `infra.metrics.Aggregator`、レポート生成は `infra.metrics.reporting` が担当し、結果は `runtime.setup.reports.register_weekly_reports` から配信キューに登録される。

### 設定とシークレット
- `config/settings.json` が主要設定。値の検証は `config.loader.SettingsLoader` が担う。
- API キーやトークンは `.env` 経由で読み込み、`runtime.setup.gates.FeatureGateResolver` によるフィーチャフラグで有効・無効を制御。
- 呼び出し回数制限は `config.quotas.CallQuotaStore` が管理し、上限超過時は `core.orchestrator` がリトライをスケジュール。

### エラーハンドリング
- 再試行可能な失敗は `adapters._retry.RetryPolicy` が担当し、不可逆エラーは `core.types.ExecutionFailure` として呼び出し元に伝播。
- 外部サービス障害時はメトリクスに失敗イベントが記録され、週次レポートへ反映される。

### テスト戦略
- ユニットテスト: `tests/unit/` で各コンポーネントをモックしながら検証。
- 統合テスト: `tests/integration/` が DI・スケジューラ・レポート生成を E2E で確認。
- 型/リンタ: `pyproject.toml` で `mypy --strict` と `ruff` を CI 実行し、実装と同じ設定をローカルでも利用。

## Quick start

1. 依存関係をインストールします。
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -e .
   ```
2. 設定と環境変数のテンプレートをコピーします。
   ```bash
   cp config/settings.example.json config/settings.json
   cp .env.example .env
   ```
3. BOT を起動します。
   ```bash
   python -m llm_generic_bot.main
   ```

## Structure
```
src/llm_generic_bot/
  main.py                 # 起動・DI
  core/
    scheduler.py          # スケジュール/ジョブオーケストレーション
    orchestrator.py       # 実行キュー制御
    orchestrator/
      processor.py        # 実行要求の許可判定と実行フロー制御
    orchestrator_metrics.py # メトリクス計測フック
    queue.py              # 実行キュー定義
    cooldown.py           # 適応型クールタイム
    arbiter.py            # 衝突回避・優先度ジッタ
    dedupe.py             # 近傍重複検出
    formatting.py         # 共通整形
    types.py              # 型・プロトコル
  adapters/
    discord.py            # Discord 送信
    misskey.py            # Misskey 送信
    openweather.py        # OpenWeather fetch
    _retry.py             # アダプタ共通再試行ロジック
  features/
    weather.py            # 天気機能
    news.py               # ニュース配信
    omikuji.py            # おみくじ
    dm_digest.py          # DM ダイジェスト
    report.py             # 週次サマリ生成
  config/
    loader.py             # 設定ロード/ホットリロード
    quotas.py             # 呼び出し制限管理
  runtime/
    providers.py          # DI エントリポイント
    history.py            # 実行履歴管理
    setup/
      jobs.py             # 定期ジョブ束ね
      reports.py          # 週次レポート登録
      sender.py           # 投稿エグゼキュータ束ね
      gates.py            # フィーチャーフラグ/ゲート制御
      runtime_helpers.py  # 共通初期化ユーティリティ
    jobs/
      common.py           # ジョブ基盤
      weather.py          # 天気ジョブ
      news.py             # ニュースジョブ
      omikuji.py          # おみくじジョブ
      dm_digest.py        # DM ダイジェストジョブ
  infra/
    __init__.py           # MetricsBackend / collect_weekly_snapshot エントリポイント
    metrics/
      __init__.py         # メトリクス DTO エクスポート
      aggregator.py       # メトリクス集計ロジック
      aggregator_state.py # 集計状態の保持
      service.py          # バックエンド実装
      reporting.py        # 週次レポート整形
tests/
.github/workflows/ci.yml
pyproject.toml
```

## License

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](http://www.apache.org/licenses/LICENSE-2.0)

Apache-2.0. Unless noted otherwise, files copied from this repo into other projects remain Apache-2.0 and require retaining NOTICE text in redistributions.
