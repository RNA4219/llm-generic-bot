# llm-generic-bot

プラットフォーム非依存の **LLM 汎用 BOT**。Discord / Misskey などへ自律投稿・応答。
- ドメインロジックと I/O を完全分離（Ports & Adapters）
- 適応型クールタイム (Anti-spam)
- ジョブ優先度・衝突回避アービタ
- 近傍重複デデュープ
- 天気要約（30℃/35℃しきい値アイコン、前日比 ΔT アラート）
- ニュース自動配信
- おみくじ生成
- DM ダイジェスト編纂
- 週次サマリ/メトリクス連携（`src/llm_generic_bot/runtime/setup/__init__.py` で週次レポート登録、`tests/integration/test_runtime_weekly_report.py` で検証）

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp config/settings.example.json config/settings.json
cp .env.example .env
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
MIT
