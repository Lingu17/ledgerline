"""Turn the frames and cues recorded by frontend/e2e/demo-video.spec.ts plus one WAV per narration line into an MP4.

  python scripts/make_demo_video.py <DEMO_DIR> <output.mp4>

Needs an ffmpeg executable: FFMPEG=<path>, or the imageio-ffmpeg package. Each frame is shown until the next one
arrived, so motion keeps its real timing; each narration line starts when its caption appeared.
"""
import json
import os
import subprocess
import sys
import wave
from pathlib import Path


def ffmpeg() -> str:
    if os.environ.get("FFMPEG"):
        return os.environ["FFMPEG"]
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def main(d: Path, out: Path) -> None:
    rec = json.loads((d / "frames.json").read_text())
    stamps, cues = rec["stamps"], rec["cues"]
    t0 = stamps[0][1]
    lines = [f"file '{(d / 'frames' / name).as_posix()}'\nduration {max(0.02, (stamps[i + 1][1] if i + 1 < len(stamps) else ts + 2.0) - ts):.3f}"
             for i, (name, ts) in enumerate(stamps)]
    lines.append(f"file '{(d / 'frames' / stamps[-1][0]).as_posix()}'")  # the concat demuxer needs the last file twice
    (d / "frames.txt").write_text("\n".join(lines) + "\n")
    total = stamps[-1][1] + 2.0 - t0

    # One narration track: silence, then each line where its caption appeared.
    with wave.open(str(d / f"{cues[0]['id']}.wav")) as w:
        params = w.getparams()
    rate, width, channels = params.framerate, params.sampwidth, params.nchannels
    track = bytearray(int(total * rate) * width * channels)
    for c in cues:
        with wave.open(str(d / f"{c['id']}.wav")) as w:
            data = w.readframes(w.getnframes())
        at = int((c["start"] - t0) * rate) * width * channels
        track[at:at + len(data)] = data[: max(0, len(track) - at)]
    with wave.open(str(d / "narration.wav"), "wb") as w:
        w.setparams(params)
        w.writeframes(bytes(track))

    subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(d / "frames.txt"),
                    "-i", str(d / "narration.wav"), "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=30",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "23", "-c:a", "aac", "-b:a", "128k",
                    "-shortest", str(out)], check=True)
    print(f"{out}: {total:.0f} s, {out.stat().st_size / 1e6:.1f} MB, {len(stamps)} frames")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
