import pytest
from fastapi.testclient import TestClient

from tidecount import db, settings, validation
from tidecount.app import app

client = TestClient(app)


def use_protocol(monkeypatch, **values):
    chosen = settings.Settings(protocol=settings.Protocol(**values))
    monkeypatch.setattr(settings, "current", lambda: chosen)


def add_video(duration=125.0, video_id="v1"):
    with db.session() as con:
        con.execute(
            "INSERT INTO videos (id, name, path, duration, width, height, status) "
            "VALUES (?, 'clip.mp4', '/nowhere.mp4', ?, 1280, 720, 'Ready to review')",
            (video_id, duration),
        )
    return video_id


@pytest.fixture(autouse=True)
def eight_points(monkeypatch):
    """Points at 15 s, 45 s ... so a 245 s video has 8 of them. Validate picks 3."""
    use_protocol(monkeypatch, trim_start_s=15, trim_end_s=0, window_s=100_000, every_s=30, validate_points=3, max_difference=0.06)


def dots(n):
    return [{"x": 0.1 + i * 0.001, "y": 0.5, "source": "user"} for i in range(n)]


def counted_video(totals=None, counter="Ana"):
    video_id = add_video(duration=245.0)
    frames = [f for f in client.get(f"/api/videos/{video_id}/snapshots").json()["frames"] if f["kind"] == "snapshot"]
    for i, f in enumerate(frames):
        n = (totals or {}).get(i, 10)
        r = client.put(f"/api/snapshot-frames/{f['id']}", json={"status": "checked", "dots": dots(n), "counter": counter})
        assert r.status_code == 200
    return video_id, frames


def test_difference_is_a_share_of_the_mean():
    assert validation.difference(0, 0) == 0
    assert validation.difference(10, 10) == 0
    assert validation.difference(10, 11) == pytest.approx(1 / 10.5)
    assert validation.difference(0, 1) == 2


def test_not_ready_until_every_point_is_counted():
    video_id = add_video(duration=245.0)
    frames = client.get(f"/api/videos/{video_id}/snapshots").json()["frames"]
    client.put(f"/api/snapshot-frames/{frames[0]['id']}", json={"status": "checked", "dots": dots(3)})
    body = client.get(f"/api/videos/{video_id}/validation").json()
    assert not body["ready"] and body["points"] == []
    assert "counted" in body["reason"]


def test_sample_is_picked_once_and_kept():
    video_id, _ = counted_video()
    first = [p["id"] for p in client.get(f"/api/videos/{video_id}/validation").json()["points"]]
    again = [p["id"] for p in client.get(f"/api/videos/{video_id}/validation").json()["points"]]
    assert len(first) == 3 and first == again


def test_counts_stay_hidden_until_you_count():
    video_id, _ = counted_video()
    point = client.get(f"/api/videos/{video_id}/validation?viewer=Ben").json()["points"][0]
    assert point["state"] == "to_count"
    assert point["counts"][0]["total"] is None
    after = client.post(f"/api/snapshot-frames/{point['id']}/validation", json={"counter": "Ben", "dots": dots(10)}).json()
    seen = next(p for p in after["points"] if p["id"] == point["id"])
    assert seen["state"] == "agree" and seen["agreed"] == 10
    assert [c["total"] for c in seen["counts"]] == [10, 10]


def test_you_cant_validate_your_own_point():
    video_id, _ = counted_video(counter="Ana")
    point = client.get(f"/api/videos/{video_id}/validation").json()["points"][0]
    r = client.post(f"/api/snapshot-frames/{point['id']}/validation", json={"counter": "Ana", "dots": dots(10)})
    assert r.status_code == 409


def test_a_wide_gap_needs_a_recount_and_a_third_count_can_settle_it():
    video_id, _ = counted_video()
    point = client.get(f"/api/videos/{video_id}/validation").json()["points"][0]
    body = client.post(f"/api/snapshot-frames/{point['id']}/validation", json={"counter": "Ben", "dots": dots(14)}).json()
    assert next(p for p in body["points"] if p["id"] == point["id"])["state"] == "recount"
    body = client.post(f"/api/snapshot-frames/{point['id']}/validation", json={"counter": "Cy", "dots": dots(14)}).json()
    settled = next(p for p in body["points"] if p["id"] == point["id"])
    assert settled["state"] == "agree" and settled["agreed"] == 14


def test_only_points_in_the_sample_take_counts():
    video_id, frames = counted_video()
    sampled = {p["id"] for p in client.get(f"/api/videos/{video_id}/validation").json()["points"]}
    other = next(f["id"] for f in frames if f["id"] not in sampled)
    assert client.post(f"/api/snapshot-frames/{other}/validation", json={"counter": "Ben", "dots": []}).status_code == 404


def test_only_a_manager_approves_and_only_when_every_point_agrees():
    video_id, _ = counted_video()
    points = client.get(f"/api/videos/{video_id}/validation").json()["points"]
    url = f"/api/videos/{video_id}/validation/approve"
    assert client.post(url, json={"name": "Mo", "role": "manager"}).status_code == 409
    for p in points:
        client.post(f"/api/snapshot-frames/{p['id']}/validation", json={"counter": "Ben", "dots": dots(10)})
    assert client.post(url, json={"name": "Vi", "role": "volunteer"}).status_code == 403
    body = client.post(url, json={"name": "Mo", "role": "manager"}).json()
    assert body["approval"]["approver"] == "Mo"
    # Approved counts are final.
    assert client.post(f"/api/snapshot-frames/{points[0]['id']}/validation", json={"counter": "Zed", "dots": []}).status_code == 409


def test_settings_have_the_protocol_defaults():
    p = settings.Protocol()
    assert p.validate_points == 6 and p.max_difference == 0.06
