import discord
from discord.ext import commands
from discord import app_commands
import os
import asyncio
import yt_dlp
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import urllib.parse, urllib.request, re
import logging
import random

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Spotify credentials (replace these with your actual credentials)
SPOTIFY_CLIENT_ID = "spotify client id here"
TOKEN = "token goes here"
SPOTIFY_CLIENT_SECRET = "insert client here"

# Set up Spotify client
spotify = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=SPOTIFY_CLIENT_ID,
                                                                 client_secret=SPOTIFY_CLIENT_SECRET))

# Set up Discord intents
intents = discord.Intents.default()
intents.message_content = True
client = commands.Bot(command_prefix=".", intents=intents)

# Dictionary to store queues and voice clients
queues = {}
voice_clients = {}
youtube_base_url = 'https://www.youtube.com/'
youtube_results_url = youtube_base_url + 'results?'
youtube_watch_url = youtube_base_url + 'watch?v='

# YouTube downloader options
yt_dl_options = {
    "format": "bestaudio/best",
    "quiet": True,
    "no_warnings": True,
    "ignoreerrors": True,
    "noplaylist": True,
    "extract_flat": "in_playlist",
    "default_search": "auto",
    'verbose': True,
}
ytdl = yt_dlp.YoutubeDL(yt_dl_options)

# FFMPEG options
ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin',
    'options': '-vn -loglevel panic -hide_banner -filter:a "volume=0.25"',
    'executable': 'path to ffmpeg goes here'  # Use 'ffmpeg' if it's globally installed also you need to inser the ffmpeg location
}

@client.event
async def on_ready():
    logger.info(f'{client.user} is now jamming')
    try:
        synced = await client.tree.sync()
        logger.info(f"Synced {len(synced)} commands")
    except Exception as e:
        logger.error(f"Error syncing commands: {e}")

# Function to stop playback and disconnect
async def stop_playback(guild_id):
    if guild_id in voice_clients and voice_clients[guild_id].is_connected():
        await voice_clients[guild_id].disconnect()
        voice_clients[guild_id] = None
        logger.info(f"Disconnected from guild {guild_id}")

# Play the next song in the queue
async def play_next(guild_id):
    if guild_id in queues and queues[guild_id]:
        title, link = queues[guild_id].pop(0)
        logger.info(f"Playing next song in queue: {title}")
        await play_song_by_link(guild_id, link)
    else:
        logger.info(f"No more songs in queue for guild {guild_id}.")

# Function to play a song from a link (used by play_next)
async def play_song_by_link(guild_id, link):
    voice_client = voice_clients.get(guild_id)
    if not voice_client:
        return

    loop = asyncio.get_event_loop()
    try:
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(link, download=False))
        title = data.get('title', 'Unknown')
        song = data.get('url')

        if not voice_client.is_playing():
            voice_client.play(discord.FFmpegPCMAudio(song, **ffmpeg_options),
                              after=lambda e: asyncio.run_coroutine_threadsafe(play_next(guild_id), client.loop))
            logger.info(f"Now playing: {title}")
    except Exception as e:
        logger.error(f"Error playing song: {e}")

# Function to play a song or a playlist
async def play_song(interaction: discord.Interaction, link: str, skip_queue: bool = False):
    if interaction.user.voice is None:
        await interaction.response.send_message("You are not connected to a voice channel.", ephemeral=True)
        return

    voice_client = voice_clients.get(interaction.guild.id)

    if not voice_client or not voice_client.is_connected():
        try:
            voice_client = await interaction.user.voice.channel.connect()
            voice_clients[interaction.guild.id] = voice_client
            logger.info(f"Connected to voice channel: {interaction.user.voice.channel.name}")
        except Exception as e:
            logger.error(f"Error connecting to voice channel: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"Error connecting to voice channel: {e}", ephemeral=True)
            return

    # Check if it's a Spotify playlist or track
    if 'spotify.com' in link:
        if 'playlist' in link:
            await handle_spotify_playlist(interaction, link)
        elif 'track' in link:
            link = await convert_spotify_to_youtube(link)

    # Handle YouTube or other links
    if 'youtube.com' not in link:
        try:
            query_string = urllib.parse.urlencode({'search_query': link})
            content = urllib.request.urlopen(youtube_results_url + query_string)
            search_results = re.findall(r'/watch\?v=(.{11})', content.read().decode())
            link = youtube_watch_url + search_results[0]
        except Exception as e:
            logger.error(f"Error retrieving YouTube link: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"Error retrieving YouTube link: {e}", ephemeral=True)
            return

    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)

        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(link, download=False))
        title = data.get('title', 'Unknown')
        thumbnail_url = data.get('thumbnail')
        song = data.get('url')

        # Add song to queue if not skipping
        if not skip_queue:
            if interaction.guild.id not in queues:
                queues[interaction.guild.id] = []
            queues[interaction.guild.id].append((title, link))

            if voice_client.is_playing():
                await interaction.followup.send(f"Added {title} to the queue.", ephemeral=True)
                return

        # Play the song if not already playing
        if not voice_client.is_playing():
            voice_client.play(discord.FFmpegPCMAudio(song, **ffmpeg_options),
                              after=lambda e: asyncio.run_coroutine_threadsafe(play_next(interaction.guild.id), client.loop))

            embed = discord.Embed(title="Now Playing", description=title, color=discord.Color.blue())
            if thumbnail_url:
                embed.set_thumbnail(url=thumbnail_url)
            embed.add_field(name="Link", value=f"[Watch on YouTube]({link})", inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)

    except Exception as e:
        logger.error(f"Error playing song: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message(f"Error playing song: {e}", ephemeral=True)

async def convert_spotify_to_youtube(link: str) -> str:
    try:
        if 'track' in link:
            track_info = spotify.track(link)
            query = f"{track_info['name']} {track_info['artists'][0]['name']}"
        else:
            return None

        query_string = urllib.parse.urlencode({'search_query': query})
        content = urllib.request.urlopen(youtube_results_url + query_string)
        search_results = re.findall(r'/watch\?v=(.{11})', content.read().decode())
        return youtube_watch_url + search_results[0]
    except Exception as e:
        logger.error(f"Error converting Spotify link: {e}")
        return None

# Handle Spotify playlist
async def handle_spotify_playlist(interaction: discord.Interaction, playlist_link: str):
    try:
        playlist_id = playlist_link.split("/")[-1].split("?")[0]
        playlist = spotify.playlist(playlist_id)

        for item in playlist['tracks']['items']:
            track = item['track']
            song_link = await convert_spotify_to_youtube(track['external_urls']['spotify'])
            if song_link:
                if interaction.guild.id not in queues:
                    queues[interaction.guild.id] = []
                queues[interaction.guild.id].append((track['name'], song_link))

        await interaction.followup.send(f"Added {playlist['name']} playlist to the queue.", ephemeral=True)
        await play_next(interaction.guild.id)

    except Exception as e:
        logger.error(f"Error processing Spotify playlist: {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message(f"Error processing playlist: {e}", ephemeral=True)

# Skip the currently playing song
@client.tree.command(name="skip", description="Skip the currently playing song")
async def skip(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    voice_client = voice_clients.get(guild_id)

    if voice_client and voice_client.is_playing():
        voice_client.stop()
        await interaction.response.send_message("Skipped the song.", ephemeral=True)
        await play_next(guild_id)
    else:
        await interaction.response.send_message("No song is currently playing.", ephemeral=True)

# Show the queue
@client.tree.command(name="queue", description="Show the current queue")
async def show_queue(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    if guild_id in queues and queues[guild_id]:
        queue_list = '\n'.join([f"{idx + 1}. {title}" for idx, (title, _) in enumerate(queues[guild_id])])
        await interaction.response.send_message(f"Current queue:\n{queue_list}", ephemeral=True)
    else:
        await interaction.response.send_message("The queue is empty.", ephemeral=True)

# Shuffle the queue
@client.tree.command(name="shuffle", description="Shuffle the current queue")
async def shuffle(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    if guild_id in queues and queues[guild_id]:
        random.shuffle(queues[guild_id])
        await interaction.response.send_message("Queue shuffled.", ephemeral=True)
    else:
        await interaction.response.send_message("The queue is empty, nothing to shuffle.", ephemeral=True)

# Add a song to the queue or playlist
@client.tree.command(name="play", description="Play a song or add it to the queue")
@app_commands.describe(link="The YouTube or Spotify link or search query for the song")
async def play(interaction: discord.Interaction, link: str):
    await play_song(interaction, link=link)

# Stop the bot and disconnect
@client.tree.command(name="stop", description="Stop playback and disconnect")
async def stop(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    await stop_playback(guild_id)
    await interaction.response.send_message("Stopped playback and disconnected.", ephemeral=True)

# Run the bot
client.run(TOKEN)
