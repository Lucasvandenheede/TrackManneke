import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
ENV_FILE = os.getenv("ENV_FILE")

if ENV_FILE:
	dotenv_path = BASE_DIR / ENV_FILE
elif APP_ENV in {"production", "prod"}:
	dotenv_path = BASE_DIR / ".env.production"
else:
	dotenv_path = BASE_DIR / ".env"

load_dotenv(dotenv_path)

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("GUILD_ID")

USER_AGENT = os.getenv("USER_AGENT")
UBISOFT_EMAIL = os.getenv("UBISOFT_EMAIL")
UBISOFT_PASSWORD = os.getenv("UBISOFT_PASSWORD")
NADEO_CLIENT_ID = os.getenv("NADEO_CLIENT_ID")
NADEO_CLIENT_SECRET = os.getenv("NADEO_CLIENT_SECRET")