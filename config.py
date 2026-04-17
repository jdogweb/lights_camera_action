import os
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

load_dotenv()

DRIVE_ID_FOLDER_ID = os.getenv("DRIVE_ID_FOLDER_ID", "")

SCOPES = ["https://www.googleapis.com/auth/drive"]
CREDS = Credentials.from_service_account_file("service_account.json", scopes=SCOPES)
DRIVE_CLIENT = build("drive", "v3", credentials=CREDS)

# GPIO pin config (BCM numbering)
STEP_PIN   = int(os.getenv("STEP_PIN", "17"))
DIR_PIN    = int(os.getenv("DIR_PIN", "27"))
ENABLE_PIN = int(os.getenv("ENABLE_PIN", "22"))

# Motor config
STEPS_PER_REV  = int(os.getenv("STEPS_PER_REV", "200"))    # 1.8° motor = 200 full steps/rev
MICROSTEP_MULT = int(os.getenv("MICROSTEP_MULT", "8"))      # DRV8825 1/8 microstepping
STEP_DELAY_S   = float(os.getenv("STEP_DELAY_S", "0.001"))  # Delay between pulses
SETTLE_DELAY_S = float(os.getenv("SETTLE_DELAY_S", "0.3"))  # Settle time after rotate
