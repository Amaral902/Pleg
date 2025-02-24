import discord
from discord.ext import commands
import os
import asyncio
import yt_dlp
from dotenv import load_dotenv
import urllib.parse, urllib.request, re

def run_bot():
    load_dotenv()
    TOKEN = os.getenv('token')
    intents = discord.Intents.default()
    intents.message_content = True
    client = commands.Bot(command_prefix=".", intents=intents)

    queues = {}
    voice_clients = {}
    youtube_base_url = 'https://www.youtube.com/'
    youtube_results_url = youtube_base_url + 'results?'
    youtube_watch_url = youtube_base_url + 'watch?v='
    yt_dl_options = {"format": "bestaudio/best"}
    ytdl = yt_dlp.YoutubeDL(yt_dl_options)

    ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -nostdin',
    'options': '-vn -loglevel panic -hide_banner -filter:a "volume=0.25"',
    'executable': 'path to ffmpeg goes here'  # Use 'ffmpeg' if it's globally installed also you need to inser the ffmpeg location
    }
    @client.event
    async def on_ready():
        print(f'{client.user} is now jamming')

    async def play_next(ctx):
        if ctx.guild.id in queues and queues[ctx.guild.id]:
            title, link = queues[ctx.guild.id].pop(0)
            await play(ctx, link=link, skip_queue=True)
        else:
            await ctx.send("Queue is empty! Add some songs to keep the music going.")

    @client.command(name="play")
    async def play(ctx, *, link=None, skip_queue=False):
        if ctx.author.voice is None:
            await ctx.send("You are not connected to a voice channel.")
            return
        
        if ctx.guild.id not in voice_clients or not voice_clients[ctx.guild.id].is_connected():
            try:
                voice_client = await ctx.author.voice.channel.connect()
                voice_clients[ctx.guild.id] = voice_client
            except Exception as e:
                await ctx.send(f"Error connecting to voice channel: {e}")
                return

        if link:
            if youtube_base_url not in link:
                query_string = urllib.parse.urlencode({'search_query': link})
                content = urllib.request.urlopen(youtube_results_url + query_string)
                search_results = re.findall(r'/watch\?v=(.{11})', content.read().decode())
                link = youtube_watch_url + search_results[0]

            try:
                loop = asyncio.get_event_loop()
                data = await loop.run_in_executor(None, lambda: ytdl.extract_info(link, download=False))
                title = data['title']
                song = data['url']

                if not skip_queue and ctx.guild.id in queues and queues[ctx.guild.id]:
                    queues[ctx.guild.id].append((title, link))
                    await ctx.send(f"**Added to queue:** {title}")
                    return

                player = discord.FFmpegOpusAudio(song, **ffmpeg_options)
                voice_clients[ctx.guild.id].play(player, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx), client.loop))
                await ctx.send(f"**Playing:** {title}")
            except Exception as e:
                await ctx.send(f"Error playing song: {e}")
        else:
            await play_next(ctx)

    @client.command(name="clear_queue")
    async def clear_queue(ctx):
        if ctx.guild.id in queues:
            queues[ctx.guild.id].clear()
            await ctx.send("Queue cleared!")
        else:
            await ctx.send("There is no queue to clear.")

    @client.command(name="pause")
    async def pause(ctx):
        try:
            voice_clients[ctx.guild.id].pause()
            await ctx.send("Playback paused.")
        except Exception as e:
            await ctx.send(f"Error pausing playback: {e}")

    @client.command(name="resume")
    async def resume(ctx):
        try:
            voice_clients[ctx.guild.id].resume()
            await ctx.send("Playback resumed.")
        except Exception as e:
            await ctx.send(f"Error resuming playback: {e}")

    @client.command(name="stop")
    async def stop(ctx):
        try:
            if ctx.guild.id in voice_clients:
                await voice_clients[ctx.guild.id].disconnect()
                del voice_clients[ctx.guild.id]
            await ctx.send("Playback stopped.")
        except Exception as e:
            await ctx.send(f"Error stopping playback: {e}")

    @client.command(name="queue")
    async def queue(ctx):
        if ctx.guild.id not in queues or not queues[ctx.guild.id]:
            await ctx.send("The queue is empty.")
            return

        queue_list = "\n".join([f"{i+1}. {title}" for i, (title, _) in enumerate(queues[ctx.guild.id])])
        await ctx.send(f"**Music Queue:**\n{queue_list}")

    @client.command(name="skip")
    async def skip(ctx):
        try:
            if ctx.guild.id in voice_clients and voice_clients[ctx.guild.id].is_playing():
                voice_clients[ctx.guild.id].stop()
                await ctx.send("Skipped current song.")
            else:
                await ctx.send("There is no song playing to skip.")
        except Exception as e:
            await ctx.send(f"Error skipping song: {e}")

    @client.command(name="add")
    async def add(ctx, *, link):
        if ctx.guild.id not in queues:
            queues[ctx.guild.id] = []
        
        if youtube_base_url not in link:
            query_string = urllib.parse.urlencode({'search_query': link})
            content = urllib.request.urlopen(youtube_results_url + query_string)
            search_results = re.findall(r'/watch\?v=(.{11})', content.read().decode())
            link = youtube_watch_url + search_results[0]

        try:
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(link, download=False))
            title = data['title']
            queues[ctx.guild.id].append((title, link))

            if not voice_clients.get(ctx.guild.id, None):
                await play(ctx, link=None)
            else:
                await ctx.send(f"**Added to queue:** {title}")
        except Exception as e:
            await ctx.send(f"Error adding song: {e}")
   

    client.run(TOKEN)

run_bot()
