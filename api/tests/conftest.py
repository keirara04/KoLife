import base64
import os

from app.config import settings

# tests never use a real key; documents encrypted here are throwaway
settings.master_key = base64.b64encode(os.urandom(32)).decode()
