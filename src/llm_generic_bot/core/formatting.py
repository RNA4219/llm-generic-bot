def clamp_lines_and_emojis(text: str, max_lines: int, max_emojis: int) -> str:
    lines = text.splitlines()
    lines = lines[:max_lines]
    # 絵文字カウントは簡易（記号除外）: 実用では emoji ライブラリ等に差替え
    joined = "\n".join(lines)
    # 最大絵文字数を超える場合は末尾の絵文字を削る
    count = sum(1 for ch in joined if ord(ch) > 0x1F300 and ord(ch) < 0x1FAFF)
    if count <= max_emojis: return joined
    # ざっくり末尾から削る
    out = []
    kept = 0
    for ch in joined:
        is_emoji = (ord(ch) > 0x1F300 and ord(ch) < 0x1FAFF)
        if is_emoji and kept >= max_emojis:
            continue
        if is_emoji: kept += 1
        out.append(ch)
    return "".join(out)
