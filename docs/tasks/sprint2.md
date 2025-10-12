---
sprint: 2
status: draft
updated: 2025-10-20
---

# Sprint 2 タスクリスト

| 状態 | ID | 要約 | 対象モジュール | 完了条件 | 備考 | 先行着手テスト |
|:----:|:---|:-----|:---------------|:---------|:-----|:----------------|
| [ ] | UX-01 | Engagement 反映ロジック調整 | `src/llm_generic_bot/features/weather.py`<br>`src/llm_generic_bot/core/orchestrator.py` | 利用者のリアクション履歴を参照し、指定クールダウン内での重複通知を抑止しつつ、閾値超過時は通知が再開される。構造化ログに Engagement 指標を含める。 | 既存の気象フィードを改修。バックエンド設定は Sprint 1 の PermitGate と整合させる。 | `tests/features/test_weather_engagement.py`: リアクション閾値・クールダウン・再開シナリオ |
| [ ] | UX-02 | ニュース配信機能実装 | `src/llm_generic_bot/features/news.py` | RSS/HTTP フィードを取得し、要約生成後に送信キューへ投入。クールダウン内は再通知しない。 | API キー情報は Secrets 管理に委譲。メトリクス出力フォーマットは Sprint 1 の構造化ログ仕様に準拠。 | `tests/features/test_news.py`: 正常取得・要約失敗時リトライ・クールダウン抑止 |
| [ ] | UX-03 | おみくじ生成ワークフロー | `src/llm_generic_bot/features/omikuji.py` | 日次テンプレートをローテーションし、既出結果を 24 時間以内に再利用しない。結果はユーザー別シードに基づく。 | 翻訳文言は `config/locales/ja.yml` に集約し、Fallback を設ける。 | `tests/features/test_omikuji.py`: シード固定・ローテーション・Fallback 文言 |
| [ ] | UX-04 | Discord DM ダイジェスト | `src/llm_generic_bot/adapters/discord.py`<br>`src/llm_generic_bot/features/*` | 指定チャンネルのログを集計し、日次スケジュールで DM 送信。失敗時はリトライし、最終的に構造化ログへ残す。 | `Scheduler` のジッタ設定と連携し、PermitGate による送信制御を尊重する。 | `tests/features/test_dm_digest.py`: 集計・送信・リトライ・PermitGate 連携 |

## 進行手順
1. `tests/features/` にテストスケルトンを追加し、UX-01〜UX-04 の期待挙動を先に固定する。
2. 各モジュールでフィーチャ実装を行い、PermitGate・構造化ログ・スケジューラと整合を確認する。
3. `pytest -q`, `mypy src`, `ruff check .` を順に実行し、品質ゲートを通過させる。
4. 完了後にチェックボックスを更新し、Sprint 1 と差分をレビュー用に比較して引継ぎ事項を整理する。
