from __future__ import annotations

import pikepdf

from pdfscan.pdf.analyze import is_encrypted
from pdfscan.pdf.verify import looks_like_pdf


# --- looks_like_pdf (magic-byte gate) -----------------------------------------
def test_looks_like_pdf_true_for_pdf_marker(tmp_path):
    p = tmp_path / "a.pdf"
    p.write_bytes(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj")
    assert looks_like_pdf(p) is True


def test_looks_like_pdf_true_with_leading_whitespace(tmp_path):
    p = tmp_path / "b.pdf"
    p.write_bytes(b"\xef\xbb\xbf   \n%PDF-1.4 rest")  # BOM + whitespace before marker
    assert looks_like_pdf(p) is True


def test_looks_like_pdf_false_for_html(tmp_path):
    p = tmp_path / "c.pdf"
    p.write_bytes(b"<!DOCTYPE html><html><body>Not found</body></html>")
    assert looks_like_pdf(p) is False


def test_looks_like_pdf_false_for_missing_file(tmp_path):
    assert looks_like_pdf(tmp_path / "missing.pdf") is False


# --- is_encrypted -------------------------------------------------------------
def test_is_encrypted_false_for_plain_pdf(tmp_path):
    plain = tmp_path / "plain.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.save(plain)
    assert is_encrypted(plain) is False


def test_is_encrypted_true_for_password_protected(tmp_path):
    enc = tmp_path / "enc.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.save(enc, encryption=pikepdf.Encryption(owner="pw", user="pw"))
    assert is_encrypted(enc) is True


def test_is_encrypted_false_for_non_pdf(tmp_path):
    junk = tmp_path / "junk.bin"
    junk.write_bytes(b"not a pdf at all")
    assert is_encrypted(junk) is False
