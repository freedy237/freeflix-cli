"""French-Manga provider handler."""

from ..scraping import french_manga
from ..cli_utils import (
    select_from_list,
    select_with_preview,
    make_preview,
    print_header,
    print_info,
    print_warning,
    get_user_input,
    pause,
    spinner,
)
from .playback import play_episode_flow
from ..i18n import t
from ..icons import icon


def _episode_sort_key(ep_num):
    try:
        return (0, int(ep_num))
    except (TypeError, ValueError):
        return (1, str(ep_num))


class _Ep:
    """Lightweight episode object accepted by play_episode_flow."""

    def __init__(self, title, players, url):
        self.title = title
        self.players = players
        self.url = url


def _play_episodes(series_title, series_url, lang, episodes, ep_nums, ep_idx, cover=""):
    """
    Play episode at index ``ep_idx`` and chain into the next ones on request.
    Shared by the normal flow and the resume-from-history flow.
    """
    headers = {"Referer": french_manga.website_origin + "/"}
    while True:
        ep_num = ep_nums[ep_idx]
        ep_obj = _Ep(f"Episode {ep_num}", episodes[ep_num], series_url)

        success = play_episode_flow(
            provider_name="French-Manga",
            series_title=series_title,
            season_title=lang.upper(),
            episode=ep_obj,
            series_url=series_url,
            season_url=series_url,
            logo_url=cover,
            headers=headers,
        )

        if not success:
            return
        if ep_idx + 1 < len(ep_nums):
            nxt = ep_nums[ep_idx + 1]
            if select_from_list(
                [t("Yes"), t("No")], f"{t('Play next episode:')} Episode {nxt}?"
            ) == 0:
                ep_idx += 1
                continue
        break


def handle_french_manga():
    """French-Manga provider flow : search → series → lang → episode → play."""
    query = get_user_input(
        t("Search query (or 'exit' to back)"),
        header=f"{icon('manga')} French-Manga",
    )
    if not query or query.lower() == "exit":
        return

    with spinner(f"{t('Searching for')} {query}…"):
        results = french_manga.search(query)
    if not results:
        print_warning(t("No results found."))
        pause()
        return

    # Preview pane : poster (TMDB thumbnail) beside the result list.
    previews = [
        make_preview(
            cover=getattr(r, "img", ""),
            title=r.title,
            panel_title="French-Manga",
        )
        for r in results
    ]
    choice = select_with_preview(
        [r.title for r in results], f"{icon('tv')} {t('Search Results:')}", previews
    )
    if choice >= len(results):  # Esc / Back
        return
    selection = results[choice]

    with spinner(f"{t('Loading')} {selection.title}…"):
        data = french_manga.get_episodes(selection.url)

    # Languages that actually have episodes
    langs = [lng for lng in ("vf", "vostfr") if data.get(lng)]
    if not langs:
        print_warning(t("No episodes found."))
        pause()
        return

    # Show the anime poster + a quick summary at selection.
    from .. import terminal_image
    title_disp = data.get("title") or selection.title
    terminal_image.show_poster(
        data.get("cover"),
        title=title_disp,
        info_lines=[f"{t('Languages')}: {', '.join(l.upper() for l in langs)}"],
    )

    while True:  # ── Language ──
        if len(langs) == 1:
            selected_lang = langs[0]
        else:
            lang_idx = select_from_list(
                langs + [t("← Back")], f"{icon('globe')} {t('Select Language:')}"
            )
            if lang_idx >= len(langs):
                return  # back → source menu
            selected_lang = langs[lang_idx]

        episodes = data[selected_lang]
        ep_nums = sorted(episodes.keys(), key=_episode_sort_key)

        ep_options = [f"Episode {n}" for n in ep_nums] + [t("← Back")]
        ep_idx = select_from_list(ep_options, f"{icon('tv')} {t('Select Episode:')}")
        if ep_idx >= len(ep_nums):
            if len(langs) == 1:
                return  # single language → back exits the handler
            continue  # back to the language picker
        break

    title = data.get("title") or selection.title

    _play_episodes(
        title, selection.url, selected_lang, episodes, ep_nums, ep_idx,
        cover=data.get("cover", ""),
    )


def resume_french_manga(data):
    """Resume French-Manga playback from history."""
    series_url = data.get("series_url") or data.get("episode_url") or ""
    series_title = data.get("series_title", "")
    lang = (data.get("season_title") or "vf").lower()
    if lang not in ("vf", "vostfr"):
        lang = "vf"
    ep_str = (data.get("episode_title") or "").replace("Episode", "").strip()

    if not series_url:
        print_warning(t("Cannot resume this entry (missing link)."))
        pause()
        return

    with spinner(f"{t('Loading')} {series_title}…"):
        epdata = french_manga.get_episodes(series_url)
    episodes = epdata.get(lang) or {}
    if not episodes:
        # The stored language has no episodes anymore — fall back to the other.
        for alt in ("vf", "vostfr"):
            if epdata.get(alt):
                lang, episodes = alt, epdata[alt]
                break
    if not episodes:
        print_warning(t("No episodes found."))
        pause()
        return

    ep_nums = sorted(episodes.keys(), key=_episode_sort_key)
    try:
        cur_idx = ep_nums.index(ep_str)
    except ValueError:
        cur_idx = 0

    cur_ep = ep_nums[cur_idx]
    has_next = cur_idx + 1 < len(ep_nums)

    options = []
    if has_next:
        options.append(f"▶ {t('Continue')} (Episode {ep_nums[cur_idx + 1]})")
    options.append(f"🔁 {t('Watch again')} (Episode {cur_ep})")
    options.append(t("← Cancel"))

    choice = select_from_list(options, t("What would you like to do?"))
    if options[choice] == t("← Cancel"):
        return

    start_idx = cur_idx + 1 if (has_next and choice == 0) else cur_idx
    _play_episodes(
        series_title, series_url, lang, episodes, ep_nums, start_idx,
        cover=epdata.get("cover", ""),
    )
