"""Focused contract tests for the Ubuntu app_webview lifecycle wiring."""
from __future__ import annotations

from unittest.mock import MagicMock


def test_linux_main_passes_endpoint_and_registry_to_shutdown_coordinator(monkeypatch):
    import app_webview
    import platform_seams
    import shutdown

    endpoint = object()
    registry = object()
    children = MagicMock()
    captured = {}

    class _Coordinator:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def install_signal_handlers(self):
            captured["signals_installed"] = True

    class _Thread:
        def join(self):
            captured["joined"] = True

    class _Server:
        _thread = _Thread()
        _accepting_work = True
        hub = MagicMock()
        backend = MagicMock()
        backend.endpoint_server = endpoint
        backend.job_registry = registry
        backend.settings_store = MagicMock()

    monkeypatch.setattr(platform_seams, "guard_children", lambda: children)
    monkeypatch.setattr(shutdown, "ShutdownCoordinator", _Coordinator)

    server = _Server()
    app_webview.linux_main(server, access_key="session-key")

    assert captured["endpoint_server"] is endpoint
    assert captured["job_registry"] is registry
    assert server.backend.attach_shutdown_coordinator.call_count == 1
    assert captured["signals_installed"] is True
    assert captured["joined"] is True
