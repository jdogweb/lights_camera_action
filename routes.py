import json
import os
import shutil
import tempfile
import threading
import time
from flask import Blueprint, request, jsonify, Response
from motor import rotate_to, rotate_continuous, rotate_relative, home
from camera import capture, preview_jpeg, record_video
from drive import upload_file
from video import frames_to_video

bp = Blueprint("main", __name__)

ANGLES_FILE = os.path.join(os.path.dirname(__file__), "angles.json")
DEFAULT_ANGLES = [0, 45, 90, 135, 180, 225, 270, 315]


def load_angles():
    if os.path.exists(ANGLES_FILE):
        with open(ANGLES_FILE) as f:
            return json.load(f)
    return DEFAULT_ANGLES


def save_angles(angles):
    with open(ANGLES_FILE, "w") as f:
        json.dump(angles, f)


@bp.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, ngrok-skip-browser-warning"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


@bp.route("/shoot", methods=["OPTIONS"])
@bp.route("/rotate", methods=["OPTIONS"])
@bp.route("/capture", methods=["OPTIONS"])
@bp.route("/angles", methods=["OPTIONS"])
@bp.route("/video360", methods=["OPTIONS"])
def cors_preflight(**_):
    return Response(status=200)


@bp.route("/angles", methods=["GET"])
def get_angles():
    """Return the current saved shoot angles."""
    return jsonify({"angles": load_angles()})


@bp.route("/angles", methods=["POST"])
def set_angles():
    """Save new shoot angles. Body: {"angles": [0, 60, 120, 180, 240, 300]}"""
    angles = request.get_json(force=True).get("angles", [])
    if not angles:
        return jsonify({"error": "angles required"}), 400
    angles = [round(float(a), 1) for a in angles]
    save_angles(angles)
    return jsonify({"angles": angles})


@bp.route("/shoot", methods=["POST"])
def shoot():
    """
    Full shoot sequence streamed via SSE. Uses saved angles unless overridden.
    Body: {"sku": "TT123"}  or  {"sku": "TT123", "angles": [0, 60, ...]}
    Streams: data: {"angle": 0, "url": "...", "index": 0, "total": 6}
    Final:   data: {"done": true, "sku": "TT123"}
    """
    data = request.get_json(force=True)
    sku = data.get("sku", "unknown")
    angles = data.get("angles") or load_angles()
    total = len(angles)

    def generate():
        for i, angle in enumerate(angles):
            rotate_to(angle)
            tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            tmp_path = tmp.name
            tmp.close()
            try:
                capture(tmp_path)
                filename = f"{sku}_{angle:05.1f}deg.jpg"
                url = upload_file(tmp_path, filename)
            finally:
                os.unlink(tmp_path)
            yield f"data: {json.dumps({'angle': angle, 'url': url, 'index': i, 'total': total})}\n\n"
        home()
        yield f"data: {json.dumps({'done': True, 'sku': sku})}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@bp.route("/rotate", methods=["POST"])
def rotate():
    """Rotate to angle. Body: {"angle": 90}"""
    angle = request.get_json(force=True).get("angle", 0)
    rotate_to(float(angle))
    return jsonify({"angle": angle})


@bp.route("/rotate/relative", methods=["POST"])
def rotate_rel():
    """Rotate by relative amount. Body: {"degrees": -360}"""
    degrees = request.get_json(force=True).get("degrees", 0)
    rotate_relative(float(degrees))
    return jsonify({"degrees": degrees})


@bp.route("/capture", methods=["POST"])
def single_capture():
    """Capture one photo and upload to Drive. Body: {"filename": "test.jpg"}"""
    data = request.get_json(force=True)
    filename = data.get("filename", "capture.jpg")
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    tmp_path = tmp.name
    tmp.close()
    try:
        capture(tmp_path)
        url = upload_file(tmp_path, filename)
    finally:
        os.unlink(tmp_path)
    return jsonify({"url": url})


@bp.route("/preview")
def preview():
    """Stream live MJPEG from the camera.

    Query params (picamera2 backend only — silently ignored for usb/mock):
      focus=1   overlay a variance-of-Laplacian focus score + centre reticle
      zoom=N    integer >=1, crops the centre 1/N × 1/N and upscales
    """
    focus = request.args.get("focus", "0") in ("1", "true", "yes")
    try:
        zoom = max(1, int(request.args.get("zoom", "1")))
    except ValueError:
        zoom = 1

    def generate():
        while True:
            try:
                # Newer picamera2 preview_jpeg accepts focus/zoom kwargs.
                jpeg = preview_jpeg(focus=focus, zoom=zoom)
            except TypeError:
                # USB / mock backends don't take kwargs.
                jpeg = preview_jpeg()
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame",
                    headers={"Cache-Control": "no-cache"})


@bp.route("/video360", methods=["POST"])
def video360():
    """
    Capture a 360° video of the watch. Streamed via SSE.

    Body: {
        "sku": "TT123",
        "mode": "stitched" | "continuous",  # default "stitched"
        "fps": 30,                           # default 30
        "duration": 10,                      # default 10 (seconds)
        "direction": "cw" | "ccw"            # default "cw"
    }

    stitched:   rotates to fps*duration discrete angles, captures a still at
                each, then assembles them into an MP4 with ffmpeg. Sharper
                frames, consistent exposure, but slow (≈ step+settle per frame).

    continuous: spins the platter smoothly through 360° while the camera
                records video in parallel. Real-time; looks more natural.

    Streams:
        data: {"phase": "capture",   "index": i, "total": N}
        data: {"phase": "recording", "elapsed": s, "duration": d}
        data: {"phase": "encoding"}
        data: {"phase": "uploading"}
    Final event:
        data: {"done": true, "sku": "...", "url": "...", "mode": "..."}
    """
    data      = request.get_json(force=True)
    sku       = data.get("sku", "unknown")
    mode      = data.get("mode", "stitched")
    fps       = int(data.get("fps", 30))
    duration  = float(data.get("duration", 10))
    direction = data.get("direction", "cw")
    cw        = direction != "ccw"

    if mode not in ("stitched", "continuous"):
        return jsonify({"error": "mode must be 'stitched' or 'continuous'"}), 400
    if fps <= 0 or duration <= 0:
        return jsonify({"error": "fps and duration must be positive"}), 400

    if mode == "stitched":
        gen = _video360_stitched(sku, fps, duration, cw)
    else:
        gen = _video360_continuous(sku, fps, duration, cw)

    return Response(
        gen,
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _video360_stitched(sku, fps, duration, cw):
    total = int(fps * duration)
    tmpdir = tempfile.mkdtemp(prefix="video360_")
    mp4_name = f"{sku}_360.mp4"
    mp4_path = os.path.join(tmpdir, mp4_name)
    try:
        yield f"data: {json.dumps({'phase':'starting','mode':'stitched','total':total,'fps':fps})}\n\n"
        sign = 1 if cw else -1
        for i in range(total):
            angle = ((i / total) * 360.0 * sign) % 360.0
            # Short settle — we're shooting for smooth playback, not max sharpness.
            rotate_to(angle, settle_s=0.05)
            frame_path = os.path.join(tmpdir, f"frame_{i:05d}.jpg")
            capture(frame_path)
            yield f"data: {json.dumps({'phase':'capture','index':i,'total':total})}\n\n"
        yield f"data: {json.dumps({'phase':'encoding'})}\n\n"
        frames_to_video(tmpdir, "frame_%05d.jpg", mp4_path, fps)
        yield f"data: {json.dumps({'phase':'uploading'})}\n\n"
        url = upload_file(mp4_path, mp4_name, mime_type="video/mp4")
        home()
        yield f"data: {json.dumps({'done':True,'sku':sku,'url':url,'mode':'stitched'})}\n\n"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _video360_continuous(sku, fps, duration, cw):
    tmpdir = tempfile.mkdtemp(prefix="video360_")
    mp4_name = f"{sku}_360.mp4"
    mp4_path = os.path.join(tmpdir, mp4_name)
    errors: list[BaseException] = []

    def _rec():
        try:
            record_video(mp4_path, duration, fps)
        except BaseException as e:
            errors.append(e)

    def _rot():
        try:
            rotate_continuous(duration, clockwise=cw)
        except BaseException as e:
            errors.append(e)

    try:
        yield f"data: {json.dumps({'phase':'starting','mode':'continuous','duration':duration,'fps':fps})}\n\n"
        rec_thread = threading.Thread(target=_rec, daemon=True)
        rot_thread = threading.Thread(target=_rot, daemon=True)
        start = time.monotonic()
        rec_thread.start()
        rot_thread.start()
        while rec_thread.is_alive() or rot_thread.is_alive():
            elapsed = time.monotonic() - start
            yield (
                "data: "
                + json.dumps({"phase": "recording",
                              "elapsed": round(elapsed, 2),
                              "duration": duration})
                + "\n\n"
            )
            time.sleep(0.5)
        rec_thread.join()
        rot_thread.join()
        if errors:
            raise errors[0]
        yield f"data: {json.dumps({'phase':'uploading'})}\n\n"
        url = upload_file(mp4_path, mp4_name, mime_type="video/mp4")
        home()
        yield f"data: {json.dumps({'done':True,'sku':sku,'url':url,'mode':'continuous'})}\n\n"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@bp.route("/status")
def status():
    return jsonify({"status": "ok"})


@bp.route("/release", methods=["POST"])
def release():
    """Manually release the motor (disable driver)."""
    from motor import release_motor
    release_motor()
    return jsonify({"status": "released"})
