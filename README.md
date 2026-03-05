# 🐕 Iditarod Fantasy Draft Bot

A Discord slash-command bot for running a snake-format fantasy league draft for the Iditarod Trail Sled Dog Race.

## Features

- Snake draft with up to 8 participants
- Musher autocomplete when picking
- Rookie requirement enforced (every drafter must pick ≥1 Rookie)
- "On the clock" pings so the right person gets notified
- Mock draft mode for practice runs before the real thing
- Restrict bot to a specific channel via `DRAFT_CHANNEL_IDS`

## Setup

### 1. Create a Discord Bot

1. Go to https://discord.com/developers/applications → **New Application**
2. **Bot** tab → **Add Bot** → copy the token
3. Under **Privileged Gateway Intents**, no extras needed for this bot
4. **OAuth2 → URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Bot permissions: `Send Messages`, `Read Message History`, `Use Slash Commands`
5. Copy the generated URL and paste it in your browser to invite the bot to your server

### 2. Get Channel ID (optional but recommended)

In Discord, go to **Settings → Advanced → enable Developer Mode**.
Right-click your draft channel → **Copy Channel ID**.

### 3. Deploy to Railway

1. Push this repo to GitHub
2. Go to https://railway.app → **New Project → Deploy from GitHub repo**
3. Select this repo
4. In **Variables**, add:
   - `DISCORD_TOKEN` = your bot token
   - `DRAFT_CHANNEL_IDS` = comma-separated channel IDs, e.g. `123,456` (optional)
5. Railway auto-detects Python and runs the `Procfile` worker

### 4. Local development

```bash
pip install -r requirements.txt
cp .env.example .env
# fill in DISCORD_TOKEN in .env
python bot.py
```

---

## Admin Flow (draft day)

```
/setup rounds:4 user1:@Alice user2:@Bob user3:@Carol ...
/randomize          ← shuffle order randomly
  — OR —
/set_order first:@Alice second:@Bob ...   ← e.g. last year's finish order
/draft_start        ← go live!
```

## Participant Commands

| Command | Description |
|---|---|
| `/pick <musher>` | Draft a musher (your turn only, with autocomplete) |
| `/available` | List all undrafted mushers |
| `/available filter:Rookie` | Only show available Rookies |
| `/mypicks` | See your picks (private/ephemeral) |
| `/picks @user` | See any participant's picks |
| `/allpicks` | See everyone's picks at once |
| `/status` | Who's on the clock, what round, etc. |

## Mock Draft Commands

| Command | Description |
|---|---|
| `/mock_start` | Start a practice draft (requires `/setup` first) |
| `/mock_pick <musher>` | Pick in the mock draft |
| `/mock_available` | Available mushers in mock |
| `/mock_status` | Mock draft status |
| `/mock_reset` | Clear the mock draft |

## Rules

- **Snake format**: Round 1 goes 1→8, Round 2 goes 8→1, etc.
- **Rookie requirement**: Every participant's last pick must be a Rookie if they haven't picked one yet. The bot enforces this automatically.
- **Blocking picks**: Only the person on the clock can use `/pick`. Everyone else gets an error.

## Musher Data

`mushers.csv` — 36 mushers, 12 Rookies and 24 Veterans, 2026 Iditarod field.
