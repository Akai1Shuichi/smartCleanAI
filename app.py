"""PyQt6 interface for scanning, quarantine, recovery, and Codex review."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from cleaner import Quarantine, build_rules, scan, units


def main():
    parser = argparse.ArgumentParser(description="SmartCleanAI — dọn ổ C trên Windows.")
    parser.add_argument("--scan", action="store_true", help="In kết quả quét, không thay đổi tệp.")
    parser.add_argument("--smoke", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("SmartCleanAI hỗ trợ Windows.")
    rules = build_rules(Path(os.environ["LOCALAPPDATA"]), Path(os.environ["APPDATA"]))
    vault = Quarantine(Path(__file__).resolve().parent / "quarantine", rules)
    if args.scan:
        sys.stdout.reconfigure(encoding="utf-8")
        items, warnings = scan(rules)
        for item in items:
            print(f"{units(item.size):>12}  {'Đang mở' if item.busy else 'Sẵn sàng':<10}  {item.path}")
        print(f"{len(items)} mục · {units(sum(item.size for item in items))}")
        for warning in warnings:
            print(f"Bỏ qua: {warning}")
        return 0

    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication

    from ui import Window

    app = QApplication([])
    app.setApplicationName("SmartCleanAI")
    app.setStyle("Fusion")
    window = Window(vault, smoke=args.smoke)
    if not args.smoke:
        window.show()
    QTimer.singleShot(0, window.start)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
