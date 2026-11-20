"""Desktop views and worker lifecycle for SmartCleanAI."""

from __future__ import annotations

import json
import os
import shutil

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QHeaderView, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSplitter, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from cleaner import CleanError, Quarantine, scan, units
from codex_review import policy_snapshot, review_rules
from assistant import ask, assistant_data, candidates_by_id


STYLE = """
QWidget { background:#12191e; color:#edf5f3; }
QLabel#title { font-size:29px; font-weight:700; }
QLabel#disk { font-size:24px; font-weight:650; }
QLabel#muted { color:#a7b8bc; }
QLabel#section { font-size:17px; font-weight:650; }
QPushButton {
    border:1px solid #34464e; background:#213038; border-radius:5px; padding:7px 13px;
}
QPushButton:hover { background:#2e444c; border-color:#61837f; }
QPushButton:focus { border-color:#83e5be; }
QPushButton:disabled { color:#819398; background:#19252a; border-color:#2b3b42; }
QPushButton[primary="true"] { background:#83e5be; color:#112820; border-color:#83e5be; font-weight:650; }
QPushButton[primary="true"]:hover { background:#a5f1d1; }
QPushButton[primary="true"]:disabled { background:#29423e; border-color:#344e47; color:#9cbbb2; }
QTabWidget::pane { border:0; border-top:1px solid #34464e; }
QTabBar::tab {
    background:#12191e; color:#a7b8bc; padding:10px 17px; border-bottom:2px solid transparent;
}
QTabBar::tab:hover { color:#edf5f3; background:#1c282d; }
QTabBar::tab:selected { color:#83e5be; border-bottom-color:#83e5be; font-weight:650; }
QTableWidget {
    background:#19252b; alternate-background-color:#1d2a30; gridline-color:#34464e;
    border:1px solid #34464e; border-radius:4px; selection-background-color:#30524b;
    selection-color:#edf5f3;
}
QTableWidget::item { padding:0 7px; }
QHeaderView::section { background:#25373d; color:#e3f2ee; padding:8px; border:0; font-weight:650; }
QScrollBar:vertical { background:#19252b; width:12px; margin:2px; border:0; }
QScrollBar::handle:vertical { background:#46605f; border-radius:3px; min-height:24px; }
QScrollBar::handle:vertical:hover { background:#64817d; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background:none; }
QProgressBar { border:0; background:#34464e; border-radius:3px; }
QProgressBar::chunk { background:#83e5be; border-radius:3px; }
QPlainTextEdit, QLineEdit { background:#19252b; border:1px solid #34464e; border-radius:4px; padding:8px; }
QLineEdit:focus { border-color:#83e5be; }
QSplitter::handle { background:#2c3d43; }
"""
LEVELS = {"ok": "Hợp lý", "review": "Cần kiểm tra", "risk": "Có rủi ro"}
LEVEL_COLORS = {"ok": "#83e5be", "review": "#f6d091", "risk": "#ff9e9e"}


class Worker(QThread):
    result = pyqtSignal(object)
    failure = pyqtSignal(str)
    progress = pyqtSignal(str)

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


def button(text, callback, *, primary=False):
    result = QPushButton(text)
    if primary:
        result.setProperty("primary", True)
    result.clicked.connect(callback)
    return result


def cell(text, *, number=False):
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    if number:
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return item


def table(headers, stretch_column=0):
    view = QTableWidget(0, len(headers))
    view.setHorizontalHeaderLabels(headers)
    view.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    view.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    view.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    view.setAlternatingRowColors(True)
    view.setShowGrid(False)
    view.verticalHeader().hide()
    view.verticalHeader().setDefaultSectionSize(31)
    view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    view.horizontalHeader().setSectionResizeMode(stretch_column, QHeaderView.ResizeMode.Stretch)
    return view


class Window(QMainWindow):
    def __init__(self, vault: Quarantine, *, smoke=False):
        super().__init__()
        self.vault = vault
        self.smoke = smoke
        self.operation_failed = False
        self.worker = None
        self.items = []
        self.records = []
        self.warnings = []
        self.findings = ()
        self.review_names = {}
        self.free_c = None
        self.free_d = None
        self.assistant_history = []
        self.assistant_items = {}
        self.assistant_plan = ()
        self.setWindowTitle("SmartCleanAI · Dọn ổ C")
        self.resize(1120, 735)
        self.setMinimumSize(790, 560)
        self.setFont(QFont("Segoe UI", 10))
        self.setStyleSheet(STYLE)
        self._layout()
        self._enable_actions()

    def _layout(self):
        root = QWidget()
        self.setCentralWidget(root)
        content = QVBoxLayout(root)
        content.setContentsMargins(29, 24, 29, 19)
        content.setSpacing(11)

        header = QHBoxLayout()
        header.addWidget(label("SmartCleanAI", "title"))
        header.addStretch()
        self.scan_button = button("Quét lại", self.refresh)
        header.addWidget(self.scan_button)
        content.addLayout(header)
        self.disk = label("Dung lượng ổ C", "disk")
        self.disk_note = label()
        self.disk_bar = QProgressBar()
        self.disk_bar.setTextVisible(False)
        self.disk_bar.setFixedHeight(6)
        content.addWidget(self.disk)
        content.addWidget(self.disk_note)
        content.addWidget(self.disk_bar)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._scan_page(), "Kết quả quét")
        self.tabs.addTab(self._restore_page(), "Khôi phục")
        self.tabs.addTab(self._review_page(), "Rà soát Codex")
        self.tabs.addTab(self._assistant_page(), "Trợ lý AI")
        content.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        self.status = label("Đang chuẩn bị…")
        self.warning_button = button("Chi tiết", self.show_warnings)
        footer.addWidget(self.status, 1)
        footer.addWidget(self.warning_button)
        content.addLayout(footer)
        self.activity = QProgressBar()
        self.activity.setRange(0, 0)
        self.activity.setTextVisible(False)
        self.activity.setFixedHeight(5)
        self.activity.hide()
        content.addWidget(self.activity)

    def _scan_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        toolbar = QHBoxLayout()
        self.selection = label()
        self.select_all = button("Chọn mục sẵn sàng", lambda: self.choose(True))
        self.select_none = button("Bỏ chọn", lambda: self.choose(False))
        toolbar.addWidget(self.selection, 1)
        toolbar.addWidget(self.select_all)
        toolbar.addWidget(self.select_none)
        layout.addLayout(toolbar)

        self.scan_table = table(("Chọn", "Mục", "Loại", "Dung lượng", "Trạng thái"), 1)
        self.scan_table.itemChanged.connect(self._enable_actions)
        self.scan_table.itemSelectionChanged.connect(self._scan_detail)
        layout.addWidget(self.scan_table, 1)
        self.scan_path = label("Tích từng dòng để chọn thư mục cần chuyển.")
        self.scan_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.scan_path)
        actions = QHBoxLayout()
        actions.addStretch()
        self.move_button = button("Chuyển sang ổ D", self.move, primary=True)
        actions.addWidget(self.move_button)
        layout.addLayout(actions)
        return page

    def _restore_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        toolbar = QHBoxLayout()
        self.record_count = label("Kho khôi phục")
        self.open_vault_button = button("Mở kho trên D", self.open_vault)
        toolbar.addWidget(self.record_count, 1)
        toolbar.addWidget(self.open_vault_button)
        layout.addLayout(toolbar)

        self.restore_table = table(("Mục", "Dung lượng", "Lần chuyển", "Trạng thái"))
        self.restore_table.itemSelectionChanged.connect(self._restore_detail)
        layout.addWidget(self.restore_table, 1)
        self.restore_path = label(str(self.vault.root))
        self.restore_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.restore_path)
        actions = QHBoxLayout()
        actions.addStretch()
        self.restore_button = button("Khôi phục mục đã chọn", self.restore, primary=True)
        actions.addWidget(self.restore_button)
        layout.addLayout(actions)
        return page

    def _review_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        toolbar = QHBoxLayout()
        self.review_note = label("Gửi mẫu quy tắc và số liệu tổng hợp đến Codex để nhận đánh giá.")
        self.preview_button = button("Xem dữ liệu gửi", self.preview)
        self.review_button = button("Kiểm tra bằng Codex", self.codex_review, primary=True)
        toolbar.addWidget(self.review_note, 1)
        toolbar.addWidget(self.preview_button)
        toolbar.addWidget(self.review_button)
        layout.addLayout(toolbar)
        self.review_summary = label("Codex dùng phiên đăng nhập CLI trên máy. Kết quả là nhận xét để bạn cân nhắc.")
        layout.addWidget(self.review_summary)

        split = QSplitter(Qt.Orientation.Vertical)
        self.review_table = table(("Quy tắc", "Đánh giá"))
        self.review_table.itemSelectionChanged.connect(self._review_detail)
        self.review_details = QPlainTextEdit()
        self.review_details.setReadOnly(True)
        self.review_details.setPlaceholderText("Chọn một quy tắc để xem nhận xét và đề xuất.")
        split.addWidget(self.review_table)
        split.addWidget(self.review_details)
        split.setSizes([270, 130])
        layout.addWidget(split, 1)
        return page

    def _assistant_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 10, 0, 0)
        toolbar = QHBoxLayout()
        toolbar.addWidget(label("Hỏi về các mục trong lần quét hoặc đặt mục tiêu dung lượng."), 1)
        self.assistant_preview = button("Xem dữ liệu gửi", self.preview_assistant)
        self.new_chat = button("Cuộc trò chuyện mới", self.clear_assistant)
        toolbar.addWidget(self.assistant_preview)
        toolbar.addWidget(self.new_chat)
        layout.addLayout(toolbar)

        suggestions = QHBoxLayout()
        self.suggest_first = button("Dọn gì trước?", lambda: self._suggest(
            "Trong các mục đã quét, nên dọn gì trước để giải phóng dung lượng mà ít ảnh hưởng nhất?"
        ))
        self.suggest_goal = button("Gợi ý 2 GiB", lambda: self._suggest(
            "Lập kế hoạch giải phóng khoảng 2 GiB, ưu tiên các mục sẵn sàng và dễ khôi phục."
        ))
        suggestions.addWidget(self.suggest_first)
        suggestions.addWidget(self.suggest_goal)
        suggestions.addStretch()
        layout.addLayout(suggestions)

        split = QSplitter(Qt.Orientation.Vertical)
        self.chat = QPlainTextEdit()
        self.chat.setReadOnly(True)
        self.chat.setPlaceholderText("Câu trả lời và các lượt hỏi tiếp sẽ hiện ở đây.")
        split.addWidget(self.chat)
        plan = QWidget()
        plan_layout = QVBoxLayout(plan)
        plan_layout.setContentsMargins(0, 6, 0, 0)
        self.plan_note = label("Kế hoạch dọn")
        plan_layout.addWidget(self.plan_note)
        self.plan_table = table(("Mục đề xuất", "Dung lượng", "Trạng thái", "Lý do"), 3)
        self.plan_table.setWordWrap(False)
        plan_layout.addWidget(self.plan_table, 1)
        plan_actions = QHBoxLayout()
        plan_actions.addStretch()
        self.select_plan_button = button("Chỉ tích mục sẵn sàng trong kế hoạch", self.select_plan)
        plan_actions.addWidget(self.select_plan_button)
        plan_layout.addLayout(plan_actions)
        split.addWidget(plan)
        split.setSizes([180, 240])
        layout.addWidget(split, 1)

        composer = QHBoxLayout()
        self.question = QLineEdit()
        self.question.setMaxLength(1200)
        self.question.setPlaceholderText("Nhập câu hỏi về việc dọn ổ C")
        self.question.returnPressed.connect(self.ask_assistant)
        self.question.textChanged.connect(self._enable_actions)
        self.ask_button = button("Gửi cho AI", self.ask_assistant, primary=True)
        composer.addWidget(self.question, 1)
        composer.addWidget(self.ask_button)
        layout.addLayout(composer)
        return page

    def _run(self, message, operation, callback):
        if self.worker is not None:
            return
        self.status.setText(message)
        self.worker = Worker(operation, self)
        self.worker.result.connect(callback)
        self.worker.progress.connect(self.status.setText)
        self.worker.failure.connect(self._failed)
        self.worker.finished.connect(self._finished)
        self.activity.show()
        self._enable_actions()
        self.worker.start()

    def _finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.activity.hide()
        self._enable_actions()
        if self.smoke:
            success = (not self.operation_failed and self.scan_table.rowCount() == len(self.items)
                       and self.disk_bar.value() >= 0)
            print(f"PyQt6 smoke · {len(self.items)} candidates")
            QApplication.exit(0 if success else 1)

    def _failed(self, error):
        self.status.setText(error)
        self.operation_failed = True
        if self.smoke:
            print(error)
            return
        QMessageBox.warning(self, "SmartCleanAI", error)

    def _load(self):
        items, problems = scan(self.vault.rules)
        records, record_warnings = self.vault.records()
        return items, records, problems + record_warnings, shutil.disk_usage("C:/"), shutil.disk_usage("D:/")

    def refresh(self):
        self._run("Đang quét ổ C…", lambda _: self._load(), self._loaded)

    def _loaded(self, data, message="", errors=()):
        self.items, self.records, self.warnings, disk_c, disk_d = data
        self.warnings.extend(errors)
        self.free_c, self.free_d = disk_c.free, disk_d.free
        if self.assistant_plan:
            self._reset_plan("Đã quét lại. Hỏi trợ lý để lấy kế hoạch theo kết quả mới.")
        self.assistant_items = candidates_by_id(self.items)
        self.disk.setText(f"{units(disk_c.free)} trống trên ổ C")
        self.disk_note.setText(f"Đã dùng {units(disk_c.used)} / {units(disk_c.total)}   ·   Ổ D còn {units(disk_d.free)}")
        self.disk_bar.setValue(round(100 * disk_c.used / disk_c.total))

        self.scan_table.blockSignals(True)
        self.scan_table.clearContents()
        self.scan_table.setRowCount(len(self.items))
        for row, item in enumerate(self.items):
            check = cell("—" if item.busy else "")
            if not item.busy:
                check.setFlags(check.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                check.setCheckState(Qt.CheckState.Unchecked)
            self.scan_table.setItem(row, 0, check)
            status = f"Thoát {item.rule.name} để dọn" if item.busy else "Sẵn sàng"
            for col, value in enumerate((item.label, item.rule.category, units(item.size), status), 1):
                self.scan_table.setItem(row, col, cell(value, number=col == 3))
            self.scan_table.item(row, 1).setToolTip(str(item.path))
        self.scan_table.clearSelection()
        self.scan_table.blockSignals(False)
        self._scan_detail()

        self.restore_table.blockSignals(True)
        self.restore_table.clearContents()
        self.restore_table.setRowCount(len(self.records))
        for row, record in enumerate(self.records):
            values = (record.label, units(record.size), record.date.replace("T", " "), self._record_state(record))
            for col, value in enumerate(values):
                self.restore_table.setItem(row, col, cell(value, number=col == 1))
        self.restore_table.clearSelection()
        self.restore_table.blockSignals(False)
        self.record_count.setText(f"{len(self.records)} hồ sơ trong kho khôi phục")
        self._restore_detail()
        self.status.setText(message or f"Tìm thấy {len(self.items)} mục · {units(sum(i.size for i in self.items))}")

    def _selected_items(self):
        return [item for row, item in enumerate(self.items)
                if self.scan_table.item(row, 0).checkState() == Qt.CheckState.Checked]

    def choose(self, select):
        self.scan_table.blockSignals(True)
        state = Qt.CheckState.Checked if select else Qt.CheckState.Unchecked
        for row, item in enumerate(self.items):
            if not item.busy:
                self.scan_table.item(row, 0).setCheckState(state)
        self.scan_table.blockSignals(False)
        self._enable_actions()

    def _scan_detail(self):
        row = self.scan_table.currentRow()
        selected = self.scan_table.selectedItems()
        self.scan_path.setText(str(self.items[row].path) if selected and 0 <= row < len(self.items)
                               else "Tích từng dòng để chọn thư mục cần chuyển.")

    @staticmethod
    def _record_state(record):
        if record.state == "restored":
            return "Đã khôi phục"
        if record.state not in {"moved", "verified"}:
            return "Bản sao chưa hoàn tất"
        if record.source.exists():
            return "Vị trí gốc đang có dữ liệu"
        return "Có thể khôi phục"

    def _selected_record(self):
        row = self.restore_table.currentRow()
        return self.records[row] if self.restore_table.selectedItems() and 0 <= row < len(self.records) else None

    def _restore_detail(self):
        record = self._selected_record()
        self.restore_path.setText(str(record.source) if record else str(self.vault.root))
        self._enable_actions()

    def _enable_actions(self, *_):
        ready = self.worker is None
        items = self._selected_items()
        record = self._selected_record()
        self.selection.setText(f"Đã chọn {len(items)} mục · {units(sum(i.size for i in items))}")
        self.scan_button.setEnabled(ready)
        self.select_all.setEnabled(ready and any(not item.busy for item in self.items))
        self.select_none.setEnabled(ready and bool(items))
        self.move_button.setEnabled(ready and bool(items))
        self.restore_button.setEnabled(ready and record is not None and self._record_state(record) == "Có thể khôi phục")
        self.open_vault_button.setEnabled(ready and self.vault.root.exists())
        self.review_button.setEnabled(ready)
        self.warning_button.setEnabled(ready and bool(self.warnings))
        self.question.setEnabled(ready)
        self.ask_button.setEnabled(ready and self.free_c is not None and bool(self.question.text().strip()))
        self.assistant_preview.setEnabled(ready and self.free_c is not None)
        self.new_chat.setEnabled(ready and bool(self.assistant_history))
        self.suggest_first.setEnabled(ready)
        self.suggest_goal.setEnabled(ready)
        self.select_plan_button.setEnabled(ready and self._plan_fits())

    def move(self):
        items = self._selected_items()
        if not items:
            return
        size = units(sum(item.size for item in items))
        if QMessageBox.question(
            self, "Chuyển sang ổ D", f"Chuyển {len(items)} mục ({size}) sang:\n{self.vault.root}"
        ) != QMessageBox.StandardButton.Yes:
            return

        def work(progress):
            moved, total, errors = 0, 0, []
            for index, item in enumerate(items, 1):
                progress(f"Đang chuyển {index}/{len(items)} · {item.label}")
                try:
                    total += self.vault.move(item)
                    moved += 1
                except (OSError, CleanError, ValueError) as error:
                    errors.append(f"{item.label} · {error}")
            tail = f" · {len(errors)} mục cần kiểm tra" if errors else ""
            return self._load(), f"Đã chuyển {moved} mục · {units(total)}{tail}", errors

        self._run("Đang chuyển…", work, lambda result: self._loaded(*result))

    def restore(self):
        record = self._selected_record()
        if not record or QMessageBox.question(
            self, "Khôi phục", f"Đưa mục đã chọn về vị trí gốc?\n\n{record.source}"
        ) != QMessageBox.StandardButton.Yes:
            return

        def work(_):
            self.vault.restore(record.id)
            return self._load()

        self._run(f"Đang khôi phục {record.label}…", work,
                  lambda data: self._loaded(data, "Đã khôi phục về vị trí gốc."))

    def _preview(self, description, data):
        dialog = QDialog(self)
        dialog.setWindowTitle("Dữ liệu gửi tới Codex")
        dialog.resize(680, 515)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label(description))
        preview = QPlainTextEdit(json.dumps(data, ensure_ascii=False, indent=2))
        preview.setReadOnly(True)
        layout.addWidget(preview, 1)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        dialog.exec()

    def preview(self):
        self._preview("Đường dẫn mẫu và số liệu từ lần quét hiện tại.", policy_snapshot(self.items))

    def codex_review(self):
        snapshot = policy_snapshot(self.items)
        self._run("Đang đợi Codex rà soát…", lambda _: review_rules(snapshot),
                  lambda result: self._reviewed(result, snapshot))

    def _reviewed(self, report, snapshot):
        self.review_names = {
            rule["id"]: f"{rule['app']} · {rule['category']}" for rule in snapshot["active_rules"]
        }
        self.review_names.update({rule["id"]: rule["name"] for rule in snapshot["prior_methods"]})
        self.findings = tuple(sorted(report.findings, key=lambda item: ("risk", "review", "ok").index(item.status)))
        self.review_summary.setText(report.summary)
        self.review_table.clearSelection()
        self.review_table.setRowCount(len(self.findings))
        for row, finding in enumerate(self.findings):
            self.review_table.setItem(row, 0, cell(self.review_names[finding.rule_id]))
            level = cell(LEVELS[finding.status])
            level.setForeground(QColor(LEVEL_COLORS[finding.status]))
            self.review_table.setItem(row, 1, level)
        if self.findings:
            self.review_table.selectRow(0)
            self._review_detail()
        self.status.setText(f"Codex đã rà soát {len(self.findings)} nhóm quy tắc.")

    def _review_detail(self):
        row = self.review_table.currentRow()
        if self.review_table.selectedItems() and 0 <= row < len(self.findings):
            finding = self.findings[row]
            self.review_details.setPlainText(f"{finding.observation}\n\nĐề xuất\n{finding.recommendation}")
        else:
            self.review_details.clear()

    def _suggest(self, text):
        self.question.setText(text)
        self.question.setFocus()

    def _assistant_data(self, question):
        return assistant_data(question, self.assistant_items, self.free_c, self.free_d, self.assistant_history)

    def preview_assistant(self):
        self._preview("Câu hỏi, tối đa 3 lượt gần nhất và số liệu quét theo mã mục.",
                      self._assistant_data(self.question.text().strip()))

    def ask_assistant(self):
        question = self.question.text().strip()
        if self.worker is not None or self.free_c is None or not question:
            return
        data = self._assistant_data(question)
        self._run("Đang đợi trợ lý AI…", lambda _: ask(data),
                  lambda reply: self._assistant_answer(question, reply))

    def _assistant_answer(self, question, reply):
        self.assistant_history.append({"question": question, "answer": reply.answer})
        self.chat.appendPlainText(f"Bạn\n{question}\n\nTrợ lý AI\n{reply.answer}\n")
        self.question.clear()
        self.assistant_plan = reply.recommendations
        self.plan_table.setRowCount(len(self.assistant_plan))
        for row, recommendation in enumerate(self.assistant_plan):
            item = self.assistant_items[recommendation.candidate_id]
            state = f"Thoát {item.rule.name}" if item.busy else "Sẵn sàng"
            values = (item.label, units(item.size), state, recommendation.reason)
            for col, value in enumerate(values):
                field = cell(value, number=col == 1)
                field.setToolTip(value if col != 0 else str(item.path))
                self.plan_table.setItem(row, col, field)
        ready = self._ready_plan()
        amount = sum(item.size for item in ready)
        total = sum(self.assistant_items[rec.candidate_id].size for rec in self.assistant_plan)
        if self.assistant_plan:
            suffix = "   ·   Ổ D không đủ cho phần sẵn sàng" if ready and not self._plan_fits() else ""
            self.plan_note.setText(f"{len(self.assistant_plan)} mục · {units(total)}   ·   "
                                   f"Sẵn sàng {len(ready)} mục · {units(amount)}{suffix}")
        else:
            self.plan_note.setText("Lượt này chỉ có phần giải thích.")
        self.status.setText("Trợ lý AI đã trả lời.")

    def _ready_plan(self):
        return [self.assistant_items[rec.candidate_id] for rec in self.assistant_plan
                if not self.assistant_items[rec.candidate_id].busy]

    def _plan_fits(self):
        ready = self._ready_plan()
        return bool(ready) and sum(item.size for item in ready) + 32 * 1024**2 <= self.free_d

    def _reset_plan(self, message):
        self.assistant_plan = ()
        self.plan_table.setRowCount(0)
        self.plan_note.setText(message)

    def clear_assistant(self):
        self.assistant_history.clear()
        self.chat.clear()
        self.question.clear()
        self._reset_plan("Kế hoạch dọn")
        self._enable_actions()

    def select_plan(self):
        if self.worker is not None or not self._plan_fits():
            return
        paths = {item.path for item in self._ready_plan()}
        self.scan_table.blockSignals(True)
        for row, item in enumerate(self.items):
            if not item.busy:
                self.scan_table.item(row, 0).setCheckState(
                    Qt.CheckState.Checked if item.path in paths else Qt.CheckState.Unchecked
                )
        self.scan_table.blockSignals(False)
        self.tabs.setCurrentIndex(0)
        self.status.setText("Đã tích các mục sẵn sàng trong kế hoạch. Kiểm tra trước khi chuyển.")
        self._enable_actions()

    def show_warnings(self):
        lines = self.warnings[:10]
        if len(lines) < len(self.warnings):
            lines.append(f"Còn {len(self.warnings) - len(lines)} thông báo.")
        QMessageBox.information(self, "Chi tiết quét và dọn", "\n\n".join(lines))

    def open_vault(self):
        try:
            os.startfile(self.vault.root)
        except OSError as error:
            QMessageBox.warning(self, "Không mở được kho", str(error))

    def closeEvent(self, event):
        if self.worker is not None:
            self.status.setText("Đợi thao tác hiện tại hoàn tất trước khi đóng.")
            event.ignore()
        else:
            event.accept()
