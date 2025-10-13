---
sprint: 2
status: in_progress
updated: 2025-10-21
known_issues:
  - "ニュース配信および Discord DM ダイジェストがサンプル設定で失敗: プロバイダ参照のインポート未解決と `runtime/providers.py` 欠落"
---

# Sprint 2 タスクリスト

| 状態 | ID | 要約 | 対象モジュール | 完了条件 | 備考 | 確認テスト |
|:----:|:---|:-----|:---------------|:---------|:-----|:-------------|
| [x] | UX-01 | Engagement 反映ロジック調整 | `src/llm_generic_bot/features/weather.py`<br>`src/llm_generic_bot/core/orchestrator.py` | 利用者のリアクション履歴を参照し、指定クールダウン内での重複通知を抑止しつつ、閾値超過時は通知が再開される。構造化ログに Engagement 指標を含める。 | 2025-10-21 実装完了。PermitGate 整合と `pytest -k weather_engagement` 緑を再確認。 | `tests/features/test_weather_engagement.py`: リアクション閾値・クールダウン・再開シナリオ |
| [ ] | UX-02 | ニュース配信機能実装 | `src/llm_generic_bot/features/news.py` | RSS/HTTP フィードを取得し、要約生成後に送信キューへ投入。クールダウン内は再通知しない。 | プロバイダ参照をインポート解決し、`runtime/providers.py` を整備してサンプル設定で成功させる追補作業を再オープン。ニュース配信が文字列指定プロバイダでも動作することを確認する。Secrets 委譲と `pytest -k news` 緑は維持。 | `tests/features/test_news.py`: 正常取得・要約失敗リトライ＋フォールバック・クールダウン抑止<br>`tests/integration/test_runtime_multicontent.py::test_setup_runtime_resolves_string_providers` |
| [x] | UX-03 | おみくじ生成ワークフロー | `src/llm_generic_bot/features/omikuji.py` | 日次テンプレートをローテーションし、既出結果を 24 時間以内に再利用しない。結果はユーザー別シードに基づく。 | 2025-10-21 実装完了。Fallback 文言と `pytest -k omikuji` 緑を再確認。 | `tests/features/test_omikuji.py`: シード固定・テンプレ消費・Fallback 文言の回帰 |
| [ ] | UX-04 | Discord DM ダイジェスト | `src/llm_generic_bot/adapters/discord.py`<br>`src/llm_generic_bot/features/*`<br>`tests/runtime/test_providers.py` | 指定チャンネルのログを集計し、日次スケジュールで DM 送信。失敗時はリトライし、最終的に構造化ログへ残す。DM ダイジェスト用サンプルプロバイダ群の検証を完了条件へ含める。 | プロバイダ参照インポートと `runtime/providers.py` 整備が未完了のためサンプル設定で失敗。PermitGate 連携と `pytest -k dm_digest` 緑は維持しつつ追補対応を実施。 | `tests/features/test_dm_digest.py`: 集計・送信・リトライ・PermitGate 連携<br>`tests/runtime/test_providers.py`: サンプルプロバイダ群の読み込み |

## 進行手順
1. `tests/features/` にテストスケルトンを追加し、UX-01〜UX-04 の期待挙動を先に固定する。
2. ランタイム設定経由のプロバイダ解決を `tests/integration/test_runtime_multicontent.py` と `tests/runtime/test_providers.py` で先に固定する。
3. 各モジュールでフィーチャ実装を行い、PermitGate・構造化ログ・スケジューラと整合を確認する。
4. `pytest -q`, `mypy src`, `ruff check .` を順に実行し、品質ゲートを通過させる。
5. 完了後にチェックボックスを更新し、Sprint 1 と差分をレビュー用に比較して引継ぎ事項を整理する。

## 完了確認メモ
- UX-02: `build_news_post` がクールダウン判定・Permit 呼び出し・要約リトライとフォールバックを実装し、`tests/features/test_news.py` で成功・再試行・抑止ケースをカバー済み。`tests/integration/test_runtime_multicontent.py::test_setup_runtime_resolves_string_providers` で文字列指定プロバイダ経由のニュース配信を確認する。サンプル設定での失敗を解消するため、プロバイダ参照のインポート解決と `runtime/providers.py` 整備後に `pytest -q`, `mypy src`, `ruff check .` を再実行する。
- UX-03: `build_omikuji_post` がテンプレ回転とユーザー別シード、ロケール Fallback を実装し、`tests/features/test_omikuji.py` で各条件を固定。
- UX-04: `build_dm_digest` が PermitGate 判定・DM 送信リトライ・失敗ログ記録を提供し、`tests/features/test_dm_digest.py` でリトライ・空データ・失敗動作を検証済み。`tests/runtime/test_providers.py` で DM ダイジェスト用サンプルプロバイダ群の読み込みを確認する。サンプル設定での失敗修正後に `pytest -q`, `mypy src`, `ruff check .` を再実行して品質ゲートを再確認する。
