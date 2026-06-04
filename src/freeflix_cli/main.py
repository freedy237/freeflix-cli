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
from . import setup_assistant
from .tracker import tracker
from .providers_registry import registry
from .languages import LANGUAGES, get_language_display, get_all_languages
from .player_manager import PLAYERS, get_player_display, get_all_players
from .handlers import (
    anime_sama,
    coflix,
    french_stream,
    french_manga,
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
    candidates = [preferred, "mpv", "vlc"]
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
            "No local player found (tried mpv, vlc). "
            "Install one with: sudo dnf install mpv"
        )
        pause()
        return

    print_info(f"Launching {chosen_name} for [cyan]{os.path.basename(selected_path)}[/cyan]")
    try:
        subprocess.run([player_bin, selected_path], check=False)
    except KeyboardInterrupt:
        pass


def _show_stats():
    """Render the viewing-stats dashboard."""
    from rich.panel import Panel
    from rich.text import Text
    from .themes import color

    clear_screen()
    print_header(t("📊 My Stats"))
    stats = tracker.get_stats()

    if stats["total"] == 0:
        print_info(t("No viewing history yet — watch something first!"))
        pause()
        return

    body = Text()
    body.append(f"\n  {t('Total watched')} : ", style="white")
    body.append(f"{stats['total']}\n", style=f"bold {color('success')}")
    body.append(f"  {t('Today')} : ", style="white")
    body.append(f"{stats['today']}", style=f"bold {color('accent')}")
    body.append(f"   {t('This week')} : ", style="white")
    body.append(f"{stats['this_week']}", style=f"bold {color('accent')}")
    body.append(f"   {t('This month')} : ", style="white")
    body.append(f"{stats['this_month']}\n", style=f"bold {color('accent')}")
    body.append(f"  🔥 {t('Day streak')} : ", style="white")
    body.append(f"{stats['streak']}\n\n", style=f"bold {color('warning')}")

    def _top(d, n=5):
        return sorted(d.items(), key=lambda kv: kv[1], reverse=True)[:n]

    if stats["by_provider"]:
        body.append(f"  {t('By source')} :\n", style=f"bold {color('info')}")
        for name, cnt in _top(stats["by_provider"]):
            body.append(f"    {name:20s} {cnt}\n", style="white")
        body.append("\n")

    if stats["by_genre"]:
        body.append(f"  {t('Favorite genres')} :\n", style=f"bold {color('info')}")
        for name, cnt in _top(stats["by_genre"]):
            body.append(f"    {name:20s} {cnt}\n", style="white")
        body.append("\n")

    if stats["top_series"]:
        body.append(f"  {t('Most watched')} :\n", style=f"bold {color('info')}")
        for name, cnt in _top(stats["top_series"]):
            body.append(f"    {name:30s} {cnt}\n", style="white")

    console.print(
        Panel(body, border_style=color("border"), expand=False,
              title=f"[{color('header')}]{t('Viewing statistics')}[/]")
    )
    pause()


def _show_about(version: str):
    """Render the About panel with version, links, credits."""
    from rich.panel import Panel
    from rich.text import Text

    body = Text()
    body.append("\n  FreeFlix CLI", style="bold cyan")
    body.append(f"  v{version}\n\n", style="bold yellow")
    body.append("  " + t("Watch movies, series and anime from your terminal.\n"),
                style="white")
    body.append("\n")
    body.append(f"  GitHub  : ", style="dim")
    body.append("https://github.com/freedy237/freeflix-cli\n", style="cyan underline")
    body.append(f"  PyPI    : ", style="dim")
    body.append("https://pypi.org/project/freeflix-cli/\n", style="cyan underline")
    body.append(f"  Issues  : ", style="dim")
    body.append("https://github.com/freedy237/freeflix-cli/issues\n", style="cyan underline")
    body.append("\n")
    body.append(f"  {t('License')} : ", style="dim")
    body.append("GPL-3.0-or-later\n", style="white")
    body.append(f"  {t('Author')}  : ", style="dim")
    body.append("freedy237 ", style="white")
    body.append("<joresdomche@gmail.com>\n", style="dim")
    body.append("\n")
    body.append(f"  {t('Based on')} ", style="dim")
    body.append("autoflix-cli", style="bold white")
    body.append(f" {t('by')} ", style="dim")
    body.append("PaulExplorer\n", style="white")
    body.append("    ", style="dim")
    body.append("https://github.com/PaulExplorer/autoflix-cli\n", style="cyan underline")
    body.append(f"\n  {t('Anime4K shaders by')} ", style="dim")
    body.append("bloc97", style="white")
    body.append(" — https://github.com/bloc97/Anime4K\n", style="cyan underline")
    body.append("\n")

    console.print(
        Panel(
            body,
            title=f"[bold cyan]ℹ  {t('About')}[/bold cyan]",
            subtitle=f"[dim]freeflix v{version}[/dim]",
            border_style="cyan",
            expand=False,
        )
    )


def _prompt_anime_language(force=False):
    """
    First-launch step 1 : ask which language the user wants their anime in,
    BEFORE the interface language is chosen. Runs once, unless ``force`` is
    set (e.g. from ``freeflix --setup``) to let the user redo the choice.

    The interface language isn't set yet at this point, so the prompt is
    intentionally bilingual (FR + EN).
    """
    if tracker.get_anime_language() and not force:
        return

    clear_screen()
    print_header("🎴 Anime language  /  Langue des animes")
    print_info(
        "Do you want anime in English (VO/sub) or in French (VF/VOSTFR)?"
    )
    print_info(
        "Voulez-vous les animes en anglais (VO/sous-titres) "
        "ou en français (VF/VOSTFR) ?"
    )

    # Order: English first, then French (codes map to anime_language).
    options = [
        ("en", "🇺🇸 English  (VO / Subtitles)"),
        ("fr", "🇫🇷 Français  (VF / VOSTFR)"),
    ]
    choice = select_from_list([label for _, label in options], "Choice / Choix:")
    code, label = options[choice]
    tracker.set_anime_language(code)
    print_success(f"Anime language set to / Langue des animes : {label}")
    pause()


def check_language_setup(force=False):
    """
    First-launch setup wizard. Two ordered steps :
      1. anime content language (English VO vs French VF) — asked first
      2. interface language (English / Français)

    Normally each step runs only if unset. With ``force=True`` (from
    ``freeflix --setup``) both steps are asked again so the user can redo
    the choices they made on first launch.
    """
    # Step 1 — anime content language (before interface language).
    _prompt_anime_language(force=force)

    # Step 2 — interface language.
    if force or not tracker.get_language():
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
    # ── CLI flags (lightweight, before anything else) ──────────
    if "--setup" in sys.argv:
        # Redo the full first-launch experience : the language wizard
        # (anime language, then interface language) AND the dependency
        # setup assistant.
        check_language_setup(force=True)
        setup_assistant.run_setup(force=True)
        return 0
    if "--version" in sys.argv or "-V" in sys.argv:
        try:
            import importlib.metadata as _im
            print(_im.version("freeflix-cli"))
        except Exception:
            print("dev")
        return 0
    if "--help" in sys.argv or "-h" in sys.argv:
        print("freeflix — terminal streaming for movies / series / anime\n")
        print("  freeflix           launch the TUI")
        print("  freeflix --setup   re-run setup : anime + interface language, then deps")
        print("  freeflix --version print the installed version")
        print("  freeflix --help    this message")
        return 0

    # ── First-launch setup (only if user hasn't declined) ──────
    if setup_assistant.should_prompt_setup():
        setup_assistant.run_setup(force=False)

    # ── Splash screen ──────────────────────────────────────────
    try:
        import importlib.metadata as _im
        _v = _im.version("freeflix-cli")
    except Exception:
        _v = ""
    from . import splash
    splash.show_splash(version=_v)

    # Register Providers
    #
    # Order matters : it is the order shown in the source menu. Anime
    # sources are listed first, then movie/series sources at the bottom.

    # ── Anime sources (top) ────────────────────────────────────
    registry.register(
        "🎌 Anime-Sama (Anime and animated movies)",
        anime_sama.handle_anime_sama,
        supported_languages=["en", "fr"],
    )
    registry.register(
        "✨ GoldenAnime (VO and Subtitles)",
        goldenanime.handle_goldenanime,
        supported_languages=["en", "fr"],
    )
    registry.register(
        "🎴 French-Manga (Anime VF/VOSTFR)",
        french_manga.handle_french_manga,
        supported_languages=["fr"],
    )

    # ── Movie / series sources (middle) ────────────────────────
    registry.register(
        "🌟 GoldenMS (Movies & Series)",
        goldenms.handle_goldenms,
        supported_languages=["en"],
    )
    registry.register(
        "🇫🇷 French-Stream (Series and movies)",
        french_stream.handle_french_stream,
        supported_languages=["fr"],
    )
    # Coflix is disabled : its player aggregator (lecteurvideo.com) is
    # Cloudflare-protected, so nothing it lists is playable from the
    # terminal. The handler/scraper stay in the tree in case the host
    # changes ; just not registered as a selectable source.
    # registry.register(
    #     "🎬 Coflix (Series and movies)",
    #     coflix.handle_coflix,
    #     supported_languages=["fr"],
    # )

    # ── Torrent sources (very bottom) ──────────────────────────
    registry.register(
        "🌊 Nyaa (Torrents — high-quality anime releases)",
        nyaa_handler.handle_nyaa,
        supported_languages=["en", "fr"],
    )

    # Check for updates
    if check_update():
        pause()

    # Check for language setup
    check_language_setup()

    # Start Proxy Server
    proxy.start_proxy_server()

    # Resolve installed version once, for the home header and About panel.
    try:
        import importlib.metadata as _im
        _VERSION = _im.version("freeflix-cli")
    except Exception:
        _VERSION = "dev"

    while True:
        clear_screen()
        print_header(f"{t('FreeFlix CLI - Home')}  •  v{_VERSION}")

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

        # 4b. My Stats
        menu_items.append(t("📊 My Stats"))
        stats_idx = len(menu_items) - 1

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

        if choice_idx == stats_idx:
            _show_stats()
            continue

        if choice_idx == providers_idx:
            # Sources are filtered by the chosen content (anime) language,
            # not the interface language. Fall back to interface language,
            # then to all sources, if it was never set.
            content_lang = tracker.get_anime_language() or tracker.get_language()
            available_providers = registry.get_providers(content_lang)

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
                anime_lang = tracker.get_anime_language()
                anime_lang_display = get_language_display(anime_lang)

                quality = tracker.get_download_quality()
                os_key = tracker.get_opensubtitles_key()
                par_n = tracker.get_parallel_downloads()
                nv_mode = tracker.get_nvidia_offload()
                from . import notifications as notif_mod
                from . import themes as themes_mod
                theme_label = themes_mod.active_theme().get("label", "?")
                notif_on = notif_mod.is_systemd_timer_installed()
                opts = [
                    f"{t('Update AniList Token')} ({'Set' if token else 'Not Set'})",
                    f"{t('Update Language')} ({lang_display})",
                    f"{t('Update Anime Language')} ({anime_lang_display})",
                    f"🎨 {t('Theme')} ({theme_label})",
                    f"{t('Choose default Player')} ({player_display})",
                    f"{t('Download Quality')} ({quality})",
                    f"{t('OpenSubtitles API Key')} ({'Set' if os_key else 'Not Set'})",
                    f"{t('Parallel Downloads')} ({par_n})",
                    f"{t('Daily New-Episode Notifications')} ({'ON' if notif_on else 'OFF'})",
                    f"Nvidia GPU offload ({nv_mode})",
                    f"ℹ {t('About')}",
                    t("Back"),
                ]

                s_choice = select_from_list(opts, t("Select Setting:"))

                if s_choice == 0:
                    new_token = get_user_input(t("Enter new AniList Token"))
                    if new_token:
                        tracker.set_anilist_token(new_token)
                        print_success(t("Token saved."))
                        pause()
                elif s_choice == 1:
                    langs = get_all_languages()
                    l_choice = select_from_list(
                        [l[1] for l in langs], t("Select Language:")
                    )
                    tracker.set_language(langs[l_choice][0])
                    print_success(f"{t('Language updated to:')} {langs[l_choice][1]}")
                    pause()
                elif s_choice == 2:
                    langs = get_all_languages()
                    a_choice = select_from_list(
                        [l[1] for l in langs], t("Anime language:")
                    )
                    tracker.set_anime_language(langs[a_choice][0])
                    print_success(
                        f"{t('Anime language updated to:')} {langs[a_choice][1]}"
                    )
                    pause()
                elif s_choice == 3:
                    tlist = themes_mod.list_themes()
                    t_choice = select_from_list(
                        [lbl for _, lbl in tlist], t("Select theme:")
                    )
                    tracker.set_theme(tlist[t_choice][0])
                    print_success(f"{t('Theme set to:')} {tlist[t_choice][1]}")
                    pause()
                elif s_choice == 4:
                    players = get_all_players()
                    p_choice = select_from_list(
                        [p[1] for p in players], t("Select default player:")
                    )
                    tracker.set_player(players[p_choice][0])
                    print_success(f"{t('Player updated to:')} {players[p_choice][1]}")
                    pause()
                elif s_choice == 5:
                    q_opts = ["auto (best available)", "1080p max", "720p max", "480p max"]
                    q_vals = ["auto", "1080", "720", "480"]
                    q_choice = select_from_list(q_opts, t("Select download quality:"))
                    tracker.set_download_quality(q_vals[q_choice])
                    print_success(f"{t('Download quality set to:')} {q_opts[q_choice]}")
                    pause()
                elif s_choice == 6:
                    print_info("Register at https://www.opensubtitles.com/en/consumers")
                    print_info("to get a free API key, then paste it here.")
                    new_key = get_user_input(t("Enter OpenSubtitles API key"))
                    if new_key:
                        tracker.set_opensubtitles_key(new_key.strip())
                        print_success(t("OpenSubtitles key saved."))
                        pause()
                elif s_choice == 7:
                    n_opts = ["1 (sequential)", "2", "3", "4"]
                    n_choice = select_from_list(n_opts, t("Max parallel downloads:"))
                    tracker.set_parallel_downloads(n_choice + 1)
                    print_success(f"{t('Parallel downloads set to')} {n_choice + 1}")
                    pause()
                elif s_choice == 8:
                    if notif_on:
                        if select_from_list([t("Yes"), t("No")], t("Disable daily notifications?")) == 0:
                            if notif_mod.uninstall_systemd_timer():
                                print_success(t("Notifications disabled."))
                            else:
                                print_error(t("Failed to disable notifications."))
                            pause()
                    else:
                        print_info("This installs a systemd --user timer that runs once a day")
                        print_info("and uses notify-send to alert you about new episodes.")
                        if select_from_list([t("Yes"), t("No")], t("Enable daily notifications?")) == 0:
                            if notif_mod.install_systemd_timer():
                                print_success(t("Notifications enabled (runs daily)."))
                            else:
                                print_error(
                                    "Failed to enable. Make sure systemd --user works "
                                    "and 'libnotify' is installed (sudo dnf install libnotify)."
                                )
                            pause()
                elif s_choice == 9:
                    print_info(t("On laptops with Intel/AMD iGPU + Nvidia dGPU, route"))
                    print_info(t("mpv to the Nvidia card for far better Anime4K perf."))
                    nv_opts = ["auto (detect nvidia-smi)", "on (force Nvidia)", "off (always iGPU)"]
                    nv_vals = ["auto", "on", "off"]
                    c = select_from_list(nv_opts, t("Nvidia GPU offload:"))
                    tracker.set_nvidia_offload(nv_vals[c])
                    print_success(f"{t('Nvidia offload:')} {nv_vals[c]}")
                    pause()
                elif s_choice == 10:
                    _show_about(_VERSION)
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
