from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from xml.etree import ElementTree

import yaml
from sqlmodel import Session, select

from app.models import Annotation, Asset, AssetSnapshot, Derivative, ExternalRef, ObjectFile, Segment, Task, utcnow


PREVIEW_CHARS = 4_000
MAX_EXTRACTED_CHARS = 2_000_000
CHUNK_CHARS = 6_000
MAX_CHUNKS = 400
WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
YAML_MIME_TYPES = {"application/x-yaml", "application/yaml", "text/yaml"}
TEXT_MIME_TYPES = {
    "application/rtf",
    "application/vnd.google-apps.document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "message/rfc822",
    "text/html",
    "text/markdown",
    "text/plain",
    *YAML_MIME_TYPES,
}
TEXT_EXTENSIONS = {".docx", ".eml", ".htm", ".html", ".md", ".rtf", ".txt", ".yaml", ".yml"}
LEGACY_DOC_MIME_TYPES = {"application/msword"}
LEGACY_DOC_EXTENSIONS = {".doc"}


@dataclass
class StructuredTextChunk:
    text: str
    title: str = ""
    locator: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TextExtractionResult:
    status: str
    parser: str
    text: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    structured_chunks: List[StructuredTextChunk] = field(default_factory=list)
    warning: Optional[str] = None

    @property
    def preview(self) -> str:
        return self.text[:PREVIEW_CHARS]

    @property
    def total_chars(self) -> int:
        return len(self.text)

    @property
    def truncated(self) -> bool:
        return bool(self.metadata.get("truncated"))


def should_attempt_text_extraction(filename: str, content_type: Optional[str], asset_type: str) -> bool:
    mime = (content_type or "").split(";")[0].strip().lower()
    suffix = Path(filename).suffix.lower()
    return mime in TEXT_MIME_TYPES or suffix in TEXT_EXTENSIONS or mime in LEGACY_DOC_MIME_TYPES or suffix in LEGACY_DOC_EXTENSIONS


class _TextHTMLParser(HTMLParser):
    BLOCK_TAGS = {
        "article",
        "blockquote",
        "body",
        "br",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__()
        self.parts: List[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag in {"script", "style"}:
            self._skip_depth += 1
        elif tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1
        elif tag in self.BLOCK_TAGS - {"br"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            if self.parts and self.parts[-1] and self.parts[-1][-1].isalnum() and data and data[0].isalnum():
                self.parts.append(" ")
            self.parts.append(data)

    def text(self) -> str:
        return _normalize_text("".join(self.parts))


def _decode_bytes(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _normalize_text(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t\f\v]+", " ", normalized)
    normalized = re.sub(r" *\n *", "\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _normalize_line_endings(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def _cap_text(value: str) -> tuple[str, bool]:
    if len(value) <= MAX_EXTRACTED_CHARS:
        return value, False
    return value[:MAX_EXTRACTED_CHARS].rstrip(), True


def _strip_html(raw: bytes) -> str:
    parser = _TextHTMLParser()
    parser.feed(_decode_bytes(raw))
    return parser.text()


def _strip_rtf(raw: bytes) -> str:
    text = _decode_bytes(raw)

    def decode_hex(match: re.Match[str]) -> str:
        try:
            return bytes.fromhex(match.group(1)).decode("cp1252")
        except UnicodeDecodeError:
            return ""

    text = re.sub(r"\\'([0-9a-fA-F]{2})", decode_hex, text)
    text = re.sub(r"\\par[d]?\b", "\n", text)
    text = re.sub(r"\\tab\b", "\t", text)
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", text)
    text = text.replace(r"\{", "{").replace(r"\}", "}").replace(r"\\", "\\")
    text = text.replace("{", "").replace("}", "")
    return _normalize_text(text)


def _extract_docx(raw_path: Path) -> str:
    with zipfile.ZipFile(raw_path) as archive:
        xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    paragraphs: List[str] = []
    for paragraph in root.iter(f"{WORD_NS}p"):
        parts: List[str] = []
        for node in paragraph.iter():
            if node.tag == f"{WORD_NS}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{WORD_NS}tab":
                parts.append("\t")
            elif node.tag == f"{WORD_NS}br":
                parts.append("\n")
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)
    return _normalize_text("\n\n".join(paragraphs))


def _extract_eml(raw: bytes) -> tuple[str, Dict[str, Any]]:
    message = BytesParser(policy=policy.default).parsebytes(raw)
    headers = {
        "subject": message.get("subject"),
        "from": message.get("from"),
        "to": message.get("to"),
        "date": message.get("date"),
    }
    body = message.get_body(preferencelist=("plain", "html"))
    if body is None:
        payload = message.get_payload(decode=True)
        body_text = _decode_bytes(payload or b"")
    elif body.get_content_type() == "text/html":
        body_text = _strip_html(body.get_payload(decode=True) or b"")
    else:
        body_text = str(body.get_content())
    header_text = "\n".join(f"{key.title()}: {value}" for key, value in headers.items() if value)
    return _normalize_text(f"{header_text}\n\n{body_text}" if header_text else body_text), headers


def _is_yaml_source(filename: str, content_type: Optional[str]) -> bool:
    mime = (content_type or "").split(";")[0].strip().lower()
    suffix = Path(filename).suffix.lower()
    return mime in YAML_MIME_TYPES or suffix in {".yaml", ".yml"}


def _text_from_yaml_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _normalize_line_endings(value)
    return yaml.safe_dump(value, allow_unicode=True, sort_keys=False).strip()


def _prompt_pair_record_messages(record: Any) -> Optional[List[Dict[str, str]]]:
    if not isinstance(record, dict):
        return None
    raw_messages = record.get("messages")
    if not isinstance(raw_messages, list) or not raw_messages:
        return None

    messages: List[Dict[str, str]] = []
    for raw_message in raw_messages:
        if not isinstance(raw_message, dict):
            return None
        role = str(raw_message.get("role", "")).strip()
        if not role or "content" not in raw_message:
            return None
        messages.append({"role": role, "content": _text_from_yaml_value(raw_message.get("content"))})

    roles = {message["role"] for message in messages}
    if not {"user", "assistant"}.issubset(roles):
        return None
    return messages


def _prompt_pair_records(parsed: Any) -> List[Dict[str, Any]]:
    if isinstance(parsed, list):
        candidates = parsed
    elif isinstance(parsed, dict) and _prompt_pair_record_messages(parsed):
        candidates = [parsed]
    elif isinstance(parsed, dict):
        candidates = []
        for key in ("examples", "pairs", "items", "data"):
            value = parsed.get(key)
            if isinstance(value, list):
                candidates = value
                break
    else:
        candidates = []

    records: List[Dict[str, Any]] = []
    for candidate in candidates:
        if isinstance(candidate, dict) and _prompt_pair_record_messages(candidate):
            records.append(candidate)
    return records


def _content_scalar(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return ""
    try:
        loaded = yaml.safe_load(stripped)
        if isinstance(loaded, str):
            return _normalize_line_endings(loaded)
    except yaml.YAMLError:
        pass
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
        return _normalize_line_endings(stripped[1:-1])
    return _normalize_line_endings(stripped)


def _leading_spaces(value: str) -> int:
    return len(value) - len(value.lstrip(" "))


def _dedent_literal_lines(lines: List[str]) -> str:
    non_empty_indents = [_leading_spaces(line) for line in lines if line.strip()]
    indent = min(non_empty_indents) if non_empty_indents else 0
    dedented = [line[indent:] if len(line) >= indent else "" for line in lines]
    return _normalize_line_endings("\n".join(dedented))


def _parse_prompt_pair_block(block_lines: List[str]) -> Optional[Dict[str, Any]]:
    messages: List[Dict[str, str]] = []
    index = 0
    role_pattern = re.compile(r"^(?P<indent>\s*)-\s+role:\s*(?P<role>.+?)\s*$")
    content_pattern = re.compile(r"^\s*content:\s*(?P<value>.*)$")

    while index < len(block_lines):
        role_match = role_pattern.match(block_lines[index])
        if not role_match:
            index += 1
            continue

        role_indent = len(role_match.group("indent"))
        role = _content_scalar(role_match.group("role"))
        index += 1
        message_lines: List[str] = []
        while index < len(block_lines):
            next_role = role_pattern.match(block_lines[index])
            if next_role and len(next_role.group("indent")) <= role_indent:
                break
            message_lines.append(block_lines[index])
            index += 1

        content = ""
        for message_index, line in enumerate(message_lines):
            content_match = content_pattern.match(line)
            if not content_match:
                continue
            value = content_match.group("value").strip()
            if value in {"|", "|-", "|+", ">", ">-", ">+"}:
                content = _dedent_literal_lines(message_lines[message_index + 1 :])
            else:
                content = _content_scalar(value)
            break

        if role and content:
            messages.append({"role": role, "content": content})

    if _prompt_pair_record_messages({"messages": messages}):
        return {"messages": messages}
    return None


def _prompt_pair_records_from_text_blocks(raw_text: str) -> List[Dict[str, Any]]:
    blocks: List[List[str]] = []
    current: Optional[List[str]] = None
    for line in raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if re.match(r"^-\s+messages:\s*$", line):
            if current is not None:
                blocks.append(current)
            current = []
        elif current is not None:
            current.append(line)
    if current is not None:
        blocks.append(current)

    records: List[Dict[str, Any]] = []
    for block in blocks:
        record = _parse_prompt_pair_block(block)
        if record:
            records.append(record)
    return records


def _single_line_preview(value: str, limit: int = 84) -> str:
    preview = re.sub(r"\s+", " ", value).strip()
    if len(preview) <= limit:
        return preview
    return f"{preview[: max(0, limit - 1)].rstrip()}..."


def _format_prompt_pair_example(record: Dict[str, Any], index: int) -> tuple[str, Dict[str, Any]]:
    messages = _prompt_pair_record_messages(record) or []
    lines = [f"Example {index}"]
    for message in messages:
        lines.extend(["", f"{message['role']}:", message["content"]])

    role_sequence = [message["role"] for message in messages]
    first_user = next((message["content"] for message in messages if message["role"] == "user"), "")
    first_assistant = next((message["content"] for message in messages if message["role"] == "assistant"), "")
    system_prompt = next((message["content"] for message in messages if message["role"] == "system"), "")
    title_preview = _single_line_preview(first_user or first_assistant or "prompt pair")
    title = f"Example {index}: {title_preview}"
    metadata = {
        "prompt_pair_example_index": index,
        "message_count": len(messages),
        "role_sequence": role_sequence,
        "structured_messages": messages,
        "system_prompt": system_prompt,
        "user_message_count": role_sequence.count("user"),
        "assistant_message_count": role_sequence.count("assistant"),
        "has_multi_turn": role_sequence.count("user") > 1 or role_sequence.count("assistant") > 1,
        "prompt_preview": _single_line_preview(first_user, 160),
        "response_preview": _single_line_preview(first_assistant, 160),
    }
    return "\n".join(lines).strip(), {"title": title, "metadata": metadata}


def _extract_prompt_pair_yaml(raw_text: str) -> Optional[tuple[str, List[StructuredTextChunk], Dict[str, Any]]]:
    parse_mode = "yaml"
    try:
        parsed = yaml.safe_load(raw_text)
        records = _prompt_pair_records(parsed)
    except yaml.YAMLError:
        records = _prompt_pair_records_from_text_blocks(raw_text)
        parse_mode = "line_block_fallback"
    if not records:
        records = _prompt_pair_records_from_text_blocks(raw_text)
        parse_mode = "line_block_fallback" if records else parse_mode
    if not records:
        return None

    chunks: List[StructuredTextChunk] = []
    for index, record in enumerate(records[:MAX_CHUNKS], start=1):
        chunk_text, formatted = _format_prompt_pair_example(record, index)
        chunks.append(
            StructuredTextChunk(
                text=chunk_text,
                title=formatted["title"],
                locator={"kind": "prompt_pair_example", "example_index": index, "chunk_index": index},
                metadata={
                    "chunking_strategy": "prompt_pair_yaml",
                    "prompt_pair_source_format": "messages",
                    **formatted["metadata"],
                },
            )
        )

    metadata = {
        "chunking_strategy": "prompt_pair_yaml",
        "structured_chunking": "prompt_pair_yaml",
        "prompt_pair_source_format": "messages",
        "prompt_pair_example_count": len(records),
        "structured_chunk_count": len(chunks),
        "structured_chunking_truncated": len(records) > len(chunks),
        "prompt_pair_parse_mode": parse_mode,
    }
    return _normalize_line_endings(raw_text), chunks, metadata


NATURAL_SECTION_START_PATTERN = re.compile(
    r"^(?:"
    r"(?:Email|Memoir|Note|Fragment|Story|Scene|Letter|Message|Conversation|Example|Pair|Prompt|Response)"
    r"(?:\s+[\w.-]+)?"
    r"|From|Subject"
    r")\s*:",
    re.IGNORECASE,
)


def _paragraph_spans(text: str) -> List[tuple[int, int, str]]:
    spans: List[tuple[int, int, str]] = []
    for match in re.finditer(r"(?s)(?:^|\n{2})(?P<body>.*?)(?=\n{2}|\Z)", text):
        body = match.group("body")
        if not body.strip():
            continue
        start, end = match.span("body")
        spans.append((start, end, body))
    return spans


def _looks_like_natural_section_start(paragraph: str) -> bool:
    first_line = paragraph.split("\n", 1)[0].strip()
    if not first_line or len(first_line) > 120:
        return False
    return bool(NATURAL_SECTION_START_PATTERN.match(first_line))


def _natural_section_review_hint(section_text: str) -> str:
    stripped = section_text.strip()
    if len(stripped) > CHUNK_CHARS:
        return "needs_split"
    content_lines = [line for line in stripped.splitlines()[1:] if line.strip()]
    if len(stripped) < 80 or len(content_lines) < 2:
        return "needs_context"
    return "complete_thought"


def _extract_natural_section_chunks(text: str) -> List[StructuredTextChunk]:
    paragraphs = _paragraph_spans(text)
    if len(paragraphs) < 2:
        return []

    section_start_indexes = [
        paragraph_index
        for paragraph_index, (_start, _end, paragraph) in enumerate(paragraphs)
        if _looks_like_natural_section_start(paragraph)
    ]
    if len(section_start_indexes) < 2 or section_start_indexes[0] != 0:
        return []

    chunks: List[StructuredTextChunk] = []
    for ordinal, paragraph_index in enumerate(section_start_indexes[:MAX_CHUNKS], start=1):
        next_paragraph_index = (
            section_start_indexes[ordinal] if ordinal < len(section_start_indexes) else len(paragraphs)
        )
        start = paragraphs[paragraph_index][0]
        end = paragraphs[next_paragraph_index - 1][1]
        section_text = text[start:end]
        title = _single_line_preview(section_text.split("\n", 1)[0], 90)
        chunks.append(
            StructuredTextChunk(
                text=section_text,
                title=title,
                locator={
                    "kind": "natural_section",
                    "chunk_index": ordinal,
                    "char_start": start,
                    "char_end": end,
                },
                metadata={
                    "chunking_strategy": "natural_section",
                    "natural_boundary": True,
                    "section_index": ordinal,
                    "char_start": start,
                    "char_end": end,
                    "section_review_hint": _natural_section_review_hint(section_text),
                },
            )
        )
    return chunks


def extract_text_from_file(path: Path, *, filename: str, content_type: Optional[str], asset_type: str) -> TextExtractionResult:
    if not should_attempt_text_extraction(filename, content_type, asset_type):
        return TextExtractionResult(status="skipped", parser="none", warning="Asset is not a supported text source.")

    suffix = Path(filename).suffix.lower()
    mime = (content_type or "").split(";")[0].strip().lower()
    if mime in LEGACY_DOC_MIME_TYPES or suffix in LEGACY_DOC_EXTENSIONS:
        return TextExtractionResult(
            status="unsupported",
            parser="legacy_doc",
            warning="Legacy .doc files need a conversion step before preview/chunk extraction.",
        )

    try:
        raw = path.read_bytes()
        metadata: Dict[str, Any] = {
            "source_byte_size": len(raw),
            "extraction_char_cap": MAX_EXTRACTED_CHARS,
            "chunk_chars": CHUNK_CHARS,
            "max_chunks": MAX_CHUNKS,
        }
        structured_chunks: List[StructuredTextChunk] = []
        if mime == "message/rfc822" or suffix == ".eml":
            text, headers = _extract_eml(raw)
            metadata["email_headers"] = headers
            parser = "eml"
        elif mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" or suffix == ".docx":
            text = _extract_docx(path)
            parser = "docx"
        elif mime == "text/html" or suffix in {".htm", ".html"}:
            text = _strip_html(raw)
            parser = "html"
        elif mime == "application/rtf" or suffix == ".rtf":
            text = _strip_rtf(raw)
            parser = "rtf"
        elif _is_yaml_source(filename, content_type):
            raw_text = _decode_bytes(raw)
            structured = _extract_prompt_pair_yaml(raw_text)
            if structured:
                text, structured_chunks, structured_metadata = structured
                parser = "prompt_pair_yaml"
                metadata.update(structured_metadata)
            else:
                text = _normalize_text(raw_text)
                parser = "plain_text"
        else:
            text = _normalize_text(_decode_bytes(raw))
            parser = "plain_text"
        metadata["raw_extracted_chars"] = len(text)
        capped, truncated = _cap_text(text)
        metadata["truncated"] = truncated
        if not structured_chunks and capped:
            natural_chunks = _extract_natural_section_chunks(capped)
            if natural_chunks:
                structured_chunks = natural_chunks
                metadata.update(
                    {
                        "chunking_strategy": "natural_section",
                        "structured_chunking": "natural_section",
                        "natural_section_count": len(natural_chunks),
                        "structured_chunk_count": len(natural_chunks),
                        "structured_chunking_truncated": len(natural_chunks) >= MAX_CHUNKS,
                    }
                )
        return TextExtractionResult(
            status="extracted" if capped else "empty",
            parser=parser,
            text=capped,
            metadata=metadata,
            structured_chunks=structured_chunks,
        )
    except Exception as exc:  # pragma: no cover - defensive; extraction must not block mirroring.
        return TextExtractionResult(status="error", parser="unknown", warning=str(exc))


def _chunk_text(text: str) -> Iterable[tuple[int, int, str]]:
    start = 0
    index = 0
    while start < len(text) and index < MAX_CHUNKS:
        end = min(start + CHUNK_CHARS, len(text))
        if end < len(text):
            paragraph_break = text.rfind("\n\n", start, end)
            sentence_break = text.rfind(". ", start, end)
            cut = max(paragraph_break, sentence_break)
            if cut > start + CHUNK_CHARS // 2:
                end = cut + (2 if cut == paragraph_break else 1)
        chunk = text[start:end].strip()
        if chunk:
            yield start, end, chunk
            index += 1
        start = end


def _source_type_for_extraction(filename: str, content_type: Optional[str]) -> str:
    mime = (content_type or "").split(";")[0].strip().lower()
    suffix = Path(filename).suffix.lower()
    if mime == "message/rfc822" or suffix == ".eml":
        return "email"
    if suffix in {".doc", ".docx", ".htm", ".html", ".rtf", ".txt", ".md", ".yaml", ".yml"} or mime in TEXT_MIME_TYPES or "wordprocessingml" in mime:
        return "document"
    return "unknown"


def _required_decisions_for_source(source_type: str) -> List[str]:
    if source_type == "email":
        return [
            "charles_voice_presence",
            "charles_email_role",
            "other_voice_roles",
            "context_use",
            "privacy_notes",
            "usable_for_voice_context",
            "usable_for_grounded_generation",
        ]
    return [
        "source_genre",
        "authorship",
        "creator_entity_ids",
        "authorship_note",
        "fictionality_status",
        "truth_status",
        "voice_presence",
        "adam_context_note",
        "privacy_level",
        "privacy_notes",
        "ready_for_processing",
    ]


def persist_text_extraction(
    session: Session,
    *,
    asset: Asset,
    source_snapshot: AssetSnapshot,
    source_object_file: ObjectFile,
    filename: str,
    content_type: Optional[str],
    extraction: TextExtractionResult,
) -> Dict[str, Any]:
    chunks: List[StructuredTextChunk] = []
    chunking_strategy = extraction.metadata.get("chunking_strategy") or "generic_text"
    if extraction.status == "extracted" and extraction.structured_chunks:
        chunks = extraction.structured_chunks[:MAX_CHUNKS]
        chunking_truncated = bool(extraction.metadata.get("structured_chunking_truncated")) or len(extraction.structured_chunks) > len(chunks)
    elif extraction.status == "extracted":
        for index, (start, end, chunk) in enumerate(_chunk_text(extraction.text), start=1):
            chunks.append(
                StructuredTextChunk(
                    text=chunk,
                    locator={"kind": "text_chunk", "chunk_index": index, "char_start": start, "char_end": end},
                    metadata={"char_start": start, "char_end": end},
                )
            )
        chunking_truncated = bool(chunks and chunks[-1].locator.get("char_end") < len(extraction.text))
    else:
        chunking_truncated = False
    metadata = {
        "status": extraction.status,
        "parser": extraction.parser,
        "preview_text": extraction.preview,
        "total_chars": extraction.total_chars,
        "truncated": extraction.truncated,
        "chunk_count": len(chunks),
        "chunking_strategy": chunking_strategy,
        "chunking_truncated": chunking_truncated,
        "source_object_file_id": source_object_file.id,
        "source_snapshot_id": source_snapshot.id,
        "source_filename": filename,
        "source_content_type": content_type,
        **extraction.metadata,
    }
    if extraction.warning:
        metadata["warning"] = extraction.warning

    derivative = Derivative(
        asset_id=asset.id,
        source_snapshot_id=source_snapshot.id,
        derivative_type="text_extraction",
        object_file_id=None,
        status=extraction.status,
        metadata_json=metadata,
    )
    session.add(derivative)
    session.flush()
    metadata["text_extraction_derivative_id"] = derivative.id
    derivative.metadata_json = metadata
    session.add(derivative)

    segment_ids: List[str] = []
    task_ids: List[str] = []
    if extraction.status == "extracted":
        preview_segment = Segment(
            human_id=f"SEG_PREVIEW_{asset.human_id}_{source_snapshot.version}",
            asset_id=asset.id,
            segment_type="text_preview",
            title=f"{asset.title or filename} preview",
            text_content=extraction.preview,
            locator={
                "kind": "preview",
                "source_snapshot_id": source_snapshot.id,
                "text_extraction_derivative_id": derivative.id,
                "char_start": 0,
                "char_end": len(extraction.preview),
            },
            source_truth_status="archival_source",
            maturity_level="L2_extracted",
            metadata_json=metadata,
        )
        session.add(preview_segment)
        session.flush()
        segment_ids.append(preview_segment.id)

        for index, chunk in enumerate(chunks, start=1):
            chunk_locator = {
                "kind": "text_chunk",
                **chunk.locator,
                "source_snapshot_id": source_snapshot.id,
                "text_extraction_derivative_id": derivative.id,
                "chunk_index": index,
            }
            segment = Segment(
                human_id=f"SEG_CHUNK_{asset.human_id}_{source_snapshot.version}_{index:04d}",
                asset_id=asset.id,
                segment_type="text_chunk",
                title=chunk.title or f"{asset.title or filename} chunk {index}",
                text_content=chunk.text,
                locator=chunk_locator,
                source_truth_status="archival_source",
                maturity_level="L2_extracted",
                metadata_json={**metadata, **chunk.metadata, "chunk_index": index, "chunk_count": len(chunks)},
            )
            session.add(segment)
            session.flush()
            segment_ids.append(segment.id)

        source_type = _source_type_for_extraction(filename, content_type)
        task_type = "email_voice_sample" if source_type == "email" else "text_segment_review"
        queue = "emails_needing_voice_review" if source_type == "email" else "text_segments_needing_review"
        task = Task(
            human_id=f"TASK_TEXT_{asset.human_id}_{source_snapshot.version}",
            task_type=task_type,
            target_type="segment",
            target_id=preview_segment.id,
            priority=85,
            queue=queue,
            reason_created="Mirrored text source was extracted into a reviewable preview and bounded chunks.",
            input_payload={
                "asset_id": asset.id,
                "asset_title": asset.title,
                "segment_title": preview_segment.title,
                "preview_text": extraction.preview,
                "source_type": source_type,
                "source_mime_type": content_type,
                "source_filename": filename,
                "email_headers": extraction.metadata.get("email_headers") if source_type == "email" else None,
                "chunk_count": len(chunks),
                "total_chars": extraction.total_chars,
                "truncated": extraction.truncated,
                "chunking_truncated": chunking_truncated,
                "chunking_strategy": chunking_strategy,
                "extraction_parser": extraction.parser,
                "text_extraction_derivative_id": derivative.id,
            },
            required_decisions=_required_decisions_for_source(source_type),
            created_by="text_extraction",
        )
        session.add(task)
        session.flush()
        task_ids.append(task.id)

        asset.processing_status = "text_extracted"
        asset.maturity_level = "L2_extracted"
    elif extraction.status == "unsupported":
        asset.processing_status = "needs_text_conversion"
    elif extraction.status in {"empty", "error"}:
        asset.processing_status = f"text_extraction_{extraction.status}"
    asset.updated_at = utcnow()
    session.add(asset)

    external_ref = session.exec(
        select(ExternalRef).where(ExternalRef.asset_id == asset.id).where(ExternalRef.source_system == "google_drive")
    ).first()
    if external_ref:
        external_ref.metadata_json = {
            **dict(external_ref.metadata_json),
            "text_extraction_status": extraction.status,
            "latest_text_extraction_derivative_id": derivative.id,
            "latest_text_preview_segment_id": segment_ids[0] if segment_ids else None,
            "latest_text_review_task_id": task_ids[0] if task_ids else None,
            "text_extracted_at": utcnow().isoformat(),
        }
        session.add(external_ref)

    annotation = Annotation(
        annotator_id="system",
        target_type="asset",
        target_id=asset.id,
        annotation_type="text_extraction",
        decisions=metadata,
        notes="Text preview/chunks were extracted from the CharlesOps mirrored copy, not from the Drive original.",
        creates_or_updates={
            "derivative_id": derivative.id,
            "segment_ids": segment_ids,
            "task_ids": task_ids,
        },
    )
    session.add(annotation)
    session.flush()

    return {
        "status": extraction.status,
        "derivative_id": derivative.id,
        "segment_ids": segment_ids,
        "task_ids": task_ids,
        "annotation_id": annotation.id,
    }
