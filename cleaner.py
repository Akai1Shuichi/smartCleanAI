"""Windows scan rules and reversible transfers from C: to the quarantine drive."""

from __future__ import annotations

import csv
import ctypes
import json
import os
import re
import shutil
import stat
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

if os.name == "nt":
    import msvcrt
    import winreg

    _copy_file = ctypes.WinDLL("kernel32", use_last_error=True).CopyFileW
    _copy_file.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int]
    _copy_file.restype = ctypes.c_int


@dataclass(frozen=True)
class Rule:
    name: str
    category: str
    root: Path
    relative: str
    processes: tuple[str, ...]
    version_folder: str = ""
    executable: str = ""
    absent_executable: Path | None = None


@dataclass(frozen=True)
class Candidate:
    rule: Rule
    path: Path
    size: int
    files: int
    busy: bool

    @property
    def label(self):
        relative = self.path.relative_to(self.rule.root).as_posix()
        return f"{self.rule.name} · {relative}"


@dataclass(frozen=True)
class Record:
    id: str
    source: Path
    label: str
    size: int
    date: str
    state: str


class CleanError(Exception):
    pass


def units(value: int) -> str:
    for suffix, divisor in (("GiB", 1024**3), ("MiB", 1024**2), ("KiB", 1024)):
        if value >= divisor:
            return f"{value / divisor:,.2f} {suffix}"
    return f"{value} B"


def copy_windows_file(source, destination):
    """Copy on NTFS with Windows attributes and alternate data streams intact."""
    def extended(path):
        path = os.fsdecode(path)
        return "\\\\?\\" + path if len(path) >= 248 else path

    if not _copy_file(extended(source), extended(destination), 1):
        raise ctypes.WinError(ctypes.get_last_error())
    return destination


def remove_staging(path: Path):
    def retry(function, name, error):
        item = checked_path(Path(name))
        if not isinstance(error[1], PermissionError) or not item.is_file():
            raise error[1]
        item.chmod(stat.S_IWRITE)
        function(item)

    shutil.rmtree(checked_path(path), onerror=retry)


def build_rules(local: Path, roaming: Path) -> tuple[Rule, ...]:
    return (
        Rule("CapCut", "Bản cũ", local / "CapCut" / "Apps", "[0-9]*",
             ("capcut.exe", "capcutlauncher.exe", "capcutupdater.exe"),
             r"([0-9]+(?:\.[0-9]+){3})", "CapCut.exe"),
        Rule("Zalo", "Bản cũ", local / "Programs" / "Zalo", "Zalo-*",
             ("zalo.exe", "zalocall.exe", "zalocap.exe", "zaloupdater.exe"),
             r"Zalo-([0-9]+(?:\.[0-9]+){2})", "Zalo.exe"),
        Rule("Postman", "Bản cũ", local / "Postman", "app-*", ("postman.exe",),
             r"app-([0-9]+(?:\.[0-9]+){2})", "Postman.exe"),
        Rule("CapCut", "Cache", local / "CapCut" / "User Data" / "Cache",
             "SmartCrop", ("capcut.exe", "capcutlauncher.exe")),
        Rule("CapCut", "Cache", local / "CapCut" / "User Data" / "Cache",
             "frameThumbnail", ("capcut.exe", "capcutlauncher.exe")),
        Rule("CapCut", "Cache", local / "CapCut" / "User Data" / "Cache",
             "RemuxCache", ("capcut.exe", "capcutlauncher.exe")),
        Rule("VS Code", "Cache", roaming / "Code", "CachedExtensionVSIXs", ("code.exe",)),
        Rule("VS Code", "Báo cáo lỗi", roaming / "Code" / "Crashpad", "reports", ("code.exe",)),
        Rule("VS Code", "Cache", roaming / "Code", "CachedData", ("code.exe",)),
        *(
            Rule(name, "Cache", local.joinpath(*root), f"{profile}/{cache}", (exe,))
            for name, root, exe in (
                ("Chrome", ("Google", "Chrome", "User Data"), "chrome.exe"),
                ("Edge", ("Microsoft", "Edge", "User Data"), "msedge.exe"),
            )
            for profile in ("Default", "Profile [0-9]*")
            for cache in ("Cache", "Code Cache", "GPUCache")
        ),
        Rule("GoLogin", "Bộ cài sót", local, "gologin-updater", ("gologin.exe",),
             absent_executable=local / "Programs" / "GoLogin" / "GoLogin.exe"),
        Rule("Antigravity", "Bộ cài sót", local, "antigravity-updater", ("antigravity.exe",),
             absent_executable=local / "Programs" / "Antigravity" / "Antigravity.exe"),
        Rule("Antigravity", "Báo cáo lỗi", roaming / "Antigravity" / "Crashpad",
             "reports", ("antigravity.exe",)),
    )


def installed_apps() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                root = winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ | view)
            except FileNotFoundError:
                continue
            with root:
                for index in range(winreg.QueryInfoKey(root)[0]):
                    try:
                        with winreg.OpenKey(root, winreg.EnumKey(root, index)) as key:
                            name = str(winreg.QueryValueEx(key, "DisplayName")[0]).casefold()
                            try:
                                version = str(winreg.QueryValueEx(key, "DisplayVersion")[0])
                            except FileNotFoundError:
                                version = ""
                            found.setdefault(name, set()).add(version)
                    except FileNotFoundError:
                        continue
    return found


def running_processes() -> set[str]:
    tasklist = Path(os.environ["SystemRoot"]) / "System32" / "tasklist.exe"
    result = subprocess.run(
        [str(tasklist), "/FO", "CSV", "/NH"], capture_output=True, text=True,
        errors="replace", check=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    names = {row[0].casefold() for row in csv.reader(result.stdout.splitlines()) if len(row) == 5}
    if not names:
        raise CleanError("Không đọc được danh sách tiến trình Windows.")
    return names


def checked_path(path: Path, *, exists: bool = True) -> Path:
    """Reject NTFS junctions, symlinks and other reparse points in the whole path."""
    if not path.is_absolute() or ".." in path.parts:
        raise CleanError(f"Đường dẫn không hợp lệ: {path}")
    for part in reversed((path, *path.parents)):
        try:
            info = part.lstat()
        except FileNotFoundError:
            if not exists and part == path:
                break
            raise
        if info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise CleanError(f"Bỏ qua đường dẫn liên kết: {part}")
    return path


def snapshot(root: Path) -> dict[str, tuple[int, int] | None]:
    checked_path(root)
    paths = [root]
    items: dict[str, tuple[int, int] | None] = {}
    while paths:
        with os.scandir(paths.pop()) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                child = Path(entry.path)
                if info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    raise CleanError(f"Bỏ qua thư mục có liên kết: {child}")
                relative = child.relative_to(root).as_posix()
                if stat.S_ISDIR(info.st_mode):
                    items[relative] = None
                    paths.append(child)
                elif stat.S_ISREG(info.st_mode):
                    items[relative] = (info.st_size, info.st_mtime_ns)
                else:
                    raise CleanError(f"Loại tệp chưa hỗ trợ: {child}")
    return items


def old_version(rule: Rule, path: Path, installed: dict[str, set[str]]) -> bool:
    matches = re.fullmatch(rule.version_folder, path.name, re.IGNORECASE)
    if not matches:
        return False
    version_options = {
        version for name, versions in installed.items()
        if name == rule.name.casefold() or name.startswith(rule.name.casefold() + " ")
        for version in versions if re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", version)
    }
    if len(version_options) != 1:
        return False
    current = next(iter(version_options))
    prefix = {"CapCut": "", "Zalo": "Zalo-", "Postman": "app-"}[rule.name]
    current_exe = rule.root / (prefix + current) / rule.executable
    try:
        valid_exe = checked_path(current_exe).is_file()
    except (OSError, CleanError):
        return False
    return valid_exe and tuple(map(int, matches[1].split("."))) < tuple(map(int, current.split(".")))


def matches_rule(rule: Rule, path: Path) -> bool:
    if not path.is_relative_to(rule.root):
        return False
    relative = path.relative_to(rule.root)
    if len(relative.parts) != len(rule.relative.split("/")) or not relative.match(rule.relative):
        return False
    if rule.version_folder:
        return re.fullmatch(rule.version_folder, path.name, re.IGNORECASE) is not None
    if rule.relative.startswith("Profile "):
        return re.fullmatch(r"Profile [0-9]+", relative.parts[0], re.IGNORECASE) is not None
    return True


def eligible(rule: Rule, path: Path, installed: dict[str, set[str]]) -> bool:
    if path.drive.upper() != "C:" or not matches_rule(rule, path):
        return False
    if rule.version_folder:
        return old_version(rule, path, installed)
    if rule.absent_executable:
        app_name = rule.name.casefold()
        return not rule.absent_executable.exists() and not any(
            name == app_name or name.startswith(app_name + " ") for name in installed
        )
    return True


def scan(rules: tuple[Rule, ...]) -> tuple[list[Candidate], list[str]]:
    installed, running = installed_apps(), running_processes()
    found, skipped = [], []
    for rule in rules:
        try:
            checked_path(rule.root)
        except FileNotFoundError:
            continue
        except (OSError, CleanError) as error:
            skipped.append(str(error))
            continue
        for path in rule.root.glob(rule.relative):
            if not eligible(rule, path, installed):
                continue
            try:
                files = [info for info in snapshot(path).values() if info is not None]
            except (OSError, CleanError) as error:
                skipped.append(str(error))
                continue
            size = sum(info[0] for info in files)
            if size:
                found.append(Candidate(rule, path, size, len(files), bool(running.intersection(rule.processes))))
    return sorted(found, key=lambda item: (-item.size, str(item.path))), skipped


class Quarantine:
    def __init__(self, root: Path, rules: tuple[Rule, ...]):
        if root.drive.upper() != "D:" or root == Path("D:/"):
            raise CleanError("Khu vực khôi phục phải là một thư mục trên ổ D.")
        self.root = root
        self.rules = rules

    @contextmanager
    def _lock(self):
        checked_path(self.root, exists=False)
        self.root.mkdir(exist_ok=True)
        lock = checked_path(self.root / ".lock", exists=False)
        with lock.open("a+b") as handle:
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise CleanError("Một phiên SmartCleanAI khác đang xử lý tệp.") from error
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    def _write(self, folder: Path, record: Record, state: str):
        temporary = folder / f"{uuid4().hex}.tmp"
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump({
                "id": record.id, "source": str(record.source), "label": record.label,
                "size": record.size, "date": record.date, "state": state,
            }, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(folder / "record.json")

    def _read(self, folder: Path) -> Record:
        manifest = checked_path(folder / "record.json")
        data = json.loads(manifest.read_text(encoding="utf-8"))
        record = Record(data["id"], Path(data["source"]), data["label"],
                        int(data["size"]), data["date"], data["state"])
        if record.id != folder.name or not any(matches_rule(rule, record.source) for rule in self.rules):
            raise CleanError(f"Hồ sơ khôi phục không hợp lệ: {folder.name}")
        return record

    def records(self) -> tuple[list[Record], list[str]]:
        records, warnings = [], []
        if not self.root.exists():
            return records, warnings
        checked_path(self.root)
        for folder in self.root.iterdir():
            if not re.fullmatch(r"[0-9a-f]{32}", folder.name):
                continue
            try:
                record = self._read(folder)
                records.append(record)
            except (OSError, CleanError, KeyError, ValueError, TypeError) as error:
                warnings.append(str(error))
        return sorted(records, key=lambda record: record.date, reverse=True), warnings

    def move(self, candidate: Candidate) -> int:
        source, rule = candidate.path, candidate.rule
        with self._lock():
            if rule not in self.rules or not eligible(rule, source, installed_apps()):
                raise CleanError("Mục này đã thay đổi hoặc không còn đủ điều kiện.")
            if running_processes().intersection(rule.processes):
                raise CleanError(f"Hãy thoát {rule.name} rồi quét lại.")
            before = snapshot(source)
            size = sum(info[0] for info in before.values() if info is not None)
            if size == 0:
                raise CleanError("Thư mục đã trống.")
            if shutil.disk_usage(self.root).free < size + 32 * 1024**2:
                raise CleanError("Ổ D không đủ dung lượng để giữ bản khôi phục.")
            record = Record(uuid4().hex, source, candidate.label, size,
                            datetime.now().isoformat(timespec="seconds"), "copying")
            folder = self.root / record.id
            folder.mkdir()
            backup = folder / "files"
            staged = source.with_name(f".smartcleanai-{record.id}")
            self._write(folder, record, "copying")
            # Preserve the original until the backup has been copied and verified.
            shutil.copytree(source, backup, symlinks=True, copy_function=copy_windows_file)
            if snapshot(source) != before or snapshot(backup) != before:
                raise CleanError("Tệp thay đổi khi sao chép. Dữ liệu gốc vẫn ở ổ C.")
            if running_processes().intersection(rule.processes):
                raise CleanError(f"{rule.name} đã mở trong lúc sao chép. Dữ liệu gốc vẫn ở ổ C.")
            self._write(folder, record, "verified")
            checked_path(staged, exists=False)
            source.rename(staged)
            if snapshot(staged) != before:
                staged.rename(source)
                raise CleanError("Tệp thay đổi trước khi dọn. Dữ liệu gốc đã được đưa về vị trí cũ.")
            try:
                remove_staging(staged)
            except OSError as error:
                raise CleanError(f"Bản khôi phục đã có trên D. Một số tệp còn ở {staged}") from error
            self._write(folder, record, "moved")
            return size

    def restore(self, record_id: str):
        if not re.fullmatch(r"[0-9a-f]{32}", record_id):
            raise CleanError("Mã bản khôi phục không hợp lệ.")
        with self._lock():
            folder = self.root / record_id
            record = self._read(folder)
            source = record.source
            if record.state not in {"moved", "verified"} or source.exists():
                raise CleanError("Vị trí gốc đã có dữ liệu hoặc bản sao chưa được xác minh.")
            if not any(matches_rule(rule, source) and source.drive.upper() == "C:" for rule in self.rules):
                raise CleanError("Vị trí khôi phục ngoài danh sách hỗ trợ.")
            rule = next(rule for rule in self.rules if matches_rule(rule, source))
            if running_processes().intersection(rule.processes):
                raise CleanError(f"Hãy thoát {rule.name} trước khi khôi phục.")
            checked_path(source, exists=False)
            backup = folder / "files"
            before = snapshot(backup)
            if shutil.disk_usage(source.parent).free < record.size + 32 * 1024**2:
                raise CleanError("Ổ C không đủ dung lượng để khôi phục.")
            staged = source.with_name(f".smartcleanai-restore-{uuid4().hex}")
            try:
                shutil.copytree(backup, staged, symlinks=True, copy_function=copy_windows_file)
                if snapshot(staged) != before:
                    raise CleanError("Bản sao khôi phục chưa khớp với kho trên D.")
                if running_processes().intersection(rule.processes):
                    raise CleanError(f"{rule.name} đã mở trong lúc khôi phục.")
                staged.rename(source)
            except (OSError, CleanError):
                if staged.exists():
                    remove_staging(staged)
                raise
            self._write(folder, record, "restored")
