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
    toast,
    crumb_reset,
    crumb_push,
    console,
)
from .i18n import t
from .icons import icon
from .update_checker import check_update
from . import setup_assistant
from .tracker import tracker
from .providers_registry import registry
from .languages import get_language_display, get_all_languages
from .player_manager import get_player_display, get_all_players
from .handlers import (
    anime_sama,
    coflix,
    french_stream,
    french_manga,
    papystreaming,
    anilist,
    goldenanime,
    goldenms,
    nyaa as nyaa_handler,
)
from . import history_ui
# NB: proxy is imported lazily (on first playback) so Flask stays out of
# FreeFlix startup — see player_manager.play_video / _stop_proxy_if_running.
import sys
import os
import time


def _stop_proxy_if_running():
    """Shut the proxy down at exit — but only if it was ever started.

    proxy is imported lazily on first playback, so if it's not already in
    sys.modules nothing played this session and there's nothing to stop
    (and no reason to import Flask just to exit)."""
    mod = sys.modules.get(__package__ + ".proxy")
    if mod is not None:
        try:
            mod.stop_proxy_server()
        except Exception:
            pass


def _handle_partial_download(it):
    """Resume or delete an interrupted download from .temp/."""
    import shutil as _sh
    from .player_manager import resume_download

    act = select_from_list(
        [t("Resume download"), t("Delete partial"), t("← Back")],
        f"{it['title']} — {t('interrupted')}",
    )
    if act == 0:
        clear_screen()
        if resume_download(it["meta"]):
            print_success(t("Download completed."))
        else:
            print_warning(
                t("Could not resume — the stream link may have expired; "
                  "re-download it from the source.")
            )
        pause()
    elif act == 1:
        _sh.rmtree(it["dir"], ignore_errors=True)
        print_success(t("Partial deleted."))
        pause()


def _downloads_summary(files, interrupted, DOWNLOAD_DIR):
    """Top panel for the downloads manager: disk space + totals."""
    import shutil
    from rich.panel import Panel
    from rich.text import Text
    from .themes import color

    total_mb = sum(s for _, _, s in files)
    free_gb = None
    try:
        du = shutil.disk_usage(DOWNLOAD_DIR if os.path.isdir(DOWNLOAD_DIR)
                               else os.path.expanduser("~"))
        free_gb = du.free / (1024 ** 3)
    except Exception:
        pass

    body = Text()
    body.append(f"  {icon('folder')} {t('Downloads')}: ", style=color("dim"))
    body.append(f"{len(files)}", style=f"bold {color('info')}")
    body.append(f"    {t('Total size')}: ", style=color("dim"))
    body.append(f"{total_mb/1024:.1f} GB" if total_mb >= 1024 else f"{total_mb:.0f} MB",
                style=f"bold {color('success')}")
    if interrupted:
        body.append(f"    {icon('download')} {t('interrupted')}: ", style=color("dim"))
        body.append(f"{len(interrupted)}", style=f"bold {color('warning')}")
    if free_gb is not None:
        body.append(f"\n  {t('Disk')}: ", style=color("dim"))
        body.append(f"{free_gb:.0f} GB {t('free')}", style=f"bold {color('accent')}")
    return Panel(body, border_style=color("border"),
                 title=f"[{color('header')}]{t('Downloads manager')}[/]", title_align="left")


def _browse_local_downloads():
    """Downloads manager: completed files (play/delete), interrupted downloads
    (resume/delete), and a disk-space summary."""
    import shutil
    import subprocess

    from .player_manager import DOWNLOAD_DIR, list_interrupted_downloads

    video_exts = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".ts"}

    while True:
        clear_screen()
        files = []
        if os.path.isdir(DOWNLOAD_DIR):
            for root, dirs, names in os.walk(DOWNLOAD_DIR):
                dirs[:] = [d for d in dirs if d != ".temp"]
                for n in names:
                    if os.path.splitext(n)[1].lower() in video_exts:
                        full = os.path.join(root, n)
                        rel = os.path.relpath(full, DOWNLOAD_DIR)
                        try:
                            size_mb = os.path.getsize(full) / (1024 * 1024)
                        except OSError:
                            size_mb = 0
                        files.append((rel, full, size_mb))
        files.sort(key=lambda x: x[0].lower())
        interrupted = list_interrupted_downloads()

        if not files and not interrupted:
            print_header(f"{icon('folder')} {t('My Downloads')}")
            print_info(f"{t('No downloads yet')} ({DOWNLOAD_DIR}).")
            print_info(t('Use the "download" option from a video to start.'))
            pause()
            return

        entries, labels, group_headers = [], [], {}
        for rel, full, size in files:
            entries.append(("file", full))
            labels.append(f"{rel}  ({size:.1f} MB)")
        if interrupted:
            group_headers[len(labels)] = t("Interrupted downloads")
            for it in interrupted:
                entries.append(("partial", it))
                pct = (f"{it['percent']}%" if it["percent"] is not None
                       else f"{it['size_mb']:.0f} MB")
                labels.append(f"{icon('download')} {it['title']} — "
                              f"{t('interrupted')} ({pct})")
        labels.append(t("← Back"))

        choice = select_from_list(labels, t("Select a file to play:"),
                                  group_headers=group_headers,
                                  top=_downloads_summary(files, interrupted, DOWNLOAD_DIR))
        if choice >= len(entries):
            return
        kind, payload = entries[choice]
        if kind == "partial":
            _handle_partial_download(payload)
            continue

        # Completed file : Play / Delete.
        act = select_from_list(
            [t("Play"), t("Delete"), t("← Back")],
            f"{os.path.basename(payload)}",
        )
        if act == 1:
            try:
                os.remove(payload)
                toast(t("Deleted."))
            except OSError as e:
                print_error(f"{e}")
                pause()
            continue
        if act != 0:
            continue

        preferred = tracker.get_player() or "mpv"
        player_bin = None
        for cand in [preferred, "mpv", "vlc"]:
            if cand in ("download", "browser", "manual"):
                continue
            b = shutil.which(cand)
            if b:
                player_bin = b
                break
        if not player_bin:
            print_error(t("No local player found (tried mpv, vlc). "
                          "Install one with: sudo dnf install mpv"))
            pause()
            continue
        try:
            subprocess.run([player_bin, payload], check=False)
        except KeyboardInterrupt:
            pass


def _show_stats():
    """Render the viewing-stats dashboard."""
    from rich.panel import Panel
    from rich.text import Text
    from .themes import color

    clear_screen()
    print_header(f"{icon('stats')} {t('My Stats')}")
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
    body.append(f"  {icon('fire')} {t('Day streak')} : ", style="white")
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


def _home_dashboard():
    """
    The enriched home 'wow' panel: a greeting, a quick stats line and a
    Continue-watching carousel — all from LOCAL data (instant, no network).
    Returned as a renderable placed above the home menu.
    """
    from rich.panel import Panel
    from rich.text import Text
    from .themes import color
    from datetime import datetime

    stats = tracker.get_stats()
    history = tracker.get_history()
    in_progress = len(tracker.data.get("episode_positions", {}))

    hour = datetime.now().hour
    greet = (t("Good night") if hour < 6 else t("Good morning") if hour < 12
             else t("Good afternoon") if hour < 18 else t("Good evening"))

    body = Text()
    body.append(f"  {greet}    ", style=f"bold {color('accent')}")
    body.append(f"{icon('stats')} {t('This week')}: ", style=color("dim"))
    body.append(f"{stats['this_week']}", style=f"bold {color('info')}")
    body.append(f"    {icon('fire')} {t('Streak')}: ", style=color("dim"))
    body.append(f"{stats['streak']}", style=f"bold {color('warning')}")
    body.append(f"    {icon('play')} {t('In progress')}: ", style=color("dim"))
    body.append(f"{in_progress}", style=f"bold {color('success')}")
    from . import recent
    _new = recent.get_items()
    if _new:
        body.append(f"    {icon('sparkle')} {t('New releases')}: ", style=color("dim"))
        body.append(f"{len(_new)}", style=f"bold {color('accent')}")

    if history:
        from .player_manager import episode_badges
        body.append(f"\n\n  {icon('play')} {t('Continue watching')}",
                    style=f"bold {color('header')}")
        for e in history[:4]:
            s = e.get("series_title", "?")
            se = e.get("season_title", "") or ""
            ep = e.get("episode_title", "") or ""
            badge = episode_badges(s, se, ep)
            row = f"     • {s}" + (f" · {se}" if se else "") + (f" · {ep}" if ep else "")
            body.append("\n" + row[:74], style="white")
            if badge:
                body.append(badge, style=color("info"))
    else:
        body.append(f"\n\n  {t('Nothing watched yet — pick a source below to start!')}",
                    style=color("dim"))

    return Panel(body, border_style=color("accent"), expand=True,
                 title="[bold]FreeFlix[/bold]", title_align="left")


def _theme_preview_panel(theme: dict, title: str):
    """A small sample panel rendered in a given theme dict (for live preview)."""
    from rich.panel import Panel
    from rich.text import Text
    body = Text()
    body.append("  ❯ Menu item (selected)\n", style=f"bold {theme['accent']} reverse")
    body.append("    Another item\n", style="white")
    body.append(f"  {t('recommended')} ✓  ", style=f"bold {theme['success']}")
    body.append("warning  ", style=theme["warning"])
    body.append("error  ", style=theme["error"])
    body.append("info\n", style=theme["info"])
    return Panel(body, border_style=theme["accent"],
                 title=f"[{theme['header']}]{title}[/]", title_align="left")


def _theme_settings():
    """Appearance → Theme : pick a theme or a custom accent, with a live preview
    panel shown before you commit."""
    from . import themes as th
    while True:
        cur = tracker.get_theme()
        acc = tracker.get_custom_accent()
        choice = select_from_list(
            [t("Choose a theme"),
             f"{t('Custom accent colour')} ({acc or t('none')})",
             t("Reset accent"),
             t("← Back")],
            f"{icon('theme')} {t('Theme')}",
        )
        if choice == 0:
            tlist = th.list_themes()
            # Show each theme name painted in its own accent for a quick glance.
            labels = []
            for key, label in tlist:
                a = th.THEMES[key]["accent"]
                labels.append(f"[{a}]●[/] {label}")
            labels.append(t("← Back"))
            idx = select_from_list(labels, t("Select theme:"),
                                   default_index=next((i for i, (k, _) in enumerate(tlist) if k == cur), 0))
            if idx >= len(tlist):
                continue
            key = tlist[idx][0]
            clear_screen()
            console.print(_theme_preview_panel(th.preview_theme(key, acc or None), tlist[idx][1]))
            if select_from_list([t("Apply"), t("← Back")], t("Apply this theme?")) == 0:
                tracker.set_theme(key)
                toast(f"{t('Theme set to:')} {tlist[idx][1]}")
        elif choice == 1:
            val = get_user_input(t("Accent colour (hex like #bd93f9 or a name), blank to cancel"))
            if val:
                clear_screen()
                console.print(_theme_preview_panel(th.preview_theme(cur, val.strip()), val.strip()))
                if select_from_list([t("Apply"), t("← Back")], t("Apply this accent?")) == 0:
                    tracker.set_custom_accent(val.strip())
                    toast(t("Accent updated."))
        elif choice == 2:
            tracker.set_custom_accent("")
            toast(t("Accent reset."))
        else:
            return


def _browse_new_releases(items):
    """Show the background-fetched new releases with posters (chafa preview
    pane); selecting one jumps straight into its latest season."""
    from .cli_utils import select_with_preview, make_preview, crumb, spinner
    from .scraping import anime_sama
    from .handlers.playback import play_episode_flow
    from .player_manager import episode_badges

    previews = [
        make_preview(
            cover=it.get("poster", ""),
            title=it["title"],
            lines=[f"{icon('sparkle')} {it['latest_season']}"],
            panel_title=t("New releases"),
        )
        for it in items
    ]
    labels = [f"{it['title']} — {it['latest_season']}" for it in items]
    idx = select_with_preview(labels, f"{icon('sparkle')} {t('New releases')}", previews)
    if idx >= len(items):
        return
    it = items[idx]

    try:
        with spinner(f"{t('Loading')} {it['latest_season']}…"):
            season = anime_sama.get_season(it["season_url"])
    except Exception:
        print_warning(t("The source may be down or rate-limiting — try again in a moment."))
        pause()
        return

    langs = list(season.episodes.keys())
    if not langs:
        print_warning(t("No episodes found."))
        pause()
        return

    with crumb(it["title"]), crumb(it["latest_season"]):
        while True:  # ── Language ──
            if len(langs) == 1:
                lang = langs[0]
            else:
                li = select_from_list(langs + [t("← Back")],
                                      f"{icon('globe')} {t('Select Language:')}")
                if li >= len(langs):
                    return
                lang = langs[li]
            episodes = season.episodes[lang]
            ep_idx = 0
            while True:  # ── Episode ──
                ep_labels = [
                    e.title + episode_badges(it["title"], it["latest_season"], e.title)
                    for e in episodes
                ]
                with crumb(lang):
                    ep_idx = select_from_list(
                        ep_labels + [t("← Back")],
                        f"{icon('tv')} {t('Select Episode:')}",
                        default_index=min(ep_idx, len(episodes) - 1),
                    )
                if ep_idx >= len(episodes):
                    break
                play_episode_flow(
                    provider_name="Anime-Sama",
                    series_title=it["title"],
                    season_title=it["latest_season"],
                    episode=episodes[ep_idx],
                    series_url=it["url"],
                    season_url=it["season_url"],
                    logo_url=it.get("poster"),
                    headers={"Referer": anime_sama.website_origin},
                )
            if len(langs) == 1:
                return


def _show_about(version: str):
    """Render the About panel with version, links, credits — themed."""
    from rich.panel import Panel
    from rich.text import Text
    from .themes import color

    accent = color("accent")
    link = f"{color('info')} underline"

    body = Text()
    body.append("\n  FreeFlix CLI", style=f"bold {accent}")
    body.append(f"  v{version}\n\n", style=f"bold {color('warning')}")
    body.append("  " + t("Watch movies, series and anime from your terminal.\n"),
                style="white")
    body.append("\n")
    body.append("  GitHub  : ", style=color("dim"))
    body.append("https://github.com/freedy237/freeflix-cli\n", style=link)
    body.append("  PyPI    : ", style=color("dim"))
    body.append("https://pypi.org/project/freeflix-cli/\n", style=link)
    body.append("  Issues  : ", style=color("dim"))
    body.append("https://github.com/freedy237/freeflix-cli/issues\n", style=link)
    body.append("\n")
    body.append(f"  {t('License')} : ", style=color("dim"))
    body.append("GPL-3.0-or-later\n", style="white")
    body.append(f"  {t('Author')}  : ", style=color("dim"))
    body.append("freedy237 ", style="white")
    body.append("<joresdomche@gmail.com>\n", style=color("dim"))
    body.append("\n")
    body.append(f"  {t('Based on')} ", style=color("dim"))
    body.append("autoflix-cli", style="bold white")
    body.append(f" {t('by')} ", style=color("dim"))
    body.append("PaulExplorer\n", style="white")
    body.append("    ", style=color("dim"))
    body.append("https://github.com/PaulExplorer/autoflix-cli\n", style=link)
    body.append(f"\n  {t('Anime4K shaders by')} ", style=color("dim"))
    body.append("bloc97", style="white")
    body.append(" — https://github.com/bloc97/Anime4K\n", style=link)
    body.append("\n")

    console.print(
        Panel(
            body,
            title=f"[bold {color('header')}]{icon('info')}  {t('About')}[/]",
            subtitle=f"[{color('dim')}]freeflix v{version}[/]",
            border_style=color("border"),
            expand=False,
        )
    )


def _set_cloudflare_token():
    """
    Settings : paste a cf_clearance cookie (+ User-Agent) so FreeFlix can
    ride a Cloudflare-cleared browser session for a blocked source.
    """
    clear_screen()
    print_header(t("Cloudflare token"))
    print_info(t("If a source is Cloudflare-blocked, pass the check in your browser,"))
    print_info(t("then paste the 'cf_clearance' cookie value + your User-Agent here."))
    print_info(t("(cf_clearance is tied to your IP + User-Agent — both must match.)"))

    fs_url = tracker.get_flaresolverr_url() or "(off)"
    print_info(f"{t('Auto-solver (FlareSolverr)')}: {fs_url}")

    hosts = [
        ("__flaresolverr__", f"{t('Set FlareSolverr URL (auto-solve)')}"),
        ("coflix.cymru", "Coflix"),
        ("anime-sama.to", "Anime-Sama"),
        ("__other__", t("Other host…")),
        ("__clear__", t("Clear all tokens")),
        ("__back__", t("← Back")),
    ]
    idx = select_from_list([label for _, label in hosts], t("Which source?"))
    key, _label = hosts[idx]
    if key == "__back__":
        return
    if key == "__flaresolverr__":
        print_info(t("FlareSolverr auto-solves Cloudflare. Leave empty to disable."))
        url = get_user_input(t("FlareSolverr URL [http://127.0.0.1:8191]"))
        tracker.set_flaresolverr_url((url or "").strip())
        print_success(t("FlareSolverr URL updated."))
        pause()
        return
    if key == "__clear__":
        tracker.clear_cf_clearance()
        print_success(t("All Cloudflare tokens cleared."))
        pause()
        return
    if key == "__other__":
        key = get_user_input(t("Host (e.g. coflix.cymru)"))
        if not key:
            return

    token = get_user_input(t("Paste cf_clearance cookie value"))
    if not token:
        return
    ua = get_user_input(t("Paste your browser User-Agent (recommended)"))
    tracker.set_cf_clearance(key.strip(), token.strip(), (ua or "").strip() or None)
    print_success(f"{t('Cloudflare token saved for')} {key}")
    pause()


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

        choice = select_from_list([lang[1] for lang in langs], t("Choice:"))
        selected_lang = langs[choice][0]
        tracker.set_language(selected_lang)
        print_success(f"{t('Language set to:')} {langs[choice][1]}")
        pause()


def _register_providers():
    """Register every provider in source-menu order (anime first, then
    movies/series, then torrents). Called once at startup."""
    _reco = f"  {icon('star')} {t('recommended')}"
    # ── Anime / Manga sources ──────────────────────────────────
    registry.register(
        f"{icon('anime')} Anime-Sama ({t('Anime and animated movies')}){_reco}",
        anime_sama.handle_anime_sama,
        supported_languages=["en", "fr"],
        category="anime",
    )
    registry.register(
        f"{icon('manga')} French-Anime ({t('Anime VF/VOSTFR')})",
        french_manga.handle_french_manga,
        supported_languages=["fr"],
        category="anime",
    )
    registry.register(
        f"{icon('sparkle')} GoldenAnime ({t('VO and Subtitles')})",
        goldenanime.handle_goldenanime,
        supported_languages=["en", "fr"],
        category="anime",
    )
    registry.register(
        f"{icon('wave')} Nyaa ({t('Torrents — high-quality anime releases')})",
        nyaa_handler.handle_nyaa,
        supported_languages=["en", "fr"],
        category="anime",
    )


    # ── Films & Series sources ─────────────────────────────────
    registry.register(
        f"{icon('star')} GoldenMS ({t('Movies & Series')})",
        goldenms.handle_goldenms,
        supported_languages=["en"],
        category="movies",
    )
    registry.register(
        f"{icon('flag_fr')} French-Stream ({t('Series and movies')}){_reco}",
        french_stream.handle_french_stream,
        supported_languages=["fr"],
        category="movies",
    )
    registry.register(
        f"{icon('movie')} Papystreaming ({t('Movies & Series')})",
        papystreaming.handle_papystreaming,
        supported_languages=["en"],
        category="movies",
    )
    # Coflix : self-heals (coflix.dance/.cymru…) ; on a Cloudflare captcha it
    # raises a clean "protégée par Cloudflare" message instead of crashing.
    registry.register(
        f"{icon('movie')} Coflix ({t('Series and movies')})",
        coflix.handle_coflix,
        supported_languages=["fr"],
        category="movies",
    )


def main():
    # ── CLI flags (lightweight, before anything else) ──────────
    if "--doctor" in sys.argv or "-D" in sys.argv:
        from .doctor import cli_doctor
        return cli_doctor()
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
        print("  freeflix --doctor  run system diagnostic")
        print("  freeflix --doctor --upload  diagnostic + upload to Gist")
        print("  freeflix --version print the installed version")
        print("  freeflix --help    this message")
        return 0

    # Kill terminal focus/mouse/paste reports so their escape sequences can't
    # be misread as a stray Esc (looked like FreeFlix closing by itself).
    from .cli_utils import disable_terminal_reports
    disable_terminal_reports()

    # Background "new releases" feed (personalised to your history) — never
    # blocks the home; results appear once ready.
    from . import recent
    recent.start_background_fetch()

    # ── Resumable dependency gate ──────────────────────────────
    #    Until the "all good" flag is cached, every launch re-checks what's
    #    installed and finishes ONLY the missing pieces (instead of jumping
    #    ahead with half the tools missing).
    setup_assistant.ensure_runtime_deps()

    # ── First launch only : default to nerd icons if a Nerd Font is present ──
    setup_assistant.maybe_default_nerd_icons()
    # Windows: make sure the terminal actually USES the Nerd Font (once).
    setup_assistant.ensure_nerd_terminal_font()

    # ── First-launch setup (only if user hasn't declined) ──────
    if setup_assistant.should_prompt_setup():
        setup_assistant.run_setup(force=False)

    # ── Resolve version (used for splash + post-upgrade migrations) ──
    try:
        import importlib.metadata as _im
        _v = _im.version("freeflix-cli")
    except Exception:
        _v = ""

    # ── Post-upgrade migrations : first launch after an upgrade finishes
    #    installing whatever the new version needs (and cleans up removals).
    setup_assistant.run_pending_migrations(_v)

    # Safety net (runs every launch, idempotent + cheap): the migration above
    # is skipped for users coming from a pre-migration version (last_setup
    # unknown), so fix a stale Anime4K input.conf unconditionally — a no-op once
    # it's already in the cross-platform format.
    setup_assistant._fix_anime4k_input_conf()

    # ── Splash + provider registration ─────────────────────────
    #    Big FreeFlix wordmark with an animated ▰▰▱ loading bar while the
    #    quiet startup work (provider registration) runs underneath.
    from . import progress
    with progress.LoadingScreen(version=_v) as _ls:
        # A short, smooth 0 -> 100% sequence so the splash feels intentional
        # instead of flashing past.
        _ls.status(t("Starting up…"), frac=0.2)
        time.sleep(0.2)
        _ls.status(t("Loading providers…"), frac=0.55)
        _register_providers()
        time.sleep(0.22)
        _ls.status(t("Preparing the library…"), frac=0.85)
        time.sleep(0.2)
        _ls.status(t("Ready"), frac=1.0)
        time.sleep(0.28)

    # Check for updates
    if check_update():
        pause()

    # Check for language setup
    check_language_setup()

    # The M3U8 proxy is started lazily on first playback (proxy.ensure_started),
    # so launching FreeFlix no longer imports Flask or binds a port up front.

    # Housekeeping : sweep abandoned .temp/ download staging in the background
    # so crashed / aborted downloads don't pile up. Never blocks startup.
    try:
        import threading as _th
        from .player_manager import cleanup_temp as _cleanup_temp
        _th.Thread(target=_cleanup_temp, daemon=True).start()
    except Exception:
        pass

    # Warm the source health cache in the background so the sources menu can
    # show an 'offline' badge without ever blocking. Best-effort.
    try:
        from . import health as _health
        from .scraping.config import portals as _portals
        _health.refresh(_portals)
    except Exception:
        pass

    # Resolve installed version once, for the home header and About panel.
    try:
        import importlib.metadata as _im
        _VERSION = _im.version("freeflix-cli")
    except Exception:
        _VERSION = "dev"

    while True:
        clear_screen()

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

        # 2. Continue from AniList (only if a token is configured)
        if tracker.get_anilist_token():
            menu_items.append(f"{icon('play')} {t('Continue from AniList')}")
            anilist_resume_idx = len(menu_items) - 1

        # 3. Browse sources — right after Resume (the main action)
        menu_items.append(f"{icon('globe')} {t('Browse Providers')}")
        providers_idx = len(menu_items) - 1

        # 3b. New releases (only if the background feed found some)
        from . import recent
        new_releases = recent.get_items()
        new_idx = -1
        if new_releases:
            menu_items.append(
                f"{icon('sparkle')} {t('New releases')} ({len(new_releases)})"
            )
            new_idx = len(menu_items) - 1

        # 4. My History
        menu_items.append(f"{icon('history')} {t('My History')}")
        history_idx = len(menu_items) - 1

        # 5. My Downloads (local files in ~/Downloads/FreeFlix/)
        menu_items.append(f"{icon('folder')} {t('My Downloads')}")
        downloads_idx = len(menu_items) - 1

        # 6. My Stats
        menu_items.append(f"{icon('stats')} {t('My Stats')}")
        stats_idx = len(menu_items) - 1

        # 6. Settings / Exit
        menu_items.append(f"{icon('settings')} {t('Settings (AniList)')}")
        settings_idx = len(menu_items) - 1

        menu_items.append(f"{icon('exit')} {t('Exit')}")

        crumb_reset(f"{icon('home')} {t('Home')}")
        choice_idx = select_from_list(
            menu_items,
            t("What would you like to do?"),
            header=f"{icon('home')} {t('FreeFlix CLI - Home')}  •  v{_VERSION}",
            top=_home_dashboard(),
        )

        if last_watch and choice_idx == resume_idx:
            history_ui.handle_resume(last_watch)
            continue

        if choice_idx == anilist_resume_idx:
            anilist.handle_anilist_continue()
            continue

        if new_idx >= 0 and choice_idx == new_idx:
            crumb_reset(f"{icon('home')} {t('Home')}", t("New releases"))
            _browse_new_releases(new_releases)
            continue

        if choice_idx == history_idx:
            crumb_reset(f"{icon('home')} {t('Home')}", t("My History"))
            history_ui.handle_history()
            continue

        if choice_idx == downloads_idx:
            crumb_reset(f"{icon('home')} {t('Home')}", t("My Downloads"))
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

            # Group the sources : anime / manga first, then films & series
            # (stable order within each group), under section headers.
            anime = [p for p in available_providers if p.get("category") == "anime"]
            movies = [p for p in available_providers if p.get("category") == "movies"]
            others = [p for p in available_providers
                      if p.get("category") not in ("anime", "movies")]
            ordered = anime + movies + others

            group_headers = {}
            if anime:
                group_headers[0] = f"{icon('anime')} {t('Anime / Manga')}"
            if movies:
                group_headers[len(anime)] = f"{icon('movie')} {t('Movies & Series')}"
            if others:
                group_headers[len(anime) + len(movies)] = t("Other")

            # Stay in the source list : when a provider's flow ends (search
            # cancelled with Esc, finished, or backed out), come back HERE —
            # not to the home menu. Only the list's "← Back" returns home.
            # Refresh the health cache when entering the menu (no-op if fresh),
            # so a source that just went down gets badged on the next visit.
            try:
                from . import health
                from .scraping.config import portals as _hp
                health.refresh(_hp)
            except Exception:
                health = None

            while True:
                crumb_reset(f"{icon('home')} {t('Home')}", t("Sources"))
                p_items = [
                    p["name"] + (health.badge_for(p["name"]) if health else "")
                    for p in ordered
                ] + [t("← Back")]
                p_idx = select_from_list(
                    p_items,
                    t("Select a Provider:"),
                    header=f"{icon('globe')} {t('Sources')}",
                    group_headers=group_headers,
                )
                if p_idx >= len(ordered):
                    break  # ← Back → home menu
                # Deeper menus inside the handler inherit this trail.
                crumb_push(ordered[p_idx]["name"])
                ordered[p_idx]["handler"]()
            continue

        if choice_idx == settings_idx:
            # Settings menu
            while True:
                crumb_reset(f"{icon('home')} {t('Home')}", t("Settings"))
                clear_screen()
                print_header(f"{icon('settings')} {t('Settings')}")
                token = tracker.get_anilist_token()
                lang = tracker.get_language()
                player = tracker.get_player()


                lang_display = get_language_display(lang)
                player_display = t(get_player_display(player))
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
                # Sub-menu picker that always has a Back row, so Esc (which
                # select_from_list maps to the last option) reliably goes back
                # instead of silently picking the last item.
                def _pick(items, prompt):
                    i = select_from_list(list(items) + [t("← Back")], prompt)
                    return None if i >= len(items) else i

                # ── Actions (each setting's handler) ──
                def _a_token():
                    nt = get_user_input(t("Enter new AniList Token"))
                    if nt:
                        tracker.set_anilist_token(nt)
                        toast(t("Token saved."))

                def _a_lang():
                    ls = get_all_languages()
                    c = _pick([x[1] for x in ls], t("Select Language:"))
                    if c is not None:
                        tracker.set_language(ls[c][0])
                        toast(f"{t('Language updated to:')} {ls[c][1]}")

                def _a_anime_lang():
                    ls = get_all_languages()
                    c = _pick([x[1] for x in ls], t("Anime language:"))
                    if c is not None:
                        tracker.set_anime_language(ls[c][0])
                        toast(f"{t('Anime language updated to:')} {ls[c][1]}")

                def _a_theme():
                    _theme_settings()

                def _a_player():
                    ps = get_all_players()
                    c = _pick([t(p[1]) for p in ps], t("Select default player:"))
                    if c is not None:
                        tracker.set_player(ps[c][0])
                        toast(f"{t('Player updated to:')} {t(ps[c][1])}")

                def _a_quality():
                    q_opts = ["auto (best available)", "1080p max", "720p max", "480p max"]
                    q_vals = ["auto", "1080", "720", "480"]
                    c = _pick(q_opts, t("Select download quality:"))
                    if c is not None:
                        tracker.set_download_quality(q_vals[c])
                        toast(f"{t('Download quality set to:')} {q_opts[c]}")

                def _a_ossub():
                    print_info(t("Register at https://www.opensubtitles.com/en/consumers"))
                    print_info(t("to get a free API key, then paste it here."))
                    nk = get_user_input(t("Enter OpenSubtitles API key"))
                    if nk:
                        tracker.set_opensubtitles_key(nk.strip())
                        toast(t("OpenSubtitles key saved."))

                def _a_parallel():
                    n_opts = ["1 (sequential)", "2", "3", "4"]
                    c = _pick(n_opts, t("Max parallel downloads:"))
                    if c is not None:
                        tracker.set_parallel_downloads(c + 1)
                        toast(f"{t('Parallel downloads set to')} {c + 1}")

                def _a_notif(notif_on=notif_on):
                    if notif_on:
                        if select_from_list([t("Yes"), t("No")], t("Disable daily notifications?")) == 0:
                            ok = notif_mod.uninstall_systemd_timer()
                            toast(t("Notifications disabled.") if ok else t("Failed to disable notifications."),
                                  "success" if ok else "error")
                    else:
                        print_info(t("This installs a systemd --user timer that runs once a day"))
                        print_info(t("and uses notify-send to alert you about new episodes."))
                        if select_from_list([t("Yes"), t("No")], t("Enable daily notifications?")) == 0:
                            if notif_mod.install_systemd_timer():
                                toast(t("Notifications enabled (runs daily)."))
                            else:
                                print_error(t("Failed to enable. Make sure systemd --user works "
                                              "and 'libnotify' is installed (sudo dnf install libnotify)."))
                                pause()

                def _a_nvidia():
                    print_info(t("On laptops with Intel/AMD iGPU + Nvidia dGPU, route"))
                    print_info(t("mpv to the Nvidia card for far better Anime4K perf."))
                    nv_opts = ["auto (detect nvidia-smi)", "on (force Nvidia)", "off (always iGPU)"]
                    nv_vals = ["auto", "on", "off"]
                    c = _pick(nv_opts, t("Nvidia GPU offload:"))
                    if c is not None:
                        tracker.set_nvidia_offload(nv_vals[c])
                        toast(f"{t('Nvidia offload:')} {nv_vals[c]}")

                def _a_posters():
                    from . import terminal_image
                    p_opts = ["auto (chafa picks best format)",
                              "sixel (photo quality — needs terminal Sixel)", "off (no posters)"]
                    p_vals = ["auto", "sixel", "off"]
                    if not terminal_image.chafa_available():
                        print_warning(t("chafa is not installed — posters won't show until you "
                                        "install it (e.g. sudo dnf install chafa)."))
                    c = _pick(p_opts, t("Show Posters:"))
                    if c is not None:
                        tracker.set_poster_mode(p_vals[c])
                        terminal_image.reset_cache()
                        toast(f"{t('Show Posters')}: {p_vals[c]}")

                def _a_icons():
                    i_opts = ["emoji (works everywhere)", "nerd (crisp icons, needs a Nerd Font)"]
                    i_vals = ["emoji", "nerd"]
                    c = _pick(i_opts, t("Icon Style:"))
                    if c is None:
                        return
                    picked = i_vals[c]
                    if picked == "nerd" and not setup_assistant.detect_nerd_font():
                        print_info(t("CaskaydiaCove Nerd Font not found on this system."))
                        if input("Install it now? [Y/n] ").strip().lower() not in ("n", "no"):
                            setup_assistant.install_nerd_font()
                    tracker.set_icon_style(picked)
                    print_success(f"{t('Icon Style')}: {picked}")
                    print_info(t("Restart FreeFlix to apply icons everywhere."))
                    pause()

                def _a_analyze():
                    new = not tracker.get_analyze_players()
                    tracker.set_analyze_players(new)
                    toast(f"{t('Player analysis:')} {'ON' if new else 'OFF'}")

                def _a_subs():
                    new = not tracker.get_subtitle_search()
                    tracker.set_subtitle_search(new)
                    toast(f"{t('Subtitle download:')} {'ON' if new else 'OFF'}")

                # ── (category, label, action) — grouped in the menu ──
                PLY, DL, APP, ACC, AB = (t("Playback"), t("Downloads"),
                                         t("Appearance"), t("Accounts"), t("About"))
                entries = [
                    (PLY, f"{t('Choose default Player')} ({player_display})", _a_player),
                    (PLY, f"Nvidia GPU offload ({nv_mode})", _a_nvidia),
                    (PLY, f"{t('Analyze players (resolutions/bitrate)')} ({'ON' if tracker.get_analyze_players() else 'OFF'})", _a_analyze),
                    (DL, f"{t('Download Quality')} ({quality})", _a_quality),
                    (DL, f"{t('Parallel Downloads')} ({par_n})", _a_parallel),
                    (DL, f"{icon('subtitle')} {t('Download subtitles')} ({'ON' if tracker.get_subtitle_search() else 'OFF'})", _a_subs),
                    (APP, f"{icon('theme')} {t('Theme')} ({theme_label})", _a_theme),
                    (APP, f"{icon('poster')} {t('Show Posters')} ({tracker.get_poster_mode()})", _a_posters),
                    (APP, f"{icon('theme')} {t('Icon Style')} ({tracker.get_icon_style()})", _a_icons),
                    (APP, f"{t('Update Language')} ({lang_display})", _a_lang),
                    (APP, f"{t('Update Anime Language')} ({anime_lang_display})", _a_anime_lang),
                    (ACC, f"{t('Update AniList Token')} ({'Set' if token else 'Not Set'})", _a_token),
                    (ACC, f"{t('OpenSubtitles API Key')} ({'Set' if os_key else 'Not Set'})", _a_ossub),
                    (ACC, f"{t('Cloudflare token')}", _set_cloudflare_token),
                    (ACC, f"{t('Daily New-Episode Notifications')} ({'ON' if notif_on else 'OFF'})", _a_notif),
                    (AB, f"{icon('info')} {t('About')}", lambda: (_show_about(_VERSION), pause())),
                ]

                labels, actions, group_headers, last_cat = [], [], {}, None
                for cat, label, fn in entries:
                    if cat != last_cat:
                        group_headers[len(labels)] = cat
                        last_cat = cat
                    labels.append(label)
                    actions.append(fn)
                labels.append(t("Back"))

                s_choice = select_from_list(labels, t("Select Setting:"),
                                            group_headers=group_headers)
                if s_choice >= len(actions):
                    break
                actions[s_choice]()
            continue

        # Exit
        print_success(t("Goodbye!"))
        _stop_proxy_if_running()
        os._exit(0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nGoodbye!")
        _stop_proxy_if_running()
        os._exit(0)
