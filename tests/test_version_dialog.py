"""Tests for release-notes cleanup in the version dialog."""

from gui.version_dialog import clean_notes, display_version


def test_display_version_normalizes_leading_v():
    assert display_version("1.2.1") == "v1.2.1"
    assert display_version("v1.2.1") == "v1.2.1"
    assert display_version("") == "?"


def test_clean_notes_drops_full_changelog_line():
    raw = (
        "## What's Changed\n"
        "* Fix permission for Linux when updating\n"
        "\n"
        "**Full Changelog**: https://github.com/o/r/compare/v1.1.0...v1.2.0\n"
    )
    cleaned = clean_notes(raw)
    assert "Full Changelog" not in cleaned
    assert "Fix permission for Linux" in cleaned


def test_clean_notes_keeps_plain_notes():
    assert clean_notes("Just a note.") == "Just a note."
    assert clean_notes("") == ""
