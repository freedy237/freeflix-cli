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
