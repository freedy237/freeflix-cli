"""French-Manga provider handler."""

from ..scraping import french_manga
from ..cli_utils import (
    select_from_list,
    print_header,
    print_info,
    print_warning,
    get_user_input,
    pause,
)
from .playback import play_episode_flow
from ..i18n import t


def _episode_sort_key(ep_num):
    try:
        return (0, int(ep_num))
    except (TypeError, ValueError):
        return (1, str(ep_num))


def handle_french_manga():
    """French-Manga provider flow : search → series → lang → episode → play."""
    print_header(t("🎴 French-Manga"))

    query = get_user_input(t("Search query (or 'exit' to back)"))
    if not query or query.lower() == "exit":
        return

    print_info(f"{t('Searching for')}: [cyan]{query}[/cyan]")
    results = french_manga.search(query)
    if not results:
        print_warning(t("No results found."))
        pause()
        return

    choice = select_from_list(
        [r.title for r in results] + [t("← Back")], t("📺 Search Results:")
    )
    if choice == len(results):
        return
    selection = results[choice]

    print_info(f"{t('Loading')} [cyan]{selection.title}[/cyan]...")
    data = french_manga.get_episodes(selection.url)

    # Languages that actually have episodes
    langs = [lng for lng in ("vf", "vostfr") if data.get(lng)]
    if not langs:
        print_warning(t("No episodes found."))
        pause()
        return

    if len(langs) == 1:
        selected_lang = langs[0]
    else:
        lang_idx = select_from_list(langs, t("🌍 Select Language:"))
        selected_lang = langs[lang_idx]

    episodes = data[selected_lang]
    ep_nums = sorted(episodes.keys(), key=_episode_sort_key)

    ep_options = [f"Episode {n}" for n in ep_nums] + [t("← Back")]
    ep_idx = select_from_list(ep_options, t("📺 Select Episode:"))
    if ep_idx == len(ep_nums):
        return

    title = data.get("title") or selection.title

    while True:
        ep_num = ep_nums[ep_idx]
        players = episodes[ep_num]

        class _Ep:
            pass

        ep_obj = _Ep()
        ep_obj.title = f"Episode {ep_num}"
        ep_obj.players = players
        ep_obj.url = selection.url

        success = play_episode_flow(
            provider_name="French-Manga",
            series_title=title,
            season_title=selected_lang.upper(),
            episode=ep_obj,
            series_url=selection.url,
            season_url=selection.url,
            headers={"Referer": french_manga.website_origin + "/"},
        )

        if success:
            if ep_idx + 1 < len(ep_nums):
                nxt = ep_nums[ep_idx + 1]
                if select_from_list(
                    [t("Yes"), t("No")], f"{t('Play next episode:')} Episode {nxt}?"
                ) == 0:
                    ep_idx += 1
                    continue
            break
        else:
            return
