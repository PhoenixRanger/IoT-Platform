Import("env")
import os
from pathlib import Path

version = (Path(env.subst("$PROJECT_DIR")) / "VERSION").read_text().strip()
env.Append(CPPDEFINES=[("FIRMWARE_VERSION", f'\\"{version}\\"')])

if env.subst("$PIOENV") == "ota":
    ota_password = os.environ.get("OTA_PASSWORD")
    if not ota_password:
        raise RuntimeError("Set OTA_PASSWORD before building/uploading the ota environment")
    env.Append(UPLOAD_FLAGS=["--auth", ota_password])
