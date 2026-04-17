import io
import os
import time

MOCK        = os.getenv("MOCK_GPIO", "0") == "1"
CAMERA_TYPE = os.getenv("CAMERA_TYPE", "picamera2")  # "picamera2" or "usb"

if MOCK:
    from PIL import Image as _Image

    def capture(path: str):
        img = _Image.new("RGB", (100, 100), color=(180, 180, 180))
        img.save(path, format="JPEG")

    def preview_jpeg() -> bytes:
        img = _Image.new("RGB", (320, 240), color=(180, 180, 180))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()

    def record_video(path: str, duration_s: float, fps: int):
        """Mock: write a minimal placeholder MP4 and sleep the duration."""
        # An empty .mp4 is enough for upload-path testing without real hardware.
        with open(path, "wb") as f:
            f.write(b"")
        time.sleep(duration_s)

elif CAMERA_TYPE == "usb":
    import cv2

    _cap = None

    def _get_cap():
        global _cap
        if _cap is None:
            index = int(os.getenv("USB_CAMERA_INDEX", "0"))
            _cap = cv2.VideoCapture(index)
            _cap.set(cv2.CAP_PROP_FRAME_WIDTH,  int(os.getenv("USB_CAM_WIDTH",  "1920")))
            _cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(os.getenv("USB_CAM_HEIGHT", "1080")))
            time.sleep(1)  # Let AEC settle
        return _cap

    def capture(path: str):
        cap = _get_cap()
        # Discard a few frames so AEC has settled on the current scene
        for _ in range(5):
            cap.read()
        ok, frame = cap.read()
        if not ok:
            raise RuntimeError("USB camera: failed to grab frame")
        cv2.imwrite(path, frame)

    def preview_jpeg() -> bytes:
        cap = _get_cap()
        ok, frame = cap.read()
        if not ok:
            raise RuntimeError("USB camera: failed to grab frame")
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return bytes(buf)

    def record_video(path: str, duration_s: float, fps: int):
        """Record a video clip from the USB camera to `path` (MP4).

        Note: most USB webcams cap around 30 fps. If the camera can't
        deliver `fps` frames per second, the output wall-clock duration
        will be longer than `duration_s` — in practice this means the
        video will look slower than the motor rotation. Keep fps at or
        below what the camera supports (see CAP_PROP_FPS at boot).
        """
        cap = _get_cap()
        # AEC warmup
        for _ in range(5):
            cap.read()
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))  or 1920
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 1080
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(path, fourcc, fps, (w, h))
        try:
            frames_needed = int(duration_s * fps)
            for _ in range(frames_needed):
                ok, frame = cap.read()
                if ok:
                    writer.write(frame)
        finally:
            writer.release()

else:
    from picamera2 import Picamera2
    from PIL import Image

    _camera = None

    def _get_camera() -> "Picamera2":
        global _camera
        if _camera is None:
            _camera = Picamera2()
            cfg = _camera.create_still_configuration(main={"size": (4056, 3040)})
            _camera.configure(cfg)
            _camera.start()
            time.sleep(2)  # Allow AEC/AWB to settle
        return _camera

    def capture(path: str):
        _get_camera().capture_file(path)

    def preview_jpeg() -> bytes:
        cam = _get_camera()
        buf = cam.capture_array("main")
        img = Image.fromarray(buf)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85)
        return out.getvalue()

    def record_video(path: str, duration_s: float, fps: int):
        """Record video from the IMX477 via picamera2 + H264 encoder → MP4.

        Reconfigures the camera into a video mode, records, and restores
        the still configuration afterwards so subsequent capture() calls
        still get a high-res JPEG.
        """
        from picamera2.encoders import H264Encoder
        from picamera2.outputs import FfmpegOutput

        cam = _get_camera()
        # Switch to a video-friendly size/framerate
        video_cfg = cam.create_video_configuration(
            main={"size": (1920, 1080)},
            controls={"FrameRate": fps},
        )
        cam.stop()
        cam.configure(video_cfg)
        cam.start()
        try:
            encoder = H264Encoder(bitrate=10_000_000)
            output = FfmpegOutput(path)
            cam.start_recording(encoder, output)
            time.sleep(duration_s)
            cam.stop_recording()
        finally:
            # Restore the still configuration so capture() still works.
            still_cfg = cam.create_still_configuration(main={"size": (4056, 3040)})
            cam.stop()
            cam.configure(still_cfg)
            cam.start()
            time.sleep(1)
