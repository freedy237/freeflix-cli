"""Match menu — live football from the YacineTV catalogue.

Cameroon time (UTC+1, no DST). The list is fetched fresh on every entry and
falls back to the last snapshot only when the API is unreachable.
"""

from __future__ import annotations

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
    return f"{badge}  {when}  ·  {ev.home}  VS  {ev.away}{league}"


def _sort_events(events: list[ym.MatchEvent], now_ts: int) -> list[ym.MatchEvent]:
    order = {"live": 0, "upcoming": 1, "ended": 2}
    return sorted(events, key=lambda e: (order.get(e.status(now_ts), 3), e.start))


def _quality_label(stream: dict) -> str:
    name = str(stream.get("name") or "?")
    return f"{icon('play')} {name}"


def _play(event: ym.MatchEvent, stream: dict, player_name: str = "") -> None:
    from ..player_manager import play_direct_stream

    title = f"YacineTV · {event.home}  VS  {event.away}"
    print_info(f"{t('Selected quality:')} {stream.get('name', '?')}")
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
    options = [f"{icon('play')} {label}" for label in labels]
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
        labels = [_match_label(ev, now_ts, now) for ev in ordered]
        labels.append(t("← Back"))
        header = (f"{icon('football')} {t('Football matches')}  ·  "
                  f"{t('Cameroon time (UTC+1)')}")

        idx = select_from_list(
            labels, t("Select a match"), header=header, clear_on_back=True,
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
            header=f"{icon('football')} {event.championship or t('Football')}",
        )
        if choice < 0 or choice >= auto_idx:
            if choice == auto_idx:
                stream = ym.pick_auto(streams)
                if not stream:
                    print_warning(t("No stream available for this match."))
                    continue
                print_info(f"{t('Auto quality:')} {stream.get('name', '?')}")
                chosen = _choose_player(player_name, allow_cancel=True)
                if chosen:
                    _play(event, stream, chosen)
            else:
                return
            continue

        chosen = _choose_player(player_name, allow_cancel=True)
        if chosen:
            _play(event, streams[choice], chosen)
