"""Local OCR for scanned (image-only) prospectus pages, using Tesseract through PyMuPDF.

Some offer documents embed the restated financial statements as scanned images with no text
layer. When the Tesseract engine is installed locally (free, open source; ``brew install
tesseract`` / ``apt install tesseract-ocr``), those pages are recognised and handed to the same
table parser and accounting checks as text pages. Nothing is sent to an external service.

OCR misreads digits now and then, and the accounting checks do not cover every line (depreciation
and finance costs, for example). Periods read from OCR'd pages are therefore stored at most as
``extracted`` — displayed with their page references, never used in scores — even when every
check passes.
"""
from __future__ import annotations

import logging
import shutil
import time
from collections.abc import Iterator
from typing import Any

log = logging.getLogger(__name__)

MIN_TEXT_CHARS = 50  # a page with less text than this is treated as image-only


def tesseract_available() -> bool:
    try:
        import pymupdf

        return shutil.which("tesseract") is not None and bool(pymupdf.get_tessdata())
    except Exception:  # noqa: BLE001 - get_tessdata raises when no language data is installed
        return False


def image_only_pages(texts: list[str]) -> list[int]:
    return [i for i, t in enumerate(texts) if len(t.strip()) < MIN_TEXT_CHARS]


class OcrPage:
    """A page whose text queries are answered from an OCR text page; everything else is the real page."""

    def __init__(self, page: Any, textpage: Any) -> None:
        self._page = page
        self._tp = textpage

    def get_text(self, option: str = "text", **kwargs: Any) -> Any:
        return self._page.get_text(option, textpage=self._tp, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._page, name)


class OcrDocument:
    """Wraps a PyMuPDF document so that selected pages are read through Tesseract."""

    def __init__(self, pdf: Any, pages: list[int], *, dpi: int = 300, language: str = "eng", time_budget_s: float = 900.0) -> None:
        self._pdf = pdf
        self._tps: dict[int, tuple[Any, Any]] = {}
        self.failed: list[int] = []
        start = time.monotonic()
        for i in pages:
            if time.monotonic() - start > time_budget_s:
                self.failed.extend(p for p in pages if p not in self._tps and p not in self.failed)
                log.warning("OCR time budget of %.0f s reached after %d pages", time_budget_s, len(self._tps))
                break
            try:
                page = pdf[i]  # the text page refers back to this page object weakly, so both are kept
                self._tps[i] = (page, page.get_textpage_ocr(language=language, dpi=dpi, full=True))
            except Exception as exc:  # noqa: BLE001 - one unreadable page must not stop the others
                log.warning("OCR failed on page %d: %s", i + 1, exc)
                self.failed.append(i)

    @property
    def ocr_pages(self) -> set[int]:
        """1-based numbers of the pages that were recognised by OCR."""
        return {i + 1 for i in self._tps}

    @property
    def page_count(self) -> int:
        return int(self._pdf.page_count)

    def __len__(self) -> int:
        return int(self._pdf.page_count)

    def __getitem__(self, i: int) -> Any:
        if i < 0:
            i += self.page_count
        if i in self._tps:
            return OcrPage(*self._tps[i])
        return self._pdf[i]

    def __iter__(self) -> Iterator[Any]:
        for i in range(self.page_count):
            yield self[i]
