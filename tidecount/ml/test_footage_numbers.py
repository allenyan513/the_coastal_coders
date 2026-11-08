from footage_numbers import percentage, segment_seconds


FAKE_VIDEO = {
    "duration": 10.0,
    "segments": [
        {"start": 0.0, "end": 4.0, "kind": "active", "is_audit": 0, "status": "needs_review"},
        {"start": 4.0, "end": 8.0, "kind": "quiet", "is_audit": 0, "status": "skipped"},
        {"start": 8.0, "end": 10.0, "kind": "quiet", "is_audit": 1, "status": "needs_review"},
    ],
}


def test_percentage():
    assert percentage(3, 12) == 25.0
    assert percentage(0, 0) == 0.0


def test_segment_sum_whole_and_clipped():
    segments = FAKE_VIDEO["segments"]
    queued = lambda segment: segment["kind"] == "active" or bool(segment["is_audit"])
    assert segment_seconds(segments, queued, 0, 10) == 6.0
    assert segment_seconds(segments, lambda segment: segment["status"] == "skipped", 0, 10) == 4.0
    assert segment_seconds(segments, queued, 2, 9) == 3.0
