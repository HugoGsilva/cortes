from app.silence import parse_silence_log
from app.windows import is_vertical, output_fps, plan_windows


def test_short_video_is_one_clip():
    assert plan_windows(30, []) == [(0.0, 30.0)]


def test_too_short_is_dropped():
    assert plan_windows(2, []) == []


def test_no_pause_cuts_on_the_clock():
    assert plan_windows(120, [], target=50, max_len=60, min_len=12) == [
        (0.0, 60.0),
        (60.0, 120.0),
    ]


def test_pause_near_the_target_ends_the_clip():
    assert plan_windows(100, [(48, 52)], target=50, max_len=60, min_len=12) == [
        (0.0, 48.0),
        (52.0, 100.0),
    ]


def test_leading_silence_is_skipped():
    windows = plan_windows(80, [(0, 5)], target=50, max_len=60, min_len=12)
    assert windows[0][0] == 5.0


def test_tail_shorter_than_min_len_is_dropped():
    assert plan_windows(70, [], target=50, max_len=60, min_len=12) == [(0.0, 60.0)]


def test_rotation_swaps_orientation():
    assert is_vertical(1920, 1080, rotate=90)
    assert not is_vertical(1920, 1080, rotate=0)


def test_fps_caps_at_30():
    assert output_fps(60) == 30
    assert output_fps(24) == 24


def test_silence_log_pairs_and_closes_open_start():
    text = "silence_start: 1.5\nsilence_end: 2.25\nsilence_start: 8\n"
    assert parse_silence_log(text, duration=10) == [(1.5, 2.25), (8.0, 10.0)]
