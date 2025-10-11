from llm_generic_bot.core.cooldown import CooldownGate

def test_multiplier_bounds():
    g = CooldownGate(1800,1.0,6.0,0.5,0.8,0.6)
    for i in range(10):
        g.note_post("discord","c","news")
    m = g.multiplier("discord","c","news", time_band_factor=1.5, engagement_recent=0.8)
    assert 1.0 <= m <= 6.0
