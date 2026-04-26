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

from sqlmodel import Session, select

from app.models import Annotation, Asset, AssetSnapshot, Derivative, ExternalRef, ObjectFile, Segment, Task, utcnow


PREVIEW_CHARS = 4_000
MAX_EXTRACTED_CHARS = 2_000_000
CHUNK_CHARS = 6_000
MAX_CHUNKS = 400
WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
TEXT_MIME_TYPES = {
    "application/rtf",
    "application/vnd.google-apps.document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "message/rfc822",
    "text/html",
    "text/markdown",
    "text/plain",
}
TEXT_EXTENSIONS = {".docx", ".eml", ".htm", ".html", ".md", ".rtf", ".txt"}
LEGACY_DOC_MIME_TYPES = {"application/msword"}
LEGACY_DOC_EXTENSIONS = {".doc"}


@dataclass
class TextExtractionResult:
    status: str
    parser: str
    text: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
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
        else:
            text = _normalize_text(_decode_bytes(raw))
            parser = "plain_text"
        metadata["raw_extracted_chars"] = len(text)
        capped, truncated = _cap_text(text)
        metadata["truncated"] = truncated
        return TextExtractionResult(
            status="extracted" if capped else "empty",
            parser=parser,
            text=capped,
            metadata=metadata,
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
    if suffix in {".doc", ".docx", ".htm", ".html", ".rtf", ".txt", ".md"} or mime in TEXT_MIME_TYPES or "wordprocessingml" in mime:
        return "document"
    return "unknown"


def _required_decisions_for_source(source_type: str) -> List[str]:
    if source_type == "email":
        return [
            "charles_voice_presence",
            "charles_email_role",
            "other_voice_roles",
            "context_use",
            "boundary_rationale",
            "usable_for_voice_context",
            "usable_for_sft",
            "usable_for_dpo",
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
        "boundary_rationale",
        "usable_for_voice_context",
        "usable_for_grounded_generation",
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
    chunks = list(_chunk_text(extraction.text)) if extraction.status == "extracted" else []
    chunking_truncated = bool(chunks and chunks[-1][1] < len(extraction.text))
    metadata = {
        "status": extraction.status,
        "parser": extraction.parser,
        "preview_text": extraction.preview,
        "total_chars": extraction.total_chars,
        "truncated": extraction.truncated,
        "chunk_count": len(chunks),
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

    segment_ids: List[str] = []
    task_ids: List[str] = []
    if extraction.status == "extracted":
        preview_segment = Segment(
            human_id=f"SEG_PREVIEW_{asset.human_id}_{source_snapshot.version}",
            asset_id=asset.id,
            segment_type="text_preview",
            title=f"{asset.title or filename} preview",
            text_content=extraction.preview,
            locator={"kind": "preview", "source_snapshot_id": source_snapshot.id, "char_start": 0, "char_end": len(extraction.preview)},
            source_truth_status="archival_source",
            maturity_level="L2_extracted",
            metadata_json=metadata,
        )
        session.add(preview_segment)
        session.flush()
        segment_ids.append(preview_segment.id)

        for index, (start, end, chunk) in enumerate(chunks, start=1):
            segment = Segment(
                human_id=f"SEG_CHUNK_{asset.human_id}_{source_snapshot.version}_{index:04d}",
                asset_id=asset.id,
                segment_type="text_chunk",
                title=f"{asset.title or filename} chunk {index}",
                text_content=chunk,
                locator={
                    "kind": "text_chunk",
                    "source_snapshot_id": source_snapshot.id,
                    "chunk_index": index,
                    "char_start": start,
                    "char_end": end,
                },
                source_truth_status="archival_source",
                maturity_level="L2_extracted",
                metadata_json={**metadata, "chunk_index": index, "chunk_count": len(chunks)},
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
                "extraction_parser": extraction.parser,
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
