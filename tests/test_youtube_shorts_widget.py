import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("SECRET_KEY", "youtube-shorts-test-secret-key")
os.environ.setdefault("ADMIN_USERNAME", "youtube_admin")
os.environ.setdefault("ADMIN_PASSWORD_HASH", "$2b$12$abcdefghijklmnopqrstuuO6aU4sS0rQ9LyKiq1hrT8zLa0vraWjK")
os.environ.setdefault("SITE_URL", "https://vreyc.com")
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.NamedTemporaryFile(suffix='.db', delete=False).name}"
os.environ.setdefault("IMAGE_UPLOAD_DIR", tempfile.mkdtemp(prefix="vre-youtube-test-uploads-"))

from main import parse_youtube_channel_id, parse_youtube_shorts_ids, youtube_video_payload


def test_parse_youtube_shorts_ids_preserves_first_unique_short():
    html = r'''
    {"url":"\/shorts\/AAA111bbb22"}
    <a href="/shorts/CCC333ddd44">Short</a>
    {"url":"\/shorts\/AAA111bbb22"}
    '''

    assert parse_youtube_shorts_ids(html) == ["AAA111bbb22", "CCC333ddd44"]


def test_parse_youtube_channel_id_accepts_initial_data_fields():
    html = '{"metadata":{"channelId":"UCexample12345"},"externalId":"UCfallback67890"}'

    assert parse_youtube_channel_id(html) == "UCexample12345"


def test_youtube_video_payload_builds_shorts_and_embed_metadata():
    payload = youtube_video_payload("AAA111bbb22", short=True)

    assert payload["kind"] == "short"
    assert payload["url"] == "https://www.youtube.com/shorts/AAA111bbb22"
    assert payload["embed_url"].startswith("https://www.youtube.com/embed/AAA111bbb22?")
    assert "mute=1" in payload["embed_url"]
    assert payload["thumbnail"] == "https://i.ytimg.com/vi/AAA111bbb22/hqdefault.jpg"
