from .tracker import tracker
from .cli_utils import (
    clear_screen,
    print_header,
    print_warning,
    select_from_list,
    print_success,
)
from .handlers import (
    anime_sama,
    coflix,
    french_stream,
    french_manga,
    goldenanime,
    goldenms,
)
from .i18n import t


def _show_entry_poster(data):
    """Draw the series poster + what we're resuming for a history entry."""
    from . import terminal_image

    cover = data.get("logo_url") or ""
    title = data.get("series_title", "")
    season = data.get("season_title", "") or ""
    ep = data.get("episode_title", "") or ""
    sub = " · ".join(x for x in (season, ep) if x and x not in (title, "Movie"))
    if cover or title:
        terminal_image.show_poster(cover, title=title, info_lines=[sub] if sub else None)


def handle_resume(data, show_poster=True):
    """Dispatch resume to provider."""
    provider = data["provider"]

    if show_poster:
        _show_entry_poster(data)

    if provider == "Anime-Sama":
        anime_sama.resume_anime_sama(data)
    elif provider == "Coflix":
        coflix.resume_coflix(data)
    elif provider == "French-Stream":
        french_stream.resume_french_stream(data)
    elif provider == "French-Manga":
        french_manga.resume_french_manga(data)
    elif provider == "GoldenAnime":
        goldenanime.resume_goldenanime(data)
    elif provider == "GoldenMS":
        goldenms.resume_goldenms(data)



def handle_history():
    """Display history list and allow resume/delete."""
    while True:
        clear_screen()
        print_header(t("📜 My History"))

        history = tracker.get_history()
        if not history:
            print_warning(t("No history found."))
            input("\nPress Enter to go back...")
            return

        options = []
        for entry in history:
            provider = entry["provider"]
            series = entry["series_title"]
            season = entry["season_title"]
            episode = entry["episode_title"]

            if provider == "Coflix":
                if season == "Movie" or episode == "Movie":
                    text = f"[{provider}] {series} (Movie)"
                else:
                    clean_season = season.replace(series, "").strip(" -")
                    if not clean_season:
                        clean_season = season
                    text = f"[{provider}] {series} - {clean_season} - {episode}"
            elif provider == "French-Stream":
                if season == "Movie" or episode == "Movie":
                    text = f"[{provider}] {series} (Movie)"
                else:
                    text = f"[{provider}] {series} - {episode}"
            elif provider == "GoldenAnime":
                text = f"[{provider}] {series} - {episode}"
            elif provider == "GoldenMS":
                if season == "Movie" or episode == "Movie":
                    text = f"[{provider}] {series} (Movie)"
                else:
                    text = f"[{provider}] {series} - {season} - {episode}"
            else:
                text = f"[{provider}] {series} - {season} - {episode}"

            options.append(text)

        options.append(t("← Back"))

        choice_idx = select_from_list(options, t("Select an entry to resume or delete:"))

        if choice_idx == len(history):  # Back
            return

        selected_entry = history[choice_idx]

        # Show the poster of the picked entry before choosing the action.
        _show_entry_poster(selected_entry)

        action = select_from_list(
            [t("▶ Resume"), t("❌ Delete"), t("← Cancel")], t("Action:")
        )

        if action == 0:  # Resume — poster already shown above.
            handle_resume(selected_entry, show_poster=False)
        elif action == 1:  # Delete
            tracker.delete_history_item(
                selected_entry["provider"], selected_entry["series_title"]
            )
            print_success(t("Entry deleted."))
