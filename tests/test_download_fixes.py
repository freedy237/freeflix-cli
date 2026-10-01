"""Tests for the 1.6.5 download fixes (duplicate filename + resume)."""

import os
import shutil


from freeflix_cli.player_manager import (
    clean_season_title,
    clean_episode_title,
    _sanitize_filename,
    _stable_temp_dir,
    DOWNLOAD_DIR,
    TEMP_DIR,
)


class TestCleanSeasonTitle:
    """Bug 2 — duplicated series name in download filenames."""

    def test_coflix_duplicate(self):
        """Coflix season_title = 'FROM - Saison 4', series = 'FROM'"""
        assert clean_season_title("FROM", "FROM - Saison 4") == "Saison 4"

    def test_no_duplicate(self):
        """Season title that doesn't contain series name is kept as-is."""
        assert clean_season_title("FROM", "Saison 4") == "Saison 4"

    def test_same_name(self):
        """When series == season (e.g. a movie), return the original."""
        assert clean_season_title("Movie", "Movie") == "Movie"

    def test_multi_word_series(self):
        """Multi-word series like 'Breaking Bad'."""
        assert (
            clean_season_title("Breaking Bad", "Breaking Bad - Season 1")
            == "Season 1"
        )

    def test_partial_prefix_only(self):
        """Only strip prefix, not substring matches mid-string."""
        result = clean_season_title("The Office", "The Office - Season 5 - Extended")
        assert result == "Season 5 - Extended"
        assert "The Office" not in result

    def test_sanitize_roundtrip(self):
        """Sanitize after dedup: no leftover duplicates in final filename."""
        clean_s = clean_season_title("FROM", "FROM - Saison 4")
        title = f"FROM - {clean_s} - Episode 1"
        safe = _sanitize_filename(title)
        assert "FROM - FROM" not in safe
        assert safe == "FROM - Saison 4 - Episode 1"

    def test_french_stream_kept_as_is(self):
        """French-Stream passes simplest season titles no dedup needed."""
        assert (
            clean_season_title("Some Series", "Saison 1")
            == "Saison 1"
        )


class TestCleanEpisodeTitle:
    """Episode titles that embed series + season (e.g. Coflix)."""

    def test_coflix_full_path(self):
        """Coflix episode title = 'FROM - Saison 4 - Episode 7', series='FROM', season='FROM - Saison 4'"""
        assert clean_episode_title("FROM", "FROM - Saison 4", "FROM - Saison 4 - Episode 7") == "Episode 7"

    def test_no_duplicate(self):
        """Episode title that doesn't contain series/season is kept."""
        assert clean_episode_title("FROM", "Saison 4", "Episode 7") == "Episode 7"

    def test_only_series_prefix(self):
        """Episode title only has series prefix, not season."""
        assert clean_episode_title("FROM", "Saison 4", "FROM - Episode 7") == "Episode 7"

    def test_only_season_prefix(self):
        """Episode title only has season prefix, not series."""
        assert clean_episode_title("FROM", "FROM - Saison 4", "Saison 4 - Episode 7") == "Episode 7"

    def test_multi_word_series(self):
        """Multi-word series like 'Breaking Bad'."""
        assert clean_episode_title("Breaking Bad", "Breaking Bad - Season 1", "Breaking Bad - Season 1 - Episode 1") == "Episode 1"


class TestStableTempDir:
    """Bug 3 — deterministic temp dir for download resume."""

    def test_temp_dir_constant(self):
        """TEMP_DIR is the hidden .temp folder under DOWNLOAD_DIR."""
        assert TEMP_DIR == os.path.join(DOWNLOAD_DIR, ".temp")

    def test_stable_temp_dir_is_deterministic(self):
        """Same safe_title → same path every call."""
        d1 = _stable_temp_dir("my_show_-_Ep1")
        d2 = _stable_temp_dir("my_show_-_Ep1")
        assert d1 == d2
        assert os.path.isdir(d1)
        # Cleanup ONLY the dir this test created — never its parents (the
        # grandparent is the user's real ~/Downloads/FreeFlix folder!).
        shutil.rmtree(d1, ignore_errors=True)

    def test_different_titles_different_dirs(self):
        """Different downloads land in separate temp dirs."""
        d1 = _stable_temp_dir("show_a_-_Ep1")
        d2 = _stable_temp_dir("show_b_-_Ep2")
        assert d1 != d2
        # Only the test's own dirs — NOT the parent FreeFlix download folder.
        shutil.rmtree(d1, ignore_errors=True)
        shutil.rmtree(d2, ignore_errors=True)

    def test_temp_dir_is_hidden(self):
        """.temp/ is a dot-prefixed hidden directory."""
        assert TEMP_DIR.endswith(".temp")
        assert os.path.basename(TEMP_DIR).startswith(".")

    def test_sanitize_filename_edge_cases(self):
        assert _sanitize_filename("") == "video"
        assert _sanitize_filename("   ") == "video"
        assert "?" not in _sanitize_filename("bad?name")
        assert "/" not in _sanitize_filename("a/b")


class TestDownloadQualityHeights:
    """Le choix batch 2160/480/360… est honoré, plus seulement 1080/720/480."""

    def test_roundtrip_any_height(self):
        from freeflix_cli.tracker import tracker
        old = tracker.get_download_quality()
        try:
            for q in ("2160", "1440", "480", "360", "1080", "720"):
                tracker.set_download_quality(q)
                assert tracker.get_download_quality() == q
            tracker.set_download_quality("1080p")
            assert tracker.get_download_quality() == "1080"
            tracker.set_download_quality("nimporte-quoi")
            assert tracker.get_download_quality() == "auto"
        finally:
            tracker.set_download_quality(old)


class TestStableTempSubfolder:
    """Deux saisons aux mêmes noms d'épisodes ne mélangent plus .temp."""

    def test_subfolder_namespaces(self):
        d1 = _stable_temp_dir("Episode_1", "Serie A - S1")
        d2 = _stable_temp_dir("Episode_1", "Serie B - S1")
        d3 = _stable_temp_dir("Episode_1", "Serie A - S1")
        assert d1 != d2
        assert d1 == d3  # déterministe → resume intact
        shutil.rmtree(d1, ignore_errors=True)
        shutil.rmtree(d2, ignore_errors=True)

    def test_no_subfolder_unchanged(self):
        d1 = _stable_temp_dir("Episode_1")
        d2 = _stable_temp_dir("Episode_1")
        assert d1 == d2
        shutil.rmtree(d1, ignore_errors=True)


class TestIsAlreadyDownloaded:
    """Extensions +.avi/.mov/.m4v et comparaison insensible à la casse."""

    def test_case_and_extra_exts(self, tmp_path, monkeypatch):
        import freeflix_cli.player_manager as pm
        monkeypatch.setattr(pm, "DOWNLOAD_DIR", str(tmp_path))
        pm._invalidate_download_index()
        (tmp_path / "Show - Ep1.MP4").write_bytes(b"x")
        (tmp_path / "Show - Ep2.avi").write_bytes(b"x")
        (tmp_path / "other.txt").write_bytes(b"x")
        try:
            assert pm.is_already_downloaded("show - ep1") is True
            assert pm.is_already_downloaded("Show - Ep2") is True
            assert pm.is_already_downloaded("Show - Ep3") is False
        finally:
            pm._invalidate_download_index()
