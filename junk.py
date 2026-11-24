"""Drive listing and regenerable project folders (node_modules, build caches) on any fixed drive.

Project folders are only listed when their parent looks like a real project (package.json plus a
lock file or .git), so modules shipped inside installed apps are never touched. They are cleaned by
moving to the Windows Recycle Bin, which the user can undo.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import stat
import time
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path

from cleaner import CleanError, checked_path

MIN_SIZE = 20 * 1024**2
MAX_DEPTH = 9
LOCKS = ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "bun.lock")
PY_MARKERS = ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "pytest.ini", "tox.ini")
# folder name -> (display kind, marker check)
KINDS = {
    "node_modules": "Thư viện Node",
    ".next": "Build Next.js",
    ".nuxt": "Build Nuxt",
    ".turbo": "Cache Turborepo",
    ".parcel-cache": "Cache Parcel",
    ".angular": "Cache Angular",
    ".pytest_cache": "Cache pytest",
    ".mypy_cache": "Cache mypy",
    ".ruff_cache": "Cache Ruff",
}
SKIP = {
    "windows", "program files", "program files (x86)", "programdata", "$recycle.bin", "recovery",
    "system volume information", "$winreagent", "$windows.~bt", "$windows.~ws", "appdata", "msocache",
    ".git", ".vscode", ".cursor", ".windsurf", ".antigravity", ".venv", "venv", "env", "site-packages",
    ".cargo", ".rustup", ".nuget", ".gradle", ".m2", ".conda", "anaconda3", "miniconda3", "scoop",
    "quarantine", "onedrive", "steamapps", "windowsapps",
}


@dataclass(frozen=True)
class JunkRule:
    name: str
    category: str = "Dự án lập trình"
    processes: tuple = ()
    relative: str = ""
    version_folder: str = ""


@dataclass(frozen=True)
class JunkCandidate:
    path: Path
    kind: str
    size: int
    files: int
    age_days: int
    busy: bool = False
    rule: JunkRule = field(default=None)

    @property
    def label(self):
        return f"{self.path.parent.name} · {self.path.name}"


@dataclass(frozen=True)
class Drive:
    root: str
    name: str
    total: int
    free: int

    @property
    def used(self):
        return self.total - self.free


def list_drives() -> list[Drive]:
    kernel = ctypes.windll.kernel32
    mask = kernel.GetLogicalDrives()
    drives = []
    for index in range(26):
        if not mask & (1 << index):
            continue
        root = f"{chr(65 + index)}:\\"
        if kernel.GetDriveTypeW(root) != 3:  # DRIVE_FIXED
            continue
        label = ctypes.create_unicode_buffer(261)
        kernel.GetVolumeInformationW(root, label, 261, None, None, None, None, 0)
        try:
            usage = shutil.disk_usage(root)
        except OSError:
            continue
        drives.append(Drive(root, label.value or "Ổ cục bộ", usage.total, usage.free))
    return drives


def _is_project(folder: Path, name: str) -> bool:
    try:
        entries = {entry.casefold() for entry in os.listdir(folder)}
    except OSError:
        return False
    if name == "node_modules" or name in {".next", ".nuxt", ".turbo", ".parcel-cache", ".angular"}:
        return "package.json" in entries and (".git" in entries or any(lock in entries for lock in LOCKS))
    return ".git" in entries or any(marker in entries for marker in PY_MARKERS)


def _measure(root: Path) -> tuple[int, int, float]:
    size = files = 0
    newest = 0.0
    stack = [root]
    while stack:
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                        continue
                    if stat.S_ISDIR(info.st_mode):
                        stack.append(Path(entry.path))
                    else:
                        size += info.st_size
                        files += 1
        except OSError:
            continue
    try:
        with os.scandir(root.parent) as entries:
            for entry in entries:
                if entry.name.casefold() not in KINDS:
                    try:
                        newest = max(newest, entry.stat(follow_symlinks=False).st_mtime)
                    except OSError:
                        pass
    except OSError:
        pass
    return size, files, newest


def scan_projects(drive: str, progress=None, skip: tuple[Path, ...] = ()) -> list[JunkCandidate]:
    root = Path(drive)
    skipped = {path.resolve() for path in skip if path.exists()}
    found, stack, seen, now = [], [(root, 0)], 0, time.time()
    while stack:
        folder, depth = stack.pop()
        try:
            iterator = os.scandir(folder)
        except OSError:
            continue
        with iterator as entries:
            for entry in entries:
                try:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if info.st_file_attributes & (stat.FILE_ATTRIBUTE_REPARSE_POINT | stat.FILE_ATTRIBUTE_SYSTEM):
                    continue
                name = entry.name.casefold()
                path = Path(entry.path)
                if name in KINDS:
                    if _is_project(folder, name):
                        size, files, newest = _measure(path)
                        if size >= MIN_SIZE:
                            age = int((now - newest) // 86400) if newest else 0
                            found.append(JunkCandidate(path, name, size, files, max(age, 0),
                                                       rule=JunkRule(KINDS[name])))
                    continue
                if name in SKIP or depth >= MAX_DEPTH or path in skipped:
                    continue
                stack.append((path, depth + 1))
        seen += 1
        if progress and seen % 400 == 0:
            progress(f"Đang quét {drive} · {folder}")
    return found


# ---------------------------------------------------------------- Recycle Bin
class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


FO_DELETE = 3
FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI, FOF_WANTNUKEWARNING = 0x4, 0x10, 0x40, 0x400, 0x4000


def recycle(candidate: JunkCandidate) -> int:
    path = candidate.path
    checked_path(path)
    if path.name.casefold() not in KINDS or not _is_project(path.parent, path.name.casefold()):
        raise CleanError("Thư mục đã thay đổi, hãy quét lại.")
    operation = _SHFILEOPSTRUCTW(
        None, FO_DELETE, str(path) + "\0", None,
        FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI | FOF_WANTNUKEWARNING,
        False, None, None,
    )
    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    if code or operation.fAnyOperationsAborted:
        raise CleanError(f"Không chuyển được vào Thùng rác (mã {code}). Có thể tệp đang được dùng.")
    return candidate.size
