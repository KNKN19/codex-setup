"""Export a Codex SessionEnd transcript as a Markdown file."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
import sys
from typing import Any


ROLE_TITLES = {
    "assistant": "Assistant",
    "user": "User",
}


def read_hook_input() -> dict[str, Any]:
    """Read the JSON payload provided by Codex to a command hook."""
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def text_from_value(value: Any) -> str:
    """Extract displayable text from common transcript content shapes."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        texts: list[str] = []
        for item in value:
            text = text_from_value(item)
            if text.strip() and not is_injected_context(text):
                texts.append(text)
        return "\n".join(texts)
    if isinstance(value, dict):
        for key in ("text", "input_text", "output_text", "content"):
            if key in value:
                text = text_from_value(value[key])
                if text.strip():
                    return text
    return ""


def is_injected_context(text: str) -> bool:
    """Identify repository instructions and runtime context added by Codex."""
    stripped = text.lstrip()
    return (
        stripped.startswith("# AGENTS.md instructions")
        or stripped.startswith("<INSTRUCTIONS>")
        or stripped.startswith("<environment_context>")
    )


def extract_messages(transcript_path: Path) -> list[tuple[str, str]]:
    """Extract role/text pairs from the JSONL transcript."""
    messages: list[tuple[str, str]] = []

    with transcript_path.open(encoding="utf-8") as transcript:
        for line in transcript:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if not isinstance(event, dict):
                continue

            candidates = [event]
            for key in ("payload", "message", "item"):
                value = event.get(key)
                if isinstance(value, dict):
                    candidates.append(value)

            for candidate in candidates:
                role = candidate.get("role")
                if role not in ROLE_TITLES:
                    continue
                text = text_from_value(candidate.get("content", candidate.get("text", "")))
                if text.strip():
                    messages.append((ROLE_TITLES[role], text.strip()))
                    break

    return expand_embedded_messages(messages)


def expand_embedded_messages(messages: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Split initial context that contains an embedded conversation transcript."""
    expanded: list[tuple[str, str]] = []
    marker_pattern = re.compile(r"^## (User|Assistant)\s*$", flags=re.MULTILINE)

    for role, text in messages:
        markers = list(marker_pattern.finditer(text))
        if not markers:
            expanded.append((role, text))
            continue

        for index, marker in enumerate(markers):
            end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
            embedded_text = text[marker.end() : end].strip()
            if embedded_text:
                expanded.append((marker.group(1), embedded_text))

    return expanded


def markdown_escape(text: str) -> str:
    """Prevent transcript headings from becoming log structure."""
    return re.sub(r"^(#{1,6})\s", r"\\\1 ", text, flags=re.MULTILINE)


def render_markdown(messages: list[tuple[str, str]]) -> str:
    """Render extracted messages as a readable Markdown transcript."""
    lines: list[str] = []
    for role, text in messages:
        lines.extend([f"## {role}", "", markdown_escape(text), ""])

    return "\n".join(lines)


def find_project_root(start: Path) -> Path:
    """Find the repository root, falling back to the hook working directory."""
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return start


def export_session_log(payload: dict[str, Any]) -> Path | None:
    """Export the transcript into the repository's logs directory."""
    transcript_name = payload.get("transcript_path")
    if not isinstance(transcript_name, str) or not transcript_name:
        return None

    transcript_path = Path(transcript_name)
    if not transcript_path.is_file():
        return None

    cwd_name = payload.get("cwd")
    session_dir = Path(cwd_name) if isinstance(cwd_name, str) else Path.cwd()
    project_root = find_project_root(session_dir)
    logs_dir = project_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = logs_dir / f"log_{timestamp}.md"
    log_path.write_text(
        render_markdown(extract_messages(transcript_path)),
        encoding="utf-8",
    )
    return log_path


export_session_log(read_hook_input())
