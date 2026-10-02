"""Tests for version-aware system_deps_ok cache invalidation.

When the user upgrades freeflix, the system_deps_ok flag survives but the
new version may have added dependencies.  We store the version alongside
the flag and invalidate on version mismatch so ``ensure_runtime_deps()``
re-checks what's actually installed.
"""

from unittest import mock

import pytest

from freeflix_cli.setup_assistant import (
    _get_installed_version,
    ensure_runtime_deps,
)
from freeflix_cli.tracker import tracker


class TestGetInstalledVersion:
    """_get_installed_version() should always return a valid string."""

    def test_returns_string(self):
        v = _get_installed_version()
        assert isinstance(v, str)

    def test_no_exceptions(self):
        try:
            _get_installed_version()
        except Exception as e:
            pytest.fail(f"_get_installed_version raised {type(e).__name__}: {e}")


class TestCacheInvalidation:
    """Version-aware cache logic inside ensure_runtime_deps()."""

    def setup_method(self):
        tracker.data.pop("system_deps_ok", None)
        tracker.data.pop("system_deps_ok_version", None)

    # ── Cache hit (short-circuit) ─────────────────────────────────

    def test_cache_hit_same_version(self):
        tracker.data["system_deps_ok"] = True
        tracker.data["system_deps_ok_version"] = "1.7.0"

        with mock.patch(
            "freeflix_cli.setup_assistant._get_installed_version",
            return_value="1.7.0",
        ):
            with mock.patch(
                "freeflix_cli.setup_assistant.runtime_ready",
            ) as mock_ready:
                result = ensure_runtime_deps()

        assert result is True
        mock_ready.assert_not_called()
        assert tracker.data.get("system_deps_ok_version") == "1.7.0"

    def test_cache_hit_no_version_stored(self):
        """Legacy cache (no version key) still short-circuits."""
        tracker.data["system_deps_ok"] = True

        with mock.patch(
            "freeflix_cli.setup_assistant._get_installed_version",
            return_value="1.7.0",
        ):
            with mock.patch(
                "freeflix_cli.setup_assistant.runtime_ready",
            ) as mock_ready:
                result = ensure_runtime_deps()

        assert result is True
        mock_ready.assert_not_called()

    def test_cache_alone_short_circuits(self):
        """Even without version key, system_deps_ok alone short-circuits."""
        tracker.data["system_deps_ok"] = True

        with mock.patch(
            "freeflix_cli.setup_assistant._get_installed_version",
        ):
            with mock.patch(
                "freeflix_cli.setup_assistant.runtime_ready",
            ) as mock_ready:
                result = ensure_runtime_deps()

        assert result is True
        mock_ready.assert_not_called()

    # ── Cache invalidation ───────────────────────────────────────

    def test_cache_invalidated_on_upgrade(self):
        tracker.data["system_deps_ok"] = True
        tracker.data["system_deps_ok_version"] = "1.7.0"

        with mock.patch(
            "freeflix_cli.setup_assistant._get_installed_version",
            return_value="1.8.0",
        ):
            with mock.patch(
                "freeflix_cli.setup_assistant.runtime_ready",
                return_value=True,
            ):
                result = ensure_runtime_deps()

        assert result is True
        assert tracker.data.get("system_deps_ok_version") == "1.8.0"

    def test_cache_invalidated_on_downgrade(self):
        tracker.data["system_deps_ok"] = True
        tracker.data["system_deps_ok_version"] = "1.8.0"

        with mock.patch(
            "freeflix_cli.setup_assistant._get_installed_version",
            return_value="1.7.0",
        ):
            with mock.patch(
                "freeflix_cli.setup_assistant.runtime_ready",
                return_value=True,
            ):
                result = ensure_runtime_deps()

        assert result is True
        assert tracker.data.get("system_deps_ok_version") == "1.7.0"

    def test_cache_clears_both_keys_on_mismatch(self):
        """Old keys are removed before re-check (visible when still missing)."""
        tracker.data["system_deps_ok"] = True
        tracker.data["system_deps_ok_version"] = "1.7.0"

        with mock.patch(
            "freeflix_cli.setup_assistant._get_installed_version",
            return_value="1.8.0",
        ):
            with mock.patch(
                "freeflix_cli.setup_assistant.runtime_ready",
                return_value=False,  # still missing tools -> don't re-set
            ):
                with mock.patch(
                    "freeflix_cli.setup_assistant.detect_os",
                    return_value="linux",
                ):
                    result = ensure_runtime_deps()

        assert result is False
        # Both keys were cleared and NOT re-set (still missing tools)
        assert tracker.data.get("system_deps_ok") is None
        assert tracker.data.get("system_deps_ok_version") is None

    # ─── Cache set (first success) ─────────────────────────────────

    def test_cache_sets_version_on_first_success(self):
        with mock.patch(
            "freeflix_cli.setup_assistant._get_installed_version",
            return_value="1.7.0",
        ):
            with mock.patch(
                "freeflix_cli.setup_assistant.runtime_ready",
                return_value=True,
            ):
                result = ensure_runtime_deps()

        assert result is True
        assert tracker.data.get("system_deps_ok") is True
        assert tracker.data.get("system_deps_ok_version") == "1.7.0"

    def test_cache_sets_version_after_winget_install(self):
        """Second cache set point (after winget) also stores version."""
        with mock.patch(
            "freeflix_cli.setup_assistant._get_installed_version",
            return_value="1.7.0",
        ):
            with mock.patch(
                "freeflix_cli.setup_assistant.runtime_ready",
                side_effect=[False, True],
            ):
                with mock.patch(
                    "freeflix_cli.setup_assistant.detect_os",
                    return_value="windows",
                ):
                    with mock.patch(
                        "freeflix_cli.setup_assistant.shutil.which",
                        return_value=None,
                    ):
                        with mock.patch(
                            "freeflix_cli.setup_assistant._auto_install_managed",
                        ):
                            result = ensure_runtime_deps()

        assert result is True
        assert tracker.data.get("system_deps_ok") is True
        assert tracker.data.get("system_deps_ok_version") == "1.7.0"

    # ─── Persistence across calls ─────────────────────────────────

    def test_subsequent_call_short_circuits(self):
        with mock.patch(
            "freeflix_cli.setup_assistant._get_installed_version",
            return_value="1.7.0",
        ):
            with mock.patch(
                "freeflix_cli.setup_assistant.runtime_ready",
                return_value=True,
            ) as mock_ready:
                ensure_runtime_deps()
                assert mock_ready.call_count == 1

                mock_ready.reset_mock()
                result = ensure_runtime_deps()

        assert result is True
        mock_ready.assert_not_called()

    def test_subsequent_call_after_upgrade_rechecks(self):
        with mock.patch(
            "freeflix_cli.setup_assistant.runtime_ready",
            return_value=True,
        ) as mock_ready:
            # First call: version 1.7.0
            with mock.patch(
                "freeflix_cli.setup_assistant._get_installed_version",
                return_value="1.7.0",
            ):
                ensure_runtime_deps()
                assert mock_ready.call_count == 1

            mock_ready.reset_mock()

            # Second call (simulating upgrade): version 1.8.0
            with mock.patch(
                "freeflix_cli.setup_assistant._get_installed_version",
                return_value="1.8.0",
            ):
                result = ensure_runtime_deps()
                assert mock_ready.call_count == 1  # re-checked
                assert tracker.data.get("system_deps_ok_version") == "1.8.0"

        assert result is True

    # ─── No-cache edge cases ──────────────────────────────────────

    def test_no_cache_at_all(self):
        with mock.patch(
            "freeflix_cli.setup_assistant._get_installed_version",
            return_value="1.7.0",
        ):
            with mock.patch(
                "freeflix_cli.setup_assistant.runtime_ready",
                return_value=True,
            ):
                result = ensure_runtime_deps()

        assert result is True
        assert tracker.data.get("system_deps_ok") is True
        assert tracker.data.get("system_deps_ok_version") == "1.7.0"

    def test_dev_version_tracked(self):
        """Dev version (not from pip) is tracked like any other."""
        with mock.patch(
            "freeflix_cli.setup_assistant._get_installed_version",
            return_value="dev",
        ):
            with mock.patch(
                "freeflix_cli.setup_assistant.runtime_ready",
                return_value=True,
            ):
                result = ensure_runtime_deps()

        assert result is True
        assert tracker.data.get("system_deps_ok_version") == "dev"

    def test_dev_to_release_invalidates(self):
        tracker.data["system_deps_ok"] = True
        tracker.data["system_deps_ok_version"] = "dev"

        with mock.patch(
            "freeflix_cli.setup_assistant._get_installed_version",
            return_value="1.8.0",
        ):
            with mock.patch(
                "freeflix_cli.setup_assistant.runtime_ready",
                return_value=True,
            ) as mock_ready:
                result = ensure_runtime_deps()

        assert result is True
        mock_ready.assert_called_once()
        assert tracker.data.get("system_deps_ok_version") == "1.8.0"


class TestInstallHealth:
    """Split-install detection (metadata says new, code runs old)."""

    def test_mismatch_detected(self):
        from freeflix_cli import install_health as ih
        with mock.patch.object(ih, "metadata_version", return_value="9.9.9"):
            st = ih.install_state()
            assert st["mismatch"] is True
            assert st["code_version"] == ih.CODE_VERSION

    def test_no_mismatch_when_equal(self):
        from freeflix_cli import install_health as ih
        with mock.patch.object(ih, "metadata_version", return_value=ih.CODE_VERSION):
            assert ih.install_state()["mismatch"] is False

    def test_no_metadata_no_mismatch(self):
        from freeflix_cli import install_health as ih
        with mock.patch.object(ih, "metadata_version", return_value=None):
            assert ih.install_state()["mismatch"] is False

    def test_find_shims_returns_list(self):
        from freeflix_cli import install_health as ih
        shims = ih.find_shims()
        assert isinstance(shims, list)

    def test_cleanup_hint_per_os(self):
        from freeflix_cli import install_health as ih
        hint = ih.cleanup_hint()
        assert isinstance(hint, str) and "freeflix-cli" in hint




class TestWindowsNotifications:
    """Backend Windows (toast + tâche planifiée) sans dépendance."""

    def test_xml_escape(self):
        from freeflix_cli import notifications as n
        assert n._xml_escape("a&b<c>d") == "a&amp;b&lt;c&gt;d"

    def test_notify_silent_without_notify_send(self):
        import os as _os
        from unittest import mock as _mock
        from freeflix_cli import notifications as n
        if _os.name == "nt":
            return  # couvert par le test toast ci-dessous
        with _mock.patch.object(n.shutil, "which", return_value=None):
            with _mock.patch.object(n.subprocess, "run") as run:
                n._notify("t", "b")
                run.assert_not_called()

    def test_windows_toast_escapes_xml(self):
        import os as _os
        from unittest import mock as _mock
        from freeflix_cli import notifications as n
        seen = {}

        class _R:
            returncode = 0

        def fake_run(cmd, **kw):
            seen["cmd"] = cmd
            return _R()

        with _mock.patch.object(_os, "name", "nt"):
            with _mock.patch.object(n.shutil, "which", return_value="powershell"):
                with _mock.patch.object(n.subprocess, "run", side_effect=fake_run):
                    assert n._notify_windows_toast("A&B", "<C>") is True
        ps = " ".join(seen["cmd"])
        assert "A&amp;B" in ps and "&lt;C&gt;" in ps
        assert "-WindowStyle" in seen["cmd"]

    def test_dispatch_uses_windows_backend(self):
        import os as _os
        from unittest import mock as _mock
        from freeflix_cli import notifications as n
        with _mock.patch.object(_os, "name", "nt"):
            with _mock.patch.object(n, "is_windows_task_installed", return_value=True):
                assert n.is_daily_notify_installed() is True
            with _mock.patch.object(n, "install_windows_task", return_value=True) as inst:
                assert n.install_daily_notify() is True
                inst.assert_called_once_with()
            with _mock.patch.object(n, "uninstall_windows_task", return_value=True) as un:
                assert n.uninstall_daily_notify() is True
                un.assert_called_once_with()

    def test_schtasks_failure_is_false(self):
        import os as _os
        from unittest import mock as _mock
        from freeflix_cli import notifications as n
        with _mock.patch.object(_os, "name", "nt"):
            with _mock.patch.object(n.subprocess, "run",
                                    side_effect=OSError("no schtasks")):
                assert n.is_windows_task_installed() is False
                assert n.install_windows_task() is False
