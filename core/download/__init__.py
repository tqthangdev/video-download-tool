"""
core.download

The yt-dlp pipeline: `ytdlp` wraps yt-dlp extraction into VideoInfo/format
choices and streams the download, `downloader` runs it for a single job and
verifies the output, and `format_selector` turns the raw formats into the
MP4/MP3 choices the UI presents.
"""
