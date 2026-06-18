import ctypes
import os
import sys

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QSystemTrayIcon,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .app_logging import setup_logging
from .audio_stream import AudioStream
from .config import Config
from .dictation_controller import DictationController
from .hotkeys import COPILOT_HOTKEY, HotkeyListener
from .i18n import friendly_error, is_rtl, tr

def get_asset_path(app_dir: str, filename: str) -> str:
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, "assets", filename)
    return os.path.join(app_dir, "assets", filename)
from .language_packs import LANGUAGE_PRESETS, get_pack
from .speech_presets import MODEL_PRESETS, language_codes, location_ids, model_ids


GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000

COPILOT_DISPLAY_SEQUENCE = "F23"
PUBLIC_LANGUAGE_PRESETS = [code for code in language_codes() if code != "he-IL"]


def _hotkey_editor_value(editor):
    sequence = editor.keySequence().toString().strip().lower()
    copilot_display_values = {"f23", "meta+shift+f23", "win+shift+f23"}
    if sequence in copilot_display_values:
        return COPILOT_HOTKEY
    if editor.property("hotkey_value") == COPILOT_HOTKEY:
        return COPILOT_HOTKEY
    return sequence or "f8"


def _set_hotkey_editor_value(editor, value):
    text = str(value or "").strip()
    editor.setProperty("hotkey_value", "")
    if text.lower() == COPILOT_HOTKEY:
        editor.setKeySequence(COPILOT_DISPLAY_SEQUENCE)
        editor.setProperty("hotkey_value", COPILOT_HOTKEY)
    else:
        editor.setKeySequence(text.title())


def _is_copilot_hotkey(value):
    text = str(value or "").lower()
    return text == COPILOT_HOTKEY or "f23" in text


def set_startup(enabled: bool):
    import winreg
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    key_name = "HebrewLiveDictation"
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
        if enabled:
            if sys.argv[0].endswith(".py"):
                executable = f'"{sys.executable}" "{os.path.abspath(sys.argv[0])}"'
            else:
                executable = f'"{os.path.abspath(sys.argv[0])}"'
            winreg.SetValueEx(key, key_name, 0, winreg.REG_SZ, executable)
        else:
            try:
                winreg.DeleteValue(key, key_name)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception as e:
        print(f"Failed to update Windows startup registry: {e}")


class WhisperDownloader(QObject):
    """Runs a local-model download off the GUI thread; emits (ok, message)."""

    finished = Signal(bool, str)

    def __init__(self, config, name):
        super().__init__()
        self.config = config
        self.name = name

    def run(self):
        try:
            from . import models

            path = models.download_model(self.config, self.name)
            self.finished.emit(True, str(path))
        except Exception as e:
            self.finished.emit(False, str(e))


class AppBridge(QObject):
    status_changed = Signal(str, str, str)
    text_changed = Signal(str, bool, str)
    error_occurred = Signal(str)
    command_executed = Signal(str, object)
    start_requested = Signal()
    stop_requested = Signal()
    quit_requested = Signal()


def clamp_position(x, y, w, h, screen):
    """Keep an (x, y, w, h) window inside a screen rect (sx, sy, sw, sh)."""
    sx, sy, sw, sh = screen
    x = max(sx, min(int(x), sx + sw - w))
    y = max(sy, min(int(y), sy + sh - h))
    return x, y


class FloatingToolbar(QWidget):
    """Draggable, always-on-top, no-focus-steal toolbar.

    Two modes: 'recording' (shows a Stop control while dictating) and 'idle' (a
    quick-start button shown when the main window is hidden). Position persists
    in config toolbar.position.
    """

    def __init__(self, config, on_start, on_stop):
        super().__init__()
        self.config = config
        self._on_start = on_start
        self._on_stop = on_stop
        self._drag_offset = None
        self._mode = "hidden"

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self._frame = QFrame(self)
        self._frame.setObjectName("floatToolbar")
        inner = QHBoxLayout(self._frame)
        inner.setContentsMargins(12, 8, 12, 8)
        inner.setSpacing(10)
        self._label = QLabel("")
        self._label.setObjectName("floatLabel")
        self._action = QPushButton("")
        self._action.setObjectName("floatButton")
        self._action.setCursor(Qt.PointingHandCursor)
        self._action.clicked.connect(self._on_action)
        inner.addWidget(self._label)
        inner.addWidget(self._action)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._frame)
        self.setStyleSheet(
            "#floatToolbar { background: rgba(15,23,42,238); border-radius: 14px; }"
            "#floatLabel { color: #f8fafc; font: 700 13px 'Segoe UI'; }"
            "#floatButton { color: #fff; background: #2563eb; border: none;"
            " border-radius: 8px; padding: 5px 12px; font: 700 12px 'Segoe UI'; }"
        )

    def set_mode(self, mode):
        self._mode = mode
        if mode == "hidden":
            self.hide()
            return
        if mode == "recording":
            self._label.setText("● " + tr(self.config, "recording"))
            self._action.setText(tr(self.config, "stop_dictation"))
        else:
            self._label.setText("🎙")
            self._action.setText(tr(self.config, "start_dictation"))
        self._show_positioned()

    def _show_positioned(self):
        self.adjustSize()
        geo = QApplication.primaryScreen().availableGeometry()
        pos = self.config.get("toolbar.position")
        if isinstance(pos, dict) and "x" in pos and "y" in pos:
            x, y = pos["x"], pos["y"]
        else:
            x = geo.x() + geo.width() - self.width() - 24
            y = geo.y() + geo.height() - self.height() - 96
        x, y = clamp_position(x, y, self.width(), self.height(), (geo.x(), geo.y(), geo.width(), geo.height()))
        self.move(x, y)
        self.show()

    def _on_action(self):
        if self._mode == "recording":
            self._on_stop()
        else:
            self._on_start()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and (event.buttons() & Qt.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        if self._drag_offset is not None:
            self._drag_offset = None
            try:
                self.config.set("toolbar.position", {"x": self.x(), "y": self.y()})
            except Exception:
                pass
            event.accept()


class DictationOverlay(QWidget):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.setWindowTitle("Hebrew Live Dictation Overlay")
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.Tool
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

        frame = QFrame()
        frame.setObjectName("overlayFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(22, 14, 22, 16)
        layout.setSpacing(8)

        self.status_label = QLabel(tr(config, "recording"))
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setObjectName("overlayStatus")

        self.text_label = QLabel("")
        self.text_label.setAlignment(Qt.AlignCenter)
        self.text_label.setWordWrap(True)
        self.text_label.setObjectName("overlayText")

        layout.addWidget(self.status_label)
        layout.addWidget(self.text_label)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(frame)

        self.resize(720, 118)
        self.apply_language()
        self.apply_theme()

    def apply_language(self):
        direction = Qt.RightToLeft if is_rtl(self.config) else Qt.LeftToRight
        self.setLayoutDirection(direction)
        self.text_label.setLayoutDirection(direction)

    def apply_theme(self):
        if self.config.get("app.theme", "light") == "dark":
            frame_bg = "rgba(20, 25, 36, 235)"
            border = "rgba(148, 163, 184, 90)"
            status = "#fda4af"
            text = "#eef2ff"
        else:
            frame_bg = "rgba(255, 255, 255, 242)"
            border = "rgba(148, 163, 184, 120)"
            status = "#2563eb"
            text = "#172033"

        self.setStyleSheet(
            f"""
            #overlayFrame {{
                background: {frame_bg};
                border: 1px solid {border};
                border-radius: 18px;
            }}
            #overlayStatus {{ color: {status}; font: 700 12px "Segoe UI"; }}
            #overlayText {{ color: {text}; font: 600 17px "Segoe UI"; }}
            """
        )

    def show_overlay(self):
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.x() + (screen.width() - self.width()) // 2
        y = screen.y() + screen.height() - self.height() - 72
        self.move(x, y)
        self.show()
        self._apply_native_window_styles()

    def _apply_native_window_styles(self):
        try:
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            get_style = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            set_style = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            style = get_style(hwnd, GWL_EXSTYLE)
            set_style(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT | WS_EX_LAYERED)
        except Exception:
            pass

    def set_status(self, message):
        self.status_label.setText(message)

    def set_text(self, text):
        words = (text or "").split()
        display = " ".join(words[-10:])
        if len(words) > 10:
            display = "... " + display
        self.text_label.setText(display)


class OnboardingDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle(tr(config, "setup_title"))
        self.setMinimumWidth(860)
        self.setMinimumHeight(520)
        self.setLayoutDirection(Qt.RightToLeft if is_rtl(config) else Qt.LeftToRight)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        title = QLabel(tr(config, "setup_title"))
        title.setObjectName("pageTitle")
        subtitle = QLabel(tr(config, "setup_subtitle"))
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        # 2-column layout for modern split setup
        body = QHBoxLayout()
        body.setSpacing(20)

        left_pane = QWidget()
        left_layout = QVBoxLayout(left_pane)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight if is_rtl(config) else Qt.AlignLeft)

        self.ui_language = QComboBox()
        self.ui_language.addItem(tr(config, "language_he"), "he")
        self.ui_language.addItem(tr(config, "language_en"), "en")
        self.ui_language.setCurrentIndex(max(0, self.ui_language.findData(config.get("app.ui_language", "he"))))

        self.language = QComboBox()
        self.language.addItems(PUBLIC_LANGUAGE_PRESETS)
        self.language.setCurrentText(config.get("languages.primary", "iw-IL"))

        self.project_id = QLineEdit(config.get("google.project_id", ""))
        advanced = bool(config.get("google.advanced_options", False))
        self.location = QComboBox()
        self.location.addItems(location_ids(include_advanced=advanced))
        self.location.setCurrentText(config.get("google.location", "eu"))
        self.model = QComboBox()
        self.model.addItems(model_ids(include_advanced=advanced))
        self.model.setCurrentText(config.get("google.model", "chirp_3"))
        self.credential_mode = QComboBox()
        self.credential_mode.addItems(["service_account_json", "adc"])
        self.credential_mode.setCurrentText(config.get("google.credential_mode", "service_account_json"))

        credentials_row = QHBoxLayout()
        self.credentials_path = QLineEdit(config.get("google.credentials_path", ""))
        browse = QPushButton(tr(config, "browse"))
        browse.clicked.connect(lambda: self._browse_file(self.credentials_path))
        credentials_row.addWidget(self.credentials_path, 1)
        credentials_row.addWidget(browse)

        from PySide6.QtWidgets import QKeySequenceEdit
        self.hotkey = QKeySequenceEdit()
        _set_hotkey_editor_value(self.hotkey, config.get("hotkeys.hotkey", "f8"))
        hotkey_row = QHBoxLayout()
        hotkey_row.addWidget(self.hotkey, 1)
        copilot = QPushButton(tr(config, "use_copilot_key"))
        copilot.setToolTip(tr(config, "use_copilot_key_tooltip"))
        copilot.clicked.connect(self._set_copilot_hotkey)
        hotkey_row.addWidget(copilot)

        form.addRow(tr(config, "ui_language"), self.ui_language)
        form.addRow(tr(config, "primary_language"), self.language)
        form.addRow(tr(config, "project_id"), self.project_id)
        form.addRow(tr(config, "location"), self.location)
        form.addRow(tr(config, "model"), self.model)
        form.addRow(tr(config, "credentials_mode"), self.credential_mode)
        form.addRow(tr(config, "credentials_json"), credentials_row)
        form.addRow(tr(config, "hotkey"), hotkey_row)
        left_layout.addLayout(form)
        body.addWidget(left_pane, 3)

        help_card = QFrame()
        help_card.setObjectName("onboardingHelpCard")
        help_layout = QVBoxLayout(help_card)
        help_layout.setContentsMargins(16, 16, 16, 16)
        help_layout.setSpacing(10)

        help_title = QLabel(tr(config, "google_setup_help_title"))
        help_title.setObjectName("helpCardTitle")
        help_text = QLabel(tr(config, "google_setup_help_text"))
        help_text.setObjectName("helpCardText")
        help_text.setWordWrap(True)

        help_layout.addWidget(help_title)
        help_layout.addWidget(help_text)
        help_layout.addStretch()
        body.addWidget(help_card, 2)

        layout.addLayout(body)

        buttons = QHBoxLayout()
        skip = QPushButton(tr(config, "skip"))
        save = QPushButton(tr(config, "save_setup"))
        save.setObjectName("primaryButton")
        skip.clicked.connect(self._skip)
        save.clicked.connect(self._save)
        buttons.addStretch()
        buttons.addWidget(skip)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _browse_file(self, line_edit):
        path, _ = QFileDialog.getOpenFileName(self, tr(self.config, "credentials_json"), "", "JSON Files (*.json);;All Files (*)")
        if path:
            line_edit.setText(path)

    def _set_copilot_hotkey(self):
        _set_hotkey_editor_value(self.hotkey, COPILOT_HOTKEY)

    def _save(self):
        language = self.language.currentText()
        preset = LANGUAGE_PRESETS.get(language, {})
        self.config.update(
            {
                "app.ui_language": self.ui_language.currentData(),
                "languages.primary": language,
                "languages.command_pack": preset.get("command_pack", "he"),
                "google.project_id": self.project_id.text().strip(),
                "google.location": self.location.currentText(),
                "google.model": self.model.currentText(),
                "google.credential_mode": self.credential_mode.currentText(),
                "google.credentials_path": self.credentials_path.text().strip(),
                "hotkeys.hotkey": _hotkey_editor_value(self.hotkey),
                "app.first_run_completed": True,
            }
        )
        self.accept()

    def _skip(self):
        self.config.update({"app.first_run_completed": True})
        self.reject()


class MainWindow(QMainWindow):
    def __init__(self, app_dir, config_dir, config, controller, bridge, hotkey_listener, on_settings_changed=None):
        super().__init__()
        self.app_dir = app_dir
        self.config_dir = config_dir
        self.config = config
        self.controller = controller
        self.bridge = bridge
        self.hotkey_listener = hotkey_listener
        self.on_settings_changed = on_settings_changed
        self.fields = {}
        self.pages = []

        self.setWindowTitle(tr(config, "app_name"))
        icon_path = get_asset_path(app_dir, "app_icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.resize(1120, 740)
        self.setMinimumSize(940, 640)
        self._build_ui()
        self._apply_theme()
        self.load_settings_to_fields()
        self._connect_instant_save_signals()

    def closeEvent(self, event):
        if self.config.get("app.minimize_on_close", True):
            event.ignore()
            self.hide()
        else:
            event.accept()
            self.bridge.quit_requested.emit()

    def _build_ui(self):
        self.setLayoutDirection(Qt.RightToLeft if is_rtl(self.config) else Qt.LeftToRight)
        shell = QWidget()
        shell.setObjectName("shell")
        root = QHBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(18, 18, 18, 18)
        sidebar_layout.setSpacing(14)

        brand = QLabel(tr(self.config, "app_name"))
        brand.setObjectName("brand")
        sidebar_layout.addWidget(brand)

        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(220)
        self.pages = [
            ("dashboard", self._dashboard_page),
            ("engine", self._engine_page),
            ("google", self._google_page),
            ("languages", self._languages_page),
            ("hotkeys", self._hotkeys_page),
            ("dictation", self._dictation_page),
            ("system", self._system_page),
            ("audio", self._audio_page),
            ("appearance", self._appearance_page),
            ("logs_about", self._logs_page),
        ]
        for key, _ in self.pages:
            item = QListWidgetItem(tr(self.config, key))
            item.setData(Qt.UserRole, key)
            self.nav.addItem(item)

        sidebar_layout.addWidget(self.nav, 1)

        self.stack = QStackedWidget()
        self.stack.setObjectName("stack")
        for _, builder in self.pages:
            self.stack.addWidget(builder())

        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        root.addWidget(sidebar)
        root.addWidget(self.stack, 1)
        old = self.centralWidget()
        self.setCentralWidget(shell)
        if old:
            old.deleteLater()

    def _rebuild_ui(self):
        row = self.nav.currentRow() if hasattr(self, "nav") else 0
        self.fields = {}
        self._build_ui()
        self._apply_theme()
        self.load_settings_to_fields()
        self._connect_instant_save_signals()
        self.nav.setCurrentRow(max(0, min(row, self.nav.count() - 1)))

    def _page(self, title_key, subtitle_key):
        container = QWidget()
        container.setObjectName("page")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(34, 28, 34, 28)
        layout.setSpacing(18)

        title = QLabel(tr(self.config, title_key))
        title.setObjectName("pageTitle")
        subtitle = QLabel(tr(self.config, subtitle_key))
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setObjectName("pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(container)
        return scroll, layout

    def _card(self, object_name="card"):
        card = QFrame()
        card.setObjectName(object_name)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(13)

        shadow = QGraphicsDropShadowEffect(card)
        theme = self.config.get("app.theme", "light")
        if theme == "dark":
            shadow.setBlurRadius(25)
            shadow.setOffset(0, 4)
            shadow.setColor(QColor(0, 0, 0, 100))
        else:
            shadow.setBlurRadius(20)
            shadow.setOffset(0, 4)
            shadow.setColor(QColor(15, 23, 42, 30))
        card.setGraphicsEffect(shadow)

        return card, layout

    def _form(self):
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight if is_rtl(self.config) else Qt.AlignLeft)
        form.setFormAlignment(Qt.AlignTop)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        return form

    def _dashboard_page(self):
        page, layout = self._page("dashboard_title", "dashboard_subtitle")
        hero, hero_layout = self._card("heroCard")

        self.error_banner = QLabel("")
        self.error_banner.setObjectName("errorBanner")
        self.error_banner.setWordWrap(True)
        self.error_banner.hide()

        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        status_row.setAlignment(Qt.AlignLeft if is_rtl(self.config) else Qt.AlignRight)

        self.status_dot = QLabel()
        self.status_dot.setFixedSize(12, 12)
        self.status_dot.setStyleSheet("background-color: #22c55e; border-radius: 6px;")

        self.status_label = QLabel(tr(self.config, "ready"))
        self.status_label.setObjectName("heroStatus")
        
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.status_label)

        self.transcript_label = QLabel("")
        self.transcript_label.setWordWrap(True)
        self.transcript_label.setAlignment(Qt.AlignTop | (Qt.AlignRight if is_rtl(self.config) else Qt.AlignLeft))
        self.transcript_label.setObjectName("transcript")
        self.transcript_label.setMinimumHeight(150)

        self.mic_button = QPushButton("🎙 " + tr(self.config, "start_dictation"))
        self.mic_button.setObjectName("micButton")
        self.mic_button.clicked.connect(lambda: self.controller.toggle_listening("preview"))

        self.model_label = QLabel("")
        self.model_label.setObjectName("metaLabel")
        self.language_label = QLabel("")
        self.language_label.setObjectName("metaLabel")

        hero_layout.addWidget(self.error_banner)
        hero_layout.addLayout(status_row)
        hero_layout.addWidget(self.transcript_label)
        hero_layout.addWidget(self.mic_button)
        hero_layout.addWidget(self.model_label)
        hero_layout.addWidget(self.language_label)
        layout.addWidget(hero)

        # Voice command reference block
        cmd_card, cmd_layout = self._card("commandsCard")
        cmd_title = QLabel(tr(self.config, "voice_commands_title"))
        cmd_title.setObjectName("commandsTitle")
        cmd_layout.addWidget(cmd_title)

        from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView
        
        pack = get_pack(self.config.get("languages.command_pack", "he"))
        is_hebrew = is_rtl(self.config)
        rows = []
        
        def clean_triggers(triggers, only_first=False):
            seen = set()
            result = []
            for t in triggers:
                norm = t.replace("'", "").replace("׳", "")
                if norm not in seen:
                    seen.add(norm)
                    result.append(t)
            if only_first and result:
                return result[0]
            return ", ".join(result)
        
        punct_groups = {}
        for cmd_say, char in pack.get("punctuation", ()):
            punct_groups.setdefault(char, []).append(cmd_say)
        for char, triggers in punct_groups.items():
            if char == "\n":
                action = "שורה חדשה (Enter)" if is_hebrew else "New Line (Enter)"
            elif char == "\n\n":
                action = "פסקה חדשה (Enterx2)" if is_hebrew else "New Paragraph (Enterx2)"
            else:
                action = f"סימן פיסוק '{char}'" if is_hebrew else f"Punctuation '{char}'"
            rows.append((action, clean_triggers(triggers, only_first=True)))
            
        emoji_groups = {}
        for cmd_say, char in pack.get("emoji", ()):
            emoji_groups.setdefault(char, []).append(cmd_say)
        for char, triggers in emoji_groups.items():
            action = f"אימוג'י {char}" if is_hebrew else f"Emoji {char}"
            rows.append((action, clean_triggers(triggers, only_first=True)))
            
        cmd_groups = {}
        for cmd_say, cmd_action in pack.get("commands", {}).items():
            cmd_groups.setdefault(cmd_action, []).append(cmd_say)
        for cmd_action, triggers in cmd_groups.items():
            if cmd_action == "delete_last_word": action_desc = "מחק מילה קודמת" if is_hebrew else "Delete Word"
            elif cmd_action == "delete_last_sentence": action_desc = "מחק משפט קודם" if is_hebrew else "Delete Sentence"
            elif cmd_action == "clear_all": action_desc = "נקה הכל" if is_hebrew else "Clear All"
            elif cmd_action == "undo": action_desc = "בטל פעולה אחרונה" if is_hebrew else "Undo"
            elif cmd_action == "send": action_desc = "שלח" if is_hebrew else "Send"
            elif cmd_action == "next_field": action_desc = "עבור שדה (Tab)" if is_hebrew else "Next Field (Tab)"
            else: action_desc = cmd_action.replace("_", " ").title()
            rows.append((action_desc, clean_triggers(triggers, only_first=False)))

        table = QTableWidget(len(rows), 2)
        table.setHorizontalHeaderLabels(["כדי לעשות" if is_hebrew else "To do this", "אמור" if is_hebrew else "Say this"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setFocusPolicy(Qt.NoFocus)
        table.setStyleSheet("QTableWidget { background-color: transparent; border: none; } QHeaderView::section { background-color: rgba(120, 120, 120, 0.1); font-weight: bold; }")

        for row, (action, say) in enumerate(rows):
            table.setItem(row, 0, QTableWidgetItem(action))
            table.setItem(row, 1, QTableWidgetItem(say))
        
        table.setMinimumHeight(240)
        cmd_layout.addWidget(table)
        layout.addWidget(cmd_card)
        layout.addStretch()
        return page

    def _engine_page(self):
        page, layout = self._page("engine_title", "engine_subtitle")
        card, card_layout = self._card()
        form = self._form()

        self._combo(
            "stt.mode",
            [
                ("smart_auto", "Smart Auto"),
                ("api", "Manual provider"),
                ("local", "Offline / Local Whisper"),
                ("auto_fallback", "Cloud + AutoFallback to local"),
            ],
            form,
            "engine_mode",
        )
        self._combo(
            "stt.provider",
            [
                ("google_v2", "Google STT V2 / Chirp 3"),
                ("deepgram", "Deepgram (best Hebrew realtime)"),
                ("groq", "Groq (cheapest cloud)"),
                ("whisper_local", "Local Whisper (offline)"),
            ],
            form,
            "engine_provider",
        )
        self._checkbox("providers.whisper.enabled", form, "engine_whisper_enabled")
        whisper_model_combo = self._combo(
            "providers.whisper.model",
            ["tiny", "base", "small", "medium", "large-v3", "distil-large-v3"],
            form,
            "engine_whisper_model",
        )
        whisper_model_combo.currentIndexChanged.connect(self._refresh_whisper_status)
        self._combo("providers.deepgram.model", ["nova-2", "nova-3"], form, "engine_deepgram_model")
        self._combo(
            "providers.groq.model",
            ["whisper-large-v3", "whisper-large-v3-turbo"],
            form,
            "engine_groq_model",
        )

        card_layout.addLayout(form)

        # Local model status + on-demand download.
        self._whisper_status_label = QLabel("")
        self._whisper_status_label.setObjectName("helperLabel")
        self._whisper_status_label.setWordWrap(True)
        download_row = QHBoxLayout()
        self._whisper_download_btn = QPushButton(tr(self.config, "engine_download_model"))
        self._whisper_download_btn.setObjectName("secondaryButton")
        self._whisper_download_btn.clicked.connect(self._download_whisper_model)
        download_row.addWidget(self._whisper_status_label, 1)
        download_row.addWidget(self._whisper_download_btn)
        card_layout.addLayout(download_row)
        self._refresh_whisper_status()

        card_layout.addWidget(self._provider_key_row("deepgram", "engine_deepgram_key"))
        card_layout.addWidget(self._provider_key_row("groq", "engine_groq_key"))
        layout.addWidget(card)
        layout.addStretch()
        return page

    def _refresh_whisper_status(self, *args):
        label = getattr(self, "_whisper_status_label", None)
        if label is None:
            return
        from . import models

        status = models.model_status(self.config)
        state = tr(self.config, "engine_whisper_downloaded") if status["downloaded"] else tr(
            self.config, "engine_whisper_not_downloaded"
        )
        label.setText(
            f"{status['name']}: {state}\n{tr(self.config, 'engine_model_path')}: {status['path']}"
        )

    def _download_whisper_model(self):
        if getattr(self, "_whisper_downloading", False):
            return
        name = self.config.get("providers.whisper.model", "small")
        from . import models

        ok, message = models.ram_preflight(name)
        if not ok:
            QMessageBox.warning(self, tr(self.config, "engine"), message)
            return
        self._whisper_downloading = True
        if getattr(self, "_whisper_download_btn", None) is not None:
            self._whisper_download_btn.setEnabled(False)
        if getattr(self, "_whisper_status_label", None) is not None:
            self._whisper_status_label.setText(f"{name}: {tr(self.config, 'engine_downloading')}")

        self._whisper_thread = QThread()
        self._whisper_worker = WhisperDownloader(self.config, name)
        self._whisper_worker.moveToThread(self._whisper_thread)
        self._whisper_thread.started.connect(self._whisper_worker.run)
        self._whisper_worker.finished.connect(self._on_whisper_downloaded)
        self._whisper_worker.finished.connect(self._whisper_thread.quit)
        self._whisper_thread.start()

    def _on_whisper_downloaded(self, ok, message):
        self._whisper_downloading = False
        if getattr(self, "_whisper_download_btn", None) is not None:
            self._whisper_download_btn.setEnabled(True)
        if ok:
            self._refresh_whisper_status()
            QMessageBox.information(self, tr(self.config, "engine"), tr(self.config, "engine_download_done"))
        else:
            if getattr(self, "_whisper_status_label", None) is not None:
                self._whisper_status_label.setText(f"{tr(self.config, 'engine_download_failed')}: {message}")
            QMessageBox.warning(self, tr(self.config, "engine"), f"{tr(self.config, 'engine_download_failed')}\n{message}")

    def _provider_key_row(self, provider, label_key):
        from . import secrets_store

        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        label = QLabel(tr(self.config, label_key))
        field = QLineEdit()
        field.setEchoMode(QLineEdit.Password)
        if secrets_store.has_secret(f"providers_{provider}_api_key"):
            field.setPlaceholderText(tr(self.config, "engine_key_placeholder_saved"))

        save_btn = QPushButton(tr(self.config, "engine_save_key"))
        save_btn.setObjectName("secondaryButton")
        save_btn.clicked.connect(lambda: self._save_provider_key(provider, field))
        test_btn = QPushButton(tr(self.config, "engine_test"))
        test_btn.setObjectName("secondaryButton")
        test_btn.clicked.connect(lambda: self._test_provider(provider))
        clear_btn = QPushButton(tr(self.config, "engine_clear_key"))
        clear_btn.setObjectName("secondaryButton")
        clear_btn.clicked.connect(lambda: self._clear_provider_key(provider, field))

        row.addWidget(label)
        row.addWidget(field, 1)
        row.addWidget(save_btn)
        row.addWidget(test_btn)
        row.addWidget(clear_btn)
        return container

    def _save_provider_key(self, provider, field):
        from . import secrets_store

        key = field.text().strip()
        if not key:
            return
        if secrets_store.set_secret(f"providers_{provider}_api_key", key):
            field.clear()
            field.setPlaceholderText(tr(self.config, "engine_key_placeholder_saved"))
            QMessageBox.information(self, tr(self.config, "engine"), tr(self.config, "engine_key_saved"))
        else:
            QMessageBox.warning(self, tr(self.config, "engine"), "Keyring unavailable.")

    def _clear_provider_key(self, provider, field):
        from . import secrets_store

        secrets_store.delete_secret(f"providers_{provider}_api_key")
        field.clear()
        field.setPlaceholderText("")
        QMessageBox.information(self, tr(self.config, "engine"), tr(self.config, "engine_key_cleared"))

    def _test_provider(self, provider):
        from .stt.verify import verify

        ok, message = verify(self.config, provider)
        title = tr(self.config, "engine")
        if ok:
            QMessageBox.information(self, title, f"{tr(self.config, 'engine_test_ok')}\n{message}")
        else:
            QMessageBox.warning(self, title, f"{tr(self.config, 'engine_test_failed')}\n{message}")

    def _google_page(self):
        page, layout = self._page("google_title", "google_subtitle")
        card, card_layout = self._card()
        form = self._form()
        
        self._line("google.project_id", form, "project_id")
        self._checkbox("google.advanced_options", form, "advanced_options")
        advanced_note = QLabel(tr(self.config, "advanced_options_note"))
        advanced_note.setObjectName("helperLabel")
        advanced_note.setWordWrap(True)
        form.addRow("", advanced_note)

        advanced = bool(self.config.get("google.advanced_options", False))
        self._combo("google.location", location_ids(include_advanced=advanced), form, "location")
        self._line("google.recognizer_id", form, "recognizer_id")
        
        model_combo = self._combo("google.model", model_ids(include_advanced=advanced), form, "model")
        self.model_desc = QLabel()
        self.model_desc.setObjectName("helperLabel")
        self.model_desc.setWordWrap(True)
        form.addRow("", self.model_desc)
        model_combo.currentIndexChanged.connect(self._update_model_descriptions)

        self._combo("google.fallback_location", location_ids(include_advanced=advanced), form, "fallback_location")
        
        fb_model_combo = self._combo("google.fallback_model", model_ids(include_advanced=advanced), form, "fallback_model")
        self.fallback_model_desc = QLabel()
        self.fallback_model_desc.setObjectName("helperLabel")
        self.fallback_model_desc.setWordWrap(True)
        form.addRow("", self.fallback_model_desc)
        fb_model_combo.currentIndexChanged.connect(self._update_model_descriptions)

        self._combo("google.credential_mode", ["service_account_json", "adc"], form, "credentials_mode")

        credentials_row = QHBoxLayout()
        credentials = QLineEdit()
        browse = QPushButton(tr(self.config, "browse"))
        browse.clicked.connect(lambda: self._browse_file(credentials))
        credentials_row.addWidget(credentials, 1)
        credentials_row.addWidget(browse)
        self.fields["google.credentials_path"] = credentials
        form.addRow(tr(self.config, "credentials_json"), credentials_row)

        self._checkbox("google.automatic_punctuation", form, "automatic_punctuation")

        # Instructions / Help Card
        guide_card, guide_card_layout = self._card("setupHelpCard")
        guide_title = QLabel(tr(self.config, "google_setup_help_title"))
        guide_title.setObjectName("setupHelpTitle")
        guide_text = QLabel(tr(self.config, "google_setup_help_text"))
        guide_text.setObjectName("setupHelpText")
        guide_text.setWordWrap(True)
        guide_card_layout.addWidget(guide_title)
        guide_card_layout.addWidget(guide_text)

        test_button = QPushButton(tr(self.config, "check_configuration"))
        test_button.setObjectName("secondaryButton")
        test_button.clicked.connect(self._check_google_config)
        card_layout.addLayout(form)
        card_layout.addWidget(test_button)
        layout.addWidget(card)
        layout.addWidget(guide_card)
        layout.addStretch()
        return page

    def _languages_page(self):
        page, layout = self._page("languages_title", "languages_subtitle")
        card, card_layout = self._card()
        form = self._form()
        self._combo("languages.primary", PUBLIC_LANGUAGE_PRESETS, form, "primary_language")
        self._line("languages.custom_code", form, "custom_language_code")
        self._combo("languages.command_pack", ["he", "en", "ar", "ru", "fr", "es"], form, "command_pack")
        self._line("languages.alternatives", form, "alternative_languages")

        phrases = QTextEdit()
        phrases.setPlaceholderText(tr(self.config, "custom_phrases_placeholder"))
        phrases.setMinimumHeight(150)
        self.fields["languages.custom_phrases"] = phrases
        form.addRow(tr(self.config, "custom_phrases"), phrases)

        card_layout.addLayout(form)
        layout.addWidget(card)
        layout.addStretch()
        return page

    def _hotkeys_page(self):
        page, layout = self._page("hotkeys_title", "hotkeys_subtitle")
        card, card_layout = self._card()
        form = self._form()
        from PySide6.QtWidgets import QKeySequenceEdit
        hk_edit = QKeySequenceEdit()
        self.fields["hotkeys.hotkey"] = hk_edit
        hotkey_row = QHBoxLayout()
        hotkey_row.addWidget(hk_edit, 1)
        copilot = QPushButton(tr(self.config, "use_copilot_key"))
        copilot.setToolTip(tr(self.config, "use_copilot_key_tooltip"))
        copilot.clicked.connect(lambda: self._set_copilot_hotkey(hk_edit))
        hotkey_row.addWidget(copilot)
        form.addRow(tr(self.config, "hotkey"), hotkey_row)
        self._combo("hotkeys.mode", [("toggle", tr(self.config, "mode_toggle")), ("push_to_talk", tr(self.config, "mode_push_to_talk"))], form, "mode")
        card_layout.addLayout(form)
        layout.addWidget(card)
        layout.addStretch()
        return page

    def _dictation_page(self):
        page, layout = self._page("dictation_title", "dictation_subtitle")
        card, card_layout = self._card()
        form = self._form()
        self._combo(
            "dictation.live_typing_mode",
            [
                ("final_only", tr(self.config, "live_typing_final_only")),
                ("live", tr(self.config, "live_typing_experimental")),
            ],
            form,
            "live_typing_mode",
        )
        note = QLabel(tr(self.config, "live_typing_beta_note"))
        note.setObjectName("helperLabel")
        note.setWordWrap(True)
        form.addRow("", note)
        card_layout.addLayout(form)
        layout.addWidget(card)
        layout.addStretch()
        return page

    def _system_page(self):
        page, layout = self._page("system_title", "system_subtitle")
        card, card_layout = self._card()
        form = self._form()
        self._checkbox("app.minimize_on_close", form, "minimize_on_close")
        self._checkbox("app.start_with_windows", form, "start_with_windows")
        self._checkbox("toolbar.enabled", form, "toolbar_enabled")
        self._checkbox("toolbar.idle_button", form, "toolbar_idle_button")
        self._checkbox("dictation.debug_log_transcripts", form, "debug_transcript_logging")
        card_layout.addLayout(form)
        layout.addWidget(card)
        layout.addStretch()
        return page

    def _audio_page(self):
        page, layout = self._page("audio_title", "audio_subtitle")
        card, card_layout = self._card()
        form = self._form()

        mic = QComboBox()
        mic.addItem(tr(self.config, "windows_default"), None)
        for dev in AudioStream.list_devices():
            mic.addItem(dev.get("display_name") or dev["name"], dev["index"])
        self.fields["audio.microphone_device"] = mic
        form.addRow(tr(self.config, "microphone"), mic)

        self._spin("audio.sample_rate", 8000, 48000, form, "sample_rate")
        self._spin("speech.frame_ms", 20, 1000, form, "frame_ms")
        self._checkbox("speech.endpointing", form, "endpointing")
        self._checkbox("speech.auto_stop_on_silence", form, "auto_stop_on_silence")
        self._checkbox("speech.vad_enabled", form, "vad_enabled")
        self._checkbox("audio.feedback_enabled", form, "audio_feedback")
        self._spin("audio.feedback_volume", 0, 100, form, "audio_feedback_volume")
        card_layout.addLayout(form)
        layout.addWidget(card)
        layout.addStretch()
        return page

    def _appearance_page(self):
        page, layout = self._page("appearance_title", "appearance_subtitle")
        card, card_layout = self._card()
        form = self._form()
        self._combo(
            "app.ui_language",
            [("he", tr(self.config, "language_he")), ("en", tr(self.config, "language_en"))],
            form,
            "ui_language",
        )
        self._combo(
            "app.theme",
            [("light", tr(self.config, "theme_light")), ("dark", tr(self.config, "theme_dark"))],
            form,
            "theme",
        )
        self._checkbox("app.show_overlay", form, "show_overlay")
        card_layout.addLayout(form)
        layout.addWidget(card)
        layout.addStretch()
        return page

    def _logs_page(self):
        page, layout = self._page("logs_title", "logs_subtitle")
        card, card_layout = self._card()
        settings = QLabel(f"{tr(self.config, 'settings_path')}: {self.config.filepath}")
        settings.setWordWrap(True)
        log = QLabel(f"{tr(self.config, 'log_path')}: {os.path.join(self.config_dir, 'hebrew_live_dictation.log')}")
        log.setWordWrap(True)
        privacy = QLabel(tr(self.config, "privacy_note"))
        privacy.setWordWrap(True)
        card_layout.addWidget(settings)
        card_layout.addWidget(log)
        card_layout.addWidget(privacy)

        open_logs = QPushButton("פתח תיקיית לוגים / Open Logs Folder")
        open_logs.setObjectName("secondaryButton")
        open_logs.clicked.connect(self._open_logs_folder)
        card_layout.addWidget(open_logs)

        export_row = QHBoxLayout()
        export_txt = QPushButton(tr(self.config, "export_txt"))
        export_txt.setObjectName("secondaryButton")
        export_txt.clicked.connect(lambda: self._export_history("txt"))
        export_docx = QPushButton(tr(self.config, "export_docx"))
        export_docx.setObjectName("secondaryButton")
        export_docx.clicked.connect(lambda: self._export_history("docx"))
        clear_history = QPushButton(tr(self.config, "history_clear"))
        clear_history.setObjectName("secondaryButton")
        clear_history.clicked.connect(self._clear_history)
        export_row.addWidget(export_txt)
        export_row.addWidget(export_docx)
        export_row.addWidget(clear_history)
        card_layout.addLayout(export_row)

        layout.addWidget(card)
        layout.addStretch()
        return page

    def _export_history(self, fmt):
        from . import export, history

        entries = history.load(self.config)
        if not entries:
            QMessageBox.information(self, tr(self.config, "logs_about"), tr(self.config, "history_empty"))
            return
        text = export.entries_to_text(entries)
        default_name = "transcript.docx" if fmt == "docx" else "transcript.txt"
        file_filter = "Word Document (*.docx)" if fmt == "docx" else "Text File (*.txt)"
        path, _ = QFileDialog.getSaveFileName(self, tr(self.config, "export_title"), default_name, file_filter)
        if not path:
            return
        try:
            if fmt == "docx":
                export.write_docx(path, text)
            else:
                export.write_txt(path, text)
            QMessageBox.information(self, tr(self.config, "logs_about"), tr(self.config, "export_done"))
        except Exception as e:
            QMessageBox.warning(self, tr(self.config, "error_title"), str(e))

    def _clear_history(self):
        from . import history

        history.clear(self.config)
        QMessageBox.information(self, tr(self.config, "logs_about"), tr(self.config, "history_cleared"))

    def _open_logs_folder(self):
        try:
            os.makedirs(self.config_dir, exist_ok=True)
            folder = os.path.normpath(self.config_dir)
            if sys.platform == "win32":
                os.startfile(folder)
                return
            if QDesktopServices.openUrl(QUrl.fromLocalFile(folder)):
                return
            raise OSError(folder)
        except Exception as e:
            QMessageBox.warning(
                self,
                tr(self.config, "error_title"),
                f"{tr(self.config, 'open_logs_failed')}\n{self.config_dir}\n{e}",
            )

    def _line(self, key, form, label_key):
        widget = QLineEdit()
        self.fields[key] = widget
        form.addRow(tr(self.config, label_key), widget)
        return widget

    def _combo(self, key, values, form, label_key):
        widget = QComboBox()
        for item in values:
            if isinstance(item, tuple):
                widget.addItem(item[1], item[0])
            else:
                widget.addItem(str(item), item)
        self.fields[key] = widget
        form.addRow(tr(self.config, label_key), widget)
        return widget

    def _checkbox(self, key, form, label_key):
        widget = QCheckBox()
        self.fields[key] = widget
        form.addRow(tr(self.config, label_key), widget)
        return widget

    def _spin(self, key, min_value, max_value, form, label_key):
        widget = QSpinBox()
        widget.setRange(min_value, max_value)
        self.fields[key] = widget
        form.addRow(tr(self.config, label_key), widget)
        return widget

    def _browse_file(self, line_edit):
        path, _ = QFileDialog.getOpenFileName(self, tr(self.config, "credentials_json"), "", "JSON Files (*.json);;All Files (*)")
        if path:
            line_edit.setText(path)

    def _set_copilot_hotkey(self, editor):
        editor.blockSignals(True)
        _set_hotkey_editor_value(editor, COPILOT_HOTKEY)
        editor.blockSignals(False)
        self.save_settings(show_message=False)

    def load_settings_to_fields(self):
        for key, widget in self.fields.items():
            widget.blockSignals(True)
            value = self.config.get(key)
            if key == "languages.alternatives" and isinstance(value, list):
                value = ", ".join(value)
            if key == "languages.custom_phrases" and isinstance(value, list):
                value = "\n".join(value)

            if isinstance(widget, QLineEdit):
                widget.setText("" if value is None else str(value))
            elif isinstance(widget, QTextEdit):
                widget.setPlainText("" if value is None else str(value))
            elif isinstance(widget, QComboBox):
                index = widget.findData(value)
                if index < 0:
                    index = widget.findText(str(value))
                widget.setCurrentIndex(max(0, index))
            elif isinstance(widget, QCheckBox):
                widget.setChecked(bool(value))
            elif isinstance(widget, QSpinBox):
                widget.setValue(int(value))
            elif widget.__class__.__name__ == "QKeySequenceEdit":
                _set_hotkey_editor_value(widget, value)
            widget.blockSignals(False)

        self._refresh_dashboard_labels()
        self._update_model_descriptions()

    def save_settings(self, show_message=True):
        previous_language = self.config.get("app.ui_language", "he")
        previous_theme = self.config.get("app.theme", "light")
        previous_advanced = self.config.get("google.advanced_options", False)
        values = {}
        for key, widget in self.fields.items():
            if isinstance(widget, QLineEdit):
                value = widget.text().strip()
                if key == "languages.alternatives":
                    value = [part.strip() for part in value.split(",") if part.strip()]
            elif isinstance(widget, QTextEdit):
                value = [line.strip() for line in widget.toPlainText().splitlines() if line.strip()]
            elif isinstance(widget, QComboBox):
                value = widget.currentData()
            elif isinstance(widget, QCheckBox):
                value = widget.isChecked()
            elif isinstance(widget, QSpinBox):
                value = widget.value()
            elif widget.__class__.__name__ == "QKeySequenceEdit":
                value = _hotkey_editor_value(widget)
            else:
                continue
            values[key] = value
        old_hotkey = self.config.get("hotkeys.hotkey")
        self.config.update(values)
        
        new_hotkey = self.config.get("hotkeys.hotkey")
        if new_hotkey and new_hotkey != old_hotkey:
            from .hotkeys import check_hotkey_conflict
            if check_hotkey_conflict(new_hotkey):
                msg = "קיצור הדרך שבחרת כבר בשימוש על ידי תוכנה אחרת בווינדוס.\nיתכן שהוא לא יעבוד במדויק או שייצור התנגשות." if is_rtl(self.config) else "The shortcut you selected is already in use by another application. It might conflict."
                title = "התנגשות מקשים" if is_rtl(self.config) else "Hotkey Conflict"
                QMessageBox.warning(self, title, msg)
            
            if _is_copilot_hotkey(new_hotkey):
                msg = tr(self.config, "copilot_hotkey_saved")
                QMessageBox.information(self, "Copilot Key", msg)
                
        self.hotkey_listener.update_settings()

        # Update Windows startup registry key
        start_with_windows = self.config.get("app.start_with_windows", False)
        set_startup(start_with_windows)

        language_changed = previous_language != self.config.get("app.ui_language", "he")
        theme_changed = previous_theme != self.config.get("app.theme", "light")
        advanced_changed = previous_advanced != self.config.get("google.advanced_options", False)
        if language_changed or theme_changed or advanced_changed:
            self._rebuild_ui()
            if self.on_settings_changed:
                self.on_settings_changed()
        else:
            self._apply_theme()
            self._refresh_dashboard_labels()

        if show_message:
            QMessageBox.information(self, tr(self.config, "saved"), tr(self.config, "settings_saved"))

    def _check_google_config(self):
        self.save_settings(show_message=False)
        mode = self.config.get("google.credential_mode", "service_account_json")
        if mode == "service_account_json":
            path = self.config.get("google.credentials_path", "")
            if not path or not os.path.exists(path):
                QMessageBox.warning(self, "Google", tr(self.config, "google_credentials_missing"))
                return
        from .google_stt_v2_stream import infer_project_id_from_credentials

        if not infer_project_id_from_credentials(self.config):
            QMessageBox.warning(self, "Google", tr(self.config, "google_project_required"))
            return
        QMessageBox.information(self, "Google", tr(self.config, "google_config_ready"))

    def set_status(self, state, message, output_mode="external"):
        if output_mode == "preview" or state == "idle":
            if state == "listening" and hasattr(self, "error_banner"):
                self.error_banner.hide()
            self.status_label.setText(message)
            self.mic_button.setText(("⏹ " if state == "listening" else "🎙 ") + (tr(self.config, "stop_dictation") if state == "listening" else tr(self.config, "start_dictation")))
            if hasattr(self, "status_dot"):
                if state == "listening":
                    self.status_dot.setStyleSheet("background-color: #ef4444; border-radius: 6px;")
                elif state in ("processing", "stopping"):
                    self.status_dot.setStyleSheet("background-color: #f59e0b; border-radius: 6px;")
                else:
                    self.status_dot.setStyleSheet("background-color: #22c55e; border-radius: 6px;")

    def set_transcript(self, text, final=False):
        if self.config.get("dictation.show_internal_preview", False):
            self.transcript_label.setText(text)
        elif text:
            self.transcript_label.setText(tr(self.config, "transcript_hidden"))
        else:
            self.transcript_label.setText("")

    def show_error(self, message):
        friendly = friendly_error(self.config, message)
        if hasattr(self, "error_banner"):
            self.error_banner.setText(f"{tr(self.config, 'error_title')}\n{friendly}")
            self.error_banner.show()
        if hasattr(self, "status_label"):
            self.status_label.setText(friendly)
        return friendly

    def set_command(self, action, result):
        labels = {
            "delete_last_word": "cmd_delete_last_word",
            "delete_last_sentence": "cmd_delete_last_sentence",
            "clear_all": "cmd_clear_all",
            "undo": "cmd_undo",
            "send": "cmd_send",
            "next_field": "cmd_next_field",
            "replace_phrase": "cmd_replace_phrase",
            "delete_phrase": "cmd_delete_phrase",
            "select_last_word": "cmd_select_last_word",
            "select_last_sentence": "cmd_select_last_sentence",
            "stop": "cmd_stop",
        }
        self.status_label.setText(tr(self.config, labels.get(action, "ready")))

    def _refresh_dashboard_labels(self):
        if not hasattr(self, "model_label"):
            return
        self.model_label.setText(
            f"{tr(self.config, 'active_model')}: "
            f"{self.config.get('google.model')} / {self.config.get('google.location')}"
        )
        self.language_label.setText(
            f"{tr(self.config, 'active_language')}: {self.config.get('languages.primary')} | "
            f"{tr(self.config, 'command_pack')}: {self.config.get('languages.command_pack')}"
        )

    def _update_model_descriptions(self):
        if not hasattr(self, "fields") or "google.model" not in self.fields:
            return
        
        # Model description
        model = self.fields["google.model"].currentText()
        preset = MODEL_PRESETS.get(model)
        desc_key = f"model_descr_{model}"
        description = tr(self.config, desc_key)
        if preset and preset.warning:
            description = f"{description}\n{preset.warning}"
        self.model_desc.setText(description)
        
        # Fallback model description
        fb_model = self.fields["google.fallback_model"].currentText()
        fb_preset = MODEL_PRESETS.get(fb_model)
        fb_desc_key = f"model_descr_{fb_model}"
        fb_description = tr(self.config, fb_desc_key)
        if fb_preset and fb_preset.warning:
            fb_description = f"{fb_description}\n{fb_preset.warning}"
        self.fallback_model_desc.setText(fb_description)

    def _connect_instant_save_signals(self):
        for key, widget in self.fields.items():
            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._on_field_changed_instantly)
            elif isinstance(widget, QCheckBox):
                widget.stateChanged.connect(self._on_field_changed_instantly)
            elif isinstance(widget, QLineEdit):
                widget.editingFinished.connect(self._on_field_changed_instantly)
            elif widget.__class__.__name__ == "QKeySequenceEdit":
                widget.editingFinished.connect(self._on_field_changed_instantly)

    def _on_field_changed_instantly(self, *args, **kwargs):
        self.save_settings(show_message=False)

    def _apply_theme(self):
        theme = self.config.get("app.theme", "light")
        if theme == "dark":
            colors = {
                "bg": "#090d16",
                "sidebar": "#0f172a",
                "surface": "#1e293b",
                "surface2": "#090d16",
                "text": "#f8fafc",
                "muted": "#94a3b8",
                "border": "#334155",
                "primary": "#3b82f6",
                "primaryHover": "#60a5fa",
                "dangerBg": "#31121d",
                "dangerText": "#fca5a5",
                "hoverBg": "rgba(255, 255, 255, 0.05)",
                "activeBg": "rgba(59, 130, 246, 0.15)",
                "onboardingHelpBg": "#1e293b",
                "onboardingHelpBorder": "#334155",
                "helpTitle": "#60a5fa",
                "cmdBoxBg": "#111827",
            }
        else:
            colors = {
                "bg": "#f8fafc",
                "sidebar": "#ffffff",
                "surface": "#ffffff",
                "surface2": "#f1f5f9",
                "text": "#0f172a",
                "muted": "#64748b",
                "border": "#e2e8f0",
                "primary": "#2563eb",
                "primaryHover": "#1d4ed8",
                "dangerBg": "#fef2f2",
                "dangerText": "#dc2626",
                "hoverBg": "rgba(0, 0, 0, 0.03)",
                "activeBg": "rgba(37, 99, 235, 0.08)",
                "onboardingHelpBg": "#f1f5f9",
                "onboardingHelpBorder": "#e2e8f0",
                "helpTitle": "#2563eb",
                "cmdBoxBg": "#f8fafc",
            }

        self.setStyleSheet(
            f"""
            QMainWindow, QWidget#shell, QWidget#page {{
                background: {colors['bg']};
                color: {colors['text']};
                font-family: "Segoe UI", "Inter", sans-serif;
                font-size: 13px;
            }}
            QWidget#sidebar {{
                background: {colors['sidebar']};
                border-right: 1px solid {colors['border']};
            }}
            QLabel#brand {{
                color: {colors['text']};
                font-size: 19px;
                font-weight: 800;
                padding: 10px 4px 14px 4px;
            }}
            QListWidget#nav {{
                background: transparent;
                border: 0;
                outline: 0;
                font-size: 14px;
            }}
            QListWidget#nav::item {{
                padding: 12px 14px;
                border-radius: 8px;
                margin: 4px 0;
                color: {colors['muted']};
            }}
            QListWidget#nav::item:hover {{
                background: {colors['hoverBg']};
                color: {colors['text']};
            }}
            QListWidget#nav::item:selected {{
                background: {colors['activeBg']};
                color: {colors['primary']};
                font-weight: 700;
            }}
            QScrollArea#pageScroll {{
                background: {colors['bg']};
                border: 0;
            }}
            QLabel#pageTitle {{
                color: {colors['text']};
                font-size: 28px;
                font-weight: 800;
            }}
            QLabel#pageSubtitle, QLabel#metaLabel {{
                color: {colors['muted']};
                font-size: 13px;
            }}
            QLabel {{
                color: {colors['text']};
            }}
            QLabel#pageSubtitle, QLabel#metaLabel, QLabel#helperLabel, QLabel#setupHelpText, QLabel#cmdBoxDesc {{
                color: {colors['muted']};
            }}
            QFrame#card, QFrame#heroCard, QFrame#commandsCard, QFrame#setupHelpCard {{
                background: {colors['surface']};
                border: 1px solid {colors['border']};
                border-radius: 12px;
            }}
            QFrame#heroCard {{
                min-height: 280px;
            }}
            QLabel#heroStatus {{
                color: {colors['text']};
                font-size: 24px;
                font-weight: 800;
            }}
            QLabel#transcript {{
                background: {colors['surface2']};
                color: {colors['text']};
                border: 1px solid {colors['border']};
                border-radius: 10px;
                padding: 14px;
                min-height: 100px;
                font-size: 17px;
            }}
            QLabel#errorBanner {{
                background: {colors['dangerBg']};
                color: {colors['dangerText']};
                border: 1px solid {colors['dangerText']};
                border-radius: 10px;
                padding: 10px 12px;
                font-weight: 600;
            }}
            QLineEdit, QTextEdit {{
                background: {colors['surface2']};
                color: {colors['text']};
                border: 1px solid {colors['border']};
                border-radius: 8px;
                padding: 8px 12px;
                min-height: 20px;
            }}
            QComboBox, QSpinBox {{
                background: {colors['surface2']};
                color: {colors['text']};
                border: 1px solid {colors['border']};
                border-radius: 8px;
                padding: 6px 24px;
                min-height: 22px;
            }}
            QLineEdit:focus, QComboBox:focus, QTextEdit:focus, QSpinBox:focus {{
                border: 1.5px solid {colors['primary']};
            }}
            QComboBox QAbstractItemView {{
                background-color: {colors['surface']};
                color: {colors['text']};
                border: 1px solid {colors['border']};
                selection-background-color: {colors['activeBg']};
                selection-color: {colors['primary']};
            }}
            QPushButton {{
                background: {colors['primary']};
                color: white;
                border: 0;
                border-radius: 8px;
                padding: 9px 15px;
                font-weight: 650;
            }}
            QPushButton:hover {{
                background: {colors['primaryHover']};
            }}
            QPushButton#secondaryButton, QPushButton#sidebarButton {{
                background: {colors['surface']};
                color: {colors['primary']};
                border: 1px solid {colors['border']};
            }}
            QPushButton#secondaryButton:hover, QPushButton#sidebarButton:hover {{
                background: {colors['surface2']};
            }}
            QPushButton#micButton {{
                min-height: 50px;
                font-size: 16px;
                border-radius: 10px;
            }}
            QCheckBox {{
                spacing: 8px;
            }}
            
            /* Custom Onboarding Help Card */
            QFrame#onboardingHelpCard {{
                background: {colors['onboardingHelpBg']};
                border: 1px solid {colors['onboardingHelpBorder']};
                border-radius: 12px;
            }}
            QLabel#helpCardTitle {{
                color: {colors['helpTitle']};
                font-size: 15px;
                font-weight: 700;
            }}
            QLabel#helpCardText {{
                color: {colors['text']};
                font-size: 12px;
                line-height: 15px;
            }}
            
            /* Google cloud setup help widget */
            QLabel#setupHelpTitle {{
                color: {colors['primary']};
                font-size: 15px;
                font-weight: 700;
            }}
            QLabel#setupHelpText {{
                color: {colors['muted']};
                font-size: 12px;
            }}
            
            /* Helper label under Google STT fields */
            QLabel#helperLabel {{
                color: {colors['muted']};
                font-size: 11.5px;
                font-style: italic;
                padding-left: 2px;
            }}
            
            /* Dashboard Command Reference Boxes */
            QLabel#commandsTitle {{
                color: {colors['text']};
                font-size: 16px;
                font-weight: 750;
            }}
            QFrame#cmdBox {{
                background: {colors['cmdBoxBg']};
                border: 1px solid {colors['border']};
                border-radius: 8px;
            }}
            QLabel#cmdBoxTitle {{
                color: {colors['primary']};
                font-weight: 700;
                font-size: 12.5px;
            }}
            QLabel#cmdBoxDesc {{
                color: {colors['text']};
                font-size: 12px;
            }}
            
            /* Slim, Modern Scrollbars */
            QScrollBar:vertical {{
                background: transparent;
                width: 8px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {colors['border']};
                min-height: 20px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {colors['muted']};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                background: none;
                height: 0px;
            }}
            QScrollBar:horizontal {{
                background: transparent;
                height: 8px;
                margin: 0px;
            }}
            QScrollBar::handle:horizontal {{
                background: {colors['border']};
                min-width: 20px;
                border-radius: 4px;
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                background: none;
                width: 0px;
            }}
            
            /* Modern QMenu context menu */
            QMenu {{
                background-color: {colors['surface']};
                color: {colors['text']};
                border: 1px solid {colors['border']};
                border-radius: 8px;
                padding: 4px 0px;
            }}
            QMenu::item {{
                padding: 6px 20px;
                border-radius: 4px;
                margin: 2px 4px;
            }}
            QMenu::item:selected {{
                background-color: {colors['activeBg']};
                color: {colors['primary']};
            }}
            QMenu::separator {{
                height: 1px;
                background: {colors['border']};
                margin: 4px 0px;
            }}
            """
        )


class QtDictationApp:
    def __init__(self, app_dir, config_dir):
        self.app_dir = app_dir
        self.config_dir = config_dir
        self.config = Config(config_dir)
        setup_logging(config_dir, self.config.get("debug_log_transcripts", False))
        self._session_finals = []

        self.qt_app = QApplication(sys.argv)
        self.qt_app.setQuitOnLastWindowClosed(False)
        icon_path = get_asset_path(app_dir, "app_icon.ico")
        if os.path.exists(icon_path):
            self.qt_app.setWindowIcon(QIcon(icon_path))
        self.bridge = AppBridge()
        self.overlay = DictationOverlay(self.config)
        self.toolbar = FloatingToolbar(
            self.config,
            on_start=self.bridge.start_requested.emit,
            on_stop=self.bridge.stop_requested.emit,
        )
        self.controller = DictationController(
            self.config,
            on_status=self.bridge.status_changed.emit,
            on_text=self.bridge.text_changed.emit,
            on_error=self.bridge.error_occurred.emit,
            on_command=self.bridge.command_executed.emit,
        )
        self.hotkey_listener = HotkeyListener(
            self.config,
            on_start_requested=self.bridge.start_requested.emit,
            on_stop_requested=self.bridge.stop_requested.emit,
        )
        self.window = MainWindow(
            app_dir,
            config_dir,
            self.config,
            self.controller,
            self.bridge,
            self.hotkey_listener,
            on_settings_changed=self._on_settings_changed,
        )
        self.tray = QSystemTrayIcon(self._icon("#22c55e"))
        self._configure_tray()
        self._connect_signals()

    def _connect_signals(self):
        self.bridge.start_requested.connect(self.controller.start_listening)
        self.bridge.stop_requested.connect(self.controller.stop_listening)
        self.bridge.status_changed.connect(self._on_status)
        self.bridge.text_changed.connect(self._on_text)
        self.bridge.error_occurred.connect(self._on_error)
        self.bridge.command_executed.connect(self._on_command)
        self.bridge.quit_requested.connect(self.quit)
        self.tray.activated.connect(self._on_tray_activated)

    def _configure_tray(self):
        self.tray.setToolTip(tr(self.config, "app_name"))
        if hasattr(self, "tray_menu") and self.tray_menu:
            self.tray_menu.deleteLater()
        self.tray_menu = QMenu()
        
        # Bold primary default action: Show application
        show = QAction("הצג תוכנה" if is_rtl(self.config) else "Show Application", self.tray_menu)
        font = show.font()
        font.setBold(True)
        show.setFont(font)
        show.triggered.connect(self._restore_window)
        
        start = QAction(tr(self.config, "tray_start"), self.tray_menu)
        stop = QAction(tr(self.config, "tray_stop"), self.tray_menu)
        quit_action = QAction(tr(self.config, "tray_exit"), self.tray_menu)
        
        start.triggered.connect(self.controller.start_listening)
        stop.triggered.connect(self.controller.stop_listening)
        quit_action.triggered.connect(self.quit)
        
        self.tray_menu.addAction(show)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(start)
        self.tray_menu.addAction(stop)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(quit_action)
        self.tray.setContextMenu(self.tray_menu)

    def _restore_window(self):
        self.window.showNormal()
        self.window.activateWindow()

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.window.isVisible() and not self.window.isMinimized():
                self.window.hide()
            else:
                self.window.showNormal()
                self.window.activateWindow()

    def _on_settings_changed(self):
        self.overlay.apply_language()
        self.overlay.apply_theme()
        self._configure_tray()

    def _icon(self, color):
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(6, 6, 52, 52)
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(25, 17, 14, 25, 7, 7)
        painter.end()
        return QIcon(pixmap)

    def _on_status(self, state, message, output_mode="external"):
        self.hotkey_listener.set_listening_state(state == "listening")
        self.window.set_status(state, message, output_mode)
        if state == "listening":
            self.window.set_transcript("", False)
            self.overlay.set_text("")
            self.tray.setIcon(self._icon("#ef4444"))
            self._play_feedback("start")
            self._update_floating_toolbar("listening")
            if self.config.get("app.show_overlay", True):
                self.overlay.set_status(message)
                self.overlay.show_overlay()
        elif state == "stopping":
            self.tray.setIcon(self._icon("#f59e0b"))
            self.overlay.set_status(message)
        else:
            self.tray.setIcon(self._icon("#22c55e"))
            self.overlay.hide()
            if state == "idle":
                self._play_feedback("stop")
            self._update_floating_toolbar("idle")
            self._flush_session_history()

    def _update_floating_toolbar(self, state):
        try:
            if state == "listening":
                if self.config.get("toolbar.enabled", False):
                    self.toolbar.set_mode("recording")
                else:
                    self.toolbar.set_mode("hidden")
            else:  # idle
                if self.config.get("toolbar.idle_button", False) and self.window.isHidden():
                    self.toolbar.set_mode("idle")
                else:
                    self.toolbar.set_mode("hidden")
        except Exception:
            pass

    def _play_feedback(self, kind):
        if not self.config.get("audio.feedback_enabled", False):
            return
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtMultimedia import QSoundEffect

            from . import audio_feedback

            volume = self.config.get("audio.feedback_volume", 50)
            path = audio_feedback.tone_path(self.config_dir, kind, volume)
            if not path:
                return
            effects = getattr(self, "_feedback_effects", None)
            if effects is None:
                effects = self._feedback_effects = {}
            effect = effects.get(kind)
            if effect is None:
                effect = QSoundEffect()
                effects[kind] = effect
            effect.setSource(QUrl.fromLocalFile(path))
            effect.setVolume(max(0.0, min(1.0, float(volume) / 100.0)))
            effect.play()
        except Exception:
            # Audio feedback is best-effort; never let it disrupt dictation.
            pass

    def _on_text(self, text, final, output_mode="external"):
        if output_mode == "preview":
            self.window.set_transcript(text, final)
        self.overlay.set_text(text)
        if final and text and text.strip():
            self._session_finals.append(text.strip())

    def _flush_session_history(self):
        if not self._session_finals:
            return
        transcript = " ".join(self._session_finals).strip()
        self._session_finals = []
        try:
            from . import history

            history.append(self.config, transcript)
        except Exception:
            pass

    def _on_error(self, message):
        friendly = self.window.show_error(message)
        if self.config.get("app.show_overlay", True):
            self.overlay.set_status(tr(self.config, "error_title"))
            self.overlay.set_text(friendly)
            self.overlay.show_overlay()

    def _on_command(self, action, result):
        self.window.set_command(action, result)
        self.overlay.set_text(self.window.status_label.text())

    def run(self):
        self.hotkey_listener.start()
        self.tray.show()
        if not self.config.get("app.first_run_completed", False):
            OnboardingDialog(self.config, self.window).exec()
            self.window._rebuild_ui()
            self.hotkey_listener.update_settings()
            self._on_settings_changed()
        if self.config.get("app.startup_minimized", False):
            self.window.hide()
        else:
            self.window.show()
        return self.qt_app.exec()

    def quit(self):
        self.hotkey_listener.stop()
        self.controller.shutdown()
        self.tray.hide()
        self.qt_app.quit()
