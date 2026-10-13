import asyncio
import os
import platform
import subprocess
import sys
from pathlib import Path

from qasync import asyncSlot

from PyQt6.QtGui import QAction, QCursor, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import QSettings, QTimer, Qt, QEvent

from gui.panels.ui_left import LeftPanel
from gui.panels.ui_right import RightPanel
from gui.dialogs.about_dialog import AboutDialog
from gui.dialogs.restore_dialog import RestoreDialog
from gui.dialogs.session_dialog import SessionDialog
from gui.dialogs.setting_dialog import SettingDialog
from gui.dialogs.version_dialog import VersionDialog
from gui.dialogs.import_result_dialog import ImportResultDialog
from gui.common.cursor_utils import apply_pointer_cursors
from gui.common.theme import THEMES, apply_theme, current_theme
from gui.panels.video_preview import fetch_thumbnail_bytes
from core.logger import logger
from core.i18n import tr, add_listener, get_lang, set_lang
from core.format_selector import build_choices, select_audio_format, select_default_format
from core.job_manager import STATUS_DONE, Job
from core.errors import ApplicationError
from core.updater.installer import spawn_updater
from core.utils import CONFIG, save_config


class MainWindow(QWidget):

    def __init__(self, engine):
        super().__init__()

        base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
        icon_path = base / "assets" / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        logger.info("GUI INIT OK")

        self.engine = engine
        self.settings = QSettings("VideoDownloadTool", "VideoDownloadTool")

        set_lang(CONFIG.get("language", "vi"))

        self.setWindowTitle(tr("app_title"))
        self.resize(900, 650)
        screen = self.screen().availableGeometry()
        window = self.frameGeometry()
        window.moveCenter(screen.center())
        self.move(window.topLeft())

        self._video_info = None
        self._choices = []
        self._pending_update = None
        self._closing = False
        self._shutdown_cancelled = False
        self._shutdown_seconds_left = 0

        self.init_ui()
        self._update_buttons()
        self._update_session_label()

    # =========================
    # UI SETUP
    # =========================
    def init_ui(self):
        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_menu_bar())

        layout = QHBoxLayout()

        self.left = LeftPanel(self.settings)
        self.right = RightPanel()

        layout.addWidget(self.left, 3)
        layout.addWidget(self.right, 3)
        root.addLayout(layout)
        self.setLayout(root)

        self.left.btn_paste.clicked.connect(self.on_paste_url)
        self.left.btn_add.clicked.connect(self.add_queue)
        self.left.auto_mp3_cb.toggled.connect(self._on_auto_mp3_toggled)

        self.right.btn_start.clicked.connect(self.start_engine)
        self.right.btn_resume.clicked.connect(self.toggle_resume_engine)
        self.right.btn_pause.clicked.connect(self.toggle_pause_engine)
        self.right.deleteRequested.connect(self.delete_job)
        self.engine.progress.connect(self.right.update_progress)
        self.engine.finished.connect(self._update_buttons)
        self.engine.finished.connect(self._on_engine_finished)

        self._apply_cursors()
        add_listener(self._retranslate)

        QTimer.singleShot(100, self._start_restore)

    # =========================
    # MENU BAR
    # =========================
    def _build_menu_bar(self) -> QMenuBar:
        bar = QMenuBar()
        self.menu = bar.addMenu(tr("menu_title"))

        self.act_import = QAction(tr("import_links"), self)
        self.act_import.setShortcut("Ctrl+I")
        self.act_import.triggered.connect(self.import_links)
        self.menu.addAction(self.act_import)

        self.act_export = QAction(tr("export_links"), self)
        self.act_export.setShortcut("Ctrl+P")
        self.act_export.triggered.connect(self.export_links)
        self.menu.addAction(self.act_export)

        self.menu.addSeparator()

        self.menu_sessions = self.menu.addMenu(tr("sessions_title"))

        self.act_session_new = QAction(tr("session_new"), self)
        self.act_session_new.setShortcut("Ctrl+N")
        self.act_session_new.triggered.connect(self._on_session_new)
        self.menu_sessions.addAction(self.act_session_new)

        # Filled on demand so it always reflects the stored sessions.
        self.menu_session_list = self.menu_sessions.addMenu(tr("session_list"))
        self.menu_session_list.aboutToShow.connect(self._populate_session_menu)

        self.act_session_manage = QAction(tr("session_manage"), self)
        self.act_session_manage.setShortcut("Ctrl+M")
        self.act_session_manage.triggered.connect(self.open_sessions)
        self.menu_sessions.addAction(self.act_session_manage)

        self.menu_language = self.menu.addMenu(tr("language_label"))
        self.act_lang = {}
        for code in ("vi", "en"):
            action = QAction(tr(f"lang_{code}"), self)
            action.setCheckable(True)
            action.triggered.connect(lambda _checked=False, c=code: self._set_language(c))
            self.menu_language.addAction(action)
            self.act_lang[code] = action
        self._sync_language_checks()

        self.menu_theme = self.menu.addMenu(tr("theme"))
        self.act_theme = {}
        for name in THEMES:
            action = QAction(tr(f"theme_{name}"), self)
            action.setCheckable(True)
            action.triggered.connect(lambda _checked=False, n=name: self._set_theme(n))
            self.menu_theme.addAction(action)
            self.act_theme[name] = action
        self._sync_theme_checks()

        self.menu.addSeparator()

        self.act_settings = QAction(tr("settings"), self)
        self.act_settings.setShortcut("Ctrl+S")
        self.act_settings.triggered.connect(self.open_settings)
        self.menu.addAction(self.act_settings)

        self.act_about = QAction(tr("about"), self)
        self.act_about.triggered.connect(self.open_about)
        self.menu.addAction(self.act_about)

        self.menu.addSeparator()

        self.act_quit = QAction(tr("quit"), self)
        self.act_quit.setShortcut("Ctrl+Q")
        self.act_quit.triggered.connect(self.close)
        self.menu.addAction(self.act_quit)

        return bar

    # =========================
    # IMPORT / EXPORT LINKS
    # =========================
    @asyncSlot()
    async def import_links(self):
        path, _ = QFileDialog.getOpenFileName(
            self, tr("file_pick_title"), "", f"{tr('all_files')} (*)"
        )
        if path:
            await self.add_jobs_from_file(path)

    def export_links(self):
        urls = self.right.queue_urls()
        if not urls:
            self._show_message(tr("notify"), tr("export_empty"))
            return

        path, _ = QFileDialog.getSaveFileName(
            self, tr("export_dialog_title"), "export_queue_link.txt", f"{tr('all_files')} (*)"
        )

        if not path:
            return

        if Path(path).suffix.lower() != ".txt":
            path += ".txt"

        try:
            Path(path).write_text("\n".join(urls) + "\n", encoding="utf-8")
        except OSError as exc:
            self._show_message(
                tr("error"), tr("export_failed").format(error=exc), critical=True
            )
            return

        self._show_message(tr("notify"), tr("export_done").format(count=len(urls)))

    # =========================
    # LANGUAGE
    # =========================
    def _set_language(self, code: str):
        if code == get_lang():
            return
        CONFIG["language"] = code
        save_config(CONFIG)
        set_lang(code)
        self._sync_language_checks()

    def _sync_language_checks(self):
        for code, action in self.act_lang.items():
            action.setChecked(get_lang() == code)

    # =========================
    # THEME
    # =========================
    def _set_theme(self, name: str):
        if name == current_theme():
            return
        CONFIG["theme"] = name
        save_config(CONFIG)
        apply_theme(name)
        self._sync_theme_checks()
        # The queue rows are painted by hand, so they need a repaint to pick up
        # the new palette.
        self.right.queue_list.viewport().update()

    def _sync_theme_checks(self):
        for name, action in self.act_theme.items():
            action.setChecked(current_theme() == name)

    # =========================
    # SETTINGS / ABOUT
    # =========================
    def open_settings(self):
        SettingDialog(self, self.engine.network).exec()
        self._on_network_settings_changed()

    def open_about(self):
        AboutDialog(self, on_check_version=self.open_version).exec()

    def open_version(self):
        """Check for a new build; once one is staged, apply it and restart."""
        dialog = VersionDialog(self)
        dialog.exec()
        if dialog.staged_root is not None:
            self._pending_update = (dialog.staged_root, dialog.staged_version)
            asyncio.ensure_future(self._apply_pending_update())

    def _start_restore(self):
        # Ask first: only run restore_session when the user wants the previous
        # session back (feedback.md #4). Nothing to ask when there is nothing
        # to restore.
        if not self.engine.db.get_restorable_jobs():
            return

        box = QMessageBox(self)
        box.setWindowTitle(tr("session_restore_confirm_title"))
        box.setText(tr("session_restore_confirm_text"))
        box.setIcon(QMessageBox.Icon.Question)
        btn_yes = box.addButton(tr("yes"), QMessageBox.ButtonRole.YesRole)
        btn_no = box.addButton(tr("no"), QMessageBox.ButtonRole.NoRole)
        box.setDefaultButton(btn_yes)
        box.exec()

        if box.clickedButton() is not btn_yes:
            # Declining starts a fresh session; the previous one stays saved and
            # can be picked from the sessions dialog (feedback.md #2).
            info = self.engine.create_session()
            self.engine.activate_session(info.id, self._base_path())
            self.right.clear_queue()
            self._update_session_label()
            return

        self.restore_modal = RestoreDialog(self)
        self.restore_modal.show()
        QTimer.singleShot(0, self._run_restore)

    def _run_restore(self):
        task = asyncio.ensure_future(self._restore_session())
        task.add_done_callback(self._restore_finished)

    def _restore_finished(self, future):
        try:
            future.result()
        except Exception:
            logger.exception("Failed to restore session")
        finally:
            if getattr(self, "restore_modal", None):
                self.restore_modal.done(QDialog.DialogCode.Accepted)
                self.restore_modal.deleteLater()
                self.restore_modal = None

    def _retranslate(self):
        self.setWindowTitle(tr("app_title"))
        self.menu.setTitle(tr("menu_title"))
        self.act_import.setText(tr("import_links"))
        self.act_export.setText(tr("export_links"))
        self.menu_sessions.setTitle(tr("sessions_title"))
        self.act_session_new.setText(tr("session_new"))
        self.menu_session_list.setTitle(tr("session_list"))
        self.act_session_manage.setText(tr("session_manage"))
        self.menu_language.setTitle(tr("language_label"))
        for code, action in self.act_lang.items():
            action.setText(tr(f"lang_{code}"))
        self._sync_language_checks()
        self.menu_theme.setTitle(tr("theme"))
        for name, action in self.act_theme.items():
            action.setText(tr(f"theme_{name}"))
        self._sync_theme_checks()
        self.act_settings.setText(tr("settings"))
        self.act_about.setText(tr("about"))
        self.act_quit.setText(tr("quit"))
        self.left.retranslate()
        self.right.retranslate()
        self._update_buttons()

    def _apply_cursors(self):
        apply_pointer_cursors(self, event_filter=self)

    def eventFilter(self, obj, event):
        if isinstance(obj, QPushButton) and event.type() == QEvent.Type.EnabledChange:
            cursor = (
                QCursor(Qt.CursorShape.ForbiddenCursor)
                if not obj.isEnabled()
                else QCursor(Qt.CursorShape.PointingHandCursor)
            )
            obj.setCursor(cursor)
        return super().eventFilter(obj, event)

    # =========================
    # PASTE URL -> PREVIEW
    # =========================
    @asyncSlot()
    async def on_paste_url(self):
        new_url = QApplication.clipboard().text().strip()
        if not new_url:
            return

        if not new_url.startswith(("http://", "https://")):
            self._show_message(
                tr("error"),
                f"{tr('clipboard_invalid')}:\n{new_url[:100]}",
                critical=True,
            )
            return

        old_url = self.left.url_input.text().strip()

        # Auto add the current preview to the queue before replacing it.
        should_auto_queue = (
            self.left.auto_queue_cb.isChecked()
            and old_url
            and old_url != new_url
            and self.left.btn_add.isEnabled()
        )
        if should_auto_queue:
            await self.add_queue()

        self.left.url_input.setText(new_url)
        await self.load_video(new_url)

    # =========================
    # LOAD VIDEO PREVIEW
    # =========================
    @asyncSlot()
    async def load_video(self, url: str):
        if not url:
            return

        self.left.on_loading(True)
        loop = asyncio.get_running_loop()

        try:
            info = await loop.run_in_executor(None, self.engine.client.extract, url)
        except ApplicationError as exc:
            self.left.on_loading(False)
            self._show_message(tr("error"), f"{tr('preview_error')}:\n{exc}", critical=True)
            return
        except Exception as exc:
            self.left.on_loading(False)
            logger.error(f"Preview failed for {url}: {exc}", exc_info=True)
            self._show_message(tr("error"), f"{tr('preview_error')}:\n{exc}", critical=True)
            return

        choices = build_choices(
            info.formats,
            self.engine.config,
            ffmpeg_available=self.engine.ffmpeg_available(),
            source_url=info.source_url,
            duration=info.duration,
        )

        if info.is_live:
            self.left.on_loading(False)
            self._show_message(tr("notify"), tr("live_unsupported"))
            return
        elif not choices:
            self.left.on_loading(False)
            self._show_message(tr("notify"), tr("no_formats"))
            return

        self._choices = choices
        self._video_info = info
        default = self._preview_default_choice()

        thumbnail = None
        if info.thumbnail:
            thumbnail = await loop.run_in_executor(None, fetch_thumbnail_bytes, info.thumbnail)

        self.left.preview.set_video(info, choices, default=default, thumbnail=thumbnail)
        self.left.on_loading(False)
        self.left._update_add_button()

    def _preview_default_choice(self):
        """Default radio selection, honouring "Auto convert to mp3"."""
        if self.left.auto_mp3_cb.isChecked():
            mp3 = select_audio_format(self._choices, self.engine.config)
            if mp3 is not None:
                return mp3
        return select_default_format(self._choices, self.engine.config)

    def _add_choice(self):
        """Format used when adding: MP3 when auto-convert is on, else the radio."""
        if self.left.auto_mp3_cb.isChecked():
            mp3 = select_audio_format(self._choices, self.engine.config)
            if mp3 is not None:
                return mp3
        return self.left.preview.selected_choice()

    def _on_auto_mp3_toggled(self, checked):
        # Keep the preview's radio selection in step with the checkbox.
        if not self._choices:
            return
        choice = self._preview_default_choice()
        if choice is not None:
            self.left.preview.select_choice(choice)

    def _clear_preview(self):
        """Empty the preview (and the URL bar) once an add has been handled."""
        self._video_info = None
        self._choices = []
        self.left.url_input.clear()
        self.left.preview.clear()
        self.left._update_add_button()

    # =========================
    # ADD QUEUE
    # =========================
    @asyncSlot()
    async def add_queue(self):
        url = self.left.url_input.text().strip()
        base_path = self.left.path_input.text().strip()
        choice = self._add_choice()

        if not url or not self._video_info or choice is None or not base_path:
            return

        self.left.btn_add.setDisabled(True)
        try:
            job = Job(
                url=url,
                title=self._video_info.title,
                save_path=Path(base_path),
                selected_format=choice.to_dict(),
                thumbnail=self._video_info.thumbnail,
                extractor=self._video_info.extractor,
            )

            result = await self.engine.add_job(job)
            status = "Waiting" if self.engine.running else ""

            if result in ("queued", "resume"):
                self.right.update_queue_item(job, status)
            elif result == "already_running":
                self._show_message(tr("notify"), tr("already_running"))
            elif result == "already_queued":
                self._show_message(tr("notify"), tr("already_queued"))
            elif result == "already_downloaded":
                self._show_message(tr("notify"), tr("already_downloaded"))

            # The URL has been dealt with, so leave the preview empty for the
            # next link instead of showing the one just added.
            self._clear_preview()
            self._update_buttons()
        except Exception as exc:
            self._show_message(tr("error"), str(exc), critical=True)
        finally:
            self.left._update_add_button()

    # =========================
    # ADD JOBS FROM FILE
    # =========================
    @asyncSlot(str)
    async def add_jobs_from_file(self, path: str):
        base_path = self.left.path_input.text().strip()
        if not base_path:
            self._show_message(tr("path_warning_title"), tr("path_empty"), critical=True)
            return

        if not path or not os.path.exists(path):
            self._show_message(tr("error"), tr("import_error_read"), critical=True)
            return

        from core.utils import parse_link_file

        links, error_code, error_detail = parse_link_file(path)
        if error_code is not None:
            message = tr(f"import_error_{error_code}")
            if error_detail:
                message = f"{message}\n\n{error_detail}"
            self._show_message(tr("import_error_title"), message, critical=True)
            return

        from gui.dialogs.add_jobs_dialog import AddJobsDialog

        modal = AddJobsDialog(self)
        modal.set_progress(0, len(links))
        modal.show()
        await asyncio.sleep(0)

        loop = asyncio.get_running_loop()
        semaphore = asyncio.Semaphore(self.engine.max_workers)
        db_lock = asyncio.Lock()
        ffmpeg = self.engine.ffmpeg_available()
        auto_mp3 = self.left.auto_mp3_cb.isChecked()
        reason_extract = tr("import_reason_extract")
        reason_no_format = tr("import_reason_no_format")
        state = {"completed": 0, "success": [], "live": [], "duplicate": [], "error": []}

        async def process(url):
            try:
                async with semaphore:
                    info = await loop.run_in_executor(None, self.engine.client.extract, url)
            except Exception as exc:
                logger.error(f"[add_from_file] Skipped {url}: {exc}")
                info = None
                state["error"].append({"title": "", "url": url, "reason": reason_extract})

            if info is not None and info.is_live:
                # Live streams are recognized but not downloadable yet.
                state["live"].append({"title": info.title, "url": url})
                info = None

            if info is not None:
                choices = build_choices(
                    info.formats, self.engine.config, ffmpeg_available=ffmpeg,
                    source_url=info.source_url, duration=info.duration,
                )
                choice = select_default_format(choices, self.engine.config)
                if auto_mp3:
                    choice = select_audio_format(choices, self.engine.config) or choice
                if choice is None:
                    state["error"].append(
                        {"title": info.title, "url": url, "reason": reason_no_format}
                    )
                else:
                    job = Job(
                        url=url,
                        title=info.title,
                        save_path=Path(base_path),
                        selected_format=choice.to_dict(),
                        thumbnail=info.thumbnail,
                        extractor=info.extractor,
                    )
                    async with db_lock:
                        result = await self.engine.add_job(job)
                        status = "Waiting" if self.engine.running else ""
                        if result in ("queued", "resume"):
                            self.right.update_queue_item(job, status)
                            state["success"].append({"title": info.title, "url": url})
                        else:
                            state["duplicate"].append({"title": info.title, "url": url})

            state["completed"] += 1
            modal.set_progress(state["completed"], len(links))
            if state["completed"] % 5 == 0:
                await asyncio.sleep(0)

        try:
            await asyncio.gather(*(process(url) for url in links))
        finally:
            modal.close()
            modal.deleteLater()

        self._update_buttons()
        result = {"file": Path(path).name, "total": len(links), **state}
        ImportResultDialog(result, self).exec()

    # =========================
    # NON-MODAL MESSAGE BOX
    # =========================
    def _show_message(self, title, text, critical=False):
        # While a modal dialog is open (e.g. the sessions manager), a box
        # parented to the main window would be hidden behind it, so attach to
        # the modal instead.
        parent = QApplication.activeModalWidget() or self
        box = QMessageBox(parent)
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(QMessageBox.Icon.Critical if critical else QMessageBox.Icon.Information)
        box.setModal(False)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        if not hasattr(self, "_active_message_boxes"):
            self._active_message_boxes = []
        self._active_message_boxes.append(box)
        box.finished.connect(lambda _: self._active_message_boxes.remove(box))
        box.show()

    # =========================
    # CHECK SAVE PATH
    # =========================
    def _check_save_path_exists(self) -> bool:
        path_str = self.left.path_input.text().strip()
        if not path_str:
            QMessageBox.warning(self, tr("path_warning_title"), tr("path_empty"))
            return False

        path = Path(path_str)
        if not path.is_absolute():
            QMessageBox.warning(
                self, tr("path_invalid_title"), f"{tr('path_invalid')}:\n{path}"
            )
            return False
        if not path.exists():
            QMessageBox.warning(
                self, tr("path_not_found_title"), f"{tr('path_not_found')}:\n{path}"
            )
            return False
        return True

    # =========================
    # SESSION RESTORE
    # =========================
    @asyncSlot()
    async def _restore_session(self):
        base_path = self.left.path_input.text().strip()

        self.right.clear_queue()
        queue = self.right.queue_list
        queue.setUpdatesEnabled(False)
        try:
            async for current, total, job in self.engine.restore_session(base_path):
                self.right.update_queue_item(job, "Waiting")
                if getattr(self, "restore_modal", None):
                    self.restore_modal.set_progress(current, total)
                if current % 10 == 0:
                    await asyncio.sleep(0)
        finally:
            queue.setUpdatesEnabled(True)
            queue.viewport().update()

        self._update_buttons()

    # =========================
    # SESSIONS
    # =========================
    def _base_path(self) -> str | None:
        return self.left.path_input.text().strip() or None

    def _update_session_label(self):
        info = self.engine.current_session()
        self.left.set_session_name(info.name if info else "")

    def _populate_queue(self, jobs):
        """Fill the queue for a session that is being switched to.

        Jobs that are already done stay in the session's database (so the same
        link is still recognised as downloaded) but are left out of the queue.
        """
        for job in jobs:
            if job.status == STATUS_DONE:
                continue
            self.right.update_queue_item(job, "Waiting")

    def open_sessions(self):
        dialog = SessionDialog(self.engine, self)
        dialog.newRequested.connect(self._on_session_new)
        dialog.selectRequested.connect(self._on_session_select)
        dialog.removeRequested.connect(self._on_session_remove)
        dialog.removeAllRequested.connect(self._on_session_remove_all)
        dialog.exec()
        # Renames / switches happen inside the dialog, so resync the label.
        self._update_session_label()
        self._update_buttons()

    def _populate_session_menu(self):
        """List the stored sessions by name; picking one switches to it."""
        self.menu_session_list.clear()
        current = self.engine.session_id
        for session in self.engine.list_sessions():
            action = self.menu_session_list.addAction(session.name)
            action.setCheckable(True)
            action.setChecked(session.id == current)
            action.setEnabled(session.id != current)
            action.triggered.connect(
                lambda _checked=False, sid=session.id: self._on_session_select(sid)
            )

    async def _stop_for_session_change(self):
        """Selecting/removing a session must not fight an active download."""
        if self.engine.running:
            await self.engine.stop()

    @asyncSlot()
    async def _on_session_new(self):
        """Start a fresh empty session; the previous one stays saved."""
        await self._stop_for_session_change()
        info = self.engine.create_session()
        self.engine.activate_session(info.id, self._base_path())
        self.right.clear_queue()
        self._update_session_label()
        self._update_buttons()

    @asyncSlot(str)
    async def _on_session_select(self, session_id):
        await self._stop_for_session_change()
        self.right.clear_queue()
        jobs = self.engine.activate_session(session_id, self._base_path())
        self._populate_queue(jobs)
        self._update_session_label()
        self._update_buttons()

    @asyncSlot(str)
    async def _on_session_remove(self, session_id):
        await self._stop_for_session_change()
        was_current = session_id == self.engine.session_id
        new_current = self.engine.delete_session(session_id)
        if was_current:
            self.right.clear_queue()
            jobs = self.engine.activate_session(new_current, self._base_path())
            self._populate_queue(jobs)
        self._update_session_label()
        self._update_buttons()

    @asyncSlot()
    async def _on_session_remove_all(self):
        await self._stop_for_session_change()
        self.engine.delete_all_sessions()
        self.right.clear_queue()
        self._update_session_label()
        self._update_buttons()

    @asyncSlot()
    async def start_engine(self):
        if self.engine.running:
            return
        if self.right.queue_list.count() == 0:
            self._show_message(tr("notify"), tr("queue_empty"))
            return
        if not self._check_save_path_exists():
            return
        self.right.set_all_status("Waiting")
        await self.engine.sync_paths(self.left.path_input.text().strip())
        await self.engine.start()
        self._update_buttons()

    @asyncSlot()
    async def toggle_pause_engine(self):
        if self.engine.running:
            await self.engine.stop()
            self.right.set_all_status("Paused")
        self._update_buttons()

    @asyncSlot()
    async def toggle_resume_engine(self):
        if not self.engine.running:
            if self.right.queue_list.count() == 0:
                return
            if not self._check_save_path_exists():
                return
            self.right.set_all_status("Waiting")
            await self.engine.sync_paths(self.left.path_input.text().strip())
            await self.engine.start()
        self._update_buttons()

    def _update_buttons(self):
        can_resume = self.right.has_status("Paused")
        if self.engine.running:
            self.right.btn_resume.setEnabled(False)
            self.right.btn_pause.setEnabled(True)
        elif can_resume:
            self.right.btn_resume.setEnabled(True)
            self.right.btn_pause.setEnabled(False)
        else:
            self.right.btn_resume.setEnabled(False)
            self.right.btn_pause.setEnabled(False)

    # =========================
    # DELETE JOB (TRASH ICON)
    # =========================
    @asyncSlot(str)
    async def delete_job(self, key: str):
        try:
            await self.engine.del_job(key)
            self.right.remove_queue_item(key)
            self._update_buttons()
        except Exception as exc:
            logger.error(f"Failed to delete job {key}: {exc}", exc_info=True)
            self._show_message(tr("error"), tr("delete_failed"), critical=True)

    # =========================
    # AUTO SHUTDOWN
    # =========================
    def _on_engine_finished(self):
        if not self.left.shutdown_cb.isChecked():
            return
        if not self.right.all_finished():
            return
        self._confirm_shutdown()

    def _confirm_shutdown(self):
        self._shutdown_cancelled = False
        self._shutdown_seconds_left = self.left.shutdown_delay_seconds

        box = QMessageBox(self)
        box.setWindowTitle(tr("shutdown_confirm_title"))
        box.setIcon(QMessageBox.Icon.Warning)
        box.setModal(False)

        def _update_text():
            box.setText(
                f"{tr('shutdown_confirm_text')}\n\n"
                f"{tr('shutdown_countdown')} {self._shutdown_seconds_left}s"
            )

        _update_text()

        btn_cancel = box.addButton(tr("cancel"), QMessageBox.ButtonRole.RejectRole)
        btn_now = box.addButton(tr("shutdown_now"), QMessageBox.ButtonRole.AcceptRole)
        box.setDefaultButton(btn_cancel)

        timer = QTimer(self)
        timer.setInterval(1000)

        def _tick():
            self._shutdown_seconds_left -= 1
            if self._shutdown_seconds_left <= 0:
                timer.stop()
                box.done(0)
                if not self._shutdown_cancelled:
                    self._shutdown_system()
                return
            _update_text()

        timer.timeout.connect(_tick)
        timer.start()

        def _on_clicked(btn):
            if btn is btn_cancel:
                self._shutdown_cancelled = True
                timer.stop()
            elif btn is btn_now:
                timer.stop()
                box.done(0)
                self._shutdown_system()

        box.buttonClicked.connect(_on_clicked)
        box.show()

    def _shutdown_system(self):
        system = platform.system()
        logger.info(f"Auto-shutdown triggered on {system} after all downloads finished")

        try:
            if system == "Windows":
                subprocess.run(["shutdown", "/s", "/t", "5"], check=False)
            elif system == "Linux":
                try:
                    subprocess.run(["systemctl", "poweroff"], check=True)
                except Exception:
                    subprocess.run(["shutdown", "-h", "now"], check=False)
            elif system == "Darwin":
                subprocess.run(
                    ["osascript", "-e", 'tell app "System Events" to shut down'],
                    check=False,
                )
            else:
                logger.warning(f"Unsupported OS for auto-shutdown: {system}")
        except Exception:
            logger.exception("Failed to shut down the system")
            self._show_message(tr("error"), tr("shutdown_failed"), critical=True)

    # =========================
    # NETWORK FALLBACK SETTINGS
    # =========================
    def _on_network_settings_changed(self):
        """The Settings dialog may have toggled the fallback; apply it now."""
        self.engine.apply_network_settings()

    # =========================
    # APPLY A STAGED UPDATE
    # =========================
    async def _apply_pending_update(self):
        """Stop the engine, hand the swap to the updater, then exit.

        The staged build is already downloaded and verified; the updater waits
        for this process to end before replacing any file.
        """
        pending, self._pending_update = self._pending_update, None
        if not pending:
            return

        source, version = pending
        self._closing = True

        try:
            if self.engine.running:
                await self.engine.stop()
        except Exception:
            logger.exception("Failed to stop the engine before updating")

        try:
            spawn_updater(source, version)
        except Exception as exc:
            logger.exception("Failed to start the updater")
            self._closing = False
            self._show_message(
                tr("error"), tr("update_failed").format(error=exc), critical=True
            )
            return

        QApplication.instance().quit()

    # =========================
    # CLOSE EVENT CONFIRMATION
    # =========================
    def closeEvent(self, event):
        if self._closing:
            event.accept()
            return

        # Jobs are saved to the current session's file as they are added, so
        # there is nothing to save on exit -- only the exit confirmation.
        msg = tr("close_confirm_running") if self.engine.running else tr("close_confirm_idle")

        box = QMessageBox(self)
        box.setWindowTitle(tr("close_confirm_title"))
        box.setText(msg)
        box.setIcon(QMessageBox.Icon.Question)

        btn_yes = box.addButton(tr("yes"), QMessageBox.ButtonRole.YesRole)
        btn_no = box.addButton(tr("no"), QMessageBox.ButtonRole.NoRole)
        box.setDefaultButton(btn_no)
        box.exec()

        if box.clickedButton() != btn_yes:
            event.ignore()
            return

        event.ignore()
        asyncio.ensure_future(self._shutdown())

    async def _shutdown(self):
        try:
            if self.engine.running:
                await self.engine.stop()
        except Exception:
            logger.exception("Failed to stop engine")
        finally:
            self._closing = True
            self.close()
