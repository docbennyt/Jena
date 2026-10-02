from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

from .compression import ArchiveFormat, compression_service
from .tasks import TaskCancelled


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".m4v"}
TEXT_EXTENSIONS = {".txt", ".md", ".json", ".csv", ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css", ".toml", ".yaml", ".yml", ".xml", ".log"}
ARCHIVE_EXTENSIONS = {".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz", ".iso", ".cab"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg"}


@dataclass
class PreviewResult:
    path: str
    kind: str
    title: str
    text: str
    image_path: str | None = None
    metadata: dict | None = None


class PreviewService:
    def __init__(self, cache_dir: Path, max_text_chars: int = 12000, compression=None) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_text_chars = max_text_chars
        self.compression = compression

    def preview(self, path: Path, token=None) -> PreviewResult:
        path = path.resolve()
        if token and token.cancelled:
            raise RuntimeError("Preview cancelled.")
        if not path.exists():
            return PreviewResult(str(path), "missing", path.name, "This item no longer exists.")
        suffix = path.suffix.lower()
        stat = path.stat()
        metadata = {"size": stat.st_size, "modified": stat.st_mtime, "path": str(path)}
        if path.is_dir():
            return PreviewResult(str(path), "folder", path.name, f"Folder\n{path}", metadata=metadata)
        try:
            if suffix in IMAGE_EXTENSIONS:
                return self._image_preview(path, metadata)
            if suffix in VIDEO_EXTENSIONS:
                return self._video_preview(path, metadata)
            if suffix == ".pdf":
                return self._pdf_preview(path, metadata)
            if suffix == ".docx":
                return self._docx_preview(path, metadata)
            if suffix == ".xlsx":
                return self._xlsx_preview(path, metadata)
            if suffix == ".pptx":
                return self._pptx_preview(path, metadata)
            if suffix in TEXT_EXTENSIONS:
                return self._text_preview(path, metadata)
            if suffix in ARCHIVE_EXTENSIONS:
                return self._archive_preview(path, metadata, token=token)
            if suffix in AUDIO_EXTENSIONS:
                return PreviewResult(str(path), "audio", path.name, "Audio file\nOpen or play externally to inspect.", metadata=metadata)
        except TaskCancelled:
            raise
        except Exception as exc:
            return PreviewResult(str(path), "fallback", path.name, f"Preview unavailable: {exc}\n\n{path}", metadata=metadata)
        return PreviewResult(str(path), "fallback", path.name, f"{path.name}\n{suffix or 'Unknown type'}\n{path}", metadata=metadata)

    def _image_preview(self, path: Path, metadata: dict) -> PreviewResult:
        from PIL import Image, ImageOps

        thumb = self._cache_path(path, ".png")
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            metadata["dimensions"] = f"{image.width} x {image.height}"
            image.thumbnail((520, 420))
            image.save(thumb, "PNG")
        return PreviewResult(str(path), "image", path.name, f"{path.name}\n{metadata['dimensions']}", str(thumb), metadata)

    def _video_preview(self, path: Path, metadata: dict) -> PreviewResult:
        import imageio_ffmpeg

        thumb = self._cache_path(path, ".jpg")
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        cmd = [exe, "-y", "-ss", "00:00:00.1", "-i", str(path), "-frames:v", "1", "-vf", "scale=520:-1", str(thumb)]
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if not thumb.exists():
            cmd = [exe, "-y", "-i", str(path), "-frames:v", "1", "-vf", "scale=520:-1", str(thumb)]
            completed = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        details = _parse_ffmpeg_details(completed.stderr)
        metadata.update(details)
        text = [path.name, "Video preview"]
        if details.get("duration"):
            text.append(f"Duration: {details['duration']}")
        if details.get("resolution"):
            text.append(f"Resolution: {details['resolution']}")
        if not thumb.exists():
            text.append("Thumbnail could not be generated. Open externally to inspect.")
            return PreviewResult(str(path), "video", path.name, "\n".join(text), metadata=metadata)
        return PreviewResult(str(path), "video", path.name, "\n".join(text), str(thumb), metadata)

    def _pdf_preview(self, path: Path, metadata: dict) -> PreviewResult:
        import fitz

        thumb = self._cache_path(path, ".png")
        doc = fitz.open(path)
        metadata["pages"] = doc.page_count
        page = doc.load_page(0)
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        pix.save(str(thumb))
        text = page.get_text("text")[: self.max_text_chars].strip()
        doc.close()
        return PreviewResult(str(path), "pdf", path.name, f"{path.name}\nPages: {metadata['pages']}\n\n{text}", str(thumb), metadata)

    def _docx_preview(self, path: Path, metadata: dict) -> PreviewResult:
        import docx

        document = docx.Document(path)
        paragraphs = [p.text.strip() for p in document.paragraphs if p.text.strip()]
        metadata["paragraphs"] = len(paragraphs)
        text = "\n\n".join(paragraphs)[: self.max_text_chars]
        return PreviewResult(str(path), "docx", path.name, text or "No text found in document.", metadata=metadata)

    def _xlsx_preview(self, path: Path, metadata: dict) -> PreviewResult:
        import openpyxl

        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        metadata["worksheets"] = workbook.sheetnames
        sheet = workbook[workbook.sheetnames[0]]
        rows = []
        for row in sheet.iter_rows(max_row=12, max_col=8, values_only=True):
            rows.append("\t".join("" if value is None else str(value) for value in row))
        workbook.close()
        return PreviewResult(str(path), "xlsx", path.name, f"Sheets: {', '.join(metadata['worksheets'])}\n\n" + "\n".join(rows), metadata=metadata)

    def _pptx_preview(self, path: Path, metadata: dict) -> PreviewResult:
        import re
        import xml.etree.ElementTree as ET

        lines = []
        slide_count = 0
        with ZipFile(path, "r") as archive:
            slide_names = sorted(name for name in archive.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", name))
            slide_count = len(slide_names)
            for index, name in enumerate(slide_names[:8], start=1):
                root = ET.fromstring(archive.read(name))
                texts = [node.text.strip() for node in root.iter() if node.tag.endswith("}t") and node.text and node.text.strip()]
                if texts:
                    lines.append(f"Slide {index}: " + " | ".join(texts))
        metadata["slides"] = slide_count
        return PreviewResult(str(path), "pptx", path.name, f"Slides: {slide_count}\n\n" + "\n".join(lines), metadata=metadata)

    def _text_preview(self, path: Path, metadata: dict) -> PreviewResult:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            text = handle.read(self.max_text_chars)
        return PreviewResult(str(path), "text", path.name, text, metadata=metadata)

    def _archive_preview(self, path: Path, metadata: dict, token=None) -> PreviewResult:
        required_format = ArchiveFormat.SEVEN_ZIP if path.suffix.lower() == ".7z" else ArchiveFormat.ZIP
        engine = self.compression or compression_service(required_format)
        all_entries = engine.list_entries(path, token=token)
        files = [entry for entry in all_entries if not entry.is_dir]
        metadata["file_count"] = len(files)
        metadata["folder_count"] = len(all_entries) - len(files)
        metadata["uncompressed_bytes"] = sum(entry.size_bytes for entry in files)
        metadata["engine"] = engine.engine_name
        metadata["entries"] = [
            {"path": entry.path, "size_bytes": entry.size_bytes, "is_dir": entry.is_dir}
            for entry in all_entries[:500]
        ]
        names = [entry.path for entry in all_entries[:80]]
        suffix = "\n\nShowing the first 500 entries." if len(all_entries) > 500 else ""
        text = f"Files: {len(files)} · Folders: {metadata['folder_count']}\nEngine: {engine.engine_name}\n\n" + "\n".join(names) + suffix
        return PreviewResult(str(path), "archive", path.name, text, metadata=metadata)

    def _cache_path(self, path: Path, suffix: str) -> Path:
        stat = path.stat()
        key = json.dumps([str(path).lower(), stat.st_mtime, stat.st_size])
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}{suffix}"


def _parse_ffmpeg_details(stderr: str) -> dict:
    details: dict[str, str] = {}
    for line in stderr.splitlines():
        line = line.strip()
        if "Duration:" in line:
            details["duration"] = line.split("Duration:", 1)[1].split(",", 1)[0].strip()
        if " Video:" in f" {line}" and "x" in line:
            parts = [part.strip() for part in line.split(",")]
            for part in parts:
                if "x" in part and any(ch.isdigit() for ch in part):
                    details["resolution"] = part.split()[0]
                    break
    return details
