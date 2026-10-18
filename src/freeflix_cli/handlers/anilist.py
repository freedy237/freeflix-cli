from ..anilist import anilist_client
from ..tracker import tracker
import re
from ..cli_utils import (
    select_from_list,
    select_with_preview,
    make_preview,
    print_info,
    print_warning,
    print_error,
    print_success,
    get_user_input,
    clean_title,
    pause,
)
from .anime_sama import anime_sama
from . import goldenanime
from ..i18n import t
from ..icons import icon


def handle_anilist_continue():
    """Handle the 'Continue from AniList' flow."""
    token = tracker.get_anilist_token()
    if not token:
        print_error(t("Please configure your AniList token in Settings > AniList first."))
        return

    anilist_client.set_token(token)
    print_info(t("Fetching your watching list from AniList..."))

    # Needs user ID first
    user = anilist_client.validate_token()
    if not user:
        print_error(t("Invalid AniList token."))
        return

    entries = anilist_client.get_user_watching(user["id"])
    if not entries:
        print_warning(t("No anime currently watching found on AniList."))
        return

    # Selection list WITH posters (chafa), like the regular source flows.
    labels, previews = [], []
    for e in entries:
        title = e["media"]["title"]["english"] or e["media"]["title"]["romaji"]
        progress = e["progress"] or 0
        total = e["media"]["episodes"] or "?"
        if isinstance(total, int) and progress >= total:
            status = f"{t('Finished')} {progress}/{total}"
        else:
            status = f"{t('Ep')} {progress+1}/{total}"
        _ci = e["media"].get("coverImage", {}) or {}
        cover = _ci.get("extraLarge") or _ci.get("large") or _ci.get("medium") or ""
        labels.append(f"{title} ({status})")
        previews.append(make_preview(cover=cover, title=title,
                                     lines=[status], panel_title="AniList"))

    choice_idx = select_with_preview(labels, t("Select Anime to Continue:"), previews)
    if choice_idx >= len(entries):  # Esc / Back
        return

    selected_entry = entries[choice_idx]
    media_title = (
        selected_entry["media"]["title"]["english"]
        or selected_entry["media"]["title"]["romaji"]
    )
    media_id = selected_entry["mediaId"]
    progress = selected_entry["progress"] or 0
    total = selected_entry["media"]["episodes"] or "?"
    next_episode_num = progress + 1

    if isinstance(total, int) and progress >= total:
        print_info(
            f"{t('Target:')} [cyan]{media_title}[/cyan] - [yellow]{t('Completed')} ({progress}/{total})[/yellow]"
        )
        # Reset to last episode for easier replay or just stay at progress
        next_episode_num = progress
    else:
        print_info(f"{t('Target:')} [cyan]{media_title}[/cyan] - {t('Episode')} {next_episode_num}")

    # --- Provider Selection ---
    providers = ["Anime-Sama (VF/VOSTFR)", "GoldenAnime (VO)", t("← Back")]
    p_choice = select_from_list(providers, t("Select a Provider:"))

    if p_choice == 2:  # Back
        return

    # Extract cover URL for both providers (extraLarge = sharpest)
    _ci = selected_entry["media"].get("coverImage", {}) or {}
    cover_url = _ci.get("extraLarge") or _ci.get("large") or _ci.get("medium")

    if p_choice == 1:  # GoldenAnime
        goldenanime.handle_goldenanime_episode(
            title=media_title,
            anilist_id=media_id,
            start_episode=next_episode_num,
            cover_url=cover_url,
        )
        return

    # --- Anime-Sama path : search → match → seasons → languages → episodes,
    #     one level per Back (state kept, no refetch). ---
    _anilist_anime_sama_flow(
        media_title,
        selected_entry["media"]["title"]["romaji"],
        media_id,
        next_episode_num,
    )


def _anilist_target_season(media_title, romaji_title):
    """Detect 'Season X' / 'S X' / 'Part X' in an AniList title (or None)."""
    for cand in (media_title, romaji_title):
        if not cand:
            continue
        for pat in (r"Season\s+(\d+)", r"\s+S(\d+)", r"Part\s+(\d+)"):
            m = re.search(pat, cand, re.IGNORECASE)
            if m:
                return int(m.group(1))
    return None


def _anilist_anime_sama_flow(media_title, romaji_title, media_id, next_episode_num):
    """Anime-Sama leg of 'Continue from AniList', with a one-level Back stack."""
    anime_sama.get_website_url()
    cleaned_title = clean_title(media_title)

    print_info(f"{t('Searching for')} '{media_title}' {t('on Anime-Sama')}...")
    results = anime_sama.search(media_title)
    if not results and cleaned_title != media_title:
        print_info(f"{t('No results for full title. Trying cleaned:')} '{cleaned_title}'...")
        results = anime_sama.search(cleaned_title)
    if not results and romaji_title and romaji_title != media_title:
        print_warning(
            f"{t('No results for English title. Trying Romaji:')} '{romaji_title}'..."
        )
        results = anime_sama.search(romaji_title)
    if not results:
        cleaned_romaji = clean_title(romaji_title)
        if cleaned_romaji and cleaned_romaji != romaji_title:
            print_info(f"{t('Trying cleaned Romaji:')} '{cleaned_romaji}'...")
            results = anime_sama.search(cleaned_romaji)

    if not results:
        print_warning(t("No results found on Anime-Sama."))
        if select_from_list([t("Try Manual Search"), t("← Back")],
                            t("What would you like to do?")) != 0:
            return
        manual_query = get_user_input(t("Enter search query"))
        if not manual_query:
            return
        results = anime_sama.search(manual_query)
        if not results:
            print_error(t("Still no results found."))
            return

    target_season_num = _anilist_target_season(media_title, romaji_title)
    from .playback import play_episode_flow

    while True:  # ── Match level ──
        r_idx = select_from_list(
            [r.title for r in results] + [t("← Back")],
            t("Select the matching result:"),
        )
        if r_idx >= len(results):
            return  # → home
        selection = results[r_idx]

        print_info(f"{t('Loading')} [cyan]{selection.title}[/cyan]...")
        try:
            series = anime_sama.get_series(selection.url)
        except Exception as e:
            print_error(f"{t('Failed to load (network/source issue):')} {type(e).__name__}")
            pause()
            continue
        if not series.seasons:
            print_warning(t("No seasons found."))
            pause()
            continue

        default_season_idx = 0
        if target_season_num is not None:
            for i, sea in enumerate(series.seasons):
                s_match = re.search(r"(?:Saison|Season)\s+(\d+)", sea.title, re.IGNORECASE)
                if s_match and int(s_match.group(1)) == target_season_num:
                    default_season_idx = i
                    break
                if (target_season_num == 1
                        and "Saison" not in sea.title
                        and "Season" not in sea.title
                        and len(series.seasons) == 1):
                    default_season_idx = 0
                    break

        while True:  # ── Season level ──
            season_idx = select_from_list(
                [sea.title for sea in series.seasons] + [t("← Back")],
                f"{icon('tv')} {t('Select Season:')}",
                default_index=default_season_idx,
            )
            if season_idx >= len(series.seasons):
                break  # → match list
            selected_season_access = series.seasons[season_idx]
            if target_season_num is not None:
                print_info(
                    f"AniList {t('suggests')} [bold]{t('Season')} {target_season_num}[/bold]."
                )
            print_info(f"{t('Loading')} [cyan]{selected_season_access.title}[/cyan]...")
            try:
                season = anime_sama.get_season(selected_season_access.url)
            except Exception as e:
                print_error(f"{t('Failed to load season (network/source issue):')} {type(e).__name__}")
                pause()
                continue
            if not season.episodes:
                print_warning(t("No episodes found."))
                pause()
                continue
            tracker.set_anilist_mapping("Anime-Sama", series.title, media_id, season.title)
            langs = list(season.episodes.keys())

            while True:  # ── Language level ──
                if len(langs) == 1:
                    selected_lang = langs[0]
                else:
                    lang_idx = select_from_list(
                        langs + [t("← Back")],
                        f"{icon('globe')} {t('Select Language:')}",
                    )
                    if lang_idx >= len(langs):
                        break  # → season
                    selected_lang = langs[lang_idx]
                episodes = season.episodes[selected_lang]

                start_ep_idx, found = 0, False
                for i, ep in enumerate(episodes):
                    m = re.search(r"(\d+)", ep.title)
                    if m and int(m.group(1)) == next_episode_num:
                        start_ep_idx, found = i, True
                        break
                if not found:
                    print_warning(
                        f"{t('Could not automatically find Episode')} {next_episode_num}. "
                        f"{t('Please select:')}"
                    )
                    chosen = select_from_list(
                        [e.title for e in episodes] + [t("← Back")],
                        f"{icon('tv')} {t('Select Episode:')}",
                    )
                    if chosen >= len(episodes):
                        break  # → language
                    start_ep_idx = chosen
                else:
                    print_success(
                        f"{t('Found Episode')} {next_episode_num}: "
                        f"{episodes[start_ep_idx].title}"
                    )

                completed = False
                ep_idx = start_ep_idx
                while True:  # ── Episode / play level ──
                    selected_episode = episodes[ep_idx]

                    def _anilist_update(ep=selected_episode):
                        m = re.search(r"(\d+)", ep.title)
                        if m and anilist_client.update_progress(media_id, int(m.group(1))):
                            print_success(t("AniList updated!"))

                    success = play_episode_flow(
                        provider_name="Anime-Sama",
                        series_title=series.title,
                        season_title=season.title,
                        episode=selected_episode,
                        series_url=series.url,
                        season_url=selected_season_access.url,
                        logo_url=series.img,
                        headers={"Referer": anime_sama.website_origin},
                        anilist_callback=_anilist_update,
                    )
                    if not success:
                        break  # → language menu
                    if ep_idx + 1 < len(episodes) and select_from_list(
                        [t("Yes"), t("No")],
                        f"{t('Play next:')} {episodes[ep_idx + 1].title} ?",
                    ) == 0:
                        ep_idx += 1
                        continue
                    completed = True
                    break
                if completed:
                    return  # playback finished → leave the provider
                if len(langs) == 1:
                    break  # single language → season menu
