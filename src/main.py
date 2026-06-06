import sys
import logging
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import discord
from discord.ext import commands
import src.config as config
from src.db import Database
from src.nadeo.auth import NadeoAuth
from src.nadeo.client import NadeoClient
from src.oauth import OAuthClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class TrackManneke(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!!", intents=intents)
        self.db: Database = None
        self.nadeo_client: NadeoClient = None
        self.oauth_client: OAuthClient = None

    async def setup_hook(self):
        await self._initialize_services()
        await self.load_extension("src.cogs.admin")
        await self.load_extension("src.cogs.totd")
        print("Cogs loaded successfully.")

        if config.GUILD_ID:
            guild = discord.Object(id=int(config.GUILD_ID))
            self.tree.copy_global_to(guild=guild)

            await self.tree.sync(guild=guild)
            print(f"Slash commands synced with Guild: {config.GUILD_ID}")
        else:
            print("Error: No GUILD_ID found in the configuration! Slash commands will not be synced to any guild.")

    async def _initialize_services(self):
        """Initialize database, Nadeo client, and OAuth client."""
        try:
            self.db = Database("src/db/trackmania.db")
            self.db.connect()
            logger.info("Database initialized")

            if not config.NADEO_SERVICE_ACCOUNT_LOGIN or not config.NADEO_SERVICE_ACCOUNT_PASSWORD:
                logger.warning("Nadeo service account credentials not configured, Nadeo client will not be available")
            else:
                auth = NadeoAuth(
                    service_account_login=config.NADEO_SERVICE_ACCOUNT_LOGIN,
                    service_account_password=config.NADEO_SERVICE_ACCOUNT_PASSWORD,
                )
                self.nadeo_client = NadeoClient(
                    auth,
                    user_agent=config.USER_AGENT or "TrackmaniaBot/1.0",
                )
                logger.info("Nadeo client initialized")

            if not config.OAUTH_CLIENT_ID or not config.OAUTH_CLIENT_SECRET:
                logger.warning("OAuth credentials not configured, cannot fetch display names")
            else:
                self.oauth_client = OAuthClient(
                    client_id=config.OAUTH_CLIENT_ID,
                    client_secret=config.OAUTH_CLIENT_SECRET,
                )
                logger.info("OAuth client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize services: {e}")
            raise

    async def close(self):
        """Clean up resources on shutdown."""
        if self.db:
            self.db.disconnect()
        if self.nadeo_client:
            await self.nadeo_client.close()
        if self.oauth_client:
            await self.oauth_client.close()
        await super().close()

    async def on_ready(self):
        print(f"Bot is online: {self.user.name} (ID: {self.user.id})")



if __name__ == "__main__":
    if not config.DISCORD_TOKEN:
        print("Error: No DISCORD_TOKEN found in the .env file!")
    else:
        bot = TrackManneke()
        bot.run(config.DISCORD_TOKEN)