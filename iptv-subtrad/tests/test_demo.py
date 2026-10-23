from subtrad.demo import demo_cues, demo_duration_s, demo_video_url


def test_demo_script_is_well_formed():
    cues = demo_cues()
    assert len(cues) >= 30
    assert all(c.text.strip() for c in cues)
    assert all(c.start_ms < c.end_ms for c in cues)
    # Pas de chevauchement, ordre chronologique, assez long pour juger la synchro.
    assert all(a.end_ms <= b.start_ms for a, b in zip(cues, cues[1:]))
    assert cues[-1].end_ms >= 120_000
    # Deux lignes maximum par réplique, comme à l'écran.
    assert all(c.text.count("\n") <= 1 for c in cues)


def test_demo_video_lasts_as_long_as_the_subtitles():
    assert demo_duration_s() * 1000 > demo_cues()[-1].end_ms
    assert demo_video_url().startswith("av://lavfi:color=")
    assert f"d={demo_duration_s()}" in demo_video_url()
