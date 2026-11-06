"""ffmpeg helpers. Uses the binary from imageio-ffmpeg, so Windows needs no separate install."""
import re
import subprocess
from pathlib import Path

import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def probe(path: str) -> dict:
    """Read duration, frame rate and size from ffmpeg's banner, since this build has no ffprobe."""
    out = subprocess.run([FFMPEG, "-hide_banner", "-i", path], capture_output=True, text=True, errors="ignore").stderr
    duration = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", out)
    video = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", out)
    fps = re.search(r"([\d.]+) fps", out)
    if not duration or not video:
        raise ValueError("This file has no readable video stream.")
    h, m, s = duration.groups()
    return {
        "duration": int(h) * 3600 + int(m) * 60 + float(s),
        "width": int(video.group(1)),
        "height": int(video.group(2)),
        "fps": float(fps.group(1)) if fps else 30.0,
    }


def make_proxy(src: str, dst: Path) -> None:
    """540p H.264 with a keyframe every half second, so browsers can play and seek quickly."""
    tmp = dst.with_suffix(".tmp.mp4")
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", src,
         "-vf", "scale=-2:540,format=yuv420p", "-r", "30", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "26", "-g", "15", "-an", "-movflags", "+faststart", str(tmp)],
        check=True, capture_output=True,
    )
    tmp.replace(dst)


def decode_frames(path: str, width: int, height: int, fps: int):
    """Yield raw BGR frames at a fixed rate, without loading the whole video."""
    size = width * height * 3
    proc = subprocess.Popen(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-i", path,
         "-vf", f"fps={fps},scale={width}:{height}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE,
    )
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield buf
    finally:
        proc.stdout.close()
        proc.terminate()
        proc.wait()


def extract_frame(path: str, t: float, dst: Path) -> None:
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.3f}", "-i", path,
         "-frames:v", "1", "-q:v", "2", str(dst)],
        check=True, capture_output=True,
    )
