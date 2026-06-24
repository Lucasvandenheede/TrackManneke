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
NADEO_SERVICE_ACCOUNT_LOGIN = os.getenv("NADEO_SERVICE_ACCOUNT_LOGIN")
NADEO_SERVICE_ACCOUNT_PASSWORD = os.getenv("NADEO_SERVICE_ACCOUNT_PASSWORD")

OAUTH_CLIENT_ID = os.getenv("OAUTH_CLIENT_ID")
OAUTH_CLIENT_SECRET = os.getenv("OAUTH_CLIENT_SECRET")

TOTD_CHANNEL_ID = os.getenv("TOTD_CHANNEL_ID")
COTD_CHANNEL_ID = os.getenv("COTD_CHANNEL_ID")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Brussels")

EMOTE_AT_ID = "1512639786689626154" if APP_ENV not in {"production", "prod"} else "1457699626533785631"
EMOTE_AT = f"<:AT:{EMOTE_AT_ID}>"
