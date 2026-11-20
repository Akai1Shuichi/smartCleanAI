"""Send an anonymized cleanup policy to an authenticated Codex CLI."""

from __future__ import annotations

import json
import os
import platform
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from cleaner import Candidate, build_rules


class ReviewError(Exception):
    pass


# Public templates describe the built-in rules. On-disk paths never enter the prompt.
LOCAL_TEMPLATE = Path("C:/LOCAL_TEMPLATE")
ROAMING_TEMPLATE = Path("C:/ROAMING_TEMPLATE")

HISTORY = (
    {
        "id": "package-caches",
        "name": "Cache công cụ lập trình",
        "scope": "Tham khảo từ lần dọn trước, không tích hợp vào nút dọn của app.",
        "previous_method": [
            "npm cache clean --force cho cache gói npm",
            "pip cache purge cho cache HTTP và wheel của pip đang dùng",
            "pnpm cache delete theo mẫu và pnpm store prune",
            "dotnet nuget locals http-cache --clear",
        ],
    },
    {
        "id": "wsl-compact",
        "name": "Thu gọn Ubuntu WSL",
        "scope": "Tham khảo từ lần dọn trước, không tích hợp vào nút dọn của app.",
        "previous_method": [
            "Kiểm tra dung lượng Linux sử dụng, chạy fstrim trong Ubuntu.",
            "Đợi distro dừng, chạy wsl --manage Ubuntu --compact nếu CLI hỗ trợ.",
            "Khởi động lại, xác minh hệ thống tệp và đo dung lượng ổ C.",
        ],
    },
)

SAFEGUARDS = (
    "Chỉ quét đường dẫn được liệt kê, trên C; từ chối symlink, junction và reparse point.",
    "Với bản cũ, chỉ liệt kê số phiên bản thấp hơn bản hiện tại có trong Registry và có tệp thực thi.",
    "Kiểm tra tiến trình liên quan khi quét, trước khi sao chép, và sau khi sao chép. Người dùng chọn từng mục.",
    "Sao chép sang kho trên D, đối chiếu cấu trúc, kích thước và mtime rồi mới thu hồi dữ liệu trên C.",
    "Dùng bản sao trên D để khôi phục; từ chối ghi đè khi đường dẫn gốc đã tồn tại.",
    "Trình duyệt chỉ xét Cache, Code Cache và GPUCache của Default hoặc Profile số, bỏ qua cookies và dữ liệu hồ sơ.",
    "Bộ cập nhật sót lại chỉ được đưa vào danh sách khi không thấy mục cài đặt và tệp chạy ở vị trí chuẩn.",
)


@dataclass(frozen=True)
class Finding:
    rule_id: str
    status: str
    observation: str
    recommendation: str


@dataclass(frozen=True)
class Review:
    summary: str
    findings: tuple[Finding, ...]


def _template_path(path: Path) -> str:
    if path.is_relative_to(LOCAL_TEMPLATE):
        return "%LOCALAPPDATA%/" + path.relative_to(LOCAL_TEMPLATE).as_posix()
    return "%APPDATA%/" + path.relative_to(ROAMING_TEMPLATE).as_posix()


def policy_snapshot(items: list[Candidate]) -> dict:
    totals: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0])
    for item in items:
        counts = totals[(item.rule.name, item.rule.category)]
        counts[0] += 1
        counts[1] += item.size
        counts[2] += int(item.busy)

    groups: dict[tuple[str, str], dict] = {}
    for rule in build_rules(LOCAL_TEMPLATE, ROAMING_TEMPLATE):
        key = (rule.name, rule.category)
        if key not in groups:
            count, size, busy = totals[key]
            groups[key] = {
                "id": f"rule-{len(groups) + 1:02}",
                "app": rule.name,
                "category": rule.category,
                "templates": [],
                "scan_count": count,
                "scan_bytes": size,
                "busy_count": busy,
            }
        groups[key]["templates"].append({
            "path": _template_path(rule.root).rstrip("/.") + "/" + rule.relative,
            "folder_pattern": rule.version_folder,
            "current_executable": rule.executable,
            "process_names": rule.processes,
            "absent_executable_template": (
                _template_path(rule.absent_executable) if rule.absent_executable else ""
            ),
        })
    return {"safeguards": SAFEGUARDS, "active_rules": list(groups.values()), "prior_methods": HISTORY}


def _native_cli() -> Path:
    path_entries = [
        Path(entry.strip('"')) for entry in os.get_exec_path() if entry and Path(entry.strip('"')).is_absolute()
    ]
    architecture = "arm64" if platform.machine().casefold() in {"arm64", "aarch64"} else "x64"
    target = "aarch64" if architecture == "arm64" else "x86_64"
    appdata = os.environ.get("APPDATA")
    if appdata:
        path_entries.append(Path(appdata) / "npm")
    for directory in path_entries:
        native = directory / "codex.exe"
        if native.is_file():
            return native
        npm_scope = directory / "node_modules" / "@openai"
        package_name = f"codex-win32-{architecture}"
        for scope in (npm_scope / "codex" / "node_modules" / "@openai", npm_scope):
            native = scope / package_name / "vendor" / f"{target}-pc-windows-msvc" / "bin" / "codex.exe"
            if native.is_file():
                return native
    raise ReviewError("Không tìm thấy Codex CLI. Cài Codex CLI và đăng nhập bằng lệnh codex login.")


def _schema(rule_ids: list[str]) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["summary", "findings"],
        "properties": {
            "summary": {"type": "string"},
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["rule_id", "status", "observation", "recommendation"],
                    "properties": {
                        "rule_id": {"type": "string", "enum": rule_ids},
                        "status": {"type": "string", "enum": ["ok", "review", "risk"]},
                        "observation": {"type": "string"},
                        "recommendation": {"type": "string"},
                    },
                },
            },
        },
    }


def request_codex(prompt: str, output_schema: dict) -> dict:
    cli = _native_cli()
    with TemporaryDirectory(prefix="smartcleanai-codex-") as temporary:
        work = Path(temporary)
        schema, answer = work / "schema.json", work / "answer.json"
        schema.write_text(json.dumps(output_schema), encoding="utf-8")
        command = [
            str(cli), "--ask-for-approval", "never", "exec",
            "--sandbox", "read-only", "--skip-git-repo-check",
            "--ephemeral", "--ignore-user-config", "--color", "never",
            "-c", 'web_search="disabled"', "-c", "project_doc_max_bytes=0",
            "--output-schema", str(schema), "--output-last-message", str(answer),
        ]
        for feature in ("shell_tool", "shell_snapshot", "apps", "hooks", "remote_plugin", "multi_agent",
                        "memories", "skill_search", "skill_mcp_dependency_install"):
            command.extend(("--disable", feature))
        env = os.environ.copy()
        for key in ("OPENAI_BASE_URL", "OPENAI_API_KEY", "CODEX_API_KEY"):
            env.pop(key, None)
        try:
            run = subprocess.run(
                [*command, "-"], input=prompt, cwd=work, env=env, capture_output=True,
                encoding="utf-8", errors="replace", timeout=150, creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except subprocess.TimeoutExpired as error:
            raise ReviewError("Codex chưa trả kết quả sau 150 giây. Hãy thử lại.") from error
        if run.returncode or not answer.is_file():
            output = run.stderr.casefold()
            if any(marker in output for marker in ("401", "unauthorized", "not logged in", "login required")):
                raise ReviewError("Codex CLI cần đăng nhập lại bằng codex login.")
            if any(marker in output for marker in ("429", "rate limit", "usage limit")):
                raise ReviewError("Codex đang chạm giới hạn sử dụng. Hãy thử lại sau.")
            if any(marker in output for marker in ("connection", "stream disconnected", "timeout", "network")):
                raise ReviewError("Codex CLI chưa kết nối được. Kiểm tra mạng và thử lại.")
            raise ReviewError(f"Codex CLI không trả được báo cáo (mã {run.returncode}). Kiểm tra codex login status và phiên bản CLI.")
        try:
            data = json.loads(answer.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object")
            return data
        except (OSError, ValueError) as error:
            raise ReviewError("Codex trả dữ liệu sai định dạng. Hãy thử lại.") from error


def review_rules(snapshot: dict) -> Review:
    rule_ids = [rule["id"] for rule in snapshot["active_rules"] + list(snapshot["prior_methods"])]
    prompt = (
        "Rà soát các quy tắc của SmartCleanAI, một công cụ dọn ổ C trên Windows. "
        "Chỉ phân tích dữ liệu JSON bên dưới. Không gọi công cụ, không đọc thêm tệp, không thi hành lệnh. "
        "Trả lời bằng tiếng Việt, ngắn gọn, đúng schema. Trả về đúng một nhận xét cho mỗi id. "
        "Đánh giá nguy cơ giữ nhầm bản hiện tại, mất dữ liệu, chạy cùng ứng dụng, và giới hạn của phương án khôi phục. "
        "Với quy trình trước đây, đánh giá điều kiện áp dụng; không tuyên bố đã chạy hoặc xác minh máy. "
        "Mức ok là hợp lý theo dữ kiện; review là cần xác minh thêm; risk là có rủi ro đáng kể. "
        "Đề xuất điều kiện hoặc thao tác kiểm tra, không đưa lệnh xóa.\n\n"
        + json.dumps(snapshot, ensure_ascii=False, indent=2)
    )
    data = request_codex(prompt, _schema(rule_ids))
    try:
        findings = tuple(Finding(**finding) for finding in data["findings"])
        summary = data["summary"]
        if (not isinstance(summary, str) or not summary.strip()
                or {finding.rule_id for finding in findings} != set(rule_ids)
                or len(findings) != len(rule_ids)
                or any(finding.status not in {"ok", "review", "risk"}
                       or not isinstance(finding.observation, str)
                       or not isinstance(finding.recommendation, str) for finding in findings)):
            raise ValueError("Incomplete review")
        return Review(summary, findings)
    except (TypeError, ValueError, KeyError) as error:
        raise ReviewError("Báo cáo Codex chưa đủ các quy tắc hoặc sai định dạng. Hãy thử lại.") from error
