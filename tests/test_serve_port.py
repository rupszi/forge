"""`forge serve` should handle a busy port gracefully (no raw traceback)."""

from __future__ import annotations

import socket

from daemon import cli


class TestPortHelpers:
    def test_free_port_not_in_use(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        # Nothing is listening on that just-released port.
        assert cli._port_in_use("127.0.0.1", port) is False

    def test_listening_port_in_use(self):
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        try:
            assert cli._port_in_use("127.0.0.1", port) is True
        finally:
            srv.close()

    def test_pid_on_free_port_is_none(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        assert cli._pid_on_port(port) is None


class TestServeBusyPort:
    def test_serve_exits_cleanly_when_port_busy(self, monkeypatch, capsys):
        from types import SimpleNamespace

        # Pretend the port is occupied and not forced.
        monkeypatch.setattr(cli, "_port_in_use", lambda host, port: True)
        monkeypatch.setattr(cli, "_pid_on_port", lambda port: 4242)
        # Guard: if it tried to actually serve, fail loudly.
        monkeypatch.setattr(
            cli,
            "_run_async",
            lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("should not serve")),
        )

        rc = cli.cmd_serve(SimpleNamespace(no_ui=True, force=False))
        out = capsys.readouterr().out
        assert rc == 1
        assert "in use" in out.lower()
        assert "4242" in out  # shows the offending PID
        assert "--force" in out  # tells the user how to reclaim
