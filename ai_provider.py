"""One entry point for every AI call: Codex CLI, Antigravity CLI or an OpenAI-compatible API.

Every call is a single prompt that must come back as one JSON object matching ``schema``.
CLIs run in an empty temporary folder in read-only mode; nothing on disk is shared with them.
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import threading
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory

PROVIDERS = {
    "codex": "Codex CLI",
    "antigravity": "Antigravity CLI (agy)",
    "api": "API (Base URL + API key)",
}
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_AGY_MODEL = "gemini-3.8-flash-medium"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SETTINGS_FILE = Path(os.environ.get("APPDATA", Path.home())) / "SmartCleanAI" / "settings.json"
AGY_READONLY_TOOLS = frozenset({
    "view_file", "read_file", "view_file_outline", "view_code_item", "list_dir", "find_by_name",
    "grep_search", "codebase_search", "read_resource", "list_resources", "list_permissions", "finish",
    "wait", "wait_5_seconds", "ask_permission", "ask_custom_permission", "ask_question",
})
READONLY_NOTE = ("[Chế độ chỉ đọc] Không tạo, sửa, xóa file; không chạy lệnh; không mở link. "
                 "Chỉ trả về đúng một object JSON theo schema.\n\n")


class AIError(Exception):
    pass


@dataclass
class Settings:
    provider: str = "codex"
    model: str = ""
    base_url: str = DEFAULT_BASE_URL
    api_key: str = field(default="", repr=False)
    cli_path: str = ""
    timeout: int = 150

    @property
    def label(self) -> str:
        return PROVIDERS.get(self.provider, self.provider)


def load_settings() -> Settings:
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        known = {key: data[key] for key in Settings.__dataclass_fields__ if key in data}
        settings = Settings(**known)
    except (OSError, ValueError, TypeError):
        settings = Settings()
    if settings.provider not in PROVIDERS:
        settings.provider = "codex"
    settings.timeout = max(20, min(int(settings.timeout or 150), 900))
    return settings


def save_settings(settings: Settings):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = SETTINGS_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(SETTINGS_FILE)


# ---------------------------------------------------------------- helpers
def _parse_json(text: str, who: str) -> dict:
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        text = text[start:end + 1] if 0 <= start < end else text
    try:
        data = json.loads(text)
    except ValueError as error:
        raise AIError(f"{who} trả dữ liệu sai định dạng. Hãy thử lại.") from error
    if not isinstance(data, dict):
        raise AIError(f"{who} trả dữ liệu sai định dạng. Hãy thử lại.")
    return data


def _kill_tree(process: subprocess.Popen):
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True,
                       creationflags=NO_WINDOW)
    else:
        process.kill()


def _clean_env() -> dict:
    env = os.environ.copy()
    for key in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "CODEX_API_KEY"):
        env.pop(key, None)
    return env


def _explicit(path: str, name: str) -> Path:
    candidate = Path(path.strip().strip('"'))
    if not candidate.is_file():
        raise AIError(f"Không thấy {name} tại {candidate}. Sửa đường dẫn trong Cài đặt.")
    return candidate


# ---------------------------------------------------------------- Codex
def find_codex(settings: Settings) -> Path:
    if settings.cli_path.strip():
        return _explicit(settings.cli_path, "Codex CLI")
    entries = [Path(e.strip('"')) for e in os.get_exec_path() if e and Path(e.strip('"')).is_absolute()]
    if os.environ.get("APPDATA"):
        entries.append(Path(os.environ["APPDATA"]) / "npm")
    arch = "arm64" if platform.machine().casefold() in {"arm64", "aarch64"} else "x64"
    target = "aarch64" if arch == "arm64" else "x86_64"
    for directory in entries:
        if (directory / "codex.exe").is_file():
            return directory / "codex.exe"
        scope = directory / "node_modules" / "@openai"
        for base in (scope / "codex" / "node_modules" / "@openai", scope):
            native = base / f"codex-win32-{arch}" / "vendor" / f"{target}-pc-windows-msvc" / "bin" / "codex.exe"
            if native.is_file():
                return native
    raise AIError("Không tìm thấy Codex CLI. Cài bằng npm i -g @openai/codex rồi chạy codex login.")


def _codex(prompt: str, schema: dict, settings: Settings) -> dict:
    cli = find_codex(settings)
    with TemporaryDirectory(prefix="smartclean-ai-") as temporary:
        work = Path(temporary)
        schema_file, answer = work / "schema.json", work / "answer.json"
        schema_file.write_text(json.dumps(schema), encoding="utf-8")
        command = [
            str(cli), "--ask-for-approval", "never", "exec", "--sandbox", "read-only",
            "--skip-git-repo-check", "--ephemeral", "--color", "never",
            "-c", 'web_search="disabled"', "-c", "project_doc_max_bytes=0",
            "-c", "features.shell_tool=false",
            "--output-schema", str(schema_file), "--output-last-message", str(answer),
        ]
        if settings.model.strip():
            command += ["--model", settings.model.strip()]
        try:
            run = subprocess.run(
                [*command, "-"], input=prompt, cwd=work, env=_clean_env(), capture_output=True,
                encoding="utf-8", errors="replace", timeout=settings.timeout, creationflags=NO_WINDOW,
            )
        except subprocess.TimeoutExpired as error:
            raise AIError(f"Codex chưa trả lời sau {settings.timeout} giây. Hãy thử lại.") from error
        if run.returncode or not answer.is_file():
            output = (run.stderr + run.stdout).casefold()
            if any(m in output for m in ("401", "unauthorized", "not logged in", "login required")):
                raise AIError("Codex CLI cần đăng nhập: chạy codex login.")
            if any(m in output for m in ("429", "rate limit", "usage limit")):
                raise AIError("Codex đang chạm giới hạn sử dụng. Hãy thử lại sau.")
            if re.search(r"model[^\n]{0,80}(not found|not supported|unknown|invalid)", output):
                raise AIError(f"Codex không dùng được model '{settings.model}'. Đổi model trong Cài đặt.")
            if any(m in output for m in ("connection", "stream disconnected", "network")):
                raise AIError("Codex chưa kết nối được. Kiểm tra mạng và thử lại.")
            raise AIError(f"Codex CLI lỗi (mã {run.returncode}). Kiểm tra trong Cài đặt.")
        return _parse_json(answer.read_text(encoding="utf-8"), "Codex")


# ---------------------------------------------------------------- Antigravity
def find_agy(settings: Settings) -> Path:
    if settings.cli_path.strip():
        return _explicit(settings.cli_path, "Antigravity CLI")
    name = "agy.exe" if os.name == "nt" else "agy"
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    for directory in [local / "agy" / "bin", *map(Path, os.get_exec_path())]:
        if (directory / name).is_file():
            return directory / name
    raise AIError("Không tìm thấy Antigravity CLI (agy). Cài agy và chạy agy một lần để đăng nhập.")


def _agy(prompt: str, schema: dict, settings: Settings) -> dict:
    cli = find_agy(settings)
    with TemporaryDirectory(prefix="smartclean-ai-") as temporary:
        work = Path(temporary)
        schema_file = work / "schema.json"
        schema_file.write_text(json.dumps(schema), encoding="utf-8")
        body = READONLY_NOTE + prompt
        if len(body) > 30000:
            (work / "prompt.txt").write_text(prompt, encoding="utf-8")
            body = READONLY_NOTE + "Yêu cầu đầy đủ nằm trong file prompt.txt ở thư mục làm việc. Đọc hết rồi làm đúng."
        command = [str(cli), "-p", body, "--output-format", "stream-json", "--json-schema", str(schema_file),
                   "--print-timeout", "0", "--model", settings.model.strip() or DEFAULT_AGY_MODEL]
        process = subprocess.Popen(command, cwd=work, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        timer = threading.Timer(settings.timeout, _kill_tree, (process,))
        timer.start()
        result, problem, errors = None, "", []
        reader = threading.Thread(target=lambda: errors.append(process.stderr.read()), daemon=True)
        reader.start()
        try:
            for line in process.stdout:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("event") == "result" and isinstance(event.get("result"), dict):
                    result = event["result"]
                    _kill_tree(process)
                    break
                step = event.get("step_update") or {}
                tool = str(step.get("tool_name") or "") if isinstance(step, dict) else ""
                if tool and step.get("state") == "ACTIVE" and tool not in AGY_READONLY_TOOLS:
                    problem = f"Antigravity định dùng công cụ '{tool}' nên đã bị dừng để giữ an toàn."
                    _kill_tree(process)
                    break
        finally:
            timed_out = not timer.is_alive() and result is None and not problem
            timer.cancel()
            process.wait(timeout=10)
        if problem:
            raise AIError(problem)
        if timed_out:
            raise AIError(f"Antigravity chưa trả lời sau {settings.timeout} giây. Hãy thử lại.")
        if not result:
            text = "".join(errors).casefold()
            if "login" in text or "unauth" in text:
                raise AIError("Antigravity CLI cần đăng nhập: mở terminal chạy agy.")
            raise AIError("Antigravity không trả kết quả. Kiểm tra trong Cài đặt.")
        if result.get("status") != "SUCCESS":
            raise AIError(f"Antigravity lỗi: {str(result.get('error') or result.get('status'))[:200]}")
        output = result.get("structured_output")
        if isinstance(output, dict):
            return output
        return _parse_json(output if isinstance(output, str) else "", "Antigravity")


# ---------------------------------------------------------------- OpenAI-compatible API
def _base(settings: Settings) -> str:
    url = (settings.base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    for suffix in ("/chat/completions", "/models"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    if not url.startswith(("http://", "https://")):
        raise AIError("Base URL phải bắt đầu bằng http:// hoặc https://")
    if not settings.api_key.strip():
        raise AIError("Chưa nhập API key trong Cài đặt.")
    return url


def _http(settings: Settings, method: str, path: str, body: dict | None = None, timeout: float = 20) -> dict:
    request = urllib.request.Request(
        _base(settings) + path, method=method,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={"Authorization": f"Bearer {settings.api_key.strip()}", "Content-Type": "application/json",
                 "User-Agent": "SmartCleanAI"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:300]
        messages = {401: "API key không hợp lệ", 403: "API key không có quyền",
                    404: "Sai Base URL (thường kết thúc bằng /v1)", 429: "Hết hạn mức hoặc gọi quá nhanh"}
        message = messages.get(error.code, f"API lỗi {error.code}")
        raise AIError(f"{message}. {detail}".strip()) from error
    except TimeoutError as error:
        raise AIError(f"API chưa trả lời sau {int(timeout)} giây.") from error
    except (urllib.error.URLError, OSError) as error:
        raise AIError("Không kết nối được tới Base URL. Kiểm tra địa chỉ và mạng.") from error
    except ValueError as error:
        raise AIError("API không trả JSON.") from error


def _api(prompt: str, schema: dict, settings: Settings) -> dict:
    if not settings.model.strip():
        raise AIError("Chưa chọn model cho API trong Cài đặt.")
    messages = [
        {"role": "system", "content": "Trả về đúng một object JSON khớp JSON Schema sau, không kèm chữ nào khác.\n"
                                      + json.dumps(schema, ensure_ascii=False)},
        {"role": "user", "content": prompt},
    ]
    formats = [{"type": "json_schema", "json_schema": {"name": "result", "strict": True, "schema": schema}},
               {"type": "json_object"}, None]
    last = None
    for fmt in formats:
        body = {"model": settings.model.strip(), "messages": messages, "stream": False}
        if fmt:
            body["response_format"] = fmt
        try:
            data = _http(settings, "POST", "/chat/completions", body, timeout=settings.timeout)
        except AIError as error:
            if fmt and "API lỗi 400" in str(error):
                last = error
                continue
            raise
        try:
            return _parse_json(data["choices"][0]["message"]["content"], "API")
        except (KeyError, IndexError, TypeError) as error:
            raise AIError("API trả dữ liệu không đúng định dạng OpenAI.") from error
    raise last or AIError("API không trả được kết quả.")


# ---------------------------------------------------------------- public
def request_ai(prompt: str, schema: dict, settings: Settings | None = None) -> dict:
    settings = settings or load_settings()
    return {"codex": _codex, "antigravity": _agy, "api": _api}[settings.provider](prompt, schema, settings)


def list_models(settings: Settings) -> list[str]:
    if settings.provider == "api":
        data = _http(settings, "GET", "/models")
        items = data.get("data") if isinstance(data, dict) else data
        return sorted({str(m["id"]) for m in items or [] if isinstance(m, dict) and m.get("id")})
    if settings.provider == "antigravity":
        return [DEFAULT_AGY_MODEL]
    return []


def check(settings: Settings) -> str:
    """Quick readiness check without spending a model call."""
    if settings.provider == "api":
        models = list_models(settings)
        return f"Kết nối được · {len(models)} model"
    binary = find_codex(settings) if settings.provider == "codex" else find_agy(settings)
    args = [str(binary), "login", "status"] if settings.provider == "codex" else [str(binary), "--version"]
    try:
        run = subprocess.run(args, capture_output=True, encoding="utf-8", errors="replace", timeout=30,
                             env=_clean_env(), creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise AIError(f"Không chạy được {binary.name}: {error}") from error
    text = (run.stdout + run.stderr).strip().splitlines()
    if run.returncode:
        hint = "codex login" if settings.provider == "codex" else "agy"
        raise AIError(f"{settings.label} chưa sẵn sàng. Chạy {hint} trong terminal. {' '.join(text)[:150]}")
    return f"Sẵn sàng · {text[0][:80] if text else binary.name}"
