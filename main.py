# Rainbow Six Siege – 2-Player Operator/Kill Tracker for Discord
# --------------------------------------------------------------
# Additions in this version:
# - "View Remaining" buttons for each player (ephemeral embed with remaining Attackers/Defenders)
# - New /tracker remaining command to list remaining ops for a player
# - /tracker play now accepts player names as well as P1/P2 (with autocomplete)
# - Main tracker embed shows per-player usage with the actual names you provided

from __future__ import annotations

import os
import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Set, Literal, Optional

import discord
from discord import app_commands
from dotenv import load_dotenv

# Load environment variables from a .env file, if present
load_dotenv()

# ------------------------- Configuration ------------------------------------
ALLOW_PENALTY_ANYTIME = True  # Set True to always enable the -10 buttons
INTENTS = discord.Intents.default()  # No privileged intents required

# ------------------------- Operators (from user list) ------------------------
ATTACKERS: List[str] = [
    "Rauora", "Striker*", "Deimos", "Ram", "Brava", "Grim", "Sens", "Osa", "Flores", "Zero",
    "Ace", "Iana", "Kali", "Amaru", "NØKK", "Gridlock", "Nomad", "Maverick", "Lion", "Finka",
    "Dokkaebi", "Zofia", "Ying", "Jackal", "Hibana", "CAPITÃO", "Blackbeard", "Buck", "Sledge",
    "Thatcher", "Ash", "Thermite", "Montagne", "Twitch", "Blitz", "IQ", "Fuze", "Glaz",
]

DEFENDERS: List[str] = [
    "Denari", "Skopós", "Sentry*", "Tubarão", "Fenrir", "Solis", "Azami", "Thorn", "Thunderbird",
    "Aruni", "Melusi", "Oryx", "Wamai", "Goyo", "Warden", "Mozzie", "Kaid", "Clash", "Maestro",
    "Alibi", "Vigil", "Ela", "Lesion", "Mira", "Echo", "Caveira", "Valkyrie", "Frost", "Mute",
    "Smoke", "Castle", "Pulse", "Doc", "Rook", "Jäger", "Bandit", "Tachanka", "Kapkan",
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

# ------------------------- Helpers ------------------------------------------
def _norm(s: str) -> str:
    return (s or "").strip().lower()

def resolve_player_key(arg: str, state: TrackerState) -> Optional[Literal["P1", "P2"]]:
    """Accepts 'P1'/'P2' or the actual player names (case-insensitive)."""
    v = _norm(arg)
    if v in {"p1", "1", "player1"}:
        return "P1"
    if v in {"p2", "2", "player2"}:
        return "P2"
    if v == _norm(state.player1.name):
        return "P1"
    if v == _norm(state.player2.name):
        return "P2"
    return None

def split_list(items: List[str], max_chars: int = 900) -> List[str]:
    """Split a list of items into comma-joined chunks that fit in embed fields."""
    chunks: List[str] = []
    cur: List[str] = []
    cur_len = 0
    for itm in items:
        add = (2 if cur else 0) + len(itm)  # account for ", "
        if cur_len + add > max_chars:
            chunks.append(", ".join(cur))
            cur = [itm]
            cur_len = len(itm)
        else:
            cur.append(itm)
            cur_len += add
    if cur:
        chunks.append(", ".join(cur))
    if not chunks:
        chunks = ["—"]
    return chunks

def make_remaining_embed(state: TrackerState, which: Literal["P1", "P2"]) -> discord.Embed:
    p = state.player(which)
    rem = p.remaining_ops()
    rem_att = sorted(list(rem & ATT_SET))
    rem_def = sorted(list(rem & DEF_SET))

    embed = discord.Embed(
        title=f"Remaining Operators – {p.name}",
        color=discord.Color.green()
    )
    embed.set_footer(text="Only you can see this (ephemeral)")
    # Attackers
    att_chunks = split_list(rem_att)
    for i, chunk in enumerate(att_chunks, start=1):
        embed.add_field(name=f"Attackers ({len(rem_att)})" + (f" – {i}" if len(att_chunks) > 1 else ""), value=chunk or "—", inline=False)
    # Defenders
    def_chunks = split_list(rem_def)
    for i, chunk in enumerate(def_chunks, start=1):
        embed.add_field(name=f"Defenders ({len(rem_def)})" + (f" – {i}" if len(def_chunks) > 1 else ""), value=chunk or "—", inline=False)
    return embed

def make_full_snapshot_embeds(state: TrackerState) -> List[discord.Embed]:
    """Build a full, public snapshot: stats + played & remaining lists for both players."""
    # Main summary
    e_main = discord.Embed(
        title="🎯 2-Player Siege Tracker — Full Snapshot",
        color=discord.Color.blurple()
    )
    e_main.description = (
        "Totals and recent history per player. Full played/remaining lists are below.\n"
        "Tip: Use `/tracker remaining` for an ephemeral, per-player view."
    )
    e_main.add_field(name=f"Player 1 – {state.player1.name}", value=format_player_block(state.player1), inline=False)
    e_main.add_field(name=f"Player 2 – {state.player2.name}", value=format_player_block(state.player2), inline=False)

    def detail(p: PlayerState) -> discord.Embed:
        rem = p.remaining_ops()
        rem_att = sorted(list(rem & ATT_SET))
        rem_def = sorted(list(rem & DEF_SET))
        played_att = sorted(list(p.played & ATT_SET))
        played_def = sorted(list(p.played & DEF_SET))

        e = discord.Embed(title=f"Details — {p.name}", color=discord.Color.green())

        # Played lists
        played_att_chunks = split_list(played_att)
        for i, chunk in enumerate(played_att_chunks, start=1):
            e.add_field(
                name=f"Played Attackers ({len(played_att)})" + (f" – {i}" if len(played_att_chunks) > 1 else ""),
                value=chunk or "—",
                inline=False
            )
        played_def_chunks = split_list(played_def)
        for i, chunk in enumerate(played_def_chunks, start=1):
            e.add_field(
                name=f"Played Defenders ({len(played_def)})" + (f" – {i}" if len(played_def_chunks) > 1 else ""),
                value=chunk or "—",
                inline=False
            )

        # Remaining lists
        rem_att_chunks = split_list(rem_att)
        for i, chunk in enumerate(rem_att_chunks, start=1):
            e.add_field(
                name=f"Remaining Attackers ({len(rem_att)})" + (f" – {i}" if len(rem_att_chunks) > 1 else ""),
                value=chunk or "—",
                inline=False
            )
        rem_def_chunks = split_list(rem_def)
        for i, chunk in enumerate(rem_def_chunks, start=1):
            e.add_field(
                name=f"Remaining Defenders ({len(rem_def)})" + (f" – {i}" if len(rem_def_chunks) > 1 else ""),
                value=chunk or "—",
                inline=False
            )
        return e

    # Return 3 embeds total (well within Discord’s 10-embed limit)
    return [e_main, detail(state.player1), detail(state.player2)]


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

    @discord.ui.button(label="P1 View Remaining", style=discord.ButtonStyle.primary, custom_id="p1_remaining")
    async def p1_remaining(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild_id
        if guild_id is None or guild_id not in TRACKERS:
            await interaction.response.send_message("No active tracker here. Use /tracker start first.", ephemeral=True)
            return
        tracker = TRACKERS[guild_id]
        embed = make_remaining_embed(tracker, "P1")
        await interaction.response.send_message(embed=embed, ephemeral=True)

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

    @discord.ui.button(label="P2 View Remaining", style=discord.ButtonStyle.primary, custom_id="p2_remaining")
    async def p2_remaining(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild_id
        if guild_id is None or guild_id not in TRACKERS:
            await interaction.response.send_message("No active tracker here. Use /tracker start first.", ephemeral=True)
            return
        tracker = TRACKERS[guild_id]
        embed = make_remaining_embed(tracker, "P2")
        await interaction.response.send_message(embed=embed, ephemeral=True)

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
        f"**Kills:** {p.kills}\n"
        f"**Totals:** Played {len(p.played)} / {ALL_COUNT} • Remaining {ALL_COUNT - len(p.played)}\n"
        f"**Attackers:** {played_att}/{len(ATTACKERS)} played • {rem_att} remaining\n"
        f"Last A: {last_att}\n"
        f"**Defenders:** {played_def}/{len(DEFENDERS)} played • {rem_def} remaining\n"
        f"Last D: {last_def}\n"
        f"**Commands:** `/tracker play player:{p.name} operator:<name>` • `/tracker remaining player:{p.name}`"
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

    embed = discord.Embed(title="🎯 2-Player Siege Tracker", color=discord.Color.blurple())
    embed.description = (
        "Use **/tracker play** to mark an operator as played.\n"
        "Use the **View Remaining** buttons or `/tracker remaining` to see operators left.\n"
        "Buttons adjust kills. Penalty buttons are always available (−10). Attackers/Defenders tracked separately."
    )
    embed.add_field(name=f"Player 1 – {tracker.player1.name}", value=format_player_block(tracker.player1), inline=False)
    embed.add_field(name=f"Player 2 – {tracker.player2.name}", value=format_player_block(tracker.player2), inline=False)

    view = TrackerView(tracker)
    await msg.edit(embed=embed, view=view)

# ---- /tracker command group ----
tracker_group = app_commands.Group(name="tracker", description="2-Player R6S tracker")

@tracker_group.command(name="start", description="Start a new 2-player tracker in this channel")
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
    embed = discord.Embed(title="🎯 2-Player Siege Tracker", color=discord.Color.blurple())
    embed.description = (
        "Use **/tracker play** to mark an operator as played.\n"
        "Use the **View Remaining** buttons or `/tracker remaining` to see operators left.\n"
        "Buttons adjust kills. Penalty buttons are always available (−10). Attackers/Defenders tracked separately."
    )
    embed.add_field(name=f"Player 1 – {state.player1.name}", value=format_player_block(state.player1), inline=False)
    embed.add_field(name=f"Player 2 – {state.player2.name}", value=format_player_block(state.player2), inline=False)

    view = TrackerView(state)
    await interaction.response.send_message(embed=embed, view=view)
    msg = await interaction.original_response()
    state.message_id = msg.id
    state.channel_id = msg.channel.id

# ---------- Autocomplete helpers ----------
async def player_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    guild_id = interaction.guild_id
    options: List[str] = []
    if guild_id and guild_id in TRACKERS:
        st = TRACKERS[guild_id]
        options = [st.player1.name, st.player2.name, "P1", "P2"]
    else:
        options = ["P1", "P2"]
    cur = (current or "").lower()
    filtered = [o for o in options if cur in o.lower()]
    return [app_commands.Choice(name=o, value=o) for o in filtered[:25]]

# Autocomplete for operator names (filters to remaining operators for selected player)
async def op_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    guild_id = interaction.guild_id
    query = (current or "").strip().lower()

    # Default to all operators if no state yet
    ops_pool = ALL_OPERATORS

    if guild_id and guild_id in TRACKERS:
        state = TRACKERS[guild_id]
        # Determine which player is selected in the same command
        try:
            which_raw: str = str(interaction.namespace.player)  # can be 'P1','P2', or a name
        except Exception:
            which_raw = "P1"
        which = resolve_player_key(which_raw, state) or "P1"
        p = state.player(which)
        ops_pool = sorted(list(p.remaining_ops()))

    if query:
        ops_pool = [o for o in ops_pool if query in o.lower()]

    # Return up to 25 choices as required by Discord
    return [app_commands.Choice(name=o, value=o) for o in ops_pool[:25]]

# ---------- Commands ----------
@tracker_group.command(name="play", description="Mark an operator as played for a player")
@app_commands.describe(player="Who played? (P1/P2 or the player's name)", operator="Operator name")
@app_commands.autocomplete(player=player_autocomplete, operator=op_autocomplete)
async def tracker_play(interaction: discord.Interaction, player: str, operator: str):
    if interaction.guild_id is None:
        await interaction.response.send_message("Run this in a server channel, not DMs.", ephemeral=True)
        return
    if interaction.guild_id not in TRACKERS:
        await interaction.response.send_message("No active tracker here. Use /tracker start first.", ephemeral=True)
        return

    state = TRACKERS[interaction.guild_id]
    which = resolve_player_key(player, state)
    if which is None:
        await interaction.response.send_message("I couldn't match that player. Use P1/P2 or the exact name shown in the tracker.", ephemeral=True)
        return

    async with state.lock:
        # Validate operator
        if operator not in ALL_OPERATORS:
            await interaction.response.send_message(f"`{operator}` isn't a recognized operator.", ephemeral=True)
            return
        p = state.player(which)
        if not p.add_play(operator):
            await interaction.response.send_message(f"{p.name} already played **{operator}**.", ephemeral=True)
            return
        await update_tracker_message(interaction.client, state)
        await interaction.response.send_message(f"Marked **{operator}** as played for **{p.name}**.", ephemeral=True)

@tracker_group.command(name="remaining", description="Show remaining operators for a player")
@app_commands.describe(player="Which player? (P1/P2 or player's name)")
@app_commands.autocomplete(player=player_autocomplete)
async def tracker_remaining(interaction: discord.Interaction, player: str):
    if interaction.guild_id is None:
        await interaction.response.send_message("Run this in a server channel, not DMs.", ephemeral=True)
        return
    if interaction.guild_id not in TRACKERS:
        await interaction.response.send_message("No active tracker here. Use /tracker start first.", ephemeral=True)
        return

    state = TRACKERS[interaction.guild_id]
    which = resolve_player_key(player, state)
    if which is None:
        await interaction.response.send_message("I couldn't match that player. Use P1/P2 or the exact name shown in the tracker.", ephemeral=True)
        return

    embed = make_remaining_embed(state, which)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tracker_group.command(name="show", description="Repost/update the tracker message and post a full snapshot")
async def tracker_show(interaction: discord.Interaction):
    if interaction.guild_id is None or interaction.guild_id not in TRACKERS:
        await interaction.response.send_message("No active tracker here. Use /tracker start.", ephemeral=True)
        return
    state = TRACKERS[interaction.guild_id]
    async with state.lock:
        # Update the pinned/live tracker message first (so the buttons/summary stay current)
        await update_tracker_message(interaction.client, state)
        # Build a comprehensive snapshot
        embeds = make_full_snapshot_embeds(state)

    # Post the snapshot publicly in-channel (non-ephemeral)
    await interaction.response.send_message(embeds=embeds)

# Register the group
bot.tree.add_command(tracker_group)

# ------------------------- Run ----------------------------------------------
if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("Please set DISCORD_TOKEN environment variable.")
    bot.run(token)
