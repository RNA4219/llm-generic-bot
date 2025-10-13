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
    cooldown.py           # 適応型クールタイム
    arbiter.py            # 衝突回避・優先度ジッタ
    dedupe.py             # 近傍重複検出
    formatting.py         # 共通整形
    types.py              # 型・プロトコル
  adapters/
    discord.py            # Discord 送信
    misskey.py            # Misskey 送信
    openweather.py        # OpenWeather fetch
  features/
    weather.py            # 天気機能
    news.py               # ニュース配信
    omikuji.py            # おみくじ
    dm_digest.py          # DM ダイジェスト
  config/
    loader.py             # 設定ロード/ホットリロード
tests/
.github/workflows/ci.yml
pyproject.toml
```

## License
MIT
