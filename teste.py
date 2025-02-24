try:
    from discord_slash import SlashCommand, SlashContext
    print("discord-py-slash-command is installed correctly.")
except ImportError:
    print("Failed to import discord-py-slash-command.")