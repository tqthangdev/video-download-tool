"""Tests for update staging details that only bite on POSIX."""

from __future__ import annotations

import os
import sys
import zipfile

from core.updater.installer import _restore_permissions, _updater_launcher


def _make_zip(path, mode):
    with zipfile.ZipFile(path, "w") as archive:
        info = zipfile.ZipInfo("VideoDownloadTool/VideoDownloadTool")
        info.external_attr = mode << 16
        archive.writestr(info, b"#!/bin/sh\necho hi\n")


def test_restore_permissions_sets_executable_bit(tmp_path):
    if os.name == "nt":
        return  # modes are not a thing there
    archive_path = tmp_path / "pkg.zip"
    _make_zip(archive_path, 0o100755)

    dest = tmp_path / "extracted"
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(dest)
        _restore_permissions(archive, dest)

    target = dest / "VideoDownloadTool" / "VideoDownloadTool"
    assert os.access(target, os.X_OK)


def test_updater_launcher_restores_missing_exec_bit(tmp_path):
    if os.name == "nt":
        return
    app = tmp_path / "extracted" / "VideoDownloadTool"
    app.mkdir(parents=True)
    exe = app / "VideoDownloadTool"
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(0o644)

    launcher = _updater_launcher(app)
    assert launcher == [str(exe)]
    assert os.access(exe, os.X_OK)


def test_updater_launcher_falls_back_to_interpreter(tmp_path):
    app = tmp_path / "source-checkout"
    app.mkdir()
    launcher = _updater_launcher(app)
    assert len(launcher) == 2
    assert launcher[0] == sys.executable
