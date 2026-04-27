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
    from libcamera import Transform
    from PIL import Image, ImageDraw, ImageFont

    _camera = None
    # Preview stream is much smaller than the 12MP main stream so the MJPEG
    # feed can run at >10 fps — essential for manual focusing.
    _PREVIEW_SIZE = (1280, 720)

    # Camera mount orientation. Set CAMERA_FLIP=1 in .env if the camera is
    # mounted upside down — applied as an ISP transform so it costs nothing
    # at runtime and affects preview, stills, and video uniformly.
    _FLIP = os.getenv("CAMERA_FLIP", "0") == "1"
    _TRANSFORM = Transform(hflip=1, vflip=1) if _FLIP else Transform()

    def _get_camera() -> "Picamera2":
        global _camera
        if _camera is None:
            _camera = Picamera2()
            # Configure a high-res `main` stream for stills *and* a low-res
            # `lores` stream for the live preview. The ISP gives us both in
            # parallel for free, so preview frames cost almost nothing.
            cfg = _camera.create_still_configuration(
                main={"size": (4056, 3040)},
                lores={"size": _PREVIEW_SIZE, "format": "YUV420"},
                display="lores",
                transform=_TRANSFORM,
            )
            _camera.configure(cfg)
            _camera.start()
            time.sleep(2)  # Allow AEC/AWB to settle
        return _camera

    def capture(path: str):
        _get_camera().capture_file(path)

    def _focus_score(gray) -> float:
        """Variance-of-Laplacian focus measure on a centre crop.
        Higher = sharper. Compare scores while turning the focus ring.
        """
        import numpy as np
        h, w = gray.shape
        cy, cx = h // 2, w // 2
        s = min(h, w) // 4  # centre crop = 1/2 width × 1/2 height of frame
        roi = gray[cy - s:cy + s, cx - s:cx + s].astype("float32")
        # Quick Laplacian via 4-neighbour finite difference (no scipy needed).
        lap = (
            -4.0 * roi[1:-1, 1:-1]
            + roi[:-2, 1:-1] + roi[2:, 1:-1]
            + roi[1:-1, :-2] + roi[1:-1, 2:]
        )
        return float(lap.var())

    def preview_jpeg(focus: bool = False, zoom: int = 1) -> bytes:
        """Return a JPEG-encoded preview frame.

        focus: overlay a focus score (variance of Laplacian on centre crop).
        zoom:  integer >=1, crops the centre 1/zoom × 1/zoom and upscales
               back to the preview size — useful for nailing fine focus.
        """
        import numpy as np
        cam = _get_camera()
        # `lores` YUV420 is small + fast; we only need the Y plane for both
        # display (greyscale is fine for focusing) and for the focus metric.
        yuv = cam.capture_array("lores")
        h_full = _PREVIEW_SIZE[1]
        y = yuv[:h_full, :_PREVIEW_SIZE[0]]  # luma plane

        if zoom > 1:
            ch, cw = y.shape
            zh, zw = ch // zoom, cw // zoom
            cy, cx = ch // 2, cw // 2
            y = y[cy - zh // 2:cy + zh // 2, cx - zw // 2:cx + zw // 2]

        img = Image.fromarray(y, mode="L").convert("RGB")
        if zoom > 1:
            img = img.resize(_PREVIEW_SIZE, Image.BILINEAR)

        if focus:
            score = _focus_score(np.asarray(img.convert("L")))
            draw = ImageDraw.Draw(img)
            # Centre reticle (1/2 × 1/2 of frame, matching the score ROI)
            w, h = img.size
            s = min(w, h) // 4
            draw.rectangle(
                [w // 2 - s, h // 2 - s, w // 2 + s, h // 2 + s],
                outline=(0, 255, 0), width=2,
            )
            label = f"focus={score:7.1f}  zoom={zoom}x"
            # Background box for legibility
            draw.rectangle([8, 8, 8 + 9 * len(label), 32], fill=(0, 0, 0))
            draw.text((12, 10), label, fill=(0, 255, 0))

        out = io.BytesIO()
        img.save(out, format="JPEG", quality=80)
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
        # Switch to a video-friendly size/framerate (same flip transform).
        video_cfg = cam.create_video_configuration(
            main={"size": (1920, 1080)},
            controls={"FrameRate": fps},
            transform=_TRANSFORM,
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
            still_cfg = cam.create_still_configuration(
                main={"size": (4056, 3040)},
                lores={"size": _PREVIEW_SIZE, "format": "YUV420"},
                display="lores",
                transform=_TRANSFORM,
            )
            cam.stop()
            cam.configure(still_cfg)
            cam.start()
            time.sleep(1)
