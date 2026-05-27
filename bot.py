import os
import asyncio
import threading

import discord
from discord.ext import commands
from flask import Flask, request, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

# ── 설정 ──────────────────────────────────────────────
BOT_TOKEN   = os.environ["DISCORD_BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]

CHANNEL_KEYWORDS = {
    "main":     "메인방",
    "private1": "밀담방1",
    "private2": "밀담방2",
    "private3": "밀담방3",
    "private4": "밀담방4",
}

# ── DB ────────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def lookup_token(token: str):
    """토큰으로 host 정보 조회. 없으면 None 반환."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT steam_id, discord_id FROM hosts WHERE token = %s", (token,))
            return cur.fetchone()

# ── Discord 클라이언트 ─────────────────────────────────
intents = discord.Intents.default()
intents.voice_states = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)

# bot.loop 에서 실행할 코루틴을 Flask 스레드에서 호출하기 위한 헬퍼
def run_coro(coro):
    future = asyncio.run_coroutine_threadsafe(coro, bot.loop)
    return future.result(timeout=10)

# ── Discord 유틸 ──────────────────────────────────────
async def get_host_voice_state(discord_id: str):
    """호스트가 현재 접속해 있는 VoiceChannel 반환. 없으면 None."""
    for guild in bot.guilds:
        member = guild.get_member(int(discord_id))
        if member and member.voice and member.voice.channel:
            return member.voice.channel
    return None

async def find_category_channels(voice_channel: discord.VoiceChannel) -> dict:
    """호스트 채널과 같은 카테고리에서 키워드로 채널 ID 매핑."""
    category = voice_channel.category
    if category is None:
        return {}

    result = {}
    for key, keyword in CHANNEL_KEYWORDS.items():
        for ch in category.voice_channels:
            if keyword in ch.name:
                result[key] = str(ch.id)
                break
    return result

async def get_voice_channel_members(voice_channel: discord.VoiceChannel) -> list:
    """같은 음성채널에 있는 멤버 목록 반환."""
    return [
        {"discord_id": str(m.id), "nickname": m.display_name}
        for m in voice_channel.members
    ]

async def move_member(discord_id: str, target_channel_id: str, host_discord_id: str) -> bool:
    """
    플레이어를 target_channel_id 로 이동.
    호스트가 같은 카테고리 안에 있을 때만 허용.
    """
    host_vc = await get_host_voice_state(host_discord_id)
    if host_vc is None:
        return False

    # 타겟 채널이 호스트 카테고리 안에 있는지 확인
    target_channel = bot.get_channel(int(target_channel_id))
    if target_channel is None:
        return False
    if target_channel.category_id != host_vc.category_id:
        return False

    # 플레이어가 현재 호스트 카테고리 안에 있는지 확인
    guild = host_vc.guild
    member = guild.get_member(int(discord_id))
    if member is None or member.voice is None:
        return False
    if member.voice.channel.category_id != host_vc.category_id:
        return False

    await member.move_to(target_channel)
    return True

async def send_dm(discord_id: str, message: str):
    user = await bot.fetch_user(int(discord_id))
    await user.send(message)

# ── Flask 앱 ──────────────────────────────────────────
app = Flask(__name__)
app.config["JSON_ENSURE_ASCII"] = False

@app.route("/auth", methods=["POST"])
def auth():
    """
    1~2단계: 호스트 토큰 인증 및 세션 데이터 반환
    입력: { token }
    출력: {
        host_steam_id, host_discord_id,
        channels: { main, private1~4 },
        players: [ { discord_id, nickname } ]
    }
    """
    data = request.get_json()
    token = data.get("token", "")

    host = lookup_token(token)
    if not host:
        return jsonify({"error": "invalid token"}), 401

    host_discord_id = host["discord_id"]
    host_steam_id   = host["steam_id"]

    # 호스트 음성채널 조회
    host_vc = run_coro(get_host_voice_state(host_discord_id))
    if host_vc is None:
        return jsonify({"error": "host not in voice channel"}), 400

    # 카테고리 내 채널 ID 수집
    channels = run_coro(find_category_channels(host_vc))

    # 같은 채널 멤버 목록
    players = run_coro(get_voice_channel_members(host_vc))

    # 호스트에게 DM 알림
    run_coro(send_dm(host_discord_id, "🎲 TTS 세션이 시작되었습니다."))

    return jsonify({
        "host_steam_id":   host_steam_id,
        "host_discord_id": host_discord_id,
        "channels":        channels,
        "players":         players,
    })


@app.route("/move", methods=["POST"])
def move():
    """
    4단계: 플레이어 음성채널 이동
    입력: { token, steam_id, discord_id, target_channel_id }
    출력: { success }
    """
    data = request.get_json()
    token             = data.get("token", "")
    discord_id        = data.get("discord_id", "")
    target_channel_id = data.get("target_channel_id", "")

    host = lookup_token(token)
    if not host:
        return jsonify({"error": "invalid token"}), 401

    success = run_coro(move_member(discord_id, target_channel_id, host["discord_id"]))
    if not success:
        return jsonify({"error": "move failed"}), 400

    return jsonify({"success": True})


# ── 실행 ──────────────────────────────────────────────
def run_flask():
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port)

@bot.event
async def on_ready():
    print(f"Bot ready: {bot.user}")
    # Flask를 별도 스레드에서 실행
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()

bot.run(BOT_TOKEN)