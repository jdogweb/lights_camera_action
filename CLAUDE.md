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
- IMX477 12.3MP camera (CSI, connected via ribbon)
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

## Pi camera (IMX477) bringup test
After (re)wiring the CSI ribbon, run this on the Pi to verify the camera
stack end-to-end before flipping the app over to it:

```bash
cd ~/lights_camera_action

# 1. OS-level smoke test (5s preview to /tmp/cam.jpg)
rpicam-still -o /tmp/cam.jpg --timeout 2000 || libcamera-still -o /tmp/cam.jpg --timeout 2000

# 2. Python / picamera2 path used by the app (still + 2s video)
python3 test_camera.py

# 3. Flip the app over to the Pi camera and restart
sed -i 's/^CAMERA_TYPE=.*/CAMERA_TYPE=picamera2/' .env
sudo systemctl restart lca
sudo systemctl status lca --no-pager

# 4. Hit the live endpoints (from the Pi or another machine on the LAN)
curl -s http://localhost:5002/status
curl -s -X POST http://localhost:5002/capture \
     -H 'Content-Type: application/json' \
     -d '{"filename":"camera_bringup_test.jpg"}'
# and visit  http://lac.local:5002/preview  in a browser for the MJPEG stream
```

If `test_camera.py` fails at the import step:
`sudo apt install -y python3-picamera2 --no-install-recommends`.
If it fails at "detect cameras", reseat the CSI ribbon (blue tab toward the
ethernet jack on the Pi end) and check `dmesg | grep -i imx477`.


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
The Pi is exposed via Cloudflare Tunnel (`cloudflared tunnel --url http://localhost:5002`) so the watchtrader Railway app can reach it.

The tunnel runs as a systemd service (`cloudflared-quick.service`, see
`systemd/cloudflared-quick.service`). It auto-starts on Pi boot and
auto-restarts on crash. **Caveat: every restart gives a new
`*.trycloudflare.com` URL** because we're using the free quick-tunnel
tier. To recover after a Pi reboot:

```bash
# On the Pi: pull the URL out of the journal
sudo journalctl -u cloudflared-quick.service --no-pager \
  | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1

# On your Mac: push it into Railway
cd /tmp/railway-rpi-update && railway variables \
  --set "RPI_URL=https://...new-url...trycloudflare.com"
```

For a stable URL across reboots, switch to a named/persistent Cloudflare tunnel
(requires a free Cloudflare account: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/tunnel-guide/local/).

## Google Drive
Uses the same service account as the watchtrader app (`service_account.json`). Uploads go to the folder set by `DRIVE_ID_FOLDER_ID` in `.env`.

## .env keys
```
DRIVE_ID_FOLDER_ID=
STEP_PIN=17
DIR_PIN=27
ENABLE_PIN=22
SLP_PIN=23
STEPS_PER_REV=200
MICROSTEP_MULT=8
STEP_DELAY_S=0.003     # half-period of step pulse; 0.001 is fast/jittery, 0.003 is the bringup default
SETTLE_DELAY_S=0.3
GEAR_RATIO=1.538       # measured 2026-04-27: commanded 360°, platter travelled ~234° at GR=1, so 360/234 ≈ 1.538
CAMERA_TYPE=picamera2  # or usb
CAMERA_FLIP=1          # 1 if camera mounted upside down (applies to preview, stills, video)
MOCK_GPIO=0            # set to 1 on Mac
USB_CAMERA_INDEX=0
```

## Calibration notes
- The motor↔platter mechanical reduction was measured by commanding `POST /rotate/relative {"degrees": 360}` with `GEAR_RATIO=1.0` and observing how far a tape mark on the platter actually travelled. Result: ~234°, giving a corrected ratio of `360/234 ≈ 1.538`.
- If you re-tension the belt or swap a pulley, repeat that test and update `GEAR_RATIO` in `.env`.
- `STEP_DELAY_S` controls the half-period of each microstep pulse. Smaller = faster but at some point the motor will start losing steps under load. `0.003` is comfortable for a loaded turntable.
