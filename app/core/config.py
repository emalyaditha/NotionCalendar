import os
from typing import List
from pydantic import BaseModel

class Settings(BaseModel):
    NOTION_TOKEN: str = os.getenv("NOTION_TOKEN", "")
    DATABASE_ID: str = os.getenv("DATABASE_ID", "")
    GOOGLE_CALENDAR_ID: str = os.getenv("GOOGLE_CALENDAR_ID", "primary")
    GOOGLE_CREDENTIALS_FILE: str = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
    GOOGLE_TOKEN_FILE: str = os.getenv("GOOGLE_TOKEN_FILE", "token.json")
    
    # Environment specific overrides
    @property
    def calendar_id(self) -> str:
        import platform
        if 'replit' in platform.node().lower() or 'repl' in platform.node().lower():
            return os.getenv("GOOGLE_CALENDAR_ID_REPLIT", self.GOOGLE_CALENDAR_ID)
        return os.getenv("GOOGLE_CALENDAR_ID_LOCAL", self.GOOGLE_CALENDAR_ID)

settings = Settings()

def validate_settings():
    if not settings.NOTION_TOKEN:
        raise ValueError("NOTION_TOKEN environment variable is required")
    if not settings.DATABASE_ID:
        raise ValueError("DATABASE_ID environment variable is required")
