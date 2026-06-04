import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("SECRET_KEY", "iframe-embed-test-secret-key")
os.environ.setdefault("ADMIN_USERNAME", "iframe_admin")
os.environ.setdefault("SITE_URL", "https://vreyc.com")
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.NamedTemporaryFile(suffix='.db', delete=False).name}"
os.environ.setdefault("IMAGE_UPLOAD_DIR", tempfile.mkdtemp(prefix="vre-test-uploads-"))

from main import datetime_local_value, format_admin_datetime, parse_admin_datetime, safe_iframe_src, sanitize_article_html


def test_sanitize_article_html_allows_safe_video_iframe_sources():
    html = '<iframe src="https://player.vimeo.com/video/12345" width="640" height="360" onclick="alert(1)" allow="fullscreen"></iframe>'

    sanitized = sanitize_article_html(html)

    assert 'class="iframe-video-embed"' in sanitized
    assert 'src="https://player.vimeo.com/video/12345"' in sanitized
    assert 'width="640"' in sanitized
    assert 'height="360"' in sanitized
    assert 'allow="fullscreen"' in sanitized
    assert 'allowfullscreen=""' in sanitized
    assert 'frameborder="0"' in sanitized
    assert 'onclick' not in sanitized


def test_sanitize_article_html_blocks_unsafe_iframe_sources_and_scripts():
    html = '<script>alert(1)</script><iframe src="javascript:alert(1)" allow="autoplay"></iframe><iframe src="https://evil.example/video"></iframe>'

    sanitized = sanitize_article_html(html)

    assert '<script' not in sanitized
    assert '<iframe' not in sanitized
    assert 'javascript:' not in sanitized
    assert 'evil.example' not in sanitized


def test_safe_iframe_src_accepts_configured_video_hosts_only():
    assert safe_iframe_src('https://www.youtube.com/watch?v=dQw4w9WgXcQ') == 'https://www.youtube.com/embed/dQw4w9WgXcQ'
    assert safe_iframe_src('https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ') == 'https://www.youtube.com/embed/dQw4w9WgXcQ'
    assert safe_iframe_src('https://player.vimeo.com/video/98765') == 'https://player.vimeo.com/video/98765'
    assert safe_iframe_src('https://www.facebook.com/plugins/video.php?href=https%3A%2F%2Fexample.com') is not None
    assert safe_iframe_src('https://ok.ru/videoembed/12345') == 'https://ok.ru/videoembed/12345'
    assert safe_iframe_src('https://example.com/embed/12345') is None
    assert safe_iframe_src('http://player.vimeo.com/video/98765') is None


def test_admin_datetime_helpers_use_twenty_four_hour_display_format():
    value = datetime(2026, 6, 5, 14, 30)

    assert format_admin_datetime(value) == "05.06.2026 14:30"
    assert datetime_local_value(value) == "2026-06-05T14:30"
    assert parse_admin_datetime("2026-06-05T23:45") == datetime(2026, 6, 5, 23, 45)
    assert parse_admin_datetime("05.06.2026 23:45") == datetime(2026, 6, 5, 23, 45)
    assert parse_admin_datetime("05.06.2026 09:00") == datetime(2026, 6, 5, 9, 0)
    assert parse_admin_datetime("05.06.2026 01:30 PM") is None
