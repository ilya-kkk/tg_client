from typing import TypedDict


class WarmupModeConfig(TypedDict):
    min_delay_sec: int
    max_delay_sec: int
    actions_per_day_range: tuple[int, int]


WARMUP_MODES: dict[str, WarmupModeConfig] = {
    "cautious": {
        "min_delay_sec": 5 * 60,
        "max_delay_sec": 30 * 60,
        "actions_per_day_range": (5, 15),
    },
    "normal": {
        "min_delay_sec": 60,
        "max_delay_sec": 10 * 60,
        "actions_per_day_range": (20, 50),
    },
    "aggressive": {
        "min_delay_sec": 15,
        "max_delay_sec": 3 * 60,
        "actions_per_day_range": (60, 120),
    },
}


ACTION_TYPES: list[str] = [
    "read_messages",
    "react_to_message",
    "join_channel",
    "view_story",
    "search_global",
    "update_status",
]
