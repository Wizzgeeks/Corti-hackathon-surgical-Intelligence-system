import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PyPdfError


class PdfExtractionError(Exception):
    """Raised when a PDF cannot be parsed."""


@dataclass
class PdfContent:
    page_count: int
    pages: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n\n".join(self.pages).strip()

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def is_scanned(self) -> bool:
        """No extractable text usually means an image-only (scanned) PDF."""
        return self.char_count == 0


def _extract(path: Path) -> PdfContent:
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            # Many clinical PDFs are encrypted with an empty owner password.
            if reader.decrypt("") == 0:
                raise PdfExtractionError("PDF is password protected.")

        pages = [(page.extract_text() or "").strip() for page in reader.pages]
        metadata = {
            k.lstrip("/"): str(v)
            for k, v in (reader.metadata or {}).items()
            if v is not None
        }
    except PdfExtractionError:
        raise
    except PyPdfError as exc:
        raise PdfExtractionError(f"Could not parse PDF: {exc}") from exc

    return PdfContent(page_count=len(pages), pages=pages, metadata=metadata)


async def read_pdf(path: Path) -> PdfContent:
    """Extract text from a PDF off the event loop."""
    return await asyncio.to_thread(_extract, path)
