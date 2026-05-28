from .cli_utils import (
    clear_screen,
    select_from_list,
    print_header,
    print_success,
    print_error,
    print_info,
    print_warning,
    get_user_input,
    pause,
    console,
)
from .i18n import t
from .update_checker import check_update
from .tracker import tracker
from .providers_registry import registry
from .languages import LANGUAGES, get_language_display, get_all_languages
from .player_manager import PLAYERS, get_player_display, get_all_players
from .handlers import (
    anime_sama,
    coflix,
    french_stream,
    wiflix,
    anilist,
    goldenanime,
    goldenms,
    nyaa as nyaa_handler,
)
from . import history_ui
from . import proxy
import sys
import os
import signal


def _browse_local_downloads():
    """List videos in ~/Downloads/FreeFlix and let the user play one locally."""
    import shutil
    import subprocess

    from .player_manager import DOWNLOAD_DIR

    clear_screen()
    print_header("📁 My Downloads")

    if not os.path.isdir(DOWNLOAD_DIR):
        print_info(f"No downloads folder yet ({DOWNLOAD_DIR}).")
        print_info('Use the "download" option from a video to start.')
        pause()
        return

    video_exts = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".ts"}
    files = []
    for root, _dirs, names in os.walk(DOWNLOAD_DIR):
        for n in names:
            if os.path.splitext(n)[1].lower() in video_exts:
                full = os.path.join(root, n)
                rel = os.path.relpath(full, DOWNLOAD_DIR)
                try:
                    size_mb = os.path.getsize(full) / (1024 * 1024)
                except OSError:
                    size_mb = 0
                files.append((rel, full, size_mb))

    if not files:
        print_info(f"No video files found in {DOWNLOAD_DIR}.")
        pause()
        return

    files.sort(key=lambda x: x[0].lower())
    labels = [f"{rel}  ({size:.1f} MB)" for rel, _full, size in files] + ["← Back"]
    choice = select_from_list(labels, "Select a file to play:")
    if choice == len(files):
        return

    selected_path = files[choice][1]

    preferred = tracker.get_player() or "mpv"
    candidates = [preferred, "mpv", "haruna", "vlc"]
    seen = set()
    player_bin = None
    chosen_name = None
    for cand in candidates:
        if cand in seen or cand in ("download", "browser", "manual"):
            continue
        seen.add(cand)
        bin_path = shutil.which(cand)
        if bin_path:
            player_bin = bin_path
            chosen_name = cand
            break

    if not player_bin:
        print_error(
            "No local player found (tried mpv, haruna, vlc). "
            "Install one with: sudo dnf install mpv haruna"
        )
        pause()
        return

    print_info(f"Launching {chosen_name} for [cyan]{os.path.basename(selected_path)}[/cyan]")
    try:
        subprocess.run([player_bin, selected_path], check=False)
    except KeyboardInterrupt:
        pass


def check_language_setup():
    """Verify if a language is set, if not, prompt for first setup."""
    if not tracker.get_language():
        clear_screen()
        print_header(t("First Launch Setup"))
        print_info(t("Please select your preferred language."))
        print_info(t(
            "This will filter available providers and set default subtitle languages."
        ))

        langs = get_all_languages()

        choice = select_from_list([l[1] for l in langs], t("Choice:"))
        selected_lang = langs[choice][0]
        tracker.set_language(selected_lang)
        print_success(f"{t('Language set to:')} {langs[choice][1]}")
        pause()


def main():
    # Register Providers
    registry.register(
        "🎌 Anime-Sama (Anime and animated movies)",
        anime_sama.handle_anime_sama,
        supported_languages=["fr"],
    )
    registry.register(
        "✨ GoldenAnime (VO and Subtitles)",
        goldenanime.handle_goldenanime,
        supported_languages=None,
    )
    registry.register(
        "🌟 GoldenMS (Movies & Series)",
        goldenms.handle_goldenms,
        supported_languages=None,
    )
    registry.register(
        "🎬 Coflix (Series and movies)",
        coflix.handle_coflix,
        supported_languages=["fr"],
    )
    registry.register(
        "🇫🇷 French-Stream (Series and movies)",
        french_stream.handle_french_stream,
        supported_languages=["fr"],
    )
    registry.register(
        "🌊 Nyaa (Torrents — high-quality anime releases)",
        nyaa_handler.handle_nyaa,
        supported_languages=None,
    )

    # Check for updates
    if check_update():
        pause()

    # Check for language setup
    check_language_setup()

    # Start Proxy Server
    proxy.start_proxy_server()

    while True:
        clear_screen()
        print_header(t("FreeFlix CLI - Home"))

        # 1. Continue Watching (History)
        last_watch = tracker.get_last_global()
        menu_items = []
        resume_idx = -1
        anilist_resume_idx = -1

        if last_watch:
            series_name = last_watch["series_title"]
            season_name = last_watch["season_title"]
            ep_name = last_watch["episode_title"]

            # Formatting logic similar to history_ui
            if last_watch["provider"] == "Coflix":
                if season_name == "Movie" or ep_name == "Movie":
                    resume_text = f"{t('▶ Resume:')}{series_name} (Movie)"
                else:
                    clean_season = season_name.replace(series_name, "").strip(" -")
                    if not clean_season:
                        clean_season = season_name
                    resume_text = (
                        f"{t('▶ Resume:')}{series_name} - {clean_season} - {ep_name}"
                    )
            elif last_watch["provider"] == "French-Stream":
                if season_name == "Movie" or ep_name == "Movie":
                    resume_text = f"{t('▶ Resume:')}{series_name} (Movie)"
                else:
                    resume_text = f"{t('▶ Resume:')}{series_name} - {ep_name}"
            elif last_watch["provider"] == "GoldenAnime":
                resume_text = f"{t('▶ Resume:')}{series_name} - {ep_name}"
            elif last_watch["provider"] == "GoldenMS":
                if season_name == "Movie" or ep_name == "Movie":
                    resume_text = f"{t('▶ Resume:')}{series_name} (Movie)"
                else:
                    resume_text = f"{t('▶ Resume:')}{series_name} - {season_name} - {ep_name}"
            else:
                resume_text = f"{t('▶ Resume:')}{series_name} - {season_name} - {ep_name}"

            menu_items.append(resume_text)
            resume_idx = 0

        # 2. Continue from AniList
        if tracker.get_anilist_token():
            menu_items.append(t("▶ Continue from AniList"))
            anilist_resume_idx = len(menu_items) - 1

        # 3. My History
        menu_items.append(t("📜 My History"))
        history_idx = len(menu_items) - 1

        # 4. My Downloads (local files in ~/Downloads/FreeFlix/)
        menu_items.append(t("📁 My Downloads"))
        downloads_idx = len(menu_items) - 1

        # 5. Providers
        menu_items.append(t("🌍 Browse Providers"))
        providers_idx = len(menu_items) - 1

        # 6. Settings / Exit
        menu_items.append(t("⚙ Settings (AniList)"))
        settings_idx = len(menu_items) - 1

        menu_items.append(t("❌ Exit"))

        choice_idx = select_from_list(menu_items, t("What would you like to do?"))

        if last_watch and choice_idx == resume_idx:
            history_ui.handle_resume(last_watch)
            continue

        if choice_idx == anilist_resume_idx:
            anilist.handle_anilist_continue()
            continue

        if choice_idx == history_idx:
            history_ui.handle_history()
            continue

        if choice_idx == downloads_idx:
            _browse_local_downloads()
            continue

        if choice_idx == providers_idx:
            user_lang = tracker.get_language()
            available_providers = registry.get_providers(user_lang)

            p_items = [p["name"] for p in available_providers] + [t("← Back")]
            p_idx = select_from_list(p_items, t("Select a Provider:"))

            if p_idx < len(available_providers):
                available_providers[p_idx]["handler"]()
            continue

        if choice_idx == settings_idx:
            # Settings menu
            while True:
                clear_screen()
                print_header(t("Settings"))
                token = tracker.get_anilist_token()
                lang = tracker.get_language()
                player = tracker.get_player()


                lang_display = get_language_display(lang)
                player_display = get_player_display(player)

                quality = tracker.get_download_quality()
                os_key = tracker.get_opensubtitles_key()
                par_n = tracker.get_parallel_downloads()
                nv_mode = tracker.get_nvidia_offload()
                from . import notifications as notif_mod
                notif_on = notif_mod.is_systemd_timer_installed()
                opts = [
                    f"{t('Update AniList Token')} ({'Set' if token else 'Not Set'})",
                    f"{t('Update Language')} ({lang_display})",
                    f"{t('Choose default Player')} ({player_display})",
                    f"{t('Download Quality')} ({quality})",
                    f"{t('OpenSubtitles API Key')} ({'Set' if os_key else 'Not Set'})",
                    f"{t('Parallel Downloads')} ({par_n})",
                    f"{t('Daily New-Episode Notifications')} ({'ON' if notif_on else 'OFF'})",
                    f"Nvidia GPU offload ({nv_mode})",
                    t("Back"),
                ]

                s_choice = select_from_list(opts, t("Select Setting:"))

                if s_choice == 0:
                    new_token = get_user_input("Enter new AniList Token")
                    if new_token:
                        tracker.set_anilist_token(new_token)
                        print_success("Token saved.")
                        pause()
                elif s_choice == 1:
                    langs = get_all_languages()
                    l_choice = select_from_list(
                        [l[1] for l in langs], "Select Language:"
                    )
                    tracker.set_language(langs[l_choice][0])
                    print_success(f"Language updated to: {langs[l_choice][1]}")
                    pause()
                elif s_choice == 2:
                    players = get_all_players()
                    p_choice = select_from_list(
                        [p[1] for p in players], "Select default player:"
                    )
                    tracker.set_player(players[p_choice][0])
                    print_success(f"Player updated to: {players[p_choice][1]}")
                    pause()
                elif s_choice == 3:
                    q_opts = ["auto (best available)", "1080p max", "720p max", "480p max"]
                    q_vals = ["auto", "1080", "720", "480"]
                    q_choice = select_from_list(q_opts, "Select download quality:")
                    tracker.set_download_quality(q_vals[q_choice])
                    print_success(f"Download quality set to: {q_opts[q_choice]}")
                    pause()
                elif s_choice == 4:
                    print_info("Register at https://www.opensubtitles.com/en/consumers")
                    print_info("to get a free API key, then paste it here.")
                    new_key = get_user_input("Enter OpenSubtitles API key")
                    if new_key:
                        tracker.set_opensubtitles_key(new_key.strip())
                        print_success("OpenSubtitles key saved.")
                        pause()
                elif s_choice == 5:
                    n_opts = ["1 (sequential)", "2", "3", "4"]
                    n_choice = select_from_list(n_opts, "Max parallel downloads:")
                    tracker.set_parallel_downloads(n_choice + 1)
                    print_success(f"Parallel downloads set to {n_choice + 1}")
                    pause()
                elif s_choice == 6:
                    if notif_on:
                        if select_from_list(["Yes", "No"], "Disable daily notifications?") == 0:
                            if notif_mod.uninstall_systemd_timer():
                                print_success("Notifications disabled.")
                            else:
                                print_error("Failed to disable notifications.")
                            pause()
                    else:
                        print_info("This installs a systemd --user timer that runs once a day")
                        print_info("and uses notify-send to alert you about new episodes.")
                        if select_from_list(["Yes", "No"], "Enable daily notifications?") == 0:
                            if notif_mod.install_systemd_timer():
                                print_success("Notifications enabled (runs daily).")
                            else:
                                print_error(
                                    "Failed to enable. Make sure systemd --user works "
                                    "and 'libnotify' is installed (sudo dnf install libnotify)."
                                )
                            pause()
                elif s_choice == 7:
                    print_info("On laptops with Intel/AMD iGPU + Nvidia dGPU, route")
                    print_info("mpv to the Nvidia card for far better Anime4K perf.")
                    nv_opts = ["auto (detect nvidia-smi)", "on (force Nvidia)", "off (always iGPU)"]
                    nv_vals = ["auto", "on", "off"]
                    c = select_from_list(nv_opts, "Nvidia GPU offload:")
                    tracker.set_nvidia_offload(nv_vals[c])
                    print_success(f"Nvidia offload: {nv_vals[c]}")
                    pause()
                else:
                    break
            continue

        # Exit
        print_success(t("Goodbye!"))
        proxy.stop_proxy_server()
        os._exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nGoodbye!")
        proxy.stop_proxy_server()
        os._exit(0)
