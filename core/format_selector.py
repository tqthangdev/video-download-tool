"""Normalized video/format model + format selection.

Turns the raw yt-dlp info dictionary into the app's own model (VideoInfo /
VideoFormat), builds the selectable FormatChoices shown as radio buttons, and
picks a default format. Nothing here downloads anything (flow.md #7-#14, #40).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

VIDEO = "video"
AUDIO = "audio"

DEFAULT_AUDIO_BITRATES = (128, 192, 320)
GROUP_VIDEO = "MP4"
GROUP_AUDIO = "MP3"

# Extensions that only ever carry audio.
AUDIO_ONLY_EXTS = ("m4a", "mp3", "opus", "aac", "ogg", "oga", "wav", "flac")

# Placeholder codec for streams whose manifest/player does not declare one
# (common for HLS). It means "present but unspecified", not "invented".
UNKNOWN_CODEC = "unknown"


@dataclass
class VideoFormat:
    """A single normalized yt-dlp source format."""

    format_id: str
    type: str
    ext: Optional[str] = None
    resolution: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None
    bitrate: Optional[int] = None  # bits per second
    filesize: Optional[int] = None
    filesize_approx: Optional[int] = None
    url: Optional[str] = None
    vcodec: Optional[str] = None
    acodec: Optional[str] = None

    @property
    def has_video(self) -> bool:
        # `type` is the classification done while normalizing; the codec check
        # is only a fallback for formats built without going through it.
        return self.type == VIDEO or self.vcodec not in (None, "none")

    @property
    def has_audio(self) -> bool:
        return self.type == AUDIO or self.acodec not in (None, "none")


@dataclass
class VideoInfo:
    url: str
    title: str
    thumbnail: Optional[str] = None
    duration: Optional[int] = None
    uploader: Optional[str] = None
    webpage_url: Optional[str] = None
    extractor: Optional[str] = None
    formats: list[VideoFormat] = field(default_factory=list)
    # Set when the formats were discovered by scanning the page ourselves
    # instead of by an extractor: the media URL they were read from.
    source_url: Optional[str] = None


@dataclass
class FormatChoice:
    """A selectable output option (one radio button)."""

    group: str  # "MP4" / "MP3"
    label: str  # "720p" / "128kbps"
    type: str  # video / audio
    format_id: str  # yt-dlp -f expression
    output_ext: str  # final file extension
    height: Optional[int] = None
    bitrate: Optional[int] = None
    needs_ffmpeg: bool = False
    filesize: Optional[int] = None
    # Media URL the formats were read from, when they came from a page scan.
    # It carries tokens that expire, so the downloader refreshes it first.
    source_url: Optional[str] = None

    @property
    def display(self) -> str:
        return f"{self.group} {self.label}".strip()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "FormatChoice":
        fields = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in (data or {}).items() if k in fields})


def normalize_formats(raw_formats) -> list[VideoFormat]:
    """Convert raw yt-dlp formats into VideoFormat objects."""
    formats: list[VideoFormat] = []

    for raw in raw_formats or []:
        format_id = raw.get("format_id")
        if not format_id:
            continue

        vcodec = raw.get("vcodec")
        acodec = raw.get("acodec")
        has_video = vcodec not in (None, "none")
        has_audio = acodec not in (None, "none")

        # yt-dlp uses None for "codec not declared" and the string "none" for
        # "this stream carries no such track". HLS/DASH manifests and the
        # generic page scanner often leave one side undeclared, so infer what
        # that side carries from the container/size instead of dropping the
        # whole format (a track is only dropped when it is explicitly absent).
        ext = (raw.get("ext") or "").lower()
        has_size = bool(raw.get("height") or raw.get("width") or raw.get("resolution"))
        video_undeclared = vcodec is None
        audio_undeclared = acodec is None

        if video_undeclared and (audio_undeclared or acodec == "none"):
            # No declared video codec: assume a picture unless it is audio-only.
            if not (ext in AUDIO_ONLY_EXTS or raw.get("abr")):
                vcodec = UNKNOWN_CODEC
                has_video = True

        if audio_undeclared and (video_undeclared or vcodec == "none"):
            # No declared audio codec: present for muxed/video containers and
            # for audio-only extensions.
            if (
                has_size
                or ext in ("mp4", "ts", "webm", "flv", "mkv")
                or ext in AUDIO_ONLY_EXTS
                or raw.get("abr")
            ):
                acodec = UNKNOWN_CODEC
                has_audio = True

        # Drop anything that carries neither video nor audio.
        if not has_video and not has_audio:
            continue

        width = raw.get("width")
        height = raw.get("height")
        resolution = raw.get("resolution")
        if not resolution and width and height:
            resolution = f"{width}x{height}"

        bitrate = None
        if has_audio and raw.get("abr"):
            bitrate = int(raw["abr"] * 1000)
        elif raw.get("tbr"):
            bitrate = int(raw["tbr"] * 1000)

        formats.append(
            VideoFormat(
                format_id=str(format_id),
                type=VIDEO if has_video else AUDIO,
                ext=raw.get("ext"),
                resolution=resolution,
                width=width,
                height=height,
                fps=raw.get("fps"),
                bitrate=bitrate,
                filesize=raw.get("filesize"),
                filesize_approx=raw.get("filesize_approx"),
                url=raw.get("url"),
                vcodec=vcodec,
                acodec=acodec,
            )
        )

    return formats


def _best_video(entries: list[VideoFormat]) -> VideoFormat:
    """Pick the most useful representative of a (height, ext) group."""

    def score(fmt: VideoFormat):
        return (
            1 if fmt.has_audio else 0,
            fmt.filesize or fmt.filesize_approx or 0,
            fmt.fps or 0,
        )

    return max(entries, key=score)


def _video_choices(formats: list[VideoFormat], has_audio_only: bool) -> list[FormatChoice]:
    videos = [f for f in formats if f.has_video]
    if not videos:
        return []

    sized = [f for f in videos if f.height]
    if not sized:
        # A plain HLS media playlist may carry no resolution at all. Offer the
        # best stream rather than hiding video entirely (flow.md #39).
        rep = _best_video(videos)
        if rep.has_audio:
            expression, needs_ffmpeg = rep.format_id, False
        elif has_audio_only:
            expression, needs_ffmpeg = f"{rep.format_id}+bestaudio/{rep.format_id}", True
        else:
            expression, needs_ffmpeg = rep.format_id, False

        return [FormatChoice(
            group=GROUP_VIDEO,
            label="Best",
            type=VIDEO,
            format_id=expression,
            output_ext="mp4",
            needs_ffmpeg=needs_ffmpeg,
            filesize=rep.filesize or rep.filesize_approx,
        )]

    groups: dict[tuple[int, str], list[VideoFormat]] = {}
    for fmt in sized:
        groups.setdefault((int(fmt.height), fmt.ext or "mp4"), []).append(fmt)

    heights_with_multiple_exts = set()
    by_height: dict[int, set[str]] = {}
    for height, ext in groups:
        by_height.setdefault(height, set()).add(ext)
    for height, exts in by_height.items():
        if len(exts) > 1:
            heights_with_multiple_exts.add(height)

    choices: list[FormatChoice] = []
    for (height, ext) in sorted(groups, key=lambda k: (k[0], k[1])):
        rep = _best_video(groups[(height, ext)])

        # Progressive (video+audio in one stream) downloads directly; a
        # video-only stream must be paired with the best audio and merged.
        if rep.has_audio:
            expression = rep.format_id
            needs_ffmpeg = False
        elif has_audio_only:
            expression = f"{rep.format_id}+bestaudio/{rep.format_id}"
            needs_ffmpeg = True
        else:
            expression = rep.format_id
            needs_ffmpeg = False

        label = f"{height}p"
        if height in heights_with_multiple_exts:
            label = f"{height}p ({ext})"

        size = rep.filesize or rep.filesize_approx
        choices.append(
            FormatChoice(
                group=GROUP_VIDEO,
                label=label,
                type=VIDEO,
                format_id=expression,
                output_ext="mp4",
                height=height,
                needs_ffmpeg=needs_ffmpeg,
                filesize=size,
            )
        )

    return choices


def _audio_choices(config: dict, ffmpeg_available: bool, has_audio: bool) -> list[FormatChoice]:
    if not has_audio:
        return []

    # MP3 is an output format: it always requires FFmpeg conversion, so it is
    # only offered when FFmpeg is actually present (flow.md #10, #44).
    if not ffmpeg_available:
        return []

    bitrates = config.get("default_audio_bitrates") or list(DEFAULT_AUDIO_BITRATES)
    choices: list[FormatChoice] = []
    for bitrate in sorted({int(b) for b in bitrates}):
        choices.append(
            FormatChoice(
                group=GROUP_AUDIO,
                label=f"{bitrate}kbps",
                type=AUDIO,
                format_id="bestaudio/best",
                output_ext="mp3",
                bitrate=bitrate,
                needs_ffmpeg=True,
            )
        )
    return choices


def build_choices(
    formats: list[VideoFormat],
    config: dict | None = None,
    ffmpeg_available: bool = True,
    source_url: str | None = None,
) -> list[FormatChoice]:
    """Build the selectable format choices from normalized formats."""
    config = config or {}
    has_audio = any(f.has_audio for f in formats)

    choices = _video_choices(formats, has_audio)
    choices.extend(_audio_choices(config, ffmpeg_available, has_audio))

    if source_url:
        for choice in choices:
            choice.source_url = source_url

    return choices


def _parse_video_quality(value) -> int:
    """'720p' / '720' -> 720. Falls back to 720."""
    if isinstance(value, int):
        return value
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return int(digits) if digits else 720


def _parse_bitrate(value) -> int:
    """'128k' / '128' -> 128. Falls back to 128."""
    if isinstance(value, int):
        return value
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return int(digits) if digits else 128


def select_audio_format(
    choices: list[FormatChoice],
    config: dict | None = None,
) -> Optional[FormatChoice]:
    """Pick the MP3 choice (configured bitrate, else the closest), or None.

    Used by "Auto convert to mp3": video formats are ignored, so None means
    the current URL offers no audio/MP3 output at all.
    """
    audios = [c for c in choices if c.type == AUDIO]
    if not audios:
        return None
    return select_default_format(audios, config)


def select_default_format(
    choices: list[FormatChoice],
    config: dict | None = None,
) -> Optional[FormatChoice]:
    """Pick the default radio selection.

    Policy (flow.md #14):
      1. configured preferred quality
      2. closest lower quality, else lowest higher one
      3. highest video
      4. audio

    Audio is only the default when the user asks for it (the "Auto convert to
    mp3" checkbox, via `select_audio_format`).
    """
    config = config or {}
    if not choices:
        return None

    videos = sorted([c for c in choices if c.type == VIDEO], key=lambda c: c.height or 0)
    audios = [c for c in choices if c.type == AUDIO]

    if videos:
        target = _parse_video_quality(config.get("default_video_quality", 720))
        for choice in videos:
            if choice.height == target:
                return choice
        lower = [c for c in videos if (c.height or 0) <= target]
        if lower:
            return lower[-1]
        return videos[0]

    if audios:
        target = _parse_bitrate(config.get("default_audio_bitrate", 128))
        exact = [c for c in audios if c.bitrate == target]
        if exact:
            return exact[0]
        ordered = sorted(audios, key=lambda c: c.bitrate or 0)
        lower = [c for c in ordered if (c.bitrate or 0) <= target]
        return lower[-1] if lower else ordered[0]

    return choices[0]
