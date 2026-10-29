"""Counting the pages of a document before it is printed (spoolsteward/policy/pages.py)."""

import io

import pytest
from pypdf import PdfWriter

from spoolsteward.policy.pages import count_pages


def pdf(pages: int) -> bytes:
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(595, 842)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def test_a_pdf_is_counted_by_its_real_pages():
    assert count_pages(pdf(1), "application/pdf") == 1
    assert count_pages(pdf(37), "application/pdf") == 37


@pytest.mark.parametrize("declared", [1, 2, 9])
def test_a_pdf_that_lies_about_its_page_count_is_counted_by_its_real_pages(declared):
    """The /Count of the page tree is only a claim. A file that says 1 and holds 5 (poppler's pdfinfo believes it) must count 5, or
    the pages limit could be passed by a crafted file. This pins the behaviour of the pypdf version in requirements/runtime.txt: a
    newer pypdf that trusted /Count would fail here, and be noticed."""
    data = pdf(5)
    assert b"/Count 5" in data
    forged = data.replace(b"/Count 5", b"/Count %d" % declared)       # one digit for one digit: no offset of the file moves
    assert forged != data
    assert count_pages(forged, "application/pdf") == 5


def test_a_damaged_or_encrypted_pdf_is_left_to_cups():
    assert count_pages(b"%PDF-1.7\n garbage", "application/pdf") is None
    w = PdfWriter()
    w.add_blank_page(100, 100)
    w.encrypt("x")
    out = io.BytesIO()
    w.write(out)
    assert count_pages(out.getvalue(), "application/pdf") is None


# ---------------------------------------------------------------- the memory ceiling while counting (IPP gateway)

import asyncio
import threading
import time
from types import SimpleNamespace

from spoolsteward.config import Settings, settings
from spoolsteward.ipp import codec, gateway
from spoolsteward.policy import pages as pages_mod


def test_the_defaults_of_the_counting_ceiling():
    s = Settings(_env_file=None)
    assert (s.page_count_at_once, s.page_count_max_mb) == (2, 32)


async def _body(data: bytes, chunk: int = 1 << 16):
    for i in range(0, len(data), chunk):
        yield data[i:i + chunk]


def _call(data: bytes):
    msg = SimpleNamespace(code=codec.PRINT_JOB, get=lambda *a: None)
    return SimpleNamespace(msg=msg, user=object(), og={}, head_rest=b"", rest=_body(data), sm=None, pages=None)


@pytest.fixture
def slow_counter(monkeypatch):
    seen = {"now": 0, "most": 0}
    lock = threading.Lock()

    def count(data, declared=None):
        with lock:
            seen["now"] += 1
            seen["most"] = max(seen["most"], seen["now"])
        time.sleep(0.15)
        with lock:
            seen["now"] -= 1
        return 3
    monkeypatch.setattr(gateway, "_has_pages_rule", lambda sm, user: True)
    monkeypatch.setattr(pages_mod, "count_pages", count)
    return seen


@pytest.mark.parametrize("limit", [1, 2])
async def test_only_that_many_documents_are_counted_at_once_and_all_are_counted(slow_counter, monkeypatch, limit):
    monkeypatch.setattr(settings, "page_count_at_once", limit)
    calls = [_call(b"%PDF-1.4 " + b"x" * 1000) for _ in range(6)]
    await asyncio.gather(*[gateway._count_pages(c) for c in calls])
    assert [c.pages for c in calls] == [3] * 6                 # nobody is skipped or refused for waiting
    assert slow_counter["most"] == limit


async def test_a_document_over_the_ceiling_is_not_read_before_printing(slow_counter, monkeypatch):
    monkeypatch.setattr(settings, "page_count_max_mb", 1)
    big, small = _call(b"%PDF-1.4 " + b"x" * (2 << 20)), _call(b"%PDF-1.4 " + b"x" * 1000)
    await gateway._count_pages(big)
    await gateway._count_pages(small)
    assert big.pages is None and small.pages == 3              # counted afterwards, as for any uncountable file
    assert b"".join([c async for c in big.rest]) is not None   # the rest of the body is still there to be forwarded
