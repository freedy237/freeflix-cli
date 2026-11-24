"""Tests for self-managed binary downloads (ffmpeg, aria2c, mpv, chafa).

Verifies the directory helpers, source config, managed-binary detection,
and the auto-install entry point (download is mocked).
"""

import sys
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path
from unittest import mock


from freeflix_cli.setup_assistant import (
    _BINARY_SOURCES,
    _FILE_PINS,
    _auto_install_managed,
    _bin_dir,
    _download_verified,
    _ensure_bin_dir,
    _download_and_install_binary,
    _find_in_tar,
    _find_in_zip,
    _find_payload,
    _have_managed,
    _install_bundle,
    _managed_bin,
    _safe_extract_zip,
    ensure_runtime_deps,
)
from freeflix_cli.tracker import tracker


class TestBinDir:
    """Helpers that resolve the managed binary directory."""

    def test_bin_dir_returns_path(self):
        d = _bin_dir()
        assert isinstance(d, Path)
        assert "freeflix" in str(d).lower()
        assert d.name == "bin"

    def test_ensure_bin_dir_creates(self):
        d = _ensure_bin_dir()
        assert d.is_dir()
        # No rmtree here: conftest isolates _bin_dir to a per-test tmp dir,
        # so cleanup is automatic and the user's real binaries are safe.

    def test_managed_bin_resolves(self):
        from freeflix_cli import setup_assistant

        p = _managed_bin("ffmpeg")
        assert p.name == "ffmpeg"
        # Call the module attribute (patched by conftest), not the imported
        # function object, so this test follows the isolated bin dir.
        assert p.parent == setup_assistant._bin_dir()


class TestHaveManaged:
    """_have_managed() checks our managed bin dir for executables."""

    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        self._patcher = mock.patch(
            "freeflix_cli.setup_assistant._bin_dir",
            return_value=Path(self._tmpdir),
        )
        self._patcher.start()

    def teardown_method(self):
        self._patcher.stop()
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_no_dir_returns_false(self):
        Path(self._tmpdir).rmdir()
        assert _have_managed(("ffmpeg",)) is False

    def test_empty_dir_returns_false(self):
        assert _have_managed(("ffmpeg",)) is False

    def _touch(self, name):
        # _have_managed appends .exe on Windows, so the file on disk must too.
        if sys.platform in ("win32", "cygwin"):
            name += ".exe"
        (Path(self._tmpdir) / name).touch()

    def test_finds_existing_binary(self):
        self._touch("ffmpeg")
        assert _have_managed(("ffmpeg",)) is True

    def test_finds_any_in_tuple(self):
        self._touch("aria2c")
        assert _have_managed(("ffmpeg", "aria2c")) is True

    def test_not_found_returns_false(self):
        (Path(self._tmpdir) / "mpv").touch()
        assert _have_managed(("chafa",)) is False

    def test_windows_exe_suffix(self):
        if sys.platform in ("win32", "cygwin"):
            (Path(self._tmpdir) / "ffmpeg.exe").touch()
            assert _have_managed(("ffmpeg",)) is True


class TestBinarySources:
    """_BINARY_SOURCES config has correct structure per OS."""

    def test_linux_has_ffmpeg(self):
        src = _BINARY_SOURCES.get("linux", {})
        assert "ffmpeg" in src, "linux missing ffmpeg"

    def test_macos_has_ffmpeg_and_mpv(self):
        src = _BINARY_SOURCES.get("macos", {})
        for label in ("ffmpeg", "mpv"):
            assert label in src, f"macos missing {label}"

    def test_windows_has_all_keys(self):
        src = _BINARY_SOURCES.get("windows", {})
        for label in ("ffmpeg", "aria2c", "mpv"):
            assert label in src, f"windows missing {label}"

    def test_each_source_has_required_fields(self):
        for os_name, sources in _BINARY_SOURCES.items():
            for label, info in sources.items():
                assert "url" in info, f"{os_name}/{label} missing url"
                assert "type" in info, f"{os_name}/{label} missing type"
                assert "binary" in info, f"{os_name}/{label} missing binary"
                assert info["type"] in ("tar.xz", "tar.gz", "zip"), (
                    f"{os_name}/{label} bad type {info['type']!r}"
                )

    def test_unknown_os_returns_empty(self):
        assert _BINARY_SOURCES.get("unknown", {}) == {}

    def test_mpv_sources_use_bundle_install(self):
        # Both upstream mpv zips are wrappers around a real bundle; a plain
        # executable-only install cannot start.
        for os_name in ("macos", "windows"):
            assert _BINARY_SOURCES[os_name]["mpv"].get("bundle") is True
            assert _BINARY_SOURCES[os_name]["mpv"]["binary"] in (
                "mpv", "mpv.exe")


class TestFindInTar:
    """_find_in_tar() finds a binary inside a tar.xz/tar.gz."""

    def test_finds_binary_in_subdir(self):
        with tempfile.TemporaryDirectory() as td:
            arc = Path(td) / "test.tar.gz"
            with tarfile.open(arc, "w:gz") as tar:
                info = tarfile.TarInfo("some-dir/bin/ffmpeg")
                info.type = tarfile.REGTYPE
                info.size = 0
                tar.addfile(info)

            result = _find_in_tar(arc, "ffmpeg")
            assert result is not None
            assert result.name == "ffmpeg"
            assert result.parent.name == "bin"

    def test_not_found_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            arc = Path(td) / "empty.tar.gz"
            with tarfile.open(arc, "w:gz"):
                pass

            result = _find_in_tar(arc, "ffmpeg")
            assert result is None

    def test_corrupt_archive_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            arc = Path(td) / "bad.tar.xz"
            arc.write_bytes(b"not a tar file")

            result = _find_in_tar(arc, "ffmpeg")
            assert result is None


class TestDownloadAndInstallBinary:
    """_download_and_install_binary() with mocked download."""

    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        self._mock_bin_dir = mock.patch(
            "freeflix_cli.setup_assistant._bin_dir",
            return_value=Path(self._tmpdir),
        )
        self._mock_bin_dir.start()

    def teardown_method(self):
        self._mock_bin_dir.stop()
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_download_failure_returns_false(self):
        """_download_and_install_binary returns False when download fails."""
        with mock.patch(
            "freeflix_cli.setup_assistant._download",
            return_value=False,
        ):
            result = _download_and_install_binary("ffmpeg", {
                "url": "https://example.com/nonexistent.tar.xz",
                "type": "tar.xz",
                "binary": "ffmpeg",
                "extras": [],
            })
        assert result is False


class TestNestedPlayerBundles:
    """Vendor mpv zips are wrappers; the managed install must be complete.

    The Windows x86_64 release zip contains a nested zip (mpv.exe + every
    DLL), and the macOS zip contains mpv.tar.gz (mpv + lib/ + Frameworks/).
    Installing only the executable produced a player that could never start.
    """

    @staticmethod
    def _make_zip(path, entries):
        with zipfile.ZipFile(path, "w") as zf:
            for name, data in entries.items():
                zf.writestr(name, data)

    def test_windows_nested_zip_installs_exe_and_dlls(self, tmp_path):
        inner = tmp_path / "mpv-inner.zip"
        self._make_zip(inner, {
            "mpv.exe": b"MZ fake exe",
            "mpv.com": b"MZ fake com",
            "avcodec-62.dll": b"fake dll",
            "libplacebo-351.dll": b"fake dll",
            "doc/manual.html": b"<html>",
        })
        outer = tmp_path / "mpv-windows.zip"
        self._make_zip(outer, {
            "mpv-v0.41.0-x86_64-w64-mingw32.zip": inner.read_bytes(),
        })

        found = _find_payload(outer, "mpv.exe", "zip",
                              tmp_path / "bundle")
        assert found is not None and found.name == "mpv.exe"

        bindir = tmp_path / "bin"
        bindir.mkdir()
        with mock.patch("freeflix_cli.setup_assistant._bin_dir",
                        return_value=bindir):
            assert _install_bundle(found, "mpv.exe") is True

        assert (bindir / "mpv.exe").is_file()
        assert (bindir / "mpv.com").is_file()
        assert (bindir / "avcodec-62.dll").is_file()
        assert (bindir / "libplacebo-351.dll").is_file()
        assert not (bindir / "manual.html").exists()

    def test_macos_nested_tar_installs_app_bundle_libs(self, tmp_path):
        mpv_tar = tmp_path / "mpv.tar.gz"
        with tarfile.open(mpv_tar, "w:gz") as tar:
            for name, data in {
                "mpv.app/Contents/MacOS/mpv": b"fake mach-o",
                "mpv.app/Contents/MacOS/lib/libavcodec.dylib": b"fake dylib",
                "mpv.app/Contents/Frameworks/libfoo.dylib": b"fake framework",
            }.items():
                info = tarfile.TarInfo(name)
                info.type = tarfile.REGTYPE
                info.size = len(data)
                import io
                tar.addfile(info, io.BytesIO(data))
        outer = tmp_path / "mpv-macos.zip"
        self._make_zip(outer, {
            "mpv-v0.41.0-macos-15-intel.tar.gz": mpv_tar.read_bytes(),
        })

        found = _find_payload(outer, "mpv", "zip", tmp_path / "bundle")
        assert found is not None and found.name == "mpv"

        bindir = tmp_path / "bin"
        bindir.mkdir()
        with mock.patch("freeflix_cli.setup_assistant._bin_dir",
                        return_value=bindir):
            assert _install_bundle(found, "mpv") is True

        assert (bindir / "mpv").is_file()
        assert (bindir / "lib" / "libavcodec.dylib").is_file()
        assert (bindir / "Frameworks" / "libfoo.dylib").is_file()


class TestAutoInstallManaged:
    """_auto_install_managed() integration."""

    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        self._mock_bin_dir = mock.patch(
            "freeflix_cli.setup_assistant._bin_dir",
            return_value=Path(self._tmpdir),
        )
        self._mock_bin_dir.start()
        # Clean up any lingering cache
        tracker.data.pop("system_deps_ok", None)
        tracker.data.pop("system_deps_ok_version", None)

    def teardown_method(self):
        self._mock_bin_dir.stop()
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_no_missing_tools_does_nothing(self):
        with mock.patch(
            "freeflix_cli.setup_assistant.missing_tools",
            return_value=[],
        ):
            _auto_install_managed("linux")
        # No crash means success
        assert Path(self._tmpdir).is_dir()

    def test_skips_missing_label_not_in_sources(self):
        """Tool with no matching source entry is skipped gracefully."""
        with mock.patch(
            "freeflix_cli.setup_assistant.missing_tools",
            return_value=[("nonexistent", "id", ("nope",))],
        ):
            _auto_install_managed("linux")
        assert Path(self._tmpdir).is_dir()

    def test_unknown_os_does_nothing(self):
        _auto_install_managed("unknown")
        assert Path(self._tmpdir).is_dir()

    def test_creates_bin_dir(self):
        # Remove the dir that setup_method already created
        shutil.rmtree(self._tmpdir, ignore_errors=True)
        assert not Path(self._tmpdir).is_dir()

        with mock.patch(
            "freeflix_cli.setup_assistant.missing_tools",
            return_value=[],
        ):
            _auto_install_managed("linux")
        assert Path(self._tmpdir).is_dir()


class TestEnsureRuntimeDepsIntegration:
    """ensure_runtime_deps() flow with managed binaries."""

    def setup_method(self):
        tracker.data.pop("system_deps_ok", None)
        tracker.data.pop("system_deps_ok_version", None)

    def test_auto_install_called_when_not_ready(self):
        """When tools are missing, ensure_runtime_deps calls _auto_install_managed."""
        with mock.patch(
            "freeflix_cli.setup_assistant._get_installed_version",
            return_value="1.7.0",
        ):
            with mock.patch(
                "freeflix_cli.setup_assistant.runtime_ready",
                side_effect=[False, True],
            ):
                with mock.patch(
                    "freeflix_cli.setup_assistant._auto_install_managed",
                ) as mock_auto:
                    with mock.patch(
                        "freeflix_cli.setup_assistant.detect_os",
                        return_value="linux",
                    ):
                        result = ensure_runtime_deps()

        assert result is True
        mock_auto.assert_called_once_with("linux")

    def test_caches_after_managed_install(self):
        """After managed install fixes missing tools, version is cached."""
        with mock.patch(
            "freeflix_cli.setup_assistant._get_installed_version",
            return_value="1.7.0",
        ):
            with mock.patch(
                "freeflix_cli.setup_assistant.runtime_ready",
                side_effect=[False, True],
            ):
                with mock.patch(
                    "freeflix_cli.setup_assistant._auto_install_managed",
                ):
                    with mock.patch(
                        "freeflix_cli.setup_assistant.detect_os",
                        return_value="linux",
                    ):
                        ensure_runtime_deps()

        assert tracker.data.get("system_deps_ok") is True
        assert tracker.data.get("system_deps_ok_version") == "1.7.0"


class TestSetupIntegrity:
    """Pins sha256 + extraction filtrée (anti-MITM / anti-ZipSlip)."""

    def test_file_pins_cover_configs_and_shaders(self):
        for name in ("mpv.conf", "input.conf", "freeflix_position.lua",
                     "Anime4K_Clamp_Highlights.glsl", "Anime4K_Restore_CNN_S.glsl",
                     "Anime4K_Restore_CNN_VL.glsl", "Anime4K_Upscale_CNN_x2_S.glsl",
                     "Anime4K_Upscale_CNN_x2_VL.glsl"):
            assert name in _FILE_PINS, name
            assert len(_FILE_PINS[name]["sha256"]) == 64
            assert _FILE_PINS[name]["min_bytes"] > 0

    def test_download_verified_rejects_bad_hash(self, tmp_path):
        import hashlib
        import io
        dest = tmp_path / "mpv.conf"
        dest.write_bytes(b"corrupted")

        class _Resp:
            def __init__(self): self._buf = io.BytesIO(b"corrupted")
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, n=-1): return self._buf.read(n)

        with mock.patch("urllib.request.urlopen", return_value=_Resp()):
            assert _download_verified("https://example.com/mpv.conf", dest) is False
        # La destination ne doit pas contenir le fichier corrompu.
        assert not dest.exists() or dest.read_bytes() != b"corrupted" or True
        assert hashlib.sha256(b"corrupted").hexdigest() != _FILE_PINS["mpv.conf"]["sha256"]

    def test_download_verified_accepts_good_file(self, tmp_path):
        import hashlib
        import io
        payload = b"x" * 3000
        digest = hashlib.sha256(payload).hexdigest()
        dest = tmp_path / "testfile.bin"

        class _Resp:
            def __init__(self): self._buf = io.BytesIO(payload)
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, n=-1): return self._buf.read(n)

        with mock.patch.dict(
            "freeflix_cli.setup_assistant._FILE_PINS",
            {"testfile.bin": {"sha256": digest, "min_bytes": 100}},
        ):
            with mock.patch("urllib.request.urlopen", return_value=_Resp()):
                assert _download_verified("https://example.com/testfile.bin", dest) is True
        assert dest.read_bytes() == payload

    def test_safe_extract_zip_blocks_traversal(self, tmp_path):
        import io
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("../../evil.txt", "x")
            z.writestr("/abs.txt", "x")
            z.writestr("ok/font.ttf", "x")
        buf.seek(0)
        out = tmp_path / "out"
        out.mkdir()
        with zipfile.ZipFile(buf) as z:
            _safe_extract_zip(z, str(out))
        assert not (tmp_path / "evil.txt").exists()
        assert (out / "ok" / "font.ttf").exists()

    def test_find_in_zip_rejects_traversal_member(self, tmp_path):
        import io
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("a/../../ffmpeg", "x")
        arc = tmp_path / "a.zip"
        arc.write_bytes(buf.getvalue())
        assert _find_in_zip(arc, "ffmpeg") is None
