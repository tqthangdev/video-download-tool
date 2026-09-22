"""Simple localization: supports vi/en, with a callback mechanism when the language changes."""

TRANSLATIONS = {
    "vi": {
        # Common
        "app_title": "Video Download Tool",
        "paste": "Dán",
        "folder": "Thư mục",
        "settings": "Cài đặt",
        "mode": "Mode:",
        "mode_manual": "Thủ công",
        "mode_auto": "Tự động",
        "add_queue": "Thêm vào danh sách",
        "about": "Giới thiệu",
        "about_title": "Giới thiệu",
        "about_desc": "Tải video/âm thanh về máy bằng yt-dlp.\nDán link, xem trước thông tin, chọn định dạng (MP4/MP3) rồi thêm vào danh sách để tải.\n\nMã nguồn: https://github.com/tqthangdev/video-download-tool",
        "start": "Bắt đầu",
        "pause": "Tạm dừng",
        "resume": "Tiếp tục",
        "clear_done": "Xóa mục đã xong",
        "queue": "Danh sách",
        "queue_with_count": "Danh sách có {count} mục",
        "auto_queue": "Tự động thêm vào danh sách",
        "shutdown_after_done": "Tắt máy khi xong trong",
        "language_label": "Ngôn ngữ",
        "lang_vi": "Tiếng Việt",
        "lang_en": "English",
        # Preview
        "duration_label": "Thời lượng",
        "uploader_label": "Kênh",
        "formats_label": "Định dạng",
        "no_formats": "Không tìm thấy định dạng nào phù hợp cho video này.",
        "loading_preview": "Đang tải thông tin video...",
        # Notifications
        "preview_error": "Không thể tải thông tin video",
        "clipboard_invalid": "Clipboard không chứa link hợp lệ",
        "already_running": "Mục này đang được tải.",
        "already_queued": "Mục này đã có trong danh sách.",
        "already_downloaded": "Mục này đã tải xong trước đó.",
        "delete_failed": "Không thể xóa mục khỏi danh sách.",
        "queue_empty": "Danh sách trống! Hãy thêm mục vào danh sách trước khi bắt đầu.",
        "notify": "Thông báo",
        "error": "Lỗi",
        # Paths
        "path_warning_title": "Cảnh báo đường dẫn",
        "path_empty": "Chưa nhập đường dẫn lưu trữ! Vui lòng chọn thư mục trước khi bắt đầu.",
        "path_invalid_title": "Đường dẫn không hợp lệ",
        "path_invalid": "Đường dẫn lưu trữ phải là thư mục tuyệt đối",
        "path_not_found_title": "Thư mục không tồn tại",
        "path_not_found": "Đường dẫn lưu trữ không tồn tại",
        "pick_folder_title": "Chọn thư mục",
        "url_placeholder": "Dán link video cần tải...",
        "path_placeholder": "Đường dẫn lưu...",
        "file_placeholder": "Chọn file chứa danh sách link...",
        "file_pick": "Chọn file",
        "file_pick_title": "Chọn file chứa danh sách link",
        "file_empty": "Chưa chọn file! Vui lòng chọn file trước.",
        "all_files": "Tất cả tệp",
        "import_error_title": "Lỗi nhập tệp",
        "import_error_not_text": "Không thể đọc tệp này dưới dạng văn bản.",
        "import_error_read": "Không thể mở tệp đã chọn.",
        "import_error_empty": "Tệp không chứa liên kết nào hợp lệ.",
        "import_error_invalid": "Một số dòng trong tệp không phải là liên kết http(s) hợp lệ:",
        "import_error_too_large": "Tệp quá lớn (giới hạn 5MB) để là danh sách liên kết.",
        "import_error_binary": "Tệp này là tệp nhị phân (chương trình/lưu trữ/media...), không phải danh sách liên kết dạng văn bản.",
        "adding_jobs_title": "Đang thêm mục",
        "adding_jobs_text": "Đang thêm mục... {current}/{total}",
        "adding_jobs_done": "Đã thêm {added} mục vào danh sách.",
        "close_confirm_title": "Xác nhận thoát",
        "close_confirm_running": "Tiến trình tải đang chạy. Bạn có chắc chắn muốn thoát ứng dụng không?",
        "close_confirm_idle": "Bạn có chắc chắn muốn thoát ứng dụng không?",
        "yes": "Có",
        "no": "Không",
        # Auto shutdown
        "shutdown_confirm_title": "Xác nhận tắt máy",
        "shutdown_confirm_text": "Tất cả mục trong hàng đợi đã tải xong.",
        "shutdown_countdown": "Máy sẽ tắt sau",
        "shutdown_now": "Tắt ngay",
        "shutdown_failed": "Không thể tắt máy tự động.",
        "shutdown_seconds": "giây",
        "shutdown_delay_hint": "Số giây đếm ngược trước khi máy tự tắt sau khi tải xong (từ khi hộp thoại xác nhận hiện ra).",
        # Settings dialog
        "settings_title": "Cài đặt",
        "settings_help_title": "Chi tiết tùy chọn",
        "apply": "Áp dụng",
        "cancel": "Hủy",
        "ok": "OK",
        "save_error": "Không thể ghi config.json. Kiểm tra quyền thư mục.",
        # Settings fields
        "field_max_workers": "Số mục tải song song (worker)",
        "field_max_workers_desc": "Số mục được tải cùng lúc.\n\nKhuyến nghị: 3. Đặt quá cao khiến máy lag và dễ bị website chặn.",
        "field_download_path": "Thư mục tải mặc định",
        "field_download_path_desc": "Thư mục mặc định để lưu file tải về.\n\nBạn vẫn có thể đổi thư mục ở màn hình chính.",
        "field_video_quality": "Chất lượng video mặc định",
        "field_video_quality_desc": "Chất lượng video được chọn sẵn khi thêm từ file (chọn trong danh sách).\n\nNếu video không có đúng chất lượng này, app chọn mức gần nhất.",
        "field_audio_bitrate": "Bitrate audio mặc định",
        "field_audio_bitrate_desc": "Bitrate MP3 được chọn sẵn khi thêm từ file (chọn trong danh sách).",
        "field_prefer": "Ưu tiên định dạng",
        "field_prefer_desc": "Khi thêm từ file: ưu tiên chọn video hay audio làm mặc định.\n\nChọn trong danh sách: Video hoặc Audio.",
        "prefer_video": "Video",
        "prefer_audio": "Audio",
        "field_gemini_api": "Gemini API key",
        "field_gemini_api_desc": "Dán API key của Google Gemini để tự động rút ngắn tiêu đề video quá dài (trên 100 ký tự).\n\nĐể trống nếu không dùng — app giữ nguyên tiêu đề như trước.\n\nLấy key tại: https://aistudio.google.com/app/apikey",
        # Queue status
    },
    "en": {
        # Common
        "app_title": "Video Download Tool",
        "paste": "Paste",
        "folder": "Folder",
        "settings": "Settings",
        "mode": "Mode:",
        "mode_manual": "Manual",
        "mode_auto": "Auto",
        "add_queue": "Add Queue",
        "about": "About",
        "about_title": "About",
        "about_desc": "Download video/audio with yt-dlp.\nPaste a link, preview its info, pick a format (MP4/MP3) and add it to the queue to download.\n\nSource: https://github.com/tqthangdev/video-download-tool",
        "start": "Start",
        "pause": "Pause",
        "resume": "Resume",
        "clear_done": "Clear Done",
        "queue": "Queue",
        "queue_with_count": "Queue has {count} item(s)",
        "auto_queue": "Automatically add to queue",
        "shutdown_after_done": "Shutdown when done in",
        "language_label": "Language",
        "lang_vi": "Tiếng Việt",
        "lang_en": "English",
        # Preview
        "duration_label": "Duration",
        "uploader_label": "Uploader",
        "formats_label": "Formats",
        "no_formats": "No supported format was found for this video.",
        "loading_preview": "Loading video info...",
        # Notifications
        "preview_error": "Failed to load video information",
        "clipboard_invalid": "Clipboard does not contain a valid URL",
        "already_running": "This item is already downloading.",
        "already_queued": "This item is already in the queue.",
        "already_downloaded": "This item was already downloaded.",
        "delete_failed": "Failed to remove item from the queue.",
        "queue_empty": "Queue is empty! Add an item to the queue before starting.",
        "notify": "Notification",
        "error": "Error",
        # Paths
        "path_warning_title": "Save path warning",
        "path_empty": "No save path entered! Please choose a folder before starting.",
        "path_invalid_title": "Invalid path",
        "path_invalid": "Save path must be an absolute directory",
        "path_not_found_title": "Directory does not exist",
        "path_not_found": "Save path does not exist",
        "pick_folder_title": "Choose folder",
        "url_placeholder": "Paste video link...",
        "path_placeholder": "Save path...",
        "file_placeholder": "Choose a file containing a list of links...",
        "file_pick": "Choose file",
        "file_pick_title": "Choose a file containing a list of links",
        "file_empty": "No file selected! Please choose a file first.",
        "all_files": "All files",
        "import_error_title": "Import error",
        "import_error_not_text": "This file could not be read as text.",
        "import_error_read": "Could not open the selected file.",
        "import_error_empty": "The file does not contain any valid links.",
        "import_error_invalid": "Some lines in the file are not valid http(s) links:",
        "import_error_too_large": "The file is too large (5MB limit) to be a link list.",
        "import_error_binary": "This is a binary file (program/archive/media/...), not a plain-text link list.",
        "adding_jobs_title": "Adding items",
        "adding_jobs_text": "Adding items... {current}/{total}",
        "adding_jobs_done": "Added {added} item(s) to the queue.",
        "close_confirm_title": "Confirm exit",
        "close_confirm_running": "Download is in progress. Are you sure you want to exit?",
        "close_confirm_idle": "Are you sure you want to exit?",
        "yes": "Yes",
        "no": "No",
        # Auto shutdown
        "shutdown_confirm_title": "Confirm shutdown",
        "shutdown_confirm_text": "All queued downloads finished.",
        "shutdown_countdown": "Shutting down in",
        "shutdown_now": "Shut down now",
        "shutdown_failed": "Auto shutdown failed.",
        "shutdown_seconds": "sec",
        "shutdown_delay_hint": "Countdown in seconds before the machine shuts down after downloads finish (from when the confirmation dialog appears).",
        # Settings dialog
        "settings_title": "Settings",
        "settings_help_title": "Option details",
        "apply": "Apply",
        "cancel": "Cancel",
        "ok": "OK",
        "save_error": "Failed to write config.json. Check folder permissions.",
        # Settings fields
        "field_max_workers": "Parallel downloads (workers)",
        "field_max_workers_desc": "How many items are downloaded at the same time.\n\nRecommended: 3. Setting it too high slows the machine down and may get blocked by websites.",
        "field_download_path": "Default download folder",
        "field_download_path_desc": "Default folder where downloads are saved.\n\nYou can still change the folder on the main screen.",
        "field_video_quality": "Default video quality",
        "field_video_quality_desc": "Pre-selected video quality when adding from a file (pick from the list).\n\nIf a video lacks that exact quality, the closest one is chosen.",
        "field_audio_bitrate": "Default audio bitrate",
        "field_audio_bitrate_desc": "Pre-selected MP3 bitrate when adding from a file (pick from the list).",
        "field_prefer": "Preferred format",
        "field_prefer_desc": "When adding from a file: prefer video or audio as the default selection.\n\nPick from the list: Video or Audio.",
        "prefer_video": "Video",
        "prefer_audio": "Audio",
        "field_gemini_api": "Gemini API key",
        "field_gemini_api_desc": "Paste a Google Gemini API key to automatically shorten video titles longer than 100 characters.\n\nLeave empty to disable it — titles are then kept as they are.\n\nGet a key at: https://aistudio.google.com/app/apikey",
        # Queue status
    },
}

# Current language
_lang = "vi"

# Listeners called when the language changes (so the UI can update itself)
_listeners = []


def tr(key: str) -> str:
    """Get the translated string for the current language."""
    return TRANSLATIONS.get(_lang, {}).get(key, key)


def get_lang() -> str:
    return _lang


def set_lang(lang: str):
    global _lang
    if lang not in TRANSLATIONS:
        lang = "vi"
    if lang == _lang:
        return
    _lang = lang
    for cb in list(_listeners):
        cb()


def add_listener(cb):
    _listeners.append(cb)


def remove_listener(cb):
    if cb in _listeners:
        _listeners.remove(cb)
