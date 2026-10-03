"""Tests for format normalization/selection edge cases."""

from core.format_selector import (
    AUDIO,
    VIDEO,
    build_choices,
    normalize_formats,
)

# What yt-dlp's generic extractor returns for a page whose player declares
# neither codec: a video with no declared video codec and explicitly no audio.
SAMPLE_RAW = [
    {
        "format_id": "0",
        "ext": "mp4",
        "protocol": "https",
        "vcodec": None,
        "acodec": "none",
        "height": None,
        "width": None,
        "resolution": None,
    },
    {
        "format_id": "1",
        "ext": "mp4",
        "protocol": "https",
        "vcodec": None,
        "acodec": "none",
        "height": None,
        "width": None,
        "resolution": None,
    },
]


def test_undeclared_video_with_explicit_no_audio_is_kept_as_video():
    formats = normalize_formats(SAMPLE_RAW)
    assert len(formats) == 2
    assert all(f.type == VIDEO for f in formats)
    assert all(f.has_video and not f.has_audio for f in formats)


def test_page_with_undeclared_codecs_yields_a_selectable_video_choice():
    formats = normalize_formats(SAMPLE_RAW)
    choices = build_choices(formats, {}, ffmpeg_available=False)
    assert choices, "the link must not end up with zero formats"
    assert choices[0].type == VIDEO
    assert choices[0].format_id in {"0", "1"}


def test_known_codecs_unchanged():
    formats = normalize_formats([
        {"format_id": "v", "ext": "mp4", "vcodec": "avc1.4d401f", "acodec": "mp4a.40.2", "height": 720},
    ])
    assert formats[0].type == VIDEO
    assert formats[0].has_video and formats[0].has_audio


def test_audio_only_streams():
    only_audio = normalize_formats([
        {"format_id": "a", "ext": "m4a", "vcodec": "none", "acodec": "mp4a.40.2", "abr": 128},
        {"format_id": "b", "ext": "m4a", "vcodec": "none", "acodec": None, "abr": 96},
    ])
    assert [f.type for f in only_audio] == [AUDIO, AUDIO]
    assert all(f.has_audio and not f.has_video for f in only_audio)


def test_undeclared_both_with_size_is_muxed():
    formats = normalize_formats([
        {"format_id": "m", "ext": "mp4", "vcodec": None, "acodec": None, "height": 1080},
    ])
    assert formats[0].has_video and formats[0].has_audio


def test_explicitly_absent_both_is_dropped():
    assert normalize_formats([
        {"format_id": "x", "ext": "mp4", "vcodec": "none", "acodec": "none"},
    ]) == []


def test_declared_video_with_undeclared_audio_stays_video_only():
    formats = normalize_formats([
        {"format_id": "v", "ext": "mp4", "vcodec": "avc1", "acodec": None, "height": 720},
    ])
    assert formats[0].has_video and not formats[0].has_audio
