import os
import time

MOCK = os.getenv("MOCK_GPIO", "0") == "1"

if MOCK:
    class _FakeGPIO:
        BCM = HIGH = LOW = OUT = 0
        def setmode(self, *a): pass
        def setup(self, *a): pass
        def output(self, pin, val): print(f"[MOCK GPIO] pin={pin} val={val}")
        def cleanup(self): pass
    GPIO = _FakeGPIO()
else:
    import RPi.GPIO as GPIO

from config import (
    STEP_PIN, DIR_PIN, ENABLE_PIN,
    STEPS_PER_REV, MICROSTEP_MULT,
    STEP_DELAY_S, SETTLE_DELAY_S,
)

_current_step = 0  # Absolute position in microsteps
_last_activity = 0  # Timestamp of last motor activity
IDLE_TIMEOUT_S = 30  # Disable motor after 30s of inactivity


def _enable_driver():
    """Enable the motor driver."""
    GPIO.output(ENABLE_PIN, GPIO.LOW)


def _disable_driver():
    """Disable the motor driver to prevent heating."""
    GPIO.output(ENABLE_PIN, GPIO.HIGH)


def _update_activity():
    """Update last activity timestamp and enable driver."""
    global _last_activity
    _last_activity = time.time()
    _enable_driver()


def setup():
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(STEP_PIN, GPIO.OUT)
    GPIO.setup(DIR_PIN, GPIO.OUT)
    GPIO.setup(ENABLE_PIN, GPIO.OUT)
    _update_activity()


def rotate_to(target_degrees: float, settle_s: float | None = None):
    """Rotate to absolute angle (0–359°) via shortest path.

    Pass settle_s to override the default SETTLE_DELAY_S (useful for video
    frames where a shorter settle is acceptable). Pass 0 to skip settle.
    """
    global _current_step
    _update_activity()  # Enable driver before moving
    total = STEPS_PER_REV * MICROSTEP_MULT
    target_step = round(target_degrees / 360 * total) % total
    delta = (target_step - _current_step) % total
    if delta > total // 2:
        delta -= total  # Shorter backwards path
    direction = GPIO.HIGH if delta >= 0 else GPIO.LOW
    GPIO.output(DIR_PIN, direction)
    for _ in range(abs(delta)):
        GPIO.output(STEP_PIN, GPIO.HIGH)
        time.sleep(STEP_DELAY_S)
        GPIO.output(STEP_PIN, GPIO.LOW)
        time.sleep(STEP_DELAY_S)
    _current_step = target_step
    settle = SETTLE_DELAY_S if settle_s is None else settle_s
    if settle > 0:
        time.sleep(settle)
    _check_idle_disable()


def rotate_continuous(duration_s: float, clockwise: bool = True):
    """Rotate exactly 360° smoothly over duration_s seconds.

    Step pulses are spread evenly across the duration so the platter
    maintains a constant angular velocity — used by the continuous
    video-capture mode. The logical position is unchanged (we end up
    back where we started).
    """
    _update_activity()  # Enable driver before moving
    total = STEPS_PER_REV * MICROSTEP_MULT
    # Each microstep is one HIGH/LOW pulse pair with a sleep on each half.
    half_period = max(0.0, duration_s / total / 2)
    direction = GPIO.HIGH if clockwise else GPIO.LOW
    GPIO.output(DIR_PIN, direction)
    for _ in range(total):
        GPIO.output(STEP_PIN, GPIO.HIGH)
        time.sleep(half_period)
        GPIO.output(STEP_PIN, GPIO.LOW)
        time.sleep(half_period)
    # Back at start position after a full revolution — no change to _current_step.
    _check_idle_disable()


def _check_idle_disable():
    """Disable driver if idle for more than IDLE_TIMEOUT_S."""
    if time.time() - _last_activity > IDLE_TIMEOUT_S:
        _disable_driver()


def home():
    """Reset logical position to 0 without physically moving."""
    global _current_step
    _current_step = 0


def cleanup():
    GPIO.output(ENABLE_PIN, GPIO.HIGH)  # Disable driver
    GPIO.cleanup()
