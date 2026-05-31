from __future__ import annotations

from pathlib import Path

from app.core import cloudflare_tunnel as tunnel


class _FakePopen:
    def __init__(self, args, stdout=None, stderr=None):
        self.args = list(args)
        self.stdout = stdout
        self.stderr = stderr
        self.pid = 12345
        self.terminated = False
        self.killed = False
        self.wait_called = False

    def poll(self):
        return None if not self.terminated else 0

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        self.wait_called = True
        return 0

    def kill(self):
        self.killed = True


def _set_common_env(monkeypatch, tmp_path: Path, *, enabled: str, token: str, auto_install: str = "0"):
    monkeypatch.setenv("TUNNEL_ENABLED", enabled)
    monkeypatch.setenv("CLOUDFLARE_TUNNEL_TOKEN", token)
    monkeypatch.setenv("TUNNEL_AUTO_INSTALL_CLOUDFLARED", auto_install)
    monkeypatch.setenv("CLOUDFLARED_BIN_PATH", str(tmp_path / "bin" / "cloudflared"))
    monkeypatch.setenv("CLOUDFLARED_LOG_PATH", str(tmp_path / "cloudflare" / "cloudflared.log"))
    monkeypatch.setenv("CLOUDFLARED_PID_PATH", str(tmp_path / "cloudflare" / "cloudflared.pid"))


def test_is_truthy_values() -> None:
    assert tunnel.is_truthy("1")
    assert tunnel.is_truthy("true")
    assert tunnel.is_truthy("yes")
    assert tunnel.is_truthy("on")
    assert not tunnel.is_truthy("0")
    assert not tunnel.is_truthy("false")
    assert not tunnel.is_truthy("")
    assert not tunnel.is_truthy(None)


def test_start_cloudflared_disabled_returns_none(monkeypatch, tmp_path: Path) -> None:
    _set_common_env(monkeypatch, tmp_path, enabled="0", token="")
    monkeypatch.setattr(tunnel.subprocess, "Popen", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("must not run")))
    result = tunnel.start_cloudflared_if_enabled()
    assert result is None


def test_start_cloudflared_enabled_without_token_warns_and_returns_none(monkeypatch, tmp_path: Path, capsys) -> None:
    _set_common_env(monkeypatch, tmp_path, enabled="1", token="")
    monkeypatch.setattr(tunnel.subprocess, "Popen", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("must not run")))
    result = tunnel.start_cloudflared_if_enabled()
    captured = capsys.readouterr()
    assert result is None
    assert "CLOUDFLARE_TUNNEL_TOKEN is missing" in captured.err


def test_start_cloudflared_missing_binary_auto_install_disabled_returns_none(monkeypatch, tmp_path: Path) -> None:
    _set_common_env(monkeypatch, tmp_path, enabled="1", token="dummy-token", auto_install="0")
    result = tunnel.start_cloudflared_if_enabled()
    assert result is None


def test_start_cloudflared_with_binary_present_starts_subprocess(monkeypatch, tmp_path: Path, capsys) -> None:
    _set_common_env(monkeypatch, tmp_path, enabled="1", token="dummy-token", auto_install="0")
    binary_path = Path(str(tmp_path / "bin" / "cloudflared"))
    binary_path.parent.mkdir(parents=True, exist_ok=True)
    binary_path.write_text("fake-binary", encoding="utf-8")

    captured_args: dict[str, list[str]] = {}

    def _fake_popen(args, stdout=None, stderr=None):
        captured_args["args"] = list(args)
        return _FakePopen(args=args, stdout=stdout, stderr=stderr)

    monkeypatch.setattr(tunnel.subprocess, "Popen", _fake_popen)

    proc = tunnel.start_cloudflared_if_enabled()
    assert proc is not None
    assert proc.pid_path.exists()
    assert proc.pid_path.read_text(encoding="utf-8").strip() == "12345"
    assert "args" in captured_args
    assert captured_args["args"][0] == str(binary_path)
    assert "dummy-token" in captured_args["args"]
    out = capsys.readouterr()
    assert "dummy-token" not in out.out
    assert "dummy-token" not in out.err
    tunnel.stop_cloudflared(proc)


def test_start_cloudflared_auto_install_success(monkeypatch, tmp_path: Path) -> None:
    _set_common_env(monkeypatch, tmp_path, enabled="1", token="dummy-token", auto_install="1")
    bin_path = Path(str(tmp_path / "bin" / "cloudflared"))
    monkeypatch.setattr(tunnel, "_is_supported_auto_install_platform", lambda: True)

    def _fake_download(destination: Path) -> None:
        destination.write_text("downloaded-binary", encoding="utf-8")

    monkeypatch.setattr(tunnel, "_download_cloudflared_binary", _fake_download)
    monkeypatch.setattr(tunnel.subprocess, "Popen", lambda args, stdout=None, stderr=None: _FakePopen(args, stdout, stderr))

    proc = tunnel.start_cloudflared_if_enabled()
    assert proc is not None
    assert bin_path.exists()
    tunnel.stop_cloudflared(proc)


def test_stop_cloudflared_terminates_and_removes_pid(monkeypatch, tmp_path: Path) -> None:
    log_path = tmp_path / "cloudflare" / "cloudflared.log"
    pid_path = tmp_path / "cloudflare" / "cloudflared.pid"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text("12345", encoding="utf-8")
    log_handle = log_path.open("a", encoding="utf-8")
    fake_process = _FakePopen(args=["cloudflared"])
    proc = tunnel.CloudflaredProcess(process=fake_process, log_handle=log_handle, pid_path=pid_path)

    tunnel.stop_cloudflared(proc)
    assert fake_process.terminated is True
    assert not pid_path.exists()
