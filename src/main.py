import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import discord
from discord.ext import commands
import src.config as config

class TrackManneke(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!!", intents=intents)

    async def setup_hook(self):
            await self.load_extension("src.cogs.admin")
            print("Cogs loaded successfully.")

            if config.GUILD_ID:
                guild = discord.Object(id=int(config.GUILD_ID))
                self.tree.copy_global_to(guild=guild)
                
                await self.tree.sync(guild=guild)
                print(f"Slash commands synced with Guild: {config.GUILD_ID}")
            else:
                print("Error: No GUILD_ID found in the configuration! Slash commands will not be synced to any guild.")

    async def on_ready(self):
        print(f"Bot is online: {self.user.name} (ID: {self.user.id})")

if __name__ == "__main__":
    if not config.DISCORD_TOKEN:
        print("Error: No DISCORD_TOKEN found in the .env file!")
    else:
        bot = TrackManneke()
        bot.run(config.DISCORD_TOKEN)