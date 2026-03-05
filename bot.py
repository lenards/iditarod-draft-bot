import os
import discord
from discord import app_commands
from discord.ext import commands
from typing import Optional
from dotenv import load_dotenv
from session import DraftSession, ALL_MUSHERS

load_dotenv()

TOKEN = os.environ["DISCORD_TOKEN"]
_channel_ids = os.environ.get("DRAFT_CHANNEL_IDS", "")
DRAFT_CHANNEL_IDS: set[int] = {
    int(cid.strip()) for cid in _channel_ids.split(",") if cid.strip().isdigit()
}

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# Sessions keyed by channel ID — each channel is an independent league
live_sessions: dict[int, DraftSession] = {}
mock_sessions: dict[int, DraftSession] = {}


def get_live(channel_id: int) -> DraftSession:
    if channel_id not in live_sessions:
        live_sessions[channel_id] = DraftSession(label="Live Draft")
    return live_sessions[channel_id]


def get_mock(channel_id: int) -> DraftSession:
    if channel_id not in mock_sessions:
        mock_sessions[channel_id] = DraftSession(label="Mock Draft")
    return mock_sessions[channel_id]


# ── channel guard ──────────────────────────────────────────────────────────

def in_draft_channel(interaction: discord.Interaction) -> bool:
    return not DRAFT_CHANNEL_IDS or interaction.channel_id in DRAFT_CHANNEL_IDS


# ── embed builders ─────────────────────────────────────────────────────────

def available_embed(session: DraftSession, filter_status: str = "all") -> discord.Embed:
    mushers = session.available(None if filter_status == "all" else filter_status)
    prefix = "🎮 Mock — " if session.label == "Mock Draft" else ""

    if not mushers:
        return discord.Embed(
            title=f"{prefix}🐕 Available Mushers",
            description="No mushers available with that filter.",
            color=0xcc3300,
        )

    rookies = [m for m in mushers if m.is_rookie]
    veterans = [m for m in mushers if not m.is_rookie]

    embed = discord.Embed(
        title=f"{prefix}🐕 Available Mushers — {len(mushers)} remaining",
        color=0x1a6b3c,
    )

    if filter_status in ("all", "rookie") and rookies:
        embed.add_field(
            name=f"🌟 Rookies ({len(rookies)})",
            value="\n".join(f"• {m.name}" for m in rookies),
            inline=True,
        )
    if filter_status in ("all", "veteran") and veterans:
        embed.add_field(
            name=f"⭐ Veterans ({len(veterans)})",
            value="\n".join(f"• {m.name}" for m in veterans),
            inline=True,
        )
    return embed


def status_embed(session: DraftSession) -> discord.Embed:
    prefix = "🎮 " if session.label == "Mock Draft" else ""
    color = 0x7289da if session.label == "Mock Draft" else 0x1a6b3c

    embed = discord.Embed(title=f"{prefix}{session.label} Status", color=color)

    if not session.is_configured:
        embed.description = "Not set up yet. An admin needs to run `/setup` first."
        return embed

    if session.is_complete:
        embed.description = "✅ Draft is complete!"
        return embed

    if not session.is_active:
        embed.description = "Configured but not started. Admin runs `/draft_start` to begin."
        embed.add_field(
            name="Round 1 Draft Order",
            value="\n".join(session.order_lines()),
            inline=False,
        )
        return embed

    on_clock_id = session.current_drafter_id
    on_clock_name = session.names.get(on_clock_id, "Unknown")
    next_id = session.next_drafter_id
    on_deck_name = session.names.get(next_id, "—") if next_id else "—"

    embed.add_field(name="🎯 On the Clock", value=f"**{on_clock_name}**", inline=True)
    embed.add_field(name="⏭ On Deck", value=on_deck_name, inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    embed.add_field(name="Round", value=f"{session.current_round} of {session.picks_per_person}", inline=True)
    embed.add_field(name="Overall Pick", value=f"{session.overall_pick_num} of {session.total_picks}", inline=True)
    embed.add_field(name="Available", value=str(len(session.available())), inline=True)
    return embed


def picks_embed(session: DraftSession, user_id: int, display_name: str) -> discord.Embed:
    prefix = "🎮 Mock — " if session.label == "Mock Draft" else ""
    picks = session.get_user_picks(user_id)

    embed = discord.Embed(
        title=f"{prefix}🐕 {display_name}'s Picks",
        color=0x7289da if session.label == "Mock Draft" else 0x1a6b3c,
    )

    if not picks:
        embed.description = "No picks yet."
    else:
        lines = []
        for i, m in enumerate(picks, 1):
            tag = "🌟" if m.is_rookie else "⭐"
            lines.append(f"{i}. {tag} **{m.name}** ({m.status})")
        embed.description = "\n".join(lines)

    has_rookie = any(m.is_rookie for m in picks)
    picks_left = session.picks_per_person - len(picks)
    footer_parts = [f"{len(picks)}/{session.picks_per_person} picks made"]
    if picks_left > 0 and not has_rookie:
        footer_parts.append("⚠️ Still needs a Rookie pick!")
    elif has_rookie:
        footer_parts.append("✅ Rookie requirement met")
    embed.set_footer(text=" | ".join(footer_parts))
    return embed


def all_picks_embed(session: DraftSession) -> discord.Embed:
    prefix = "🎮 Mock — " if session.label == "Mock Draft" else ""
    embed = discord.Embed(
        title=f"{prefix}🐕 All Draft Picks",
        color=0x7289da if session.label == "Mock Draft" else 0x1a6b3c,
    )
    if not session.is_configured:
        embed.description = "Draft not configured yet."
        return embed
    for uid in session.participants:
        name = session.names.get(uid, str(uid))
        picks = session.picks.get(uid, [])
        if picks:
            lines = [
                f"{'🌟' if m.is_rookie else '⭐'} {m.name} ({m.status})"
                for m in picks
            ]
            value = "\n".join(lines)
        else:
            value = "_No picks yet_"
        embed.add_field(name=name, value=value, inline=True)
    return embed


# ── autocomplete ───────────────────────────────────────────────────────────

async def musher_autocomplete(interaction: discord.Interaction, current: str):
    live = get_live(interaction.channel_id)
    source = live.available() if live.is_configured else ALL_MUSHERS
    return [
        app_commands.Choice(name=m.name, value=m.name)
        for m in source
        if current.lower() in m.name.lower()
    ][:25]


async def mock_musher_autocomplete(interaction: discord.Interaction, current: str):
    mock = get_mock(interaction.channel_id)
    source = mock.available() if mock.is_configured else ALL_MUSHERS
    return [
        app_commands.Choice(name=m.name, value=m.name)
        for m in source
        if current.lower() in m.name.lower()
    ][:25]


# ── bot events ─────────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    synced = await bot.tree.sync()
    print(f"Logged in as {bot.user} | {len(synced)} slash commands synced")


# ── admin commands ─────────────────────────────────────────────────────────

@bot.tree.command(name="setup", description="[Admin] Configure draft participants and rounds")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    rounds="Picks per person (default: 4)",
    user1="Participant 1", user2="Participant 2", user3="Participant 3",
    user4="Participant 4", user5="Participant 5", user6="Participant 6",
    user7="Participant 7", user8="Participant 8",
)
async def setup(
    interaction: discord.Interaction,
    rounds: int = 4,
    user1: Optional[discord.Member] = None,
    user2: Optional[discord.Member] = None,
    user3: Optional[discord.Member] = None,
    user4: Optional[discord.Member] = None,
    user5: Optional[discord.Member] = None,
    user6: Optional[discord.Member] = None,
    user7: Optional[discord.Member] = None,
    user8: Optional[discord.Member] = None,
):
    members = [u for u in [user1, user2, user3, user4, user5, user6, user7, user8] if u]
    if len(members) < 2:
        await interaction.response.send_message(
            "❌ Need at least 2 participants. Add them with the `user1`, `user2`, … parameters.",
            ephemeral=True,
        )
        return

    live = get_live(interaction.channel_id)
    live.configure(members, picks_per_person=rounds)

    rookies = sum(1 for m in ALL_MUSHERS if m.is_rookie)
    veterans = len(ALL_MUSHERS) - rookies

    embed = discord.Embed(
        title="🐕 Iditarod Fantasy Draft — Configured!",
        description=(
            f"**{len(members)} participants** · **{rounds} picks each** · "
            f"**{len(members) * rounds} total picks**\n"
            f"Musher pool: {len(ALL_MUSHERS)} total ({rookies} Rookies, {veterans} Veterans)"
        ),
        color=0x1a6b3c,
    )
    embed.add_field(
        name="Round 1 Order (as entered)",
        value="\n".join(live.order_lines()),
        inline=False,
    )
    embed.add_field(
        name="Next steps",
        value="• `/randomize` — shuffle the order randomly\n"
              "• `/set_order` — set a specific order (e.g. last year's results)\n"
              "• `/draft_start` — begin the draft\n"
              "• `/mock_start` — let people practice first",
        inline=False,
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="randomize", description="[Admin] Randomly shuffle the draft order")
@app_commands.checks.has_permissions(administrator=True)
async def randomize(interaction: discord.Interaction):
    live = get_live(interaction.channel_id)
    if not live.is_configured:
        await interaction.response.send_message("❌ Run `/setup` first!", ephemeral=True)
        return
    if live.is_active:
        await interaction.response.send_message("❌ Can't shuffle after the draft has started.", ephemeral=True)
        return

    live.randomize()
    embed = discord.Embed(title="🎲 Draft Order Randomized!", color=0x1a6b3c)
    embed.add_field(name="New Round 1 Order", value="\n".join(live.order_lines()), inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="set_order", description="[Admin] Set the exact Round 1 draft order")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    first="Picks 1st", second="Picks 2nd", third="Picks 3rd", fourth="Picks 4th",
    fifth="Picks 5th", sixth="Picks 6th", seventh="Picks 7th", eighth="Picks 8th",
)
async def set_order(
    interaction: discord.Interaction,
    first: discord.Member,
    second: discord.Member,
    third: Optional[discord.Member] = None,
    fourth: Optional[discord.Member] = None,
    fifth: Optional[discord.Member] = None,
    sixth: Optional[discord.Member] = None,
    seventh: Optional[discord.Member] = None,
    eighth: Optional[discord.Member] = None,
):
    if not live.is_configured:
        await interaction.response.send_message("❌ Run `/setup` first!", ephemeral=True)
        return
    if live.is_active:
        await interaction.response.send_message("❌ Can't change the order after the draft has started.", ephemeral=True)
        return

    live = get_live(interaction.channel_id)
    if not live.is_configured:
        await interaction.response.send_message("❌ Run `/setup` first!", ephemeral=True)
        return
    if live.is_active:
        await interaction.response.send_message("❌ Can't change the order after the draft has started.", ephemeral=True)
        return

    members = [m for m in [first, second, third, fourth, fifth, sixth, seventh, eighth] if m]
    ok, msg = live.set_explicit_order(members)
    if not ok:
        await interaction.response.send_message(f"❌ {msg}", ephemeral=True)
        return

    embed = discord.Embed(title="✅ Draft Order Set!", color=0x1a6b3c)
    embed.add_field(name="Round 1 Order", value="\n".join(live.order_lines()), inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="draft_start", description="[Admin] Start the live draft")
@app_commands.checks.has_permissions(administrator=True)
async def draft_start(interaction: discord.Interaction):
    live = get_live(interaction.channel_id)
    if not live.is_configured:
        await interaction.response.send_message("❌ Run `/setup` first!", ephemeral=True)
        return
    if live.is_active:
        await interaction.response.send_message("❌ The draft is already running!", ephemeral=True)
        return

    live.start()

    on_clock_id = live.current_drafter_id
    next_id = live.next_drafter_id

    embed = discord.Embed(
        title="🏁 The 2026 Iditarod Fantasy Draft Has Begun!",
        description=(
            f"Snake draft · {live.picks_per_person} rounds · {live.total_picks} total picks\n"
            f"Remember: every drafter must pick **at least one Rookie** musher!"
        ),
        color=0x1a6b3c,
    )
    embed.add_field(name="🎯 On the Clock", value=f"<@{on_clock_id}>", inline=True)
    on_deck_str = f"<@{next_id}>" if next_id else "—"
    embed.add_field(name="⏭ On Deck", value=on_deck_str, inline=True)
    embed.add_field(name="How to pick", value="`/pick` then type a musher name (autocomplete available)", inline=False)

    await interaction.response.send_message(embed=embed)
    await interaction.channel.send(
        f"<@{on_clock_id}> — you're on the clock! 🕐 Use `/pick` to draft your musher."
    )


@bot.tree.command(name="draft_reset", description="[Admin] Completely reset the live draft")
@app_commands.checks.has_permissions(administrator=True)
async def draft_reset(interaction: discord.Interaction):
    get_live(interaction.channel_id).reset()
    await interaction.response.send_message(
        "🔄 Live draft has been reset. Run `/setup` to configure a new draft."
    )


# ── participant commands ────────────────────────────────────────────────────

@bot.tree.command(name="available", description="List undrafted mushers")
@app_commands.describe(filter="Filter by status (default: all)")
@app_commands.choices(filter=[
    app_commands.Choice(name="All", value="all"),
    app_commands.Choice(name="Rookies only", value="rookie"),
    app_commands.Choice(name="Veterans only", value="veteran"),
])
async def available_cmd(interaction: discord.Interaction, filter: str = "all"):
    await interaction.response.send_message(embed=available_embed(get_live(interaction.channel_id), filter))


@bot.tree.command(name="pick", description="Draft a musher (only works when it's your turn)")
@app_commands.describe(musher="Start typing to search available mushers")
@app_commands.autocomplete(musher=musher_autocomplete)
async def pick(interaction: discord.Interaction, musher: str):
    if not in_draft_channel(interaction):
        await interaction.response.send_message(
            "❌ Draft picks must be made in the draft channel.", ephemeral=True
        )
        return

    live = get_live(interaction.channel_id)
    success, message, picked, pick_num, round_num = live.make_pick(interaction.user.id, musher)

    if not success:
        await interaction.response.send_message(f"❌ {message}", ephemeral=True)
        return

    color = 0xf5a623 if picked.is_rookie else 0x1a6b3c
    embed = discord.Embed(
        title=f"✅ Pick #{pick_num} — Round {round_num}",
        color=color,
    )
    status_tag = "🌟 Rookie" if picked.is_rookie else "⭐ Veteran"
    embed.add_field(name="Drafter", value=interaction.user.display_name, inline=True)
    embed.add_field(name="Musher", value=f"**{picked.name}**", inline=True)
    embed.add_field(name="Status", value=status_tag, inline=True)

    await interaction.response.send_message(embed=embed)

    if live.is_complete:
        await interaction.channel.send(
            "🏁 **The draft is complete!** Use `/allpicks` to see everyone's teams. Good luck on the trail! 🐕"
        )
    else:
        next_id = live.current_drafter_id
        await interaction.channel.send(
            f"<@{next_id}> — you're on the clock! 🕐 "
            f"Round {live.current_round}, pick {live.overall_pick_num} of {live.total_picks}. "
            f"Use `/pick` to draft your musher."
        )


@bot.tree.command(name="whos_up", description="Show who is currently on the clock")
async def whos_up(interaction: discord.Interaction):
    live = get_live(interaction.channel_id)
    if not live.is_active:
        await interaction.response.send_message("The draft hasn't started yet.", ephemeral=True)
        return
    if live.is_complete:
        await interaction.response.send_message("The draft is complete!", ephemeral=True)
        return
    on_clock_id = live.current_drafter_id
    next_id = live.next_drafter_id
    on_deck = f" | ⏭ On deck: {live.names.get(next_id)}" if next_id else ""
    await interaction.response.send_message(
        f"🎯 **{live.names.get(on_clock_id)}** is on the clock "
        f"(Round {live.current_round}, pick {live.overall_pick_num}/{live.total_picks}){on_deck}"
    )


@bot.tree.command(name="status", description="Show the current draft status")
async def status(interaction: discord.Interaction):
    await interaction.response.send_message(embed=status_embed(get_live(interaction.channel_id)))


@bot.tree.command(name="mypicks", description="See your current draft picks (private)")
async def mypicks(interaction: discord.Interaction):
    live = get_live(interaction.channel_id)
    embed = picks_embed(live, interaction.user.id, interaction.user.display_name)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="picks", description="See a participant's draft picks")
@app_commands.describe(user="Which participant to view (defaults to you)")
async def picks_cmd(interaction: discord.Interaction, user: Optional[discord.Member] = None):
    live = get_live(interaction.channel_id)
    target = user or interaction.user
    await interaction.response.send_message(
        embed=picks_embed(live, target.id, target.display_name)
    )


@bot.tree.command(name="allpicks", description="See everyone's picks at once")
async def allpicks(interaction: discord.Interaction):
    await interaction.response.send_message(embed=all_picks_embed(get_live(interaction.channel_id)))


# ── mock draft commands ─────────────────────────────────────────────────────

@bot.tree.command(name="mock_start", description="Start a mock draft using the configured participants")
async def mock_start(interaction: discord.Interaction):
    live = get_live(interaction.channel_id)
    if not live.is_configured:
        await interaction.response.send_message(
            "❌ The draft participants haven't been configured yet. "
            "An admin needs to run `/setup` first.",
            ephemeral=True,
        )
        return

    mock = get_mock(interaction.channel_id)
    mock.configure_from_ids(live.participants[:], live.names.copy(), live.picks_per_person)
    mock.randomize()
    mock.start()

    on_clock_id = mock.current_drafter_id

    embed = discord.Embed(
        title="🎮 Mock Draft Started — Practice Run!",
        description="Picks here don't affect the real draft. Use this to get a feel for the bot.",
        color=0x7289da,
    )
    embed.add_field(
        name="Mock Round 1 Order (randomized)",
        value="\n".join(mock.order_lines()),
        inline=False,
    )
    embed.add_field(name="On the Clock", value=f"**{mock.names.get(on_clock_id)}**", inline=False)
    embed.set_footer(text="Use /mock_pick to draft · /mock_reset to clear · /mock_status to check state")

    await interaction.response.send_message(embed=embed)
    await interaction.channel.send(
        f"<@{on_clock_id}> — you're first in the mock draft! Use `/mock_pick` to go."
    )


@bot.tree.command(name="mock_pick", description="Make a pick in the mock draft")
@app_commands.describe(musher="Start typing to search available mushers")
@app_commands.autocomplete(musher=mock_musher_autocomplete)
async def mock_pick(interaction: discord.Interaction, musher: str):
    mock = get_mock(interaction.channel_id)
    success, message, picked, pick_num, round_num = mock.make_pick(interaction.user.id, musher)

    if not success:
        await interaction.response.send_message(f"❌ {message}", ephemeral=True)
        return

    embed = discord.Embed(
        title=f"🎮 Mock Pick #{pick_num} — Round {round_num}",
        color=0x7289da,
    )
    status_tag = "🌟 Rookie" if picked.is_rookie else "⭐ Veteran"
    embed.add_field(name="Drafter", value=interaction.user.display_name, inline=True)
    embed.add_field(name="Musher", value=f"**{picked.name}**", inline=True)
    embed.add_field(name="Status", value=status_tag, inline=True)

    await interaction.response.send_message(embed=embed)

    if mock.is_complete:
        await interaction.channel.send(
            "🎮 **Mock draft complete!** Run `/mock_reset` for another practice round, "
            "or `/mock_start` to try a different order."
        )
    else:
        next_id = mock.current_drafter_id
        await interaction.channel.send(
            f"<@{next_id}> — you're on the clock in the mock draft! 🎮 "
            f"Round {mock.current_round}. Use `/mock_pick`."
        )


@bot.tree.command(name="mock_status", description="Show the mock draft status")
async def mock_status(interaction: discord.Interaction):
    await interaction.response.send_message(embed=status_embed(get_mock(interaction.channel_id)))


@bot.tree.command(name="mock_available", description="List available mushers in the mock draft")
@app_commands.choices(filter=[
    app_commands.Choice(name="All", value="all"),
    app_commands.Choice(name="Rookies only", value="rookie"),
    app_commands.Choice(name="Veterans only", value="veteran"),
])
async def mock_available(interaction: discord.Interaction, filter: str = "all"):
    await interaction.response.send_message(embed=available_embed(get_mock(interaction.channel_id), filter))


@bot.tree.command(name="mock_reset", description="Reset the mock draft")
async def mock_reset(interaction: discord.Interaction):
    get_mock(interaction.channel_id).reset()
    await interaction.response.send_message(
        "🎮 Mock draft reset. Run `/mock_start` for another practice round."
    )


# ── help ───────────────────────────────────────────────────────────────────

@bot.tree.command(name="draft_help", description="Show all available draft bot commands")
async def draft_help(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🐕 Iditarod Fantasy Draft Bot — Commands",
        description="Snake draft bot for the 2026 Iditarod Trail Sled Dog Race.\nEvery drafter must pick **at least one Rookie** musher!",
        color=0x1a6b3c,
    )
    embed.add_field(
        name="📋 Draft Info",
        value=(
            "`/status` — full draft status, who's on the clock\n"
            "`/whos_up` — quick one-liner: who's on the clock\n"
            "`/available` — list undrafted mushers (filter by Rookie/Veteran)\n"
            "`/allpicks` — see everyone's picks at once"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎯 Making Picks",
        value=(
            "`/pick` — draft a musher (your turn only, autocomplete available)\n"
            "`/mypicks` — see your picks (private)\n"
            "`/picks` — see any participant's picks"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎮 Mock Draft",
        value=(
            "`/mock_start` — start a practice draft\n"
            "`/mock_pick` — make a pick in the mock draft\n"
            "`/mock_available` — available mushers in mock\n"
            "`/mock_status` — mock draft status\n"
            "`/mock_reset` — clear the mock draft"
        ),
        inline=False,
    )
    embed.add_field(
        name="⚙️ Admin Only",
        value=(
            "`/setup` — configure participants and rounds\n"
            "`/randomize` — shuffle the draft order\n"
            "`/set_order` — set a specific draft order\n"
            "`/draft_start` — begin the live draft\n"
            "`/draft_reset` — reset everything"
        ),
        inline=False,
    )
    embed.set_footer(text="36 mushers · 13 Rookies · 23 Veterans · Snake format")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ── run ────────────────────────────────────────────────────────────────────

bot.run(TOKEN)
