"""Send an anonymized cleanup policy to the configured AI provider."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from ai_provider import AIError, request_ai
from cleaner import Candidate, build_rules


ReviewError = AIError


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
    return request_ai(prompt, output_schema)


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
