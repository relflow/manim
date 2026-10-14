"""Upload control flow uses a fake SDK and never contacts YouTube."""

import builtins
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import youtube


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "series.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "segments": [
                    {"id": "first-model", "youtube_id": None},
                ],
            }
        )
    )
    package = tmp_path / "dist" / "first-model"
    package.mkdir(parents=True)
    for name in ("first-model.mp4", "captions.srt", "thumbnail.jpg"):
        (package / name).write_bytes(b"reviewed media")
    (package / "youtube.txt").write_text("Your First Model\n\nA reviewed explanation.\n")
    client = tmp_path / "desktop-client.json"
    client.write_text("{}")
    return tmp_path, client


class Request:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    def execute(self):
        if self.error:
            raise self.error
        return self.result

    def next_chunk(self, num_retries):
        assert num_retries == 3
        return None, self.execute()


class HttpFailure(Exception):
    def __init__(self, status, reason):
        self.resp = type("Response", (), {"status": status})()
        self.content = json.dumps({"error": {"errors": [{"reason": reason}], "message": "secret/session-uri"}}).encode()
        super().__init__("secret/session-uri")


class Resource:
    def __init__(self, service, name):
        self.service, self.name = service, name

    def list(self, **parameters):
        s = self.service
        if self.name == "channels":
            result = [{"id": s.mine if parameters.get("mine") else "channel-relflow"}]
        elif self.name == "videos":
            result = [s.video] if s.video else []
        elif self.name == "playlists":
            result = [s.playlist] if s.playlist else []
        elif self.name == "playlistItems":
            result = s.playlist_items
        elif self.name == "captions":
            result = s.caption_tracks
        else:
            raise AssertionError(self.name)
        return Request({"items": result})

    def insert(self, **parameters):
        s = self.service
        s.mutations.append((self.name, parameters))
        body = parameters["body"]
        if self.name == "playlists":
            s.playlist = {
                "id": "playlist-relflow",
                "snippet": {**body["snippet"], "channelId": "channel-relflow"},
                "status": body["status"],
            }
            return Request(s.playlist)
        if self.name == "videos":
            assert parameters["notifySubscribers"] is False
            assert body["status"]["selfDeclaredMadeForKids"] is False
            s.video = {
                "id": "aB012345_-Z",
                "snippet": {**body["snippet"], "channelId": "channel-relflow"},
                "status": body["status"],
            }
            return Request(s.video, RuntimeError("secret/session-uri") if s.fail_video else None)
        if self.name == "captions":
            if s.fail_captions:
                return Request(error=RuntimeError("secret/session-uri"))
            caption = {"id": "caption-english", "snippet": body["snippet"]}
            s.caption_tracks.append(caption)
            return Request(caption)
        if self.name == "playlistItems":
            item = {"snippet": body["snippet"]}
            s.playlist_items.insert(body["snippet"]["position"], item)
            return Request(item)
        raise AssertionError(self.name)

    def set(self, **parameters):
        self.service.mutations.append((self.name, parameters))
        return Request({}, self.service.thumbnail_error)


class Service:
    def __init__(self):
        self.mine = "channel-relflow"
        self.video = self.playlist = None
        self.caption_tracks, self.playlist_items, self.mutations = [], [], []
        self.fail_captions = self.fail_video = False
        self.thumbnail_error = None

    def __getattr__(self, name):
        return lambda: Resource(self, name)

    def connect(self, _client):
        return self, lambda path, **kwargs: {"path": str(path), **kwargs}


def run(workspace, service):
    root, client = workspace
    return youtube.publish(root, client, connect=service.connect)


def state(root: Path):
    return json.loads((root / "dist/youtube-state.json").read_text())


def test_wrong_authenticated_channel_has_no_mutations(workspace):
    service = Service()
    service.mine = "unrelated-channel"
    with pytest.raises(youtube.UploadError, match="authenticated channel is not"):
        run(workspace, service)
    assert service.mutations == []
    assert not (workspace[0] / "dist/youtube-state.json").exists()


def test_completed_retry_skips_all_uploads_and_attachments(workspace):
    service = Service()
    run(workspace, service)
    first = list(service.mutations)
    run(workspace, service)
    assert service.mutations == first
    saved = state(workspace[0])["uploads"]["first-model"]
    assert saved["video_id"] == "aB012345_-Z"
    assert saved["captions_id"] == "caption-english"
    assert saved["thumbnail_done"] is True
    assert json.loads((workspace[0] / "series.json").read_text())["segments"][0]["youtube_id"] == saved["video_id"]


def test_captions_failure_checkpoints_video_before_retry(workspace):
    service = Service()
    service.fail_captions = True
    with pytest.raises(RuntimeError):
        run(workspace, service)
    assert state(workspace[0])["uploads"]["first-model"]["video_id"] == "aB012345_-Z"
    service.fail_captions = False
    run(workspace, service)
    assert [name for name, _ in service.mutations].count("videos") == 1


def test_changed_source_refused_before_authentication(workspace):
    service = Service()
    run(workspace, service)
    (workspace[0] / "dist/first-model/first-model.mp4").write_bytes(b"different render")
    with pytest.raises(youtube.UploadError, match="Source hash mismatch"):
        youtube.publish(*workspace, connect=lambda _: pytest.fail("must not authenticate"))


def test_ambiguous_media_upload_never_automatically_reuploads(workspace):
    service = Service()
    service.fail_video = True
    with pytest.raises(youtube.UploadError, match="may be ambiguous"):
        run(workspace, service)
    assert state(workspace[0])["uploads"]["first-model"]["upload_pending"] is True
    with pytest.raises(youtube.UploadError, match="may have completed"):
        youtube.publish(*workspace, connect=lambda _: pytest.fail("must not authenticate"))
    assert [name for name, _ in service.mutations].count("videos") == 1


def test_plan_needs_no_sdk_or_authentication(workspace, monkeypatch, capsys):
    monkeypatch.setattr(youtube, "ROOT", workspace[0])
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        assert not name.startswith(("google", "oauth"))
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    assert youtube.main(["--plan"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["privacy"] == "unlisted"
    assert not (workspace[0] / "dist/youtube-state.json").exists()


def test_authentication_suppresses_library_logs_and_requests_only_online_access(monkeypatch, caplog, capsys):
    credentials, service, media = object(), object(), object()
    previous_disable = logging.root.manager.disable
    library_logger = logging.getLogger("requests_oauthlib.oauth2_session")

    class Flow:
        @staticmethod
        def from_client_secrets_file(path, scopes):
            assert logging.root.manager.disable == logging.CRITICAL
            assert path == "desktop-client.json"
            assert scopes == ["https://www.googleapis.com/auth/youtube.force-ssl"]
            return Flow()

        def run_local_server(self, **kwargs):
            assert kwargs["host"] == "127.0.0.1" and kwargs["port"] == 0
            assert kwargs["authorization_prompt_message"] == ""
            assert kwargs["access_type"] == "online"
            assert kwargs["timeout_seconds"] == 300
            library_logger.debug("fake sensitive token response")
            logging.getLogger("google_auth_oauthlib.flow").info("fake sensitive callback")
            return credentials

    def build(name, version, **kwargs):
        assert (name, version) == ("youtube", "v3")
        assert kwargs == {"credentials": credentials, "cache_discovery": False}
        return service

    imports = {
        "google_auth_oauthlib.flow": SimpleNamespace(InstalledAppFlow=Flow),
        "googleapiclient.discovery": SimpleNamespace(build=build),
        "googleapiclient.http": SimpleNamespace(MediaFileUpload=media),
    }
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        return imports[name] if name in imports else original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    try:
        logging.disable(logging.NOTSET)
        with caplog.at_level(logging.DEBUG):
            assert youtube.authenticate(Path("desktop-client.json")) == (service, media)
            assert logging.root.manager.disable == logging.CRITICAL
        assert caplog.records == []
        assert capsys.readouterr().out == ""
    finally:
        logging.disable(previous_disable)


def test_visible_safari_uses_stdin_and_suppresses_process_output(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(youtube.subprocess, "run", run)
    assert youtube.VisibleSafari().open('https://example.invalid/?value="quoted"') is True
    command, options = calls[0]
    assert command == ["osascript"]
    assert "make new document with properties" in options["input"]
    assert '\\"quoted\\"' in options["input"]
    assert options["stdout"] == options["stderr"] == youtube.subprocess.DEVNULL
    assert options["timeout"] == 30


def test_visible_safari_reports_failure_without_process_details(monkeypatch):
    monkeypatch.setattr(youtube.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1))
    with pytest.raises(youtube.UploadError, match="Safari could not open"):
        youtube.VisibleSafari().open("https://example.invalid/")


def test_playlist_contents_retries_only_propagation_404(monkeypatch):
    calls, waits = [], []

    def delayed_items(service, resource, **kwargs):
        calls.append(resource)
        if len(calls) < 3:
            raise HttpFailure(404, "playlistNotFound")
        return [{"id": "ready"}]

    monkeypatch.setattr(youtube, "items", delayed_items)
    monkeypatch.setattr(youtube.time, "sleep", waits.append)
    assert youtube.playlist_contents(object(), "playlist") == [{"id": "ready"}]
    assert calls == ["playlistItems"] * 3
    assert waits == [1, 2]


def test_main_sanitizes_sdk_error_details(workspace, monkeypatch, capsys):
    monkeypatch.setattr(youtube, "ROOT", workspace[0])
    service = Service()
    service.fail_captions = True
    monkeypatch.setattr(youtube, "authenticate", service.connect)
    assert youtube.main(["--client-secrets", str(workspace[1])]) == 1
    output = capsys.readouterr().out
    assert "RuntimeError" in output
    assert "secret/session-uri" not in output


def test_forbidden_custom_thumbnail_is_checkpointed_and_playlist_continues(workspace, capsys):
    service = Service()
    service.thumbnail_error = HttpFailure(403, "forbidden")
    run(workspace, service)
    saved = state(workspace[0])["uploads"]["first-model"]
    assert saved["thumbnail_skipped"] == "forbidden"
    assert not saved.get("thumbnail_done")
    assert saved["captions_id"] == "caption-english"
    assert len(service.playlist_items) == 1
    before = list(service.mutations)
    run(workspace, service)
    assert service.mutations == before
    output = capsys.readouterr().out
    assert "custom thumbnail unavailable (HTTP 403: forbidden)" in output
    assert "secret/session-uri" not in output


@pytest.mark.parametrize(
    "status,reason", [(403, "quotaExceeded"), (403, "insufficientPermissions"), (500, "forbidden")]
)
def test_other_thumbnail_errors_stop_and_preserve_progress(workspace, status, reason):
    service = Service()
    service.thumbnail_error = HttpFailure(status, reason)
    with pytest.raises(HttpFailure):
        run(workspace, service)
    saved = state(workspace[0])["uploads"]["first-model"]
    assert saved["video_id"] == "aB012345_-Z"
    assert saved["captions_id"] == "caption-english"
    assert not saved.get("thumbnail_skipped")
    assert service.playlist_items == []


def test_main_reports_only_safe_http_status_reason_and_action(workspace, monkeypatch, capsys):
    monkeypatch.setattr(youtube, "ROOT", workspace[0])
    service = Service()
    service.thumbnail_error = HttpFailure(403, "accessNotConfigured")
    monkeypatch.setattr(youtube, "authenticate", service.connect)
    assert youtube.main(["--client-secrets", str(workspace[1])]) == 1
    output = capsys.readouterr().out
    assert "HTTP 403: accessNotConfigured" in output
    assert "Enable YouTube Data API v3" in output
    assert "secret/session-uri" not in output


@pytest.mark.parametrize("field,value", [("channelId", "unrelated-channel"), ("title", "changed title")])
def test_remote_mismatch_refused_before_mutations(workspace, field, value):
    service = Service()
    run(workspace, service)
    service.video["snippet"][field] = value
    before = list(service.mutations)
    with pytest.raises(youtube.UploadError, match="mismatch|metadata differs"):
        run(workspace, service)
    assert service.mutations == before
