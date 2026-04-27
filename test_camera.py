#!/usr/bin/env python3
"""
Quick bringup test for the IMX477 Pi camera.

Run on the Pi:
    cd ~/lights_camera_action
    python3 test_camera.py

It will:
  1. Confirm picamera2 is importable.
  2. Detect the connected camera(s) via Picamera2.global_camera_info().
  3. Capture a single still to /tmp/picam_test.jpg.
  4. Capture a 2s video to /tmp/picam_test.mp4 (sanity-checks the H264 path
     used by /video360 continuous mode).
  5. Print pass/fail for each step and exit non-zero on any failure.

This script does NOT touch GPIO / the motor / Google Drive — it is purely a
camera-stack health check.
"""
from __future__ import annotations

import os
import sys
import time
import traceback


def _step(label: str) -> None:
    print(f"\n=== {label} ===", flush=True)


def main() -> int:
    failures: list[str] = []

    _step("1. Import picamera2")
    try:
        from picamera2 import Picamera2
        print("OK: picamera2 imported")
    except Exception:
        traceback.print_exc()
        print("FAIL: could not import picamera2. Install with:")
        print("  sudo apt install -y python3-picamera2 --no-install-recommends")
        return 1  # everything else depends on this

    _step("2. Detect cameras")
    try:
        info = Picamera2.global_camera_info()
        if not info:
            print("FAIL: no cameras detected. Check the ribbon cable seating "
                  "and that the camera is enabled (raspi-config -> Interface).")
            failures.append("detect")
        else:
            for i, c in enumerate(info):
                print(f"  [{i}] {c.get('Model', '?')}  "
                      f"location={c.get('Location', '?')}  "
                      f"id={c.get('Id', '?')}")
            print(f"OK: {len(info)} camera(s) detected")
    except Exception:
        traceback.print_exc()
        failures.append("detect")

    cam = None
    try:
        _step("3. Capture still -> /tmp/picam_test.jpg (4056x3040)")
        try:
            cam = Picamera2()
            cfg = cam.create_still_configuration(main={"size": (4056, 3040)})
            cam.configure(cfg)
            cam.start()
            time.sleep(2)  # AEC/AWB settle
            still_path = "/tmp/picam_test.jpg"
            cam.capture_file(still_path)
            size = os.path.getsize(still_path)
            print(f"OK: wrote {still_path} ({size:,} bytes)")
            if size < 50_000:
                print("WARN: file is suspiciously small for a 12MP JPEG")
                failures.append("still-small")
        except Exception:
            traceback.print_exc()
            failures.append("still")

        _step("4. Record 2s video -> /tmp/picam_test.mp4 (1920x1080 @ 30fps)")
        try:
            from picamera2.encoders import H264Encoder
            from picamera2.outputs import FfmpegOutput
            video_cfg = cam.create_video_configuration(
                main={"size": (1920, 1080)},
                controls={"FrameRate": 30},
            )
            cam.stop()
            cam.configure(video_cfg)
            cam.start()
            mp4_path = "/tmp/picam_test.mp4"
            encoder = H264Encoder(bitrate=10_000_000)
            output = FfmpegOutput(mp4_path)
            cam.start_recording(encoder, output)
            time.sleep(2)
            cam.stop_recording()
            size = os.path.getsize(mp4_path)
            print(f"OK: wrote {mp4_path} ({size:,} bytes)")
            if size < 50_000:
                print("WARN: video file is suspiciously small")
                failures.append("video-small")
        except Exception:
            traceback.print_exc()
            failures.append("video")
    finally:
        if cam is not None:
            try:
                cam.stop()
                cam.close()
            except Exception:
                pass

    _step("Summary")
    if failures:
        print(f"FAILED steps: {', '.join(failures)}")
        return 1
    print("ALL CAMERA TESTS PASSED ✅")
    print("Next: set CAMERA_TYPE=picamera2 in .env and restart lca.service")
    return 0


if __name__ == "__main__":
    sys.exit(main())
