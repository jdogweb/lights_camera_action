import io
from googleapiclient.http import MediaIoBaseUpload
from config import DRIVE_CLIENT, DRIVE_ID_FOLDER_ID


def upload_file(local_path: str, filename: str, mime_type: str = "image/jpeg") -> str:
    """Upload a local file to Google Drive, make it public, return shareable URL."""
    with open(local_path, "rb") as f:
        data = f.read()
    file_metadata = {"name": filename}
    if DRIVE_ID_FOLDER_ID:
        file_metadata["parents"] = [DRIVE_ID_FOLDER_ID]
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type)
    uploaded = DRIVE_CLIENT.files().create(
        body=file_metadata,
        media_body=media,
        fields="id",
        supportsAllDrives=True,
    ).execute()
    file_id = uploaded["id"]
    DRIVE_CLIENT.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
        supportsAllDrives=True,
    ).execute()
    return f"https://drive.google.com/file/d/{file_id}/view"
