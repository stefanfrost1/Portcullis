"""
Formatting utilities for the MyEngineAPI Streamlit frontend.
"""


def bytes_to_human(n: int | None) -> str:
    """Convert a byte count to a human-readable string. e.g. 1536 → '1.5 KB'."""
    if n is None:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024.0:
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PB"


def seconds_to_human(n: int | None) -> str:
    """Convert a second count to a human-readable string. e.g. 3661 → '1h 1m 1s'."""
    if n is None:
        return "—"
    n = int(n)
    if n < 0:
        return "—"
    parts = []
    days, n = divmod(n, 86400)
    hours, n = divmod(n, 3600)
    minutes, seconds = divmod(n, 60)
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


def state_color(state: str | None) -> str:
    """Return an emoji badge for a Docker container state."""
    mapping = {
        "running": "🟢",
        "paused": "🟡",
        "restarting": "🔄",
        "exited": "🔴",
        "dead": "💀",
        "created": "⚪",
        "removing": "🗑️",
    }
    return mapping.get((state or "").lower(), "❓")


def health_badge(ok: bool) -> str:
    """Return a short health badge string."""
    return "🟢 Connected" if ok else "🔴 Unreachable"


def percent_bar(value: float, width: int = 20) -> str:
    """Return a simple ASCII progress bar for a percentage value."""
    value = max(0.0, min(100.0, value or 0.0))
    filled = int(round(value / 100 * width))
    bar = "█" * filled + "░" * (width - filled)
    return f"{bar} {value:.1f}%"
