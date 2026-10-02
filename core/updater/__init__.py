"""
core/updater

Checks GitHub Releases for a newer build, downloads it, verifies it, and hands
the actual replacement over to the standalone updater process. The GUI only
talks to this package, never to the GitHub API directly.
"""

# Staging area, inside the app folder. A prepared package is downloaded and
# extracted under `.update/<version>/`; the updater process reads the extracted
# app from there and the running app removes the whole folder on next startup.
UPDATE_DIR_NAME = ".update"
