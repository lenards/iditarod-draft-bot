import csv
import random
from dataclasses import dataclass
from typing import Optional
from pathlib import Path


@dataclass
class Musher:
    name: str
    sex: str
    city: str
    state: str
    country: str
    status: str

    @property
    def is_rookie(self) -> bool:
        return self.status.strip().lower() == "rookie"

    def display_line(self) -> str:
        tag = "🌟 Rookie" if self.is_rookie else "⭐ Veteran"
        location = ", ".join(p for p in [self.city, self.state or self.country] if p)
        return f"**{self.name}** — {tag}" + (f" ({location})" if location else "")


def load_mushers() -> list[Musher]:
    csv_path = Path(__file__).parent / "mushers.csv"
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [
            Musher(
                name=row["Musher Name"].strip(),
                sex=row["Sex"].strip(),
                city=row["City"].strip(),
                state=row["State"].strip(),
                country=row["Country"].strip(),
                status=row["Status"].strip(),
            )
            for row in reader
        ]


# Load once at import time — shared across both live and mock sessions
ALL_MUSHERS: list[Musher] = load_mushers()


class DraftSession:
    def __init__(self, label: str = "Draft"):
        self.label = label
        self.picks_per_person: int = 4
        self.participants: list[int] = []        # Discord user IDs in current order
        self.names: dict[int, str] = {}          # user_id -> display_name
        self.draft_order: list[int] = []         # full snake-expanded pick list
        self.picks: dict[int, list[Musher]] = {} # user_id -> mushers picked
        self.taken: set[str] = set()             # musher names already drafted
        self.current_pick_index: int = 0
        self.is_active: bool = False
        self.is_configured: bool = False

    # ── configuration ──────────────────────────────────────────────────────

    def configure(self, members: list, picks_per_person: int = 4):
        """Set up participants from a list of discord.Member objects."""
        self.picks_per_person = picks_per_person
        self.participants = [m.id for m in members]
        self.names = {m.id: m.display_name for m in members}
        self.picks = {m.id: [] for m in members}
        self.taken = set()
        self.current_pick_index = 0
        self.is_active = False
        self.is_configured = True
        self._build_snake_order()

    def configure_from_ids(self, participant_ids: list[int], names: dict[int, str], picks_per_person: int = 4):
        """Set up participants from existing IDs/names (used for mock drafts)."""
        self.picks_per_person = picks_per_person
        self.participants = participant_ids[:]
        self.names = names.copy()
        self.picks = {uid: [] for uid in participant_ids}
        self.taken = set()
        self.current_pick_index = 0
        self.is_active = False
        self.is_configured = True
        self._build_snake_order()

    def randomize(self):
        """Shuffle the participant order and rebuild the snake draft."""
        random.shuffle(self.participants)
        self._build_snake_order()

    def set_explicit_order(self, members: list) -> tuple[bool, str]:
        """Reorder participants to match the given member list."""
        ordered_ids = [m.id for m in members]
        unknown = [uid for uid in ordered_ids if uid not in self.names]
        if unknown:
            return False, "Some users are not in the participant list."
        if set(ordered_ids) != set(self.participants):
            return False, "The order must include all current participants."
        self.participants = ordered_ids
        self._build_snake_order()
        return True, "Order updated."

    def _build_snake_order(self):
        """Build the full snake draft order list."""
        order = []
        for round_num in range(self.picks_per_person):
            if round_num % 2 == 0:
                order.extend(self.participants)
            else:
                order.extend(reversed(self.participants))
        self.draft_order = order

    def start(self):
        self.is_active = True
        self.current_pick_index = 0

    def reset(self):
        label = self.label
        self.__init__(label=label)

    # ── state properties ───────────────────────────────────────────────────

    @property
    def current_drafter_id(self) -> Optional[int]:
        if self.current_pick_index < len(self.draft_order):
            return self.draft_order[self.current_pick_index]
        return None

    @property
    def next_drafter_id(self) -> Optional[int]:
        if self.current_pick_index + 1 < len(self.draft_order):
            return self.draft_order[self.current_pick_index + 1]
        return None

    @property
    def current_round(self) -> int:
        if not self.participants:
            return 0
        return (self.current_pick_index // len(self.participants)) + 1

    @property
    def overall_pick_num(self) -> int:
        return self.current_pick_index + 1

    @property
    def total_picks(self) -> int:
        return len(self.draft_order)

    @property
    def is_complete(self) -> bool:
        return self.current_pick_index >= len(self.draft_order)

    # ── queries ────────────────────────────────────────────────────────────

    def available(self, filter_status: Optional[str] = None) -> list[Musher]:
        avail = [m for m in ALL_MUSHERS if m.name not in self.taken]
        if filter_status and filter_status.lower() not in ("all", ""):
            avail = [m for m in avail if m.status.lower() == filter_status.lower()]
        return avail

    def find_musher(self, query: str) -> Optional[Musher]:
        q = query.strip().lower()
        for m in ALL_MUSHERS:
            if m.name.lower() == q:
                return m
        matches = [m for m in ALL_MUSHERS if q in m.name.lower()]
        if len(matches) == 1:
            return matches[0]
        return None

    def _user_needs_rookie(self, user_id: int) -> bool:
        user_picks = self.picks[user_id]
        has_rookie = any(m.is_rookie for m in user_picks)
        picks_made = len(user_picks)
        return picks_made == self.picks_per_person - 1 and not has_rookie

    def order_lines(self) -> list[str]:
        return [
            f"{i}. {self.names.get(uid, str(uid))}"
            for i, uid in enumerate(self.participants, 1)
        ]

    # ── pick action ────────────────────────────────────────────────────────

    def make_pick(self, user_id: int, musher_name: str) -> tuple[bool, str, Optional[Musher], int, int]:
        """
        Returns (success, message, musher_or_None, pick_number, round_number).
        pick_number and round_number reflect the pick just made.
        """
        if not self.is_active:
            return False, "The draft hasn't started yet.", None, 0, 0
        if self.is_complete:
            return False, "The draft is complete!", None, 0, 0
        if self.current_drafter_id != user_id:
            on_clock = self.names.get(self.current_drafter_id, "someone else")
            return False, f"It's not your turn — **{on_clock}** is on the clock!", None, 0, 0

        musher = self.find_musher(musher_name)
        if not musher:
            return False, f"`{musher_name}` not found. Use `/available` to browse mushers.", None, 0, 0
        if musher.name in self.taken:
            return False, f"**{musher.name}** has already been drafted!", None, 0, 0
        if self._user_needs_rookie(user_id) and not musher.is_rookie:
            return False, (
                "Your last pick must be a **Rookie**! "
                "Use `/available filter:Rookie` to see who's still available."
            ), None, 0, 0

        pick_number = self.current_pick_index + 1
        round_number = self.current_round

        self.picks[user_id].append(musher)
        self.taken.add(musher.name)
        self.current_pick_index += 1

        return True, f"Picked **{musher.name}** ({musher.status})!", musher, pick_number, round_number
