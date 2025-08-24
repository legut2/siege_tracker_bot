# Rainbow Six Siege – 2‑Player Operator/Kill Tracker for Discord
# --------------------------------------------------------------
# Features
# - Tracks kills for two players with +1 / -1 buttons
# - Tracks which operators each player has already played (Attackers & Defenders)
# - Slash command with autocomplete to mark an operator as "played"
# - "Penalty -10" button for each player that becomes enabled once that player has
#   used every operator (or anytime if you prefer — toggle via ALLOW_PENALTY_ANYTIME)
# - Single-file script. Requires: `pip install -U discord.py python-dotenv`
#
# Quick start
# 1) Create a Discord application & bot (https://discord.com/developers/applications)
# 2) Give the bot the following scopes when generating the invite URL:
#    - scopes: `bot applications.commands`
#    - bot permissions: Send Messages, Embed Links, Use Slash Commands
# 3) Set your token in the DISCORD_TOKEN environment variable
#    (or replace `os.getenv("DISCORD_TOKEN")` below with your token string for testing)
# 4) Run: `python discord_siege_tracker.py`
# 5) In your server, use: `/tracker start player1:<name> player2:<name>`
#    Then record plays: `/tracker play player:<P1 or P2> operator:<name>`
#
# Notes
# - State is kept in memory per guild. If the bot restarts, the active tracker view will reset.
# - Operator autocomplete suggests remaining operators matching your input.
# - The "Penalty -10" buttons enable automatically when a player has no operators left.
#   If you want the penalty button always enabled, set ALLOW_PENALTY_ANYTIME = True.

from __future__ import annotations

import os
import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Set, Literal

import discord
from discord import app_commands
from dotenv import load_dotenv
import io, json, time

# Load environment variables from a .env file, if present
load_dotenv()

# ---- Channel persistence config ----
STATE_CHANNEL_NAME = os.getenv("STATE_CHANNEL_NAME", "game-state")  # the channel name to store snapshots
STATE_SNAPSHOT_LIMIT = int(os.getenv("STATE_SNAPSHOT_LIMIT", "5"))    # keep last N snapshots per guild
SAVE_MIN_INTERVAL = float(os.getenv("SAVE_MIN_INTERVAL", "10.0"))     # debounce saves (seconds)
_LAST_SAVE: Dict[int, float] = {}

# ------------------------- Configuration ------------------------------------
ALLOW_PENALTY_ANYTIME = True  # Set True to always enable the -10 buttons
INTENTS = discord.Intents.default()  # No privileged intents required

# ------------------------- Operators (from user list) ------------------------
ATTACKERS: List[str] = [
    "Rauora",
    "Striker*",
    "Deimos",
    "Ram",
    "Brava",
    "Grim",
    "Sens",
    "Osa",
    "Flores",
    "Zero",
    "Ace",
    "Iana",
    "Kali",
    "Amaru",
    "NØKK",
    "Gridlock",
    "Nomad",
    "Maverick",
    "Lion",
    "Finka",
    "Dokkaebi",
    "Zofia",
    "Ying",
    "Jackal",
    "Hibana",
    "CAPITÃO",
    "Blackbeard",
    "Buck",
    "Sledge",
    "Thatcher",
    "Ash",
    "Thermite",
    "Montagne",
    "Twitch",
    "Blitz",
    "IQ",
    "Fuze",
    "Glaz",
]

DEFENDERS: List[str] = [
    "Denari",
    "Skopós",
    "Sentry*",
    "Tubarão",
    "Fenrir",
    "Solis",
    "Azami",
    "Thorn",
    "Thunderbird",
    "Aruni",
    "Melusi",
    "Oryx",
    "Wamai",
    "Goyo",
    "Warden",
    "Mozzie",
    "Kaid",
    "Clash",
    "Maestro",
    "Alibi",
    "Vigil",
    "Ela",
    "Lesion",
    "Mira",
    "Echo",
    "Caveira",
    "Valkyrie",
    "Frost",
    "Mute",
    "Smoke",
    "Castle",
    "Pulse",
    "Doc",
    "Rook",
    "Jäger",
    "Bandit",
    "Tachanka",
    "Kapkan",
]

ALL_OPERATORS: List[str] = ATTACKERS + DEFENDERS
ALL_COUNT = len(ALL_OPERATORS)
ATT_SET = set(ATTACKERS)
DEF_SET = set(DEFENDERS)

# ------------------------- Data Models --------------------------------------
@dataclass
class PlayerState:
    name: str
    kills: int = 0
    played: Set[str] = field(default_factory=set)
    history: List[str] = field(default_factory=list)

    def add_play(self, operator: str) -> bool:
        """Add an operator to this player's played set and history. Returns False if already played."""
        if operator in self.played:
            return False
        self.played.add(operator)
        self.history.append(operator)
        return True

    def remaining_ops(self) -> Set[str]:
        return set(ALL_OPERATORS) - self.played

    def remaining_counts(self) -> tuple[int, int]:
        rem = self.remaining_ops()
        return len(rem & ATT_SET), len(rem & DEF_SET)

@dataclass
class TrackerState:
    guild_id: int
    owner_id: int
    player1: PlayerState
    player2: PlayerState
    message_id: int | None = None
    channel_id: int | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def player(self, key: Literal["P1", "P2"]) -> PlayerState:
        return self.player1 if key == "P1" else self.player2

# guild_id -> TrackerState
TRACKERS: Dict[int, TrackerState] = {}

# ------------------------- Discord Channel Persistence ------------------------------------

# Reuse the same serialize/deserialize helpers

def serialize_state(state: TrackerState) -> dict:
    return {
        "version": 1,
        "guild_id": state.guild_id,
        "tracker": {
            "message_id": state.message_id,
            "channel_id": state.channel_id,
            "player1": {
                "name": state.player1.name,
                "kills": state.player1.kills,
                "played": sorted(list(state.player1.played)),
                "history": state.player1.history,
            },
            "player2": {
                "name": state.player2.name,
                "kills": state.player2.kills,
                "played": sorted(list(state.player2.played)),
                "history": state.player2.history,
            },
        },
    }

def deserialize_state(data: dict) -> TrackerState:
    p1 = data["tracker"]["player1"]
    p2 = data["tracker"]["player2"]
    return TrackerState(
        guild_id=int(data["guild_id"]),
        owner_id=0,
        player1=PlayerState(
            name=p1["name"],
            kills=int(p1["kills"]),
            played=set(p1.get("played", [])),
            history=list(p1.get("history", [])),
        ),
        player2=PlayerState(
            name=p2["name"],
            kills=int(p2["kills"]),
            played=set(p2.get("played", [])),
            history=list(p2.get("history", [])),
        ),
        message_id=data["tracker"].get("message_id"),
        channel_id=data["tracker"].get("channel_id"),
    )

async def get_state_channel(guild: discord.Guild) -> discord.TextChannel | None:
    if guild is None:
        return None
    # Try to find existing channel by name
    for ch in guild.text_channels:
        if ch.name == STATE_CHANNEL_NAME:
            return ch
    # Try to create if we have permission
    try:
        ch = await guild.create_text_channel(STATE_CHANNEL_NAME, reason="Siege tracker: create state channel")
        return ch
    except Exception:
        return None

async def save_state_to_channel(client: discord.Client, state: TrackerState, force: bool = False):
    now = time.monotonic()
    last = _LAST_SAVE.get(state.guild_id, 0.0)
    if not force and (now - last) < SAVE_MIN_INTERVAL:
        return
    _LAST_SAVE[state.guild_id] = now

    guild = client.get_guild(state.guild_id)
    if guild is None:
        return
    ch = await get_state_channel(guild)
    if ch is None:
        return

    payload = json.dumps(serialize_state(state), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    filename = f"state-{state.guild_id}-{int(time.time())}.json"
    try:
        await ch.send(content="【siege-tracker snapshot】", file=discord.File(io.BytesIO(payload), filename=filename))
    except Exception:
        return

    # Optional cleanup: keep only the most recent N snapshots from this bot
    try:
        snapshots = []
        async for msg in ch.history(limit=50):
            if msg.author.id == client.user.id and msg.attachments and "siege-tracker snapshot" in (msg.content or ""):
                snapshots.append(msg)
        # Keep newest STATE_SNAPSHOT_LIMIT
        snapshots.sort(key=lambda m: m.created_at, reverse=True)
        for msg in snapshots[STATE_SNAPSHOT_LIMIT:]:
            try:
                await msg.delete()
            except Exception:
                pass
    except Exception:
        pass

async def load_state_from_channel(client: discord.Client, guild: discord.Guild):
    ch = await get_state_channel(guild)
    if ch is None:
        return
    try:
        async for msg in ch.history(limit=50):
            if msg.author.id != client.user.id or not msg.attachments:
                continue
            for att in msg.attachments:
                if att.filename.endswith(".json"):
                    raw = await att.read()
                    data = json.loads(raw.decode("utf-8"))
                    restored = deserialize_state(data)
                    TRACKERS[guild.id] = restored
                    try:
                        await update_tracker_message(client, restored)
                    except Exception:
                        pass
                    return
    except Exception:
        pass

# ------------------------- UI Components ------------------------------------
class TrackerView(discord.ui.View):
    def __init__(self, tracker: TrackerState):
        super().__init__(timeout=None)
        self.tracker = tracker
        # Initialize button states based on remaining operators
        self.update_penalty_buttons()

    # ------ Helpers ------
    def update_penalty_buttons(self):
        p1_done = len(self.tracker.player1.remaining_ops()) == 0
        p2_done = len(self.tracker.player2.remaining_ops()) == 0
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.custom_id == "penalty_p1":
                    item.disabled = (not ALLOW_PENALTY_ANYTIME) and (not p1_done)
                elif item.custom_id == "penalty_p2":
                    item.disabled = (not ALLOW_PENALTY_ANYTIME) and (not p2_done)

    # ------ P1 Buttons ------
    @discord.ui.button(label="P1 +1 Kill", style=discord.ButtonStyle.success, custom_id="p1_plus")
    async def p1_plus(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._adjust_kills(interaction, "P1", +1)

    @discord.ui.button(label="P1 -1 Kill", style=discord.ButtonStyle.secondary, custom_id="p1_minus")
    async def p1_minus(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._adjust_kills(interaction, "P1", -1)

    @discord.ui.button(label="P1 Penalty -10", style=discord.ButtonStyle.danger, custom_id="penalty_p1")
    async def penalty_p1(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._adjust_kills(interaction, "P1", -10)

    # ------ P2 Buttons ------
    @discord.ui.button(label="P2 +1 Kill", style=discord.ButtonStyle.success, custom_id="p2_plus")
    async def p2_plus(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._adjust_kills(interaction, "P2", +1)

    @discord.ui.button(label="P2 -1 Kill", style=discord.ButtonStyle.secondary, custom_id="p2_minus")
    async def p2_minus(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._adjust_kills(interaction, "P2", -1)

    @discord.ui.button(label="P2 Penalty -10", style=discord.ButtonStyle.danger, custom_id="penalty_p2")
    async def penalty_p2(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._adjust_kills(interaction, "P2", -10)

    # ------ Shared ------
    async def _adjust_kills(self, interaction: discord.Interaction, which: Literal["P1", "P2"], delta: int):
        guild_id = interaction.guild_id
        if guild_id is None or guild_id not in TRACKERS:
            await interaction.response.send_message("No active tracker here. Use /tracker start first.", ephemeral=True)
            return
        tracker = TRACKERS[guild_id]
        async with tracker.lock:
            p = tracker.player(which)
            p.kills = max(0, p.kills + delta)
            # Update penalty button states in case something changed
            self.update_penalty_buttons()
            await update_tracker_message(interaction.client, tracker)
            await save_state_to_channel(interaction.client, tracker)
            try:
                await interaction.response.defer()  # Acknowledge without extra message
            except discord.InteractionResponded:
                pass

# ------------------------- Bot & Commands -----------------------------------
class SiegeTracker(discord.Client):
    def __init__(self):
        super().__init__(intents=INTENTS)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        # Sync commands globally; for faster iteration, you can limit to a test guild
        await self.tree.sync()

bot = SiegeTracker()

# ---- Helpers to render/update the main message ----

def format_player_block(p: PlayerState) -> str:
    rem_att, rem_def = p.remaining_counts()
    played_att = len(p.played & ATT_SET)
    played_def = len(p.played & DEF_SET)

    def last_from_history(side_set: Set[str], n: int = 5) -> str:
        seen: Set[str] = set()
        out: List[str] = []
        for op in reversed(p.history):
            if op in side_set and op not in seen:
                out.append(op)
                seen.add(op)
            if len(out) >= n:
                break
        return ", ".join(out) if out else "—"

    last_att = last_from_history(ATT_SET)
    last_def = last_from_history(DEF_SET)

    return (
        f"**Kills:** {p.kills}"
        f"**Totals:** Played {len(p.played)} / {ALL_COUNT} • Remaining {ALL_COUNT - len(p.played)}"
        f"**Attackers:** {played_att}/{len(ATTACKERS)} played • {rem_att} remaining"
        f"Last A: {last_att}"
        f"**Defenders:** {played_def}/{len(DEFENDERS)} played • {rem_def} remaining"
        f"Last D: {last_def}"
    )

async def update_tracker_message(client: discord.Client, tracker: TrackerState):
    if tracker.channel_id is None or tracker.message_id is None:
        return
    channel = client.get_channel(tracker.channel_id)
    if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
        return
    try:
        msg = await channel.fetch_message(tracker.message_id)
    except discord.NotFound:
        return

    embed = discord.Embed(title="🎯 2‑Player Siege Tracker", color=discord.Color.blurple())
    embed.description = (
        "Use **/tracker play** to mark an operator as played."
        "Buttons adjust kills. Penalty buttons are always available (−10). Attackers/Defenders tracked separately."
    )
    embed.add_field(name=f"Player 1 – {tracker.player1.name}", value=format_player_block(tracker.player1), inline=False)
    embed.add_field(name=f"Player 2 – {tracker.player2.name}", value=format_player_block(tracker.player2), inline=False)

    view = TrackerView(tracker)
    await msg.edit(embed=embed, view=view)

# ---- /tracker command group ----
tracker_group = app_commands.Group(name="tracker", description="2‑Player R6S tracker")

@tracker_group.command(name="start", description="Start a new 2‑player tracker in this channel")
@app_commands.describe(player1="Display name for Player 1", player2="Display name for Player 2")
async def tracker_start(interaction: discord.Interaction, player1: str, player2: str):
    if interaction.guild_id is None:
        await interaction.response.send_message("Run this in a server channel, not DMs.", ephemeral=True)
        return

    state = TrackerState(
        guild_id=interaction.guild_id,
        owner_id=interaction.user.id,
        player1=PlayerState(name=player1),
        player2=PlayerState(name=player2),
    )
    TRACKERS[interaction.guild_id] = state

    # Send initial message with view
    embed = discord.Embed(title="🎯 2‑Player Siege Tracker", color=discord.Color.blurple())
    embed.description = (
        "Use **/tracker play** to mark an operator as played."
        "Buttons adjust kills. Penalty buttons are always available (−10). Attackers/Defenders tracked separately."
    )
    embed.add_field(name=f"Player 1 – {state.player1.name}", value=format_player_block(state.player1), inline=False)
    embed.add_field(name=f"Player 2 – {state.player2.name}", value=format_player_block(state.player2), inline=False)

    view = TrackerView(state)
    await interaction.response.send_message(embed=embed, view=view)
    msg = await interaction.original_response()
    state.message_id = msg.id
    state.channel_id = msg.channel.id

    # Persist initial state
    await save_state_to_channel(interaction.client, state, force=True)

# Autocomplete for operator names (filters to remaining operators for selected player)
async def op_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    guild_id = interaction.guild_id
    query = (current or "").strip().lower()

    # Default to all operators if no state yet
    ops_pool = ALL_OPERATORS

    if guild_id and guild_id in TRACKERS:
        state = TRACKERS[guild_id]
        # Which player was chosen in the same command?
        try:
            which: str = str(interaction.namespace.player)  # "P1" or "P2"
        except Exception:
            which = "P1"
        p = state.player(which) if which in ("P1", "P2") else state.player1
        ops_pool = sorted(list(p.remaining_ops()))

    if query:
        ops_pool = [o for o in ops_pool if query in o.lower()]

    # Return up to 25 choices as required by Discord
    return [app_commands.Choice(name=o, value=o) for o in ops_pool[:25]]

@tracker_group.command(name="play", description="Mark an operator as played for a player")
@app_commands.describe(player="Which player?", operator="Operator name (autocomplete)")
@app_commands.autocomplete(operator=op_autocomplete)
async def tracker_play(interaction: discord.Interaction, player: Literal["P1", "P2"], operator: str):
    if interaction.guild_id is None:
        await interaction.response.send_message("Run this in a server channel, not DMs.", ephemeral=True)
        return
    if interaction.guild_id not in TRACKERS:
        await interaction.response.send_message("No active tracker here. Use /tracker start first.", ephemeral=True)
        return

    state = TRACKERS[interaction.guild_id]
    async with state.lock:
        # Validate operator
        if operator not in ALL_OPERATORS:
            await interaction.response.send_message(f"`{operator}` isn't a recognized operator.", ephemeral=True)
            return
        p = state.player(player)
        if not p.add_play(operator):
            await interaction.response.send_message(f"{p.name} already played **{operator}**.", ephemeral=True)
            return
        await update_tracker_message(interaction.client, state)
        await save_state_to_channel(interaction.client, state)
        await interaction.response.send_message(f"Marked **{operator}** as played for **{p.name}**.", ephemeral=True)

# Optional: show current status again
@tracker_group.command(name="show", description="Repost/update the tracker message if it went missing")
async def tracker_show(interaction: discord.Interaction):
    if interaction.guild_id is None or interaction.guild_id not in TRACKERS:
        await interaction.response.send_message("No active tracker here. Use /tracker start.", ephemeral=True)
        return
    state = TRACKERS[interaction.guild_id]
    async with state.lock:
        await update_tracker_message(interaction.client, state)
    await interaction.response.send_message("Tracker refreshed.", ephemeral=True)

# Restore state on startup for all guilds
@bot.event
async def on_ready():
    for g in bot.guilds:
        try:
            await load_state_from_channel(bot, g)
        except Exception:
            pass

# Register the group
bot.tree.add_command(tracker_group)

# ------------------------- Run ----------------------------------------------
if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("Please set DISCORD_TOKEN environment variable.")
    bot.run(token)
