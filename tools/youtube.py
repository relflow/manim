"""Upload reviewed clips with the official YouTube SDK; OAuth stays in memory."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANNEL = "@relflow-ai"
PLAYLIST = "RelFlow, Visualized"
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")


class UploadError(ValueError):
    """A safe, actionable message without SDK responses or credentials."""


class VisibleSafari:
    """Open an explicit Safari document without exposing the OAuth URL in argv."""

    def open(self, url, new=0, autoraise=True):
        quoted = url.replace("\\", "\\\\").replace('"', '\\"')
        script = (
            f'tell application "Safari"\nmake new document with properties {{URL:"{quoted}"}}\nactivate\nend tell\n'
        )
        try:
            result = subprocess.run(
                ["osascript"],
                input=script,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise UploadError("Safari could not open the authorization window; no uploads started") from error
        if result.returncode:
            raise UploadError("Safari could not open the authorization window; no uploads started")
        return True


def http_details(error: Exception) -> tuple[int | None, tuple[str, ...]]:
    """Extract only HTTP status and API reason codes, never request URLs or messages."""
    status = getattr(getattr(error, "resp", None), "status", None)
    if type(status) is not int or not 100 <= status <= 599:
        status = None
    reasons = []
    try:
        errors = json.loads(getattr(error, "content", b"{}"))["error"].get("errors", [])
        for detail in errors:
            reason = detail.get("reason")
            if isinstance(reason, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", reason):
                reasons.append(reason)
    except (AttributeError, KeyError, TypeError, ValueError, UnicodeError):
        pass
    return status, tuple(sorted(set(reasons)))


def error_summary(error: Exception) -> str:
    status, reasons = http_details(error)
    summary = f"HTTP {status}" if status else type(error).__name__
    if reasons:
        summary += ": " + ", ".join(reasons)
    hints = {
        "accessNotConfigured": "Enable YouTube Data API v3 in the OAuth client's Google Cloud project.",
        "quotaExceeded": "The project's API quota is exhausted; check its quota before retrying.",
        "dailyLimitExceeded": "The project's daily API limit was reached; retry after it resets.",
        "uploadLimitExceeded": "The channel's upload limit was reached; check YouTube Studio.",
        "insufficientPermissions": "Authorize again and grant the requested YouTube permission.",
        "youtubeSignupRequired": "Create the channel in YouTube Studio before uploading.",
        "forbidden": "Check the channel's permissions and feature eligibility in YouTube Studio.",
    }
    for reason in reasons:
        if reason in hints:
            summary += ". " + hints[reason]
    return summary


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise UploadError(f"Expected a JSON object: {path}")
    return value


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def upload_plan(root: Path, segment: str = "all", no_thumbnails: bool = False) -> list[dict]:
    """Validate every selected package without importing the optional SDK."""
    series = read_json(root / "series.json")
    packages = []
    seen = set()
    for sequence, entry in enumerate(series["segments"], 1):
        slug = entry["id"]
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug) or slug in seen:
            raise UploadError("Invalid or duplicate segment ID")
        seen.add(slug)
        if segment not in {"all", slug}:
            continue
        directory = root / "dist" / slug
        paths = {
            "video": directory / f"{slug}.mp4",
            "captions": directory / "captions.srt",
            "thumbnail": directory / "thumbnail.jpg",
            "metadata": directory / "youtube.txt",
        }
        for name, path in paths.items():
            if name == "thumbnail" and no_thumbnails and not path.exists():
                continue
            if not path.is_file() or path.stat().st_size == 0:
                raise UploadError(f"Missing or empty {name} for {slug}: {path}")
        title, _, description = paths["metadata"].read_text(encoding="utf-8").partition("\n")
        title, description = title.strip(), description.strip()
        if not title or len(title) > 100 or any(c in title for c in "<>"):
            raise UploadError(f"Invalid YouTube title for {slug}")
        if not description or len(description.encode("utf-8")) > 5000 or any(c in description for c in "<>"):
            raise UploadError(f"Invalid YouTube description for {slug}")
        packages.append(
            {
                "id": slug,
                "sequence": sequence,
                "title": title,
                "description": description,
                "paths": {key: str(path) for key, path in paths.items()},
                "source": {key: digest(path) for key, path in paths.items() if path.is_file()},
                "youtube_id": entry.get("youtube_id"),
                "privacy": "unlisted",
                "notify_subscribers": False,
                "made_for_kids": False,
            }
        )
    if not packages:
        raise UploadError(f"Unknown segment: {segment}")
    return packages


def authenticate(client_secrets: Path):
    """The SDK alone reads the supplied client file; never persist OAuth tokens."""
    # OAuth and HTTP debug logs can contain callbacks, tokens, and upload URLs.
    # This dedicated CLI reports its own safe diagnostics throughout the run.
    logging.disable(logging.CRITICAL)
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    browser = None
    if sys.platform == "darwin":
        webbrowser.register("relflow-safari", None, VisibleSafari())
        browser = "relflow-safari"
    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_secrets), ["https://www.googleapis.com/auth/youtube.force-ssl"]
    )
    credentials = flow.run_local_server(
        host="127.0.0.1",
        port=0,
        authorization_prompt_message="",
        success_message="YouTube authorization complete. You may close this tab.",
        access_type="online",
        browser=browser,
        timeout_seconds=300,
    )
    return build("youtube", "v3", credentials=credentials, cache_discovery=False), MediaFileUpload


def items(service, resource: str, **parameters) -> list[dict]:
    found = []
    while True:
        response = getattr(service, resource)().list(**parameters).execute()
        found.extend(response.get("items", []))
        if not response.get("nextPageToken"):
            return found
        parameters["pageToken"] = response["nextPageToken"]


def playlist_contents(service, playlist_id: str) -> list[dict]:
    """New playlists can briefly return playlistNotFound before becoming readable."""
    for attempt in range(6):
        try:
            return items(service, "playlistItems", part="snippet", playlistId=playlist_id, maxResults=50)
        except Exception as error:
            if http_details(error) != (404, ("playlistNotFound",)) or attempt == 5:
                raise
            time.sleep(2**attempt)


def verify_video(service, video_id: str, channel_id: str, package: dict) -> None:
    if not isinstance(video_id, str) or VIDEO_ID.fullmatch(video_id) is None:
        raise UploadError("Invalid saved YouTube video ID")
    videos = items(service, "videos", part="snippet,status", id=video_id)
    if len(videos) != 1:
        raise UploadError(f"Saved video unavailable for {package['id']}; refusing to reupload")
    video = videos[0]
    snippet, status = video["snippet"], video["status"]
    if (
        snippet.get("channelId") != channel_id
        or status.get("privacyStatus") != "unlisted"
        or status.get("embeddable") is not True
    ):
        raise UploadError(f"Video ownership, unlisted visibility, or embedding mismatch: {package['id']}")
    if any(snippet.get(key) != package[key] for key in ("title", "description")):
        raise UploadError(f"Remote metadata differs for {package['id']}; refusing to change an existing video")


def save_series_id(root: Path, package: dict, video_id: str) -> None:
    path = root / "series.json"
    series = read_json(path)
    entry = next(entry for entry in series["segments"] if entry["id"] == package["id"])
    if entry.get("youtube_id") not in {None, video_id}:
        raise UploadError(f"series.json already records another video for {package['id']}")
    if entry.get("youtube_id") != video_id:
        entry["youtube_id"] = video_id
        atomic_json(path, series)


def publish(
    root: Path,
    client_secrets: Path,
    channel: str = CHANNEL,
    segment: str = "all",
    playlist_title: str = PLAYLIST,
    no_thumbnails: bool = False,
    connect=None,
) -> dict:
    if channel != CHANNEL:
        raise UploadError(f"This series must be uploaded to {CHANNEL}")
    if not playlist_title.strip() or len(playlist_title) > 150 or any(c in playlist_title for c in "<>"):
        raise UploadError("Invalid playlist title")
    packages = upload_plan(root, segment, no_thumbnails)
    state_path = root / "dist" / "youtube-state.json"
    state = (
        read_json(state_path)
        if state_path.exists()
        else {
            "schema": 1,
            "channel_handle": channel,
            "channel_id": None,
            "uploads": {},
            "playlist": None,
        }
    )
    if state.get("schema") != 1 or state.get("channel_handle") != channel or not isinstance(state.get("uploads"), dict):
        raise UploadError("Upload state belongs to another channel or has an invalid format")
    if state.get("playlist") and state["playlist"].get("title") != playlist_title:
        raise UploadError("Saved playlist title differs; refusing to create another playlist")
    for package in packages:
        entry = state["uploads"].get(package["id"])
        if entry and entry.get("source") != package["source"]:
            raise UploadError(f"Source hash mismatch for {package['id']}; refusing to reuse upload state")
        if entry and entry.get("upload_pending") and not entry.get("video_id"):
            raise UploadError(
                f"An earlier upload of {package['id']} may have completed. Check YouTube Studio and "
                "recover its video ID in youtube-state.json before retrying; no automatic reupload."
            )
        if package["youtube_id"] and (not entry or entry.get("video_id") != package["youtube_id"]):
            raise UploadError(f"series.json ID has no matching upload state for {package['id']}; reconcile it first")
    if not client_secrets.is_file():
        raise UploadError("Supply your downloaded Desktop OAuth client file with --client-secrets")
    service, media = (connect or authenticate)(client_secrets)
    expected = items(service, "channels", part="id", forHandle=channel)
    mine = items(service, "channels", part="id", mine=True)
    if len(expected) != 1 or len(mine) != 1 or expected[0]["id"] != mine[0]["id"]:
        raise UploadError(f"The authenticated channel is not {channel}; no uploads were started")
    channel_id = mine[0]["id"]
    if state.get("channel_id") not in {None, channel_id}:
        raise UploadError("Saved upload state belongs to a different YouTube channel")
    state["channel_id"] = channel_id
    # Check every reusable selected video before the first remote mutation.
    for package in packages:
        entry = state["uploads"].get(package["id"], {})
        if entry.get("video_id"):
            verify_video(service, entry["video_id"], channel_id, package)
    playlist = state.get("playlist")
    if playlist:
        matches = items(service, "playlists", part="snippet,status", id=playlist["id"])
    else:
        matches = [
            p
            for p in items(service, "playlists", part="snippet,status", mine=True, maxResults=50)
            if p["snippet"]["title"] == playlist_title and p["status"]["privacyStatus"] == "unlisted"
        ]
        if len(matches) > 1:
            raise UploadError("Multiple matching playlists exist; choose its ID in youtube-state.json")
    if matches:
        playlist = matches[0]
        if (
            playlist["snippet"].get("channelId") != channel_id
            or playlist["snippet"].get("title") != playlist_title
            or playlist["status"].get("privacyStatus") != "unlisted"
        ):
            raise UploadError("Saved playlist ownership, title, or visibility mismatch")
    elif state.get("playlist"):
        raise UploadError("Saved playlist is unavailable; refusing to create another")
    else:
        playlist = (
            service.playlists()
            .insert(
                part="snippet,status",
                body={
                    "snippet": {"title": playlist_title, "defaultLanguage": "en"},
                    "status": {"privacyStatus": "unlisted"},
                },
            )
            .execute()
        )
    state["playlist"] = {"id": playlist["id"], "title": playlist_title}
    atomic_json(state_path, state)
    playlist_items = playlist_contents(service, playlist["id"])
    order = {entry["id"]: index for index, entry in enumerate(read_json(root / "series.json")["segments"])}
    known = {entry["video_id"]: order[slug] for slug, entry in state["uploads"].items() if entry.get("video_id")}
    current = [item["snippet"]["resourceId"]["videoId"] for item in playlist_items]
    if any(video_id not in known for video_id in current) or current != sorted(current, key=known.get):
        raise UploadError("Playlist has unrelated or out-of-order videos; review it before continuing")
    for package in packages:
        slug = package["id"]
        entry = state["uploads"].setdefault(slug, {"source": package["source"]})
        if not entry.get("video_id"):
            entry["upload_pending"] = True
            atomic_json(state_path, state)
            try:
                request = service.videos().insert(
                    part="snippet,status",
                    notifySubscribers=False,
                    body={
                        "snippet": {
                            "title": package["title"],
                            "description": package["description"],
                            "categoryId": "27",
                            "defaultLanguage": "en",
                            "defaultAudioLanguage": "en",
                        },
                        "status": {"privacyStatus": "unlisted", "embeddable": True, "selfDeclaredMadeForKids": False},
                    },
                    media_body=media(package["paths"]["video"], mimetype="video/mp4", resumable=True),
                )
                response = None
                while response is None:
                    _, response = request.next_chunk(num_retries=3)
                entry["video_id"] = response["id"]
                entry["upload_pending"] = False
                atomic_json(state_path, state)
            except Exception as error:
                raise UploadError(
                    f"Upload outcome for {slug} may be ambiguous ({error_summary(error)}). "
                    "Check YouTube Studio before retrying; "
                    "the saved pending marker prevents an automatic duplicate."
                ) from error
        video_id = entry["video_id"]
        verify_video(service, video_id, channel_id, package)
        save_series_id(root, package, video_id)
        if not entry.get("captions_id"):
            captions = [
                c
                for c in items(service, "captions", part="snippet", videoId=video_id)
                if c["snippet"].get("language") == "en" and c["snippet"].get("name") == "English"
            ]
            if len(captions) > 1:
                raise UploadError(f"Multiple English caption tracks for {slug}; review them before retrying")
            caption = (
                captions[0]
                if captions
                else service.captions()
                .insert(
                    part="snippet",
                    body={
                        "snippet": {"videoId": video_id, "language": "en", "name": "English", "isDraft": False},
                    },
                    media_body=media(package["paths"]["captions"], mimetype="application/octet-stream"),
                )
                .execute()
            )
            entry["captions_id"] = caption["id"]
            atomic_json(state_path, state)
        if not no_thumbnails and not entry.get("thumbnail_done") and not entry.get("thumbnail_skipped"):
            try:
                service.thumbnails().set(
                    videoId=video_id, media_body=media(package["paths"]["thumbnail"], mimetype="image/jpeg")
                ).execute()
                entry["thumbnail_done"] = True
            except Exception as error:
                if http_details(error) != (403, ("forbidden",)):
                    raise
                entry["thumbnail_skipped"] = "forbidden"
                print(
                    f"{slug}: custom thumbnail unavailable (HTTP 403: forbidden); using YouTube's automatic thumbnail."
                )
            atomic_json(state_path, state)
        if video_id not in current:
            known[video_id] = order[slug]
            position = sum(known[existing] < order[slug] for existing in current)
            service.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": playlist["id"],
                        "position": position,
                        "resourceId": {"kind": "youtube#video", "videoId": video_id},
                    }
                },
            ).execute()
            current.insert(position, video_id)
            atomic_json(state_path, state)
        print(f"{slug}: https://youtu.be/{video_id} (unlisted)")
    return state


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", default=CHANNEL)
    parser.add_argument("--client-secrets", type=Path)
    parser.add_argument("--segment", default="all")
    parser.add_argument("--playlist-title", default=PLAYLIST)
    parser.add_argument("--no-thumbnails", action="store_true")
    parser.add_argument(
        "--plan", action="store_true", help="Print validated metadata without SDK imports or authentication"
    )
    args = parser.parse_args(argv)
    try:
        if args.channel != CHANNEL:
            raise UploadError(f"This series must be uploaded to {CHANNEL}")
        if args.plan:
            print(json.dumps(upload_plan(ROOT, args.segment, args.no_thumbnails), indent=2))
        else:
            if not args.client_secrets:
                raise UploadError("--client-secrets is required for upload; use --plan for offline validation")
            publish(ROOT, args.client_secrets, args.channel, args.segment, args.playlist_title, args.no_thumbnails)
    except UploadError as error:
        print(f"YouTube upload stopped: {error}")
        return 1
    except Exception as error:
        # HTTP errors may include resumable session URLs. Never print exception details.
        print(
            f"YouTube upload stopped ({error_summary(error)}). Saved progress will be reused; "
            "check Studio before retrying if a media upload was interrupted."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
