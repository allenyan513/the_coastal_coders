#!/usr/bin/env python3
"""Print pitch-safe footage numbers from Tideflow's existing analysis API."""

import argparse
import json
import urllib.parse
import urllib.request


MANUAL_HOURS_PER_VIDEO_HOUR = 7.0  # Coastal Action's estimate: ~7 h to annotate 1 h.
REFERENCE_SECOND = 841
REFERENCE_FISH = 36  # Coastal Action researcher's hand count in one frame at 14:01.


def percentage(part, total):
    """Return a percentage, or zero when the denominator is zero."""
    return 100.0 * part / total if total else 0.0


def segment_seconds(segments, predicate, start=0.0, end=None):
    """Sum the portions of matching segments that overlap [start, end)."""
    if end is None:
        end = float("inf")
    total = 0.0
    for segment in segments:
        if not predicate(segment):
            continue
        left = max(float(segment["start"]), start)
        right = min(float(segment["end"]), end)
        total += max(0.0, right - left)
    return total


def api_get(base, path, query=None):
    url = base.rstrip("/") + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    with urllib.request.urlopen(url) as response:
        return json.load(response)


def parse_scalar(raw):
    raw = raw.strip()
    if raw.startswith(('"', "'")) and raw.endswith(raw[0]):
        return raw[1:-1]
    lowered = raw.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    try:
        return float(raw) if "." in raw else int(raw)
    except ValueError:
        return raw


def read_settings(path):
    """Read the simple scalar values used here without a third-party TOML dependency."""
    result = {"": {}}
    section = ""
    with open(path, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip()
                result.setdefault(section, {})
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                result.setdefault(section, {})[key.strip()] = parse_scalar(value)
    return result


def detector_setting(settings, detector, key):
    own = settings.get("detector." + detector, {})
    return own.get(key, settings.get("defaults", {}).get(key))


def overlap_seconds(second, start, end):
    return max(0.0, min(float(second) + 1.0, end) - max(float(second), start))


def range_numbers(detail, dense_detections, start, end):
    seconds = [row for row in detail.get("seconds", []) if overlap_seconds(row["second"], start, end) > 0]
    detected = sum(overlap_seconds(row["second"], start, end) for row in seconds if row["detections"] > 0)
    busy = sum(overlap_seconds(row["second"], start, end) for row in seconds if row["detections"] >= dense_detections)
    duration = max(0.0, end - start)
    nothing = max(0.0, duration - detected)
    peak_row = max(seconds, key=lambda row: row["detections"], default=None)
    segments = detail.get("segments", [])
    queued = segment_seconds(
        segments,
        lambda segment: segment.get("kind") == "active" or bool(segment.get("is_audit")),
        start,
        end,
    )
    skipped = segment_seconds(segments, lambda segment: segment.get("status") == "skipped", start, end)
    return {
        "duration": duration,
        "detected": detected,
        "nothing": nothing,
        "busy": busy,
        "peak": int(peak_row["detections"]) if peak_row else 0,
        "peak_t": float(peak_row["second"]) if peak_row else None,
        "queued": queued,
        "skipped": skipped,
    }


def clock(seconds):
    if seconds is None:
        return "—"
    seconds = int(seconds)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def seconds_text(value):
    return str(int(round(value)))


def hours_text(value):
    return f"{value:.1f} h"


def metric_table(title, numbers):
    duration = numbers["duration"]
    return [
        f"### {title}",
        "",
        "| Measure | Result |",
        "|---|---:|",
        f"| Footage duration | {seconds_text(duration)} s |",
        f"| Fish-detected seconds | {seconds_text(numbers['detected'])} s ({percentage(numbers['detected'], duration):.0f}%) |",
        f"| Nothing detected by AI | {seconds_text(numbers['nothing'])} s ({percentage(numbers['nothing'], duration):.0f}%) |",
        f"| Busy seconds (≥ dense threshold) | {seconds_text(numbers['busy'])} s ({percentage(numbers['busy'], duration):.0f}%) |",
        f"| Peak detections in one second | {numbers['peak']} at {clock(numbers['peak_t'])} |",
        f"| Queued for a person | {seconds_text(numbers['queued'])} s ({percentage(numbers['queued'], duration):.0f}%) |",
        f"| Skipped by AI | {seconds_text(numbers['skipped'])} s ({percentage(numbers['skipped'], duration):.0f}%) |",
        "",
    ]


def render_run(base, video, detail, summary, settings):
    duration = float(detail.get("duration") or video.get("duration") or 0)
    dense = int(settings.get("queue", {}).get("dense_detections", 8))
    default_detector = settings.get("", {}).get("default_detector", "")
    detector = video.get("detector", "")
    queue_threshold = detector_setting(settings, detector, "queue_threshold")
    is_default = detector == default_detector
    whole = range_numbers(detail, dense, 0.0, duration)

    protocol = settings.get("protocol", {})
    protocol_start = float(protocol.get("trim_start_s", 0))
    protocol_end = min(duration, protocol_start + float(protocol.get("window_s", duration)))
    has_protocol = protocol_end > protocol_start

    lines = [
        f"## {video['name']} — {detector}" + (" (default detector)" if is_default else ""),
        "",
        f"Status: **{video.get('status', 'unknown')}**  ",
        f"Detector: **{detector}**  ",
        f"Settings hash: **{detail.get('settings_hash') or 'unavailable'}**  ",
        f"Queue threshold: **{queue_threshold}**  ",
        f"Analysis rate: **{settings.get('', {}).get('fps', 'unknown')} fps**  ",
        f"Busy threshold: **{dense} detections/second**",
        "",
    ]
    lines += metric_table("Whole video", whole)
    if has_protocol:
        protocol_numbers = range_numbers(detail, dense, protocol_start, protocol_end)
        lines += metric_table(
            f"Protocol window ({clock(protocol_start)}–{clock(protocol_end)})",
            protocol_numbers,
        )
    else:
        lines += ["### Protocol window", "", "Not available: the configured protocol window starts after this clipped run ends.", ""]

    api_skipped = float(summary.get("skipped", 0))
    difference = abs(api_skipped - whole["skipped"])
    if difference <= 1.0:
        skipped_check = f"Matched summary.skipped within 1 s ({api_skipped:.1f} s)."
    else:
        skipped_check = (
            f"Did not match summary.skipped: segment sum {whole['skipped']:.1f} s versus "
            f"summary {api_skipped:.1f} s (difference {difference:.1f} s). "
            "The summary may have been produced from a different segment state."
        )

    audit_seconds = segment_seconds(detail.get("segments", []), lambda segment: bool(segment.get("is_audit")))
    audit_done = int(summary.get("audit_segments", 0))
    audit_total = int(summary.get("audit_total", 0))
    audit_fish = int(summary.get("audit_fish", 0))
    lines += [
        "### Review and audit", "",
        f"- Skipped cross-check: {skipped_check}",
        f"- Audit: {audit_done} of {audit_total} segments completed; {audit_seconds:.0f} s selected for audit; {audit_fish} fish found.",
        f"- Review time so far: {float(summary.get('review_seconds', 0)):.0f} s.",
    ]
    if audit_done == 0:
        lines.append("- **Audit not done yet: complete a few audit segments in the review queue to get a real missed-fish number.**")
    lines.append("")

    duration_h = duration / 3600.0
    manual_h = duration_h * MANUAL_HOURS_PER_VIDEO_HOUR
    queued_h = whole["queued"] / 3600.0
    review_seconds = float(summary.get("review_seconds", 0))
    lines += [
        "### Rough time-saved estimates", "",
        f"- **Rough estimate (queued footage):** {hours_text(manual_h)} by hand versus {hours_text(queued_h)} to watch the queued footage for this video.",
    ]
    if review_seconds > 0:
        lines.append(
            f"- **Rough estimate (actual review so far):** {hours_text(manual_h)} by hand versus "
            f"{hours_text(review_seconds / 3600.0)} recorded active review time so far."
        )
    else:
        lines.append("- Actual-review comparison unavailable: no active review time has been recorded yet.")
    lines.append("")

    reference_row = next((row for row in detail.get("seconds", []) if int(row["second"]) == REFERENCE_SECOND), None)
    if reference_row is not None:
        frame_boxes = api_get(base, f"/api/videos/{video['id']}/frame-boxes", {"t": REFERENCE_SECOND})
        reference = (
            f"At **14:01**, the researcher hand-counted **{REFERENCE_FISH} fish** in one frame. "
            f"This run recorded **{reference_row['detections']} detections** for that second at the queue threshold. "
            f"The freeze-frame endpoint offered **{len(frame_boxes.get('boxes', []))} additional boxes** "
            f"at threshold {frame_boxes.get('threshold')} on its nearest analysed frame ({frame_boxes.get('t', REFERENCE_SECOND):.1f} s)."
        )
    else:
        reference = (
            f"The **14:01 reference check is unavailable for this run**: it is a clipped video and has no API second at "
            f"841 s. Coastal Action's cited reference remains **{REFERENCE_FISH} fish in one frame**."
        )
    lines += ["### 14:01 reference check", "", reference, ""]

    watch_share = percentage(whole["queued"], duration)
    detected_share = percentage(whole["detected"], duration)
    per_hour_queued = whole["queued"] / duration if duration else 0.0
    lines += [
        "### Ready-to-say pitch lines", "",
        f'- “AI found fish in {detected_share:.0f}% of the footage, so the team only needed to watch {watch_share:.0f}%.”',
    ]
    if audit_done > 0:
        lines.append(
            f'- “Staff spot-checked a random sample of the skipped footage and found {audit_fish} fish the AI missed.”'
        )
    else:
        lines.append("- Audit not done yet: complete a few audit segments in the review queue to get a real missed-fish number.")
    lines.append(
        f'- “Rough estimate: about {MANUAL_HOURS_PER_VIDEO_HOUR:.0f} h by hand → about {per_hour_queued:.1f} h with Tideflow per hour of video.”'
    )
    lines += [
        "",
        f"Caveat: {reference} “Nothing detected by AI” does not mean no fish were present.",
        "",
        "How estimated: detection values and segments came from the existing Tideflow API; thresholds and protocol limits came from settings.toml. The manual baseline is Coastal Action's cited estimate of about 7 annotation hours per video hour.",
        "",
    ]
    return lines


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://localhost:8000", help="Tideflow API base URL")
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--video-id", help="Exact Tideflow video/run ID")
    choice.add_argument("--name-contains", help="Case-insensitive substring in the video name")
    parser.add_argument("--out", default="data/demo/footage_numbers.md", help="Markdown output path")
    parser.add_argument("--settings", default="settings.toml", help="Tideflow settings.toml path")
    return parser.parse_args()


def main():
    args = parse_args()
    videos = api_get(args.base, "/api/videos")
    if args.video_id:
        matches = [video for video in videos if video.get("id") == args.video_id]
    else:
        needle = args.name_contains.lower()
        matches = [video for video in videos if needle in video.get("name", "").lower()]
    if not matches:
        raise SystemExit("No matching video run found in GET /api/videos.")

    settings = read_settings(args.settings)
    lines = [
        "# Coastal Action footage numbers", "",
        "All figures below come from existing Tideflow API responses and settings.toml. No review decisions were recorded.",
        "",
    ]
    for video in matches:
        detail = api_get(args.base, f"/api/videos/{video['id']}")
        if video.get("status") != "Ready to review":
            default_detector = settings.get("", {}).get("default_detector", "")
            marker = " (default detector)" if video.get("detector") == default_detector else ""
            lines += [
                f"## {video['name']} — {video.get('detector', 'unknown')}" + marker,
                "",
                f"Status: **{video.get('status', 'unknown')}**  ",
                f"Stage: **{detail.get('stage') or 'unknown'}**  ",
                f"Progress: **{float(detail.get('progress', 0)) * 100:.0f}%**",
                "",
                "No footage metrics are reported for this run because its existing analysis is incomplete.",
                "",
            ]
            continue
        summary = api_get(args.base, f"/api/videos/{video['id']}/summary")
        lines += render_run(args.base, video, detail, summary, settings)

    text = "\n".join(lines).rstrip() + "\n"
    parent = args.out.rsplit("/", 1)[0] if "/" in args.out else ""
    if parent:
        import os
        os.makedirs(parent, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write(text)
    print(text, end="")


if __name__ == "__main__":
    main()
