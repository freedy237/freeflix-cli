"""Match menu — live football from the YacineTV catalogue.

Cameroon time (UTC+1, no DST). The list is fetched fresh on every entry and
falls back to the last snapshot only when the API is unreachable.
"""

from __future__ import annotations

import re

from datetime import datetime, timedelta, timezone

from ..cli_utils import (
    print_error,
    print_info,
    print_warning,
    select_from_list,
    spinner,
)
from ..i18n import t
from ..icons import icon
from ..scraping import yacine_match as ym
from ..tracker import tracker

_CAM = timezone(timedelta(hours=1))


def _when_label(ev: ym.MatchEvent, now: datetime) -> str:
    dt = ev.start_dt
    today = now.date()
    if dt.date() == today:
        return f"{dt:%H:%M}"
    if dt.date() == today + timedelta(days=1):
        return f"{t('Tomorrow')} {dt:%H:%M}"
    return f"{dt:%d/%m %H:%M}"


def _channel_label(channel: str) -> str:
    """Short, stable live-TV badge for every channel.

    beIN SPORTS 1..N → B1..BN · Dubai Sports N → DS N · any other channel
    keeps a compact form of its own name, so new sources never print a long
    full label in front of the match.
    """
    name = (channel or "").strip()
    if not name:
        return ""
    m = re.search(r"be\s*in\s*sports?\s*(\d+)", name, re.I)
    if m:
        return f"B{m.group(1)}"
    m = re.search(r"dubai\s*sports?\s*(\d*)", name, re.I)
    if m:
        return f"DS{m.group(1)}"
    # Generic: initials of the words, then a trailing number (never twice).
    # "Canal+ Sport 2" → "CS2", "Sky Sports F1" → "SSF1", "ESPN" → "E".
    words = [w for w in re.split(r"[\s\-]+", name) if w and w[0].isalnum()]
    letters = "".join(w[0] for w in words).upper()
    if words and words[-1].isdigit():
        short = letters[:-1] + words[-1]
    else:
        short = letters
    return (short or name)[:6]


def _match_label(ev: ym.MatchEvent, now_ts: int, now: datetime) -> str:
    state = ev.status(now_ts)
    when = _when_label(ev, now)
    if state == "live":
        badge = f"● {t('LIVE')}"
    elif state == "ended":
        badge = f"✓ {t('Finished')}"
    else:
        badge = f"○ {t('Upcoming')}"
    league = f"  ·  {ev.championship}" if ev.championship else ""
    channel = f"({_channel_label(ev.channel)})  " if ev.channel else ""
    return f"{channel}{badge}  {when}  ·  {ev.home}  VS  {ev.away}{league}"


def _sort_events(events: list[ym.MatchEvent], now_ts: int) -> list[ym.MatchEvent]:
    order = {"live": 0, "upcoming": 1, "ended": 2}
    return sorted(events, key=lambda e: (order.get(e.status(now_ts), 3), e.start))


_GROUP_ICONS = {"live": "fire", "upcoming": "clock", "ended": "check"}


def _group_label(state: str, count: int) -> str:
    key = {"live": "LIVE now", "upcoming": "Upcoming",
           "ended": "Finished"}.get(state, state)
    return f"{icon(_GROUP_ICONS.get(state, 'clock'))} {t(key)} ({count})"


def _fit(text: str, width: int) -> str:
    """Pad/truncate to an exact DISPLAY width (wide glyphs count as 2)."""
    from rich.cells import cell_len

    out = ""
    for ch in str(text or ""):
        if cell_len(out + ch) > width:
            break
        out += ch
    if cell_len(out) < width:
        out += " " * (width - cell_len(out))
    return out


def _column_widths(events: list[ym.MatchEvent], now: datetime) -> dict:
    """Widths shared by EVERY row of the screen (all status sections)."""
    from rich.cells import cell_len

    chans = [f"({_channel_label(e.channel)})" if e.channel else "" for e in events]
    whens = [_when_label(e, now) for e in events]
    teams = [f"{e.home}  VS  {e.away}" for e in events]
    leagues = [e.championship or "" for e in events]

    def width(values, minimum=0, maximum=10_000):
        w = max([cell_len(v) for v in values] + [minimum])
        return min(w, maximum)

    return {"channel": width(chans), "when": width(whens, minimum=5),
            "teams": width(teams, maximum=46), "league": width(leagues, maximum=30)}


def _build_rows(events: list[ym.MatchEvent], now: datetime, widths: dict = None):
    """Aligned table: channel | time | teams | competition.

    Column widths are computed from the actual content (display cells, so
    accented and Arabic names line up correctly) — every row has the same
    shape, no more ragged badges pushing the times around.
    """
    chans = [f"({_channel_label(e.channel)})" if e.channel else "" for e in events]
    whens = [_when_label(e, now) for e in events]
    teams = [f"{e.home}  VS  {e.away}" for e in events]
    leagues = [e.championship or "" for e in events]

    widths = widths or _column_widths(events, now)
    w_channel = widths["channel"]
    w_when = widths["when"]
    w_teams = widths["teams"]
    w_league = widths["league"]

    rows = []
    for ch, wh, tm, lg in zip(chans, whens, teams, leagues):
        row = _fit(ch, w_channel) + "  " + _fit(wh, w_when) + "  " + _fit(tm, w_teams)
        if lg:
            row += "  ·  " + _fit(lg, w_league)
        rows.append(row.rstrip())
    return rows


# Conservative live HLS minimums (Mbps) used for the GB/hour estimate.
_MIN_MBPS = {2160: 15.0, 1440: 8.0, 1080: 5.0, 720: 2.5,
             480: 1.0, 360: 0.7}


def _quality_metrics(stream: dict) -> tuple[int | None, float, float]:
    """(height, minimum Mbps, estimated GB/hour) for a stream label."""
    name = str(stream.get("name") or "?")
    low = name.lower()
    m = re.search(r"(\d{3,4})p", low)
    if m:
        height = int(m.group(1))
    elif any(k in low for k in ("4k", "uhd", "2160")):
        height = 2160
    elif any(k in low for k in ("1440", "2k")):
        height = 1440
    elif "hd" in low or "fhd" in low:
        height = 1080
    elif "sd" in low:
        height = 720
    elif "low" in low:
        height = 480
    else:
        height = None
    mbps = _MIN_MBPS.get(height, 2.0)
    return height, mbps, mbps * 3600 / 8 / 1000


def _quality_label(stream: dict) -> str:
    name = str(stream.get("name") or "?")
    height, mbps, gb = _quality_metrics(stream)
    res = f" ({height}p)" if height else ""
    return (f"{icon('play')} {name}{res}  ·  ≥ {mbps:.1f} Mbps  ·  "
            f"~{gb:.2f} {t('GB/h')}")


def _play(event: ym.MatchEvent, stream: dict, player_name: str = "") -> None:
    from ..player_manager import match_stream_reachable, play_direct_stream

    title = f"YacineTV · {event.home}  VS  {event.away}"
    print_info(f"{t('Selected quality:')} {stream.get('name', '?')}")
    ok, why = match_stream_reachable(stream["url"], stream.get("headers") or {})
    if not ok:
        print_warning(f"{t('Cannot play this match:')} {why}")
        print_info(t("This channel is often blocked or taken down; try another match."))
        return
    ok = play_direct_stream(stream["url"], stream.get("headers") or {}, title,
                            player_name=player_name or None)
    if not ok:
        print_warning(t("Could not start the match stream."))


def _available_players() -> list[str]:
    from ..player_manager import get_mpv_path, get_vlc_path

    out = []
    if get_mpv_path():
        out.append("mpv")
    if get_vlc_path():
        out.append("vlc")
    return out


def _current_player() -> str:
    avail = _available_players()
    saved = (tracker.get_match_player() or "").lower()
    if saved in avail:
        return saved
    return "mpv" if "mpv" in avail else ("vlc" if "vlc" in avail else "")


def _choose_player(current: str, allow_cancel: bool = False):
    """Choose mpv/VLC after quality. Returns None when Back is pressed."""
    avail = _available_players()
    if len(avail) < 2:
        if avail:
            return avail[0]
        print_warning(t("No video player found (mpv or VLC)."))
        return None
    labels = ["mpv" if n == "mpv" else "VLC" for n in avail]
    options = list(labels)
    if allow_cancel:
        options.append(t("← Back"))
    default = labels.index(current) if current in labels else 0
    idx = select_from_list(
        options, t("Choose a player"), header=f"{icon('football')} {t('Match')}",
        default_index=default,
    )
    if 0 <= idx < len(avail):
        chosen = avail[idx]
        tracker.set_match_player(chosen)
        print_info(f"{t('Match player set to:')} {chosen}")
        return chosen
    return None if allow_cancel else current


def handle_match() -> None:
    """Live football list → quality (Auto at the bottom) → playback."""
    while True:
        # Refresh on every pass (including after a playback) so the list and
        # the LIVE badges follow the catalogue, like the weekly planning.
        try:
            with spinner(t("Loading matches…")):
                events, cached = ym.fetch_events()
                events = ym.localize_events(
                    events, tracker.get_language() or "en")
        except Exception as e:
            print_error(f"{t('Matches unavailable:')} {e}")
            return

        if cached:
            print_warning(t("Showing cached matches — network unavailable."))
        if not events:
            print_warning(t("No football matches right now."))
            return

        now = datetime.now(tz=_CAM)
        now_ts = int(now.timestamp())
        ordered = _sort_events(events, now_ts)
        player_name = _current_player()
        # Group by status with section headers so the rows line up in
        # columns; "finished" stays collapsed at the bottom.
        labels = []
        group_headers = {}
        widths = _column_widths(ordered, now)
        for state in ("live", "upcoming", "ended"):
            group = [ev for ev in ordered if ev.status(now_ts) == state]
            if not group:
                continue
            group_headers[len(labels)] = _group_label(state, len(group))
            labels.extend(_build_rows(group, now, widths))
        labels.append(t("← Back"))
        header = (f"{icon('football')} {t('Football matches')}  ·  "
                  f"{t('Cameroon time (UTC+1)')}")

        idx = select_from_list(
            labels, t("Select a match"), header=header,
            group_headers=group_headers, clear_on_back=True,
        )
        if idx < 0 or idx >= len(ordered):
            return
        event = ordered[idx]

        try:
            with spinner(t("Loading streams…")):
                streams = ym.fetch_streams(event.id)
        except Exception as e:
            print_error(f"{t('Streams unavailable:')} {e}")
            continue

        if not streams:
            print_warning(t("No stream available for this match."))
            continue

        options = [_quality_label(s) for s in streams]
        options.append(f"{icon('sparkle')} {t('Auto (best quality)')}")
        options.append(t("← Back"))
        auto_idx = len(streams)
        choice = select_from_list(
            options,
            f"{t('Choose the quality')}  ·  {event.home}  VS  {event.away}",
            header=(f"{icon('football')} "
                    f"{event.championship or t('Football')}"
                    + (f"  ·  {_channel_label(event.channel)}"
                       if event.channel else "")),
        )
        if choice < 0 or choice >= auto_idx:
            if choice == auto_idx:
                stream = ym.pick_auto(streams)
                if not stream:
                    print_warning(t("No stream available for this match."))
                    continue
                _h, _mbps, _gb = _quality_metrics(stream)
                print_info(f"{t('Auto quality:')} {stream.get('name', '?')}  ·  "
                           f"≥ {_mbps:.1f} {t('Mbps')}  ·  ~{_gb:.2f} "
                           f"{t('GB/h')}")
                chosen = _choose_player(player_name, allow_cancel=True)
                if chosen:
                    _play(event, stream, chosen)
            else:
                return
            continue

        chosen = _choose_player(player_name, allow_cancel=True)
        if chosen:
            _play(event, streams[choice], chosen)
