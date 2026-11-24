"""Desktop views and worker lifecycle for SmartCleanAI."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import ai_provider
from ai_provider import AIError, PROVIDERS
from assistant import ask, assistant_data, candidates_by_id, local_plan
from cleaner import CleanError, Quarantine, scan, units
from junk import JunkCandidate, list_drives, recycle, scan_projects

ACCENT, AMBER, RED, MUTED, GREEN = "#3b82f6", "#fbbf24", "#f87171", "#8b9bb8", "#34d399"
STYLE = f"""
QWidget {{ background:#0b1220; color:#e6edf7; }}
QFrame#sidebar {{ background:#0e172a; border-right:1px solid #1a2540; }}
QFrame#sidebar QLabel, QFrame#sidebar QPushButton#nav {{ background:transparent; }}
QFrame#sidebar QPushButton#nav:hover {{ background:#15213a; }}
QFrame#sidebar QPushButton#nav:checked {{ background:#1d3a6e; }}
QFrame#sidebar QLabel#logo {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #60a5fa, stop:1 #2563eb);
    color:white; border-radius:9px; font-size:16px; font-weight:800; }}
QLabel#brand {{ font-size:18px; font-weight:800; color:#ffffff; }}
QLabel#title {{ font-size:24px; font-weight:800; color:#ffffff; }}
QLabel#muted {{ color:{MUTED}; }}
QLabel#small {{ color:{MUTED}; font-size:12px; }}
QLabel#letter {{ font-size:30px; font-weight:800; color:#ffffff; }}
QLabel#banner {{ background:#2a2110; color:{AMBER}; border:1px solid #4a3a14; border-radius:10px; padding:9px 13px; }}
QFrame#card {{ background:#111a2e; border:1px solid #1c2945; border-radius:14px; }}
QFrame#aicard {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #13224a, stop:1 #1a1846);
    border:1px solid #2b3f7a; border-radius:14px; }}
QFrame#card QLabel, QFrame#aicard QLabel {{ background:transparent; }}
QPushButton {{ border:1px solid #24324f; background:#141f36; border-radius:10px; padding:8px 16px; color:#dbe5f5; }}
QPushButton:hover {{ background:#1b2945; border-color:#36507f; }}
QPushButton:focus {{ border-color:#60a5fa; }}
QPushButton:disabled {{ color:#55627c; background:#0f1729; border-color:#18223a; }}
QPushButton[primary="true"] {{ background:{ACCENT}; color:white; border:0; font-weight:700; padding:10px 22px; }}
QPushButton[primary="true"]:hover {{ background:#60a5fa; }}
QPushButton[primary="true"]:disabled {{ background:#1a2b4d; color:#5d73a0; }}
QPushButton[ai="true"] {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #2563eb, stop:1 #7c3aed);
    color:white; border:0; font-weight:700; padding:10px 22px; }}
QPushButton[ai="true"]:hover {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #3b82f6, stop:1 #8b5cf6); }}
QPushButton[ai="true"]:disabled {{ background:#1a2240; color:#5d6a95; }}
QPushButton#nav {{ text-align:left; border:0; border-radius:10px; padding:11px 14px; color:#9fb0cc; font-weight:600; }}
QPushButton#nav:checked {{ color:#ffffff; }}
QPushButton#chip {{ border-radius:12px; padding:4px 14px; background:transparent; color:#9fb0cc; border:1px solid #24324f; }}
QPushButton#chip:hover {{ color:#ffffff; }}
QPushButton#chip:checked {{ background:#1d3a6e; border-color:{ACCENT}; color:#ffffff; }}
QPushButton#ghost {{ background:transparent; border:0; color:#9fb0cc; padding:6px 10px; }}
QPushButton#ghost:hover {{ color:#ffffff; background:#141f36; }}
QPushButton#drive {{ background:#111a2e; border:1px solid #1c2945; border-radius:16px; padding:0; }}
QPushButton#drive:hover {{ border-color:#36507f; background:#13203a; }}
QPushButton#drive:checked {{ border:2px solid {ACCENT}; background:#13244a; }}
QPushButton#drive QLabel {{ background:transparent; }}
QTableWidget {{
    background:#111a2e; alternate-background-color:#111a2e; border:1px solid #1c2945; border-radius:14px;
    selection-background-color:#1b3260; selection-color:#ffffff; outline:0;
}}
QTableWidget::item {{ padding:0 10px; border-bottom:1px solid #18233c; }}
QHeaderView {{ background:transparent; }}
QHeaderView::section {{ background:#111a2e; color:{MUTED}; padding:10px; border:0; border-bottom:1px solid #1c2945;
    font-size:12px; font-weight:600; }}
QScrollBar:vertical {{ background:transparent; width:10px; margin:4px 2px; border:0; }}
QScrollBar::handle:vertical {{ background:#26365a; border-radius:4px; min-height:24px; }}
QScrollBar::handle:vertical:hover {{ background:#3a5285; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background:none; }}
QProgressBar {{ border:0; background:#1c2945; border-radius:3px; }}
QProgressBar::chunk {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #60a5fa, stop:1 #2563eb); border-radius:3px; }}
QProgressBar[low="true"]::chunk {{ background:{RED}; }}
QTableWidget::indicator {{ width:16px; height:16px; border:1px solid #3a4d75; border-radius:5px; background:#0b1220; }}
QTableWidget::indicator:checked {{ background:{ACCENT}; border-color:{ACCENT}; image:none; }}
QPlainTextEdit, QLineEdit, QSpinBox, QComboBox {{
    background:#111a2e; border:1px solid #1c2945; border-radius:10px; padding:8px 10px;
    selection-background-color:{ACCENT};
}}
QFrame#aicard QLineEdit {{ background:#0b1220; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color:{ACCENT}; }}
QComboBox::drop-down {{ border:0; width:26px; }}
QComboBox QAbstractItemView {{ background:#141f36; border:1px solid #24324f; selection-background-color:#1d3a6e; }}
QToolTip {{ background:#1b2945; color:#e6edf7; border:1px solid #2c3f66; padding:6px; border-radius:6px; }}
"""
RISKS = {"low": ("Thấp", GREEN), "medium": ("Vừa", AMBER), "high": ("Cao", RED)}
RESERVE = 32 * 1024**2
GOAL_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(gb|gib|g|mb|mib)\b", re.I)


class Worker(QThread):
    result = pyqtSignal(object)
    failure = pyqtSignal(str)
    progress = pyqtSignal(object)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            self.result.emit(self.operation(self.progress.emit))
        except Exception as error:
            self.failure.emit(str(error))


def label(text="", role="muted"):
    result = QLabel(text)
    result.setObjectName(role)
    result.setTextFormat(Qt.TextFormat.PlainText)
    result.setWordWrap(True)
    return result


def button(text, callback, *, primary=False, ai=False, name=None):
    result = QPushButton(text)
    if primary:
        result.setProperty("primary", True)
    if ai:
        result.setProperty("ai", True)
    if name:
        result.setObjectName(name)
    result.setCursor(Qt.CursorShape.PointingHandCursor)
    result.clicked.connect(callback)
    return result


def cell(text, *, number=False, color=None, tip=None):
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    if number:
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    if color:
        item.setForeground(QColor(color))
    if tip:
        item.setToolTip(tip)
    return item


def table(headers, stretch_column=0, *, multi=False):
    view = QTableWidget(0, len(headers))
    view.setHorizontalHeaderLabels(headers)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection if multi
                          else QAbstractItemView.SelectionMode.SingleSelection)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.setShowGrid(False)
    view.setWordWrap(False)
    view.verticalHeader().hide()
    view.verticalHeader().setDefaultSectionSize(40)
    header = view.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(stretch_column, QHeaderView.ResizeMode.Stretch)
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return view


def check_cell(checked, enabled=True):
    item = cell("" if enabled else "🔒")
    if enabled:
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    return item


def refresh_style(widget, **properties):
    for key, value in properties.items():
        widget.setProperty(key, value)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class DriveCard(QPushButton):
    def __init__(self, drive):
        super().__init__()
        self.drive = drive
        self.setObjectName("drive")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(138)
        self.setMinimumWidth(220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(6)
        top = QHBoxLayout()
        top.addWidget(label(drive.root.rstrip("\\"), "letter"))
        top.addStretch()
        top.addWidget(label(drive.name, "small"))
        layout.addLayout(top)
        layout.addStretch()
        bar = QProgressBar()
        bar.setTextVisible(False)
        bar.setFixedHeight(6)
        bar.setValue(round(100 * drive.used / drive.total) if drive.total else 0)
        refresh_style(bar, low=drive.free < 10 * 1024**3)
        layout.addWidget(bar)
        layout.addWidget(label(f"Còn {units(drive.free)} / {units(drive.total)}", "small"))
        for child in self.findChildren(QWidget):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


class ConfirmClean(QDialog):
    """Lists exactly what will be cleaned and where it goes before any file is touched."""

    def __init__(self, parent, items, free_vault):
        super().__init__(parent)
        total = sum(item.size for item in items)
        vault = sum(item.size for item in items if not isinstance(item, JunkCandidate))
        self.setWindowTitle("Xác nhận dọn")
        self.resize(620, 450)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(label(f"Dọn {len(items)} mục · {units(total)}", "title"))
        view = table(("Mục", "Dung lượng", "Chuyển tới"))
        view.setRowCount(len(items))
        for row, item in enumerate(items):
            view.setItem(row, 0, cell(item.label, tip=str(item.path)))
            view.setItem(row, 1, cell(units(item.size), number=True))
            view.setItem(row, 2, cell("Thùng rác" if isinstance(item, JunkCandidate) else "Kho trên ổ D", color=MUTED))
        layout.addWidget(view, 1)
        layout.addWidget(label("Có thể lấy lại bất cứ lúc nào ở mục Khôi phục hoặc Thùng rác.", "small"))
        fits = vault + RESERVE <= free_vault
        if not fits:
            layout.addWidget(label(f"Ổ D chỉ còn {units(free_vault)}, hãy bỏ bớt mục.", "banner"))
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(button("Hủy", self.reject))
        go = button("Dọn ngay", self.accept, primary=True)
        go.setEnabled(fits)
        go.setDefault(True)
        actions.addWidget(go)
        layout.addLayout(actions)


class Window(QMainWindow):
    def __init__(self, vault: Quarantine, *, smoke=False):
        super().__init__()
        self.vault = vault
        self.smoke = smoke
        self.operation_failed = False
        self.worker = None
        self.drive = None
        self.drives = []
        self.items = []
        self.checked = set()
        self.records = []
        self.warnings = []
        self.free_drive = None
        self.free_vault = None
        self.category = ""
        self.history = []
        self.id_items = {}
        self.notes = {}
        self.setWindowTitle("SmartClean")
        self.resize(1220, 780)
        self.setMinimumSize(980, 640)
        self.setFont(QFont("Segoe UI", 10))
        self.setStyleSheet(STYLE)
        self._layout()
        self._load_settings()
        self._enable_actions()

    # ------------------------------------------------------------------ layout
    def _layout(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._sidebar())
        main = QVBoxLayout()
        main.setContentsMargins(30, 24, 30, 14)
        main.setSpacing(10)
        self.pages = QStackedWidget()
        for page in (self._clean_page(), self._restore_page(), self._settings_page()):
            self.pages.addWidget(page)
        main.addWidget(self.pages, 1)
        footer = QHBoxLayout()
        self.status = label("")
        self.activity = QProgressBar()
        self.activity.setTextVisible(False)
        self.activity.setFixedSize(200, 6)
        self.activity.hide()
        self.warning_button = button("", self.show_warnings, name="ghost")
        self.warning_button.hide()
        footer.addWidget(self.status, 1)
        footer.addWidget(self.activity)
        footer.addWidget(self.warning_button)
        main.addLayout(footer)
        outer.addLayout(main, 1)

    def _sidebar(self):
        bar = QFrame()
        bar.setObjectName("sidebar")
        bar.setFixedWidth(210)
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(14, 22, 14, 18)
        layout.setSpacing(4)
        brand = QHBoxLayout()
        logo = QLabel("S")
        logo.setObjectName("logo")
        logo.setFixedSize(34, 34)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.addWidget(logo)
        brand.addWidget(label("SmartClean", "brand"), 1)
        layout.addLayout(brand)
        layout.addSpacing(22)
        self.nav = QButtonGroup(self)
        self.nav_buttons = []
        for index, text in enumerate(("Dọn dẹp", "Khôi phục", "Cài đặt")):
            item = button(text, lambda _=False, i=index: self.go(i), name="nav")
            item.setCheckable(True)
            self.nav.addButton(item, index)
            self.nav_buttons.append(item)
            layout.addWidget(item)
        self.nav_buttons[0].setChecked(True)
        layout.addStretch()
        self.side_ai = label("", "small")
        layout.addWidget(self.side_ai)
        return bar

    def go(self, index):
        self.pages.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)

    @staticmethod
    def _header(title_widget, *widgets):
        row = QHBoxLayout()
        row.addWidget(title_widget, 1)
        for widget in widgets:
            row.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
        return row

    # ---- clean: drive picker and results share one page
    def _clean_page(self):
        self.clean_stack = QStackedWidget()
        self.clean_stack.addWidget(self._picker())
        self.clean_stack.addWidget(self._results())
        return self.clean_stack

    def _picker(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        layout.addWidget(label("Chọn ổ đĩa cần dọn", "title"))
        self.drive_grid = QGridLayout()
        self.drive_grid.setSpacing(14)
        self.drive_group = QButtonGroup(self)
        self.drive_group.buttonClicked.connect(lambda card: self._pick_drive(card.drive))
        layout.addLayout(self.drive_grid)
        layout.addSpacing(6)
        row = QHBoxLayout()
        row.addStretch()
        self.scan_ai = button("✨  Quét bằng AI", self.scan_drive, ai=True)
        self.scan_ai.setMinimumSize(260, 50)
        row.addWidget(self.scan_ai)
        row.addStretch()
        layout.addLayout(row)
        self.picker_ai = label("", "small")
        self.picker_ai.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.picker_ai)
        layout.addStretch()
        return page

    def _results(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        holder = QWidget()
        title = QVBoxLayout(holder)
        title.setContentsMargins(0, 0, 0, 0)
        title.setSpacing(0)
        self.result_title = label("", "title")
        self.result_note = label("", "small")
        title.addWidget(self.result_title)
        title.addWidget(self.result_note)
        self.change_drive = button("← Đổi ổ", self.back_to_picker, name="ghost")
        self.rescan = button("Quét lại", self.scan_drive)
        layout.addLayout(self._header(holder, self.change_drive, self.rescan))

        card = QFrame()
        card.setObjectName("aicard")
        ai = QVBoxLayout(card)
        ai.setContentsMargins(18, 14, 18, 14)
        ai.setSpacing(10)
        self.ai_answer = label("", "muted")
        self.ai_answer.setStyleSheet("color:#dbe5f5;")
        ai.addWidget(self.ai_answer)
        ask_row = QHBoxLayout()
        self.question = QLineEdit()
        self.question.setMaxLength(1200)
        self.question.setPlaceholderText("Hỏi AI hoặc đặt mục tiêu, ví dụ: dọn 5 GB")
        self.question.returnPressed.connect(self.ask_ai)
        self.question.textChanged.connect(self._enable_actions)
        self.ask_button = button("Gửi", self.ask_ai, ai=True)
        ask_row.addWidget(self.question, 1)
        ask_row.addWidget(self.ask_button)
        ai.addLayout(ask_row)
        layout.addWidget(card)

        self.busy_banner = label("", "banner")
        self.busy_banner.hide()
        layout.addWidget(self.busy_banner)

        filters = QHBoxLayout()
        filters.setSpacing(6)
        self.chips = QButtonGroup(self)
        self.chip_row = QHBoxLayout()
        self.chip_row.setSpacing(6)
        filters.addLayout(self.chip_row)
        filters.addStretch()
        self.select_all = button("Chọn tất cả", lambda: self.choose(True), name="ghost")
        self.select_none = button("Bỏ chọn", lambda: self.choose(False), name="ghost")
        filters.addWidget(self.select_all)
        filters.addWidget(self.select_none)
        layout.addLayout(filters)

        self.scan_table = table(("", "Mục", "Loại", "Dung lượng", "AI"), 1)
        self.scan_table.cellClicked.connect(self._toggle_scan)
        self.scan_table.itemSelectionChanged.connect(self._scan_detail)
        toggle = QShortcut(QKeySequence(Qt.Key.Key_Space), self.scan_table, activated=self._toggle_current)
        toggle.setContext(Qt.ShortcutContext.WidgetShortcut)
        layout.addWidget(self.scan_table, 1)

        actions = QHBoxLayout()
        self.detail = label("", "small")
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        actions.addWidget(self.detail, 1)
        self.move_button = button("Dọn", self.move, primary=True)
        self.move_button.setMinimumHeight(42)
        actions.addWidget(self.move_button)
        layout.addLayout(actions)
        return page

    def _restore_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self.open_vault_button = button("Mở kho", self.open_vault, name="ghost")
        self.open_bin = button("Mở Thùng rác", self.open_recycle_bin, name="ghost")
        layout.addLayout(self._header(label("Khôi phục", "title"), self.open_bin, self.open_vault_button))
        self.record_count = label("", "muted")
        layout.addWidget(self.record_count)
        self.restore_table = table(("Mục", "Dung lượng", "Ngày dọn", "Trạng thái"), multi=True)
        self.restore_table.itemSelectionChanged.connect(self._enable_actions)
        layout.addWidget(self.restore_table, 1)
        actions = QHBoxLayout()
        actions.addWidget(label("Thư mục dự án đã dọn nằm trong Thùng rác của Windows.", "small"), 1)
        self.restore_button = button("Khôi phục", self.restore, primary=True)
        actions.addWidget(self.restore_button)
        layout.addLayout(actions)
        return page

    def _settings_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(label("Cài đặt AI", "title"))
        card = QFrame()
        card.setObjectName("card")
        form = QGridLayout(card)
        form.setContentsMargins(22, 20, 22, 20)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        form.setColumnStretch(1, 1)

        self.provider = QComboBox()
        for key, name in PROVIDERS.items():
            self.provider.addItem(name, key)
        self.provider.currentIndexChanged.connect(self._provider_changed)
        self.base_url = QLineEdit()
        self.base_url.setPlaceholderText(ai_provider.DEFAULT_BASE_URL)
        self.api_key = QLineEdit()
        self.api_key.setPlaceholderText("sk-...")
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.show_key = button("Hiện", self._toggle_key, name="ghost")
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.lineEdit().setPlaceholderText("Mặc định")
        self.load_models = button("Tải danh sách", self.fetch_models)
        self.cli_path = QLineEdit()
        self.cli_path.setPlaceholderText("Tự tìm")
        self.browse_cli = button("Chọn…", self._browse_cli)
        self.timeout = QSpinBox()
        self.timeout.setRange(20, 900)
        self.timeout.setSuffix(" giây")
        self.timeout.setFixedWidth(130)
        self.timeout.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)

        def row(index, text, *widgets):
            name = label(text, "muted")
            form.addWidget(name, index, 0)
            box = QHBoxLayout()
            stretchy = [w for w in widgets if isinstance(w, (QLineEdit, QComboBox))]
            for widget in widgets:
                box.addWidget(widget, 1 if widget in stretchy else 0)
            if not stretchy:
                box.addStretch()
            form.addLayout(box, index, 1)
            return name, widgets

        row(0, "Nguồn AI", self.provider)
        self.base_row = row(1, "Base URL", self.base_url)
        self.key_row = row(2, "API key", self.api_key, self.show_key)
        row(3, "Model", self.model, self.load_models)
        self.cli_row = row(4, "Đường dẫn CLI", self.cli_path, self.browse_cli)
        row(5, "Thời gian chờ", self.timeout)
        layout.addWidget(card)

        actions = QHBoxLayout()
        self.check_result = label("", "muted")
        actions.addWidget(self.check_result, 1)
        self.preview_button = button("Dữ liệu gửi", self.preview, name="ghost")
        self.check_button = button("Kiểm tra kết nối", self.check_ai)
        self.save_button = button("Lưu", self.save_settings, primary=True)
        actions.addWidget(self.preview_button)
        actions.addWidget(self.check_button)
        actions.addWidget(self.save_button)
        layout.addLayout(actions)
        layout.addStretch()
        return page

    # ------------------------------------------------------------------ settings
    def _load_settings(self):
        settings = ai_provider.load_settings()
        self.provider.setCurrentIndex(max(self.provider.findData(settings.provider), 0))
        self.base_url.setText(settings.base_url)
        self.api_key.setText(settings.api_key)
        self.model.setEditText(settings.model)
        self.cli_path.setText(settings.cli_path)
        self.timeout.setValue(settings.timeout)
        self._provider_changed()
        self._show_provider(settings)

    def _form_settings(self):
        return ai_provider.Settings(
            provider=self.provider.currentData(), model=self.model.currentText().strip(),
            base_url=self.base_url.text().strip() or ai_provider.DEFAULT_BASE_URL,
            api_key=self.api_key.text().strip(), cli_path=self.cli_path.text().strip(),
            timeout=self.timeout.value(),
        )

    def _show_provider(self, settings):
        model = f" · {settings.model}" if settings.model else ""
        self.side_ai.setText(f"AI: {settings.label}{model}")
        self.picker_ai.setText(f"Dùng {settings.label}{model}")

    def _provider_changed(self, *_):
        api = self.provider.currentData() == "api"
        for (name, widgets), visible in ((self.base_row, api), (self.key_row, api), (self.cli_row, not api)):
            name.setVisible(visible)
            for widget in widgets:
                widget.setVisible(visible)
        self.load_models.setVisible(self.provider.currentData() != "codex")

    def _toggle_key(self):
        hidden = self.api_key.echoMode() == QLineEdit.EchoMode.Password
        self.api_key.setEchoMode(QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password)
        self.show_key.setText("Ẩn" if hidden else "Hiện")

    def _browse_cli(self):
        path, _ = QFileDialog.getOpenFileName(self, "Chọn tệp CLI", "", "Chương trình (*.exe);;Tất cả (*)")
        if path:
            self.cli_path.setText(path)

    def _settings_message(self, text, color=MUTED):
        self.check_result.setStyleSheet(f"color:{color};")
        self.check_result.setText(text)

    def save_settings(self):
        settings = self._form_settings()
        try:
            ai_provider.save_settings(settings)
        except OSError as error:
            self._settings_message(f"Không lưu được: {error}", RED)
            return
        self._show_provider(settings)
        self._settings_message("✓ Đã lưu", GREEN)

    def check_ai(self):
        settings = self._form_settings()
        self._settings_message("Đang kiểm tra…")
        self._run("Đang kiểm tra kết nối AI…", lambda _: ai_provider.check(settings),
                  lambda message: self._settings_message("✓ " + message, GREEN),
                  failed=lambda error: self._settings_message("✗ " + error, RED))

    def fetch_models(self):
        settings = self._form_settings()

        def done(models):
            current = self.model.currentText()
            self.model.clear()
            self.model.addItems(models)
            self.model.setEditText(current or (models[0] if models else ""))
            self._settings_message(f"✓ {len(models)} model", GREEN)

        self._run("Đang tải danh sách model…", lambda _: ai_provider.list_models(settings), done,
                  failed=lambda error: self._settings_message("✗ " + error, RED))

    # ------------------------------------------------------------------ workers
    def _run(self, message, operation, callback, failed=None):
        if self.worker is not None:
            return
        self.status.setText(message)
        self.worker = Worker(operation, self)
        self.worker.result.connect(callback)
        self.worker.progress.connect(self._progress)
        self.worker.failure.connect(failed or self._failed)
        self.worker.finished.connect(self._finished)
        self.activity.setRange(0, 0)
        self.activity.show()
        self._enable_actions()
        self.worker.start()

    def _progress(self, payload):
        if isinstance(payload, tuple):
            text, done, total = payload
            self.activity.setRange(0, total)
            self.activity.setValue(done)
        else:
            text = payload
        self.status.setText(text)

    def _finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.activity.hide()
        if self.status.text().startswith(("Đang", "✨")):
            self.status.setText("")
        self._enable_actions()
        if self.smoke:
            success = not self.operation_failed and self.scan_table.rowCount() == len(self.items)
            print(f"PyQt6 smoke · {len(self.items)} candidates")
            QApplication.exit(0 if success else 1)

    def _failed(self, error):
        self.status.setText(error)
        self.operation_failed = True
        if self.smoke:
            print(error)
            return
        QMessageBox.warning(self, "SmartClean", error)

    # ------------------------------------------------------------------ drives & scan
    def start(self):
        try:
            self.drives = list_drives()
        except OSError as error:
            self._failed(str(error))
            return
        for card in self.drive_group.buttons():
            self.drive_group.removeButton(card)
            card.deleteLater()
        for index, drive in enumerate(self.drives):
            card = DriveCard(drive)
            self.drive_group.addButton(card)
            self.drive_grid.addWidget(card, index // 3, index % 3)
        current = self.drive.root if self.drive else "C:\\"
        chosen = next((d for d in self.drives if d.root == current), self.drives[0] if self.drives else None)
        if chosen:
            self._pick_drive(chosen)
        self._load_records()
        if self.smoke:
            self.scan_drive()

    def _pick_drive(self, drive):
        self.drive = drive
        for card in self.drive_group.buttons():
            card.setChecked(card.drive.root == drive.root)
        self.scan_ai.setText(f"✨  Quét ổ {drive.root.rstrip(chr(92))} bằng AI")
        self._enable_actions()

    def back_to_picker(self):
        if self.worker is None:
            self.start()
            self.clean_stack.setCurrentIndex(0)

    def _load_records(self):
        try:
            self.records, problems = self.vault.records()
            self.warnings = list(problems)
        except (OSError, CleanError) as error:
            self.records, self.warnings = [], [str(error)]
        self._fill_restore_table()

    def _scan_work(self, drive, progress, *, with_ai=True):
        items, problems = [], []
        if drive.upper().startswith("C"):
            progress("Đang quét ứng dụng trên ổ C…")
            items, problems = scan(self.vault.rules)
        progress(f"Đang quét dự án trên ổ {drive.rstrip(chr(92))}…")
        items += scan_projects(drive, progress, skip=(self.vault.root,))
        items.sort(key=lambda item: (-item.size, str(item.path)))
        records, record_warnings = self.vault.records()
        free_drive = shutil.disk_usage(drive).free
        free_vault = shutil.disk_usage(self.vault.root.anchor).free
        identities = candidates_by_id(items)
        reply, note = None, ""
        if items and with_ai and not self.smoke:
            progress("✨ AI đang phân tích…")
            data = assistant_data("Phân tích danh sách và chọn các mục nên dọn ngay, ít rủi ro.",
                                  identities, drive, free_drive, free_vault, [])
            try:
                reply = ask(data)
            except AIError as error:
                note = str(error)
        if reply is None:
            reply = local_plan(identities, 0, free_vault)
        return items, records, problems + record_warnings, free_drive, free_vault, reply, note

    def scan_drive(self):
        if self.drive is None or self.worker is not None:
            return
        drive = self.drive.root
        self._run(f"Đang quét ổ {drive.rstrip(chr(92))}…", lambda progress: self._scan_work(drive, progress),
                  self._scanned)

    def _scanned(self, data, message=""):
        items, self.records, self.warnings, self.free_drive, self.free_vault, reply, note = data
        self.items = items
        self.id_items = candidates_by_id(items)
        self.history = []
        self.clean_stack.setCurrentIndex(1)
        self.result_title.setText(f"Ổ {self.drive.root.rstrip(chr(92))}")
        total = sum(item.size for item in items)
        self.result_note.setText(f"Còn trống {units(self.free_drive)}  ·  Tìm thấy {len(items)} mục · {units(total)}")
        busy = [item for item in items if item.busy]
        if busy:
            apps = sorted({item.rule.name for item in busy})
            self.busy_banner.setText(f"Đóng {', '.join(apps)} rồi quét lại để dọn thêm {units(sum(i.size for i in busy))}")
        self.busy_banner.setVisible(bool(busy))
        self._rebuild_chips()
        self._apply_reply(reply, offline=bool(note) or self.smoke, reset=True)
        self._fill_restore_table()
        self.status.setText(message or (f"AI chưa sẵn sàng nên dùng gợi ý offline · {note}" if note else ""))

    def _apply_reply(self, reply, *, offline=False, reset=False):
        self.ai_answer.setText(("Offline · " if offline else "✨ ") + reply.answer)
        if reply.recommendations or reset:
            self.notes = {self.id_items[rec.candidate_id].path: rec for rec in reply.recommendations}
            self.checked = {self.id_items[rec.candidate_id].path for rec in reply.recommendations
                            if rec.risk != "high" and not self.id_items[rec.candidate_id].busy}
        self._fill_scan_table()

    def _rebuild_chips(self):
        for chip in self.chips.buttons():
            self.chips.removeButton(chip)
            chip.deleteLater()
        categories = sorted({item.rule.category for item in self.items})
        if self.category not in categories:
            self.category = ""
        for name in ("", *categories):
            count = sum(1 for item in self.items if not name or item.rule.category == name)
            chip = button(f"{name or 'Tất cả'}  {count}", lambda _=False, n=name: self._set_category(n), name="chip")
            chip.setCheckable(True)
            chip.setChecked(name == self.category)
            self.chips.addButton(chip)
            self.chip_row.addWidget(chip)

    def _set_category(self, name):
        self.category = name
        self._apply_filter()

    def _fill_scan_table(self):
        self.scan_table.setRowCount(len(self.items))
        for row, item in enumerate(self.items):
            self.scan_table.setItem(row, 0, check_cell(item.path in self.checked, not item.busy))
            self.scan_table.setItem(row, 1, cell(item.label, tip=str(item.path)))
            self.scan_table.setItem(row, 2, cell(item.rule.category, color=MUTED))
            self.scan_table.setItem(row, 3, cell(units(item.size), number=True))
            self.scan_table.setItem(row, 4, self._note_cell(item))
        self._apply_filter()
        self._scan_detail()

    def _note_cell(self, item):
        if item.busy:
            return cell(f"Đóng {item.rule.name}", color=AMBER)
        note = self.notes.get(item.path)
        if not note:
            return cell("—", color="#3a4d75")
        risk, color = RISKS[note.risk]
        return cell(f"● {risk}", color=color, tip=note.reason)

    def _apply_filter(self, *_):
        for row, item in enumerate(self.items):
            self.scan_table.setRowHidden(row, bool(self.category and item.rule.category != self.category))
        self._enable_actions()

    def _set_checked(self, row, state):
        item = self.items[row]
        if item.busy:
            return
        (self.checked.add if state else self.checked.discard)(item.path)
        self.scan_table.item(row, 0).setCheckState(Qt.CheckState.Checked if state else Qt.CheckState.Unchecked)

    def _toggle_scan(self, row, _column):
        if self.worker is None and 0 <= row < len(self.items):
            self._set_checked(row, self.items[row].path not in self.checked)
            self._enable_actions()

    def _toggle_current(self):
        self._toggle_scan(self.scan_table.currentRow(), 0)

    def _selected_items(self):
        return [item for item in self.items if item.path in self.checked]

    def choose(self, select):
        for row in range(len(self.items)):
            if not self.scan_table.isRowHidden(row) or not select:
                self._set_checked(row, select)
        self._enable_actions()

    def _scan_detail(self):
        row = self.scan_table.currentRow()
        if self.scan_table.selectedItems() and 0 <= row < len(self.items):
            item = self.items[row]
            note = self.notes.get(item.path)
            self.detail.setText(f"{note.reason}   ·   {item.path}" if note else str(item.path))
        else:
            self.detail.setText("")

    # ------------------------------------------------------------------ AI follow-up
    @staticmethod
    def _goal(text):
        match = GOAL_RE.search(text)
        if not match:
            return 0
        value = float(match.group(1).replace(",", "."))
        return int(value * (1024**2 if match.group(2).lower().startswith("m") else 1024**3))

    def _data(self, question):
        return assistant_data(question, self.id_items, self.drive.root if self.drive else "", self.free_drive or 0,
                              self.free_vault or 0, self.history, self._goal(question))

    def ask_ai(self):
        question = self.question.text().strip()
        if not question or self.worker is not None or self.free_drive is None:
            return
        data = self._data(question)
        self.ai_answer.setText("✨ Đang suy nghĩ…")

        def answered(reply):
            self.history.append({"question": question, "answer": reply.answer})
            self.question.clear()
            self._apply_reply(reply)

        def failed(error):
            if data["goal_bytes"]:
                self._apply_reply(local_plan(self.id_items, data["goal_bytes"], self.free_vault), offline=True)
            else:
                self.ai_answer.setText(f"AI chưa trả lời được: {error}")
            self.status.setText(error)

        self._run("✨ AI đang trả lời…", lambda _: ask(data), answered, failed=failed)

    def preview(self):
        if not self.id_items:
            QMessageBox.information(self, "Dữ liệu gửi", "Hãy quét một ổ đĩa trước.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Dữ liệu gửi cho AI")
        dialog.resize(700, 540)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label("Chỉ gồm loại mục và dung lượng, không có đường dẫn hay tên tệp thật."))
        text = QPlainTextEdit(json.dumps(self._data("<câu hỏi của bạn>"), ensure_ascii=False, indent=2))
        text.setReadOnly(True)
        layout.addWidget(text, 1)
        layout.addWidget(button("Đóng", dialog.reject), 0, Qt.AlignmentFlag.AlignRight)
        dialog.exec()

    # ------------------------------------------------------------------ state
    def _enable_actions(self, *_):
        ready = self.worker is None
        items = self._selected_items()
        size = sum(item.size for item in items)
        self.move_button.setText(f"Dọn {len(items)} mục · {units(size)}" if items else "Dọn")
        self.move_button.setEnabled(ready and bool(items))
        self.scan_ai.setEnabled(ready and self.drive is not None)
        self.rescan.setEnabled(ready)
        self.change_drive.setEnabled(ready)
        self.select_all.setEnabled(ready and any(not i.busy for i in self.items))
        self.select_none.setEnabled(ready and bool(items))
        self.question.setEnabled(ready)
        self.ask_button.setEnabled(ready and bool(self.question.text().strip()))
        restorable = self._restorable()
        self.restore_button.setText(f"Khôi phục {len(restorable)} mục" if restorable else "Khôi phục")
        self.restore_button.setEnabled(ready and bool(restorable))
        self.open_vault_button.setEnabled(self.vault.root.exists())
        for widget in (self.check_button, self.load_models, self.save_button):
            widget.setEnabled(ready)
        self.warning_button.setText(f"⚠ {len(self.warnings)}")
        self.warning_button.setVisible(ready and bool(self.warnings))

    # ------------------------------------------------------------------ cleaning
    def move(self):
        items = [item for item in self._selected_items() if not item.busy]
        if not items or self.worker is not None:
            return
        if not self.smoke and ConfirmClean(self, items, self.free_vault).exec() != QDialog.DialogCode.Accepted:
            return
        drive, before = self.drive.root, self.free_drive

        def work(progress):
            moved, total, recycled, errors = 0, 0, 0, []
            for index, item in enumerate(items, 1):
                progress((f"Đang dọn {index}/{len(items)} · {item.label}", index - 1, len(items)))
                try:
                    if isinstance(item, JunkCandidate):
                        total += recycle(item)
                        recycled += item.size
                    else:
                        total += self.vault.move(item)
                    moved += 1
                except (OSError, CleanError, ValueError) as error:
                    errors.append(f"{item.label} · {error}")
            progress(("Đang quét lại…", len(items), len(items)))
            return self._scan_work(drive, progress, with_ai=False), moved, total, recycled, errors

        self._run("Đang dọn…", work, lambda result: self._cleaned(before, *result))

    def _cleaned(self, before, data, moved, total, recycled, errors):
        self._scanned(data, f"Đã dọn {moved} mục · {units(total)}" + (f" · {len(errors)} lỗi" if errors else ""))
        self.warnings.extend(errors)
        self._enable_actions()
        if self.smoke:
            return
        gained = max(self.free_drive - before, 0)
        box = QMessageBox(self)
        box.setWindowTitle("Dọn xong")
        box.setIcon(QMessageBox.Icon.Warning if errors else QMessageBox.Icon.Information)
        box.setText(f"Đã dọn {moved} mục · {units(total)}")
        text = f"Ổ {self.drive.root.rstrip(chr(92))}: {units(before)} → {units(self.free_drive)} (+{units(gained)})"
        if recycled:
            text += f"\n{units(recycled)} đang ở Thùng rác. Dọn sạch Thùng rác để lấy lại dung lượng."
        if errors:
            text += f"\n{len(errors)} mục lỗi"
            box.setDetailedText("\n\n".join(errors))
        box.setInformativeText(text)
        box.exec()

    # ------------------------------------------------------------------ restore
    def _fill_restore_table(self):
        self.restore_table.blockSignals(True)
        self.restore_table.setRowCount(len(self.records))
        colors = {"Có thể khôi phục": GREEN, "Đã khôi phục": MUTED}
        for row, record in enumerate(self.records):
            state = self._record_state(record)
            self.restore_table.setItem(row, 0, cell(record.label, tip=str(record.source)))
            self.restore_table.setItem(row, 1, cell(units(record.size), number=True))
            self.restore_table.setItem(row, 2, cell(record.date.replace("T", "  "), color=MUTED))
            self.restore_table.setItem(row, 3, cell(state, color=colors.get(state, AMBER)))
        self.restore_table.clearSelection()
        self.restore_table.blockSignals(False)
        total = sum(record.size for record in self.records if record.state != "restored")
        self.record_count.setText(f"{len(self.records)} mục · {units(total)} trong kho")
        self._enable_actions()

    @staticmethod
    def _record_state(record):
        if record.state == "restored":
            return "Đã khôi phục"
        if record.state not in {"moved", "verified"}:
            return "Bản sao chưa hoàn tất"
        if record.source.exists():
            return "Vị trí gốc đang có dữ liệu"
        return "Có thể khôi phục"

    def _restorable(self):
        rows = sorted({index.row() for index in self.restore_table.selectionModel().selectedRows()})
        return [self.records[row] for row in rows
                if 0 <= row < len(self.records) and self._record_state(self.records[row]) == "Có thể khôi phục"]

    def restore(self):
        records = self._restorable()
        if not records:
            return
        names = "\n".join(f"• {record.label}" for record in records[:8])
        if len(records) > 8:
            names += f"\n… và {len(records) - 8} mục khác"
        if QMessageBox.question(self, "Khôi phục", f"Đưa {len(records)} mục về vị trí gốc?\n\n{names}") \
                != QMessageBox.StandardButton.Yes:
            return

        def work(progress):
            errors = []
            for index, record in enumerate(records, 1):
                progress((f"Đang khôi phục {index}/{len(records)} · {record.label}", index - 1, len(records)))
                try:
                    self.vault.restore(record.id)
                except (OSError, CleanError, ValueError) as error:
                    errors.append(f"{record.label} · {error}")
            return self.vault.records(), len(records) - len(errors), errors

        def done(result):
            (self.records, problems), count, errors = result
            self.warnings = list(problems) + errors
            self._fill_restore_table()
            self.status.setText(f"Đã khôi phục {count} mục" + (f" · {len(errors)} lỗi" if errors else ""))

        self._run("Đang khôi phục…", work, done)

    # ------------------------------------------------------------------ misc
    def show_warnings(self):
        lines = self.warnings[:10]
        if len(lines) < len(self.warnings):
            lines.append(f"Còn {len(self.warnings) - len(lines)} thông báo.")
        QMessageBox.information(self, "Chi tiết", "\n\n".join(lines))

    def open_vault(self):
        try:
            os.startfile(self.vault.root)
        except OSError as error:
            QMessageBox.warning(self, "Không mở được kho", str(error))

    def open_recycle_bin(self):
        subprocess.Popen(["explorer.exe", "shell:RecycleBinFolder"])

    def closeEvent(self, event):
        if self.worker is not None:
            self.status.setText("Đợi thao tác hiện tại hoàn tất trước khi đóng.")
            event.ignore()
        else:
            event.accept()
