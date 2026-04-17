# lights_camera_action

Flask app running on a Raspberry Pi 4 that controls an automated watch photography turntable for Time Trader.

## What it does
- Controls a NEMA 17 stepper motor via DRV8825 driver (GPIO pins, BCM numbering)
- Captures photos via camera (USB or IMX477 CSI)
- Uploads photos to Google Drive using a service account
- Streams results back to the watchtrader app via SSE
- Serves a live MJPEG camera preview stream

## Hardware
- Raspberry Pi 4 4GB — hostname `lac`, user `jdogweb`
- NEMA 17 stepper motor (1.8°/step, 200 steps/rev)
- DRV8825 driver — STEP=GPIO17, DIR=GPIO27, EN=GPIO22 (BCM)
- IMX477 12.3MP camera (not yet connected — using USB camera in the meantime)
- GT2 belt drive, 200mm lazy Susan bearing, acrylic turntable plate
- 40cm LED lightbox

## Key files
- `app.py` — Flask entry point, port 5002, registers blueprint, sets up motor on startup
- `config.py` — Google Drive client, GPIO pin config, motor config (all from .env)
- `motor.py` — DRV8825 stepper control. Set `MOCK_GPIO=1` in .env to run on Mac without hardware
- `camera.py` — Camera capture. `CAMERA_TYPE=usb` for USB camera, `CAMERA_TYPE=picamera2` for IMX477
- `drive.py` — Upload local file to Google Drive, return shareable URL
- `video.py` — ffmpeg-based helper to stitch numbered frames into an MP4
- `routes.py` — All Flask routes
- `angles.json` — Saved shoot angles (created on first save via Camera Setup)

## API endpoints
- `GET /status` — health check
- `POST /shoot` — SSE stream: rotates through saved angles, captures + uploads each, streams Drive URLs back
- `POST /rotate` — rotate to angle `{"angle": 90}`
- `GET /preview` — MJPEG live camera stream
- `GET /angles` — get current saved shoot angles
- `POST /angles` — save new shoot angles `{"angles": [0, 60, 120, 180, 240, 300]}`
- `POST /capture` — single capture + Drive upload
- `POST /video360` — 360° video capture, SSE stream, final MP4 uploaded to Drive.
  Body: `{"sku": "TT123", "mode": "stitched"|"continuous", "fps": 30, "duration": 10, "direction": "cw"|"ccw"}`.
  `stitched` rotates to `fps*duration` discrete angles and ffmpeg-stitches the stills (sharper, slow).
  `continuous` spins the platter smoothly while the camera records video in parallel (real-time).
  Requires `ffmpeg` on PATH (`sudo apt install ffmpeg`) for stitched mode.

## Running on Pi
```bash
sudo systemctl start lca    # start
sudo systemctl restart lca  # restart
sudo systemctl status lca   # check logs
```

## Running locally (Mac, no hardware)
```bash
MOCK_GPIO=1 python3 app.py
```

## Auto-deploy from GitHub (Railway-style)
The Pi polls `origin/main` every 60s and restarts `lca.service` when new commits land.
Push → wait up to a minute → running. Driven by `deploy.sh` + the `systemd/lca-deploy.*` units.

**First-time setup (Mac):**
```bash
cd ~/lights_camera_action
git init && git add . && git commit -m "initial"
# Create empty repo on github.com (e.g. jdogweb/lights_camera_action), then:
git branch -M main
git remote add origin git@github.com:jdogweb/lights_camera_action.git
git push -u origin main
```

**First-time setup (Pi) — clone to `/home/jdogweb/lights_camera_action`:**
```bash
# Back up the secrets that are gitignored
cp ~/lights_camera_action/.env ~/lca-env.bak
cp ~/lights_camera_action/service_account.json ~/lca-sa.bak
cp ~/lights_camera_action/angles.json ~/lca-angles.bak 2>/dev/null || true

# Swap the folder for a fresh clone
mv ~/lights_camera_action ~/lights_camera_action.old
git clone git@github.com:jdogweb/lights_camera_action.git ~/lights_camera_action

# Restore the secrets
mv ~/lca-env.bak        ~/lights_camera_action/.env
mv ~/lca-sa.bak         ~/lights_camera_action/service_account.json
mv ~/lca-angles.bak     ~/lights_camera_action/angles.json 2>/dev/null || true

# Install the timer (one-time)
cd ~/lights_camera_action
./install-autodeploy.sh
```

**Day-to-day:** edit on Mac → `git push` → Pi pulls and restarts within 60s.
Tail the deploy log with `journalctl -u lca-deploy.service -f`.

Note: if `requirements.txt` changes, `deploy.sh` runs `pip install --user`. If you use a venv, edit `deploy.sh` to point at the venv's pip.

## Tunnel
The Pi is exposed via Cloudflare Tunnel (`cloudflared tunnel --url http://localhost:5002`) so the watchtrader Railway app can reach it. The tunnel URL changes on each restart — update `RPI_URL` in Railway env vars when it does.

## Google Drive
Uses the same service account as the watchtrader app (`service_account.json`). Uploads go to the folder set by `DRIVE_ID_FOLDER_ID` in `.env`.

## .env keys
```
DRIVE_ID_FOLDER_ID=
STEP_PIN=17
DIR_PIN=27
ENABLE_PIN=22
STEPS_PER_REV=200
MICROSTEP_MULT=8
STEP_DELAY_S=0.001
SETTLE_DELAY_S=0.3
CAMERA_TYPE=usb        # or picamera2
MOCK_GPIO=0            # set to 1 on Mac
USB_CAMERA_INDEX=0
```
