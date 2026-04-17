"""Video assembly helpers — uses ffmpeg as a subprocess."""
import os
import shutil
import subprocess


def frames_to_video(frame_dir: str, pattern: str, out_path: str, fps: int) -> None:
    """Assemble numbered frames in `frame_dir` matching `pattern` into an MP4.

    `pattern` is an ffmpeg-style sprintf pattern, e.g. "frame_%05d.jpg".
    Frames must be numbered starting at 0 and be contiguous.

    Requires ffmpeg on PATH. Raises RuntimeError if ffmpeg is missing or
    the encode fails.
    """
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg not found on PATH — install it (apt install ffmpeg) "
            "to use stitched 360 video mode."
        )

    input_spec = os.path.join(frame_dir, pattern)
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", input_spec,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-crf", "18",
        "-movflags", "+faststart",
        out_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed (exit {result.returncode}):\n{result.stderr[-2000:]}"
        )
