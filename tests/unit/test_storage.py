from __future__ import annotations

from pdfscan.storage.layout import render_storage_path, save_pdf

TPL = "{root}/{site}/{path}/{filename}"
HASH_TPL = "{root}/{site}/{hash}.pdf"


def test_mirror_site_path_url_decoded():
    p = render_storage_path(
        "https://hr.sfsu.edu/sites/default/files/a%20b.pdf", "hr", "abc123",
        root="/data/rem", template=TPL,
    )
    s = p.as_posix()
    assert s.endswith("hr/sites/default/files/a b.pdf")


def test_empty_path_segment_collapses():
    p = render_storage_path(
        "https://x.edu/file.pdf", "x", "h", root="/data", template=TPL
    )
    assert "//" not in p.as_posix()
    assert p.name == "file.pdf"


def test_box_static_filename_kept():
    p = render_storage_path(
        "https://sfsu.app.box.com/public/static/abcdef.pdf", "hr", "h", root="/d", template=TPL
    )
    assert p.name == "abcdef.pdf"


def test_non_pdf_basename_falls_back_to_hash():
    p = render_storage_path(
        "https://x.edu/download?id=5", "x", "deadbeefdeadbeef0000", root="/d", template=TPL
    )
    assert p.name.endswith(".pdf")
    assert "deadbeef" in p.name


def test_date_token():
    p = render_storage_path(
        "https://x.edu/a.pdf", "x", "h", root="/d",
        template="{root}/{site}/{date}/{filename}", today="2026-06-24",
    )
    assert "2026-06-24" in p.as_posix()


# --- save_pdf: content-addressed dedup ----------------------------------------
def test_save_pdf_dedup_same_hash_does_not_overwrite(tmp_path):
    root = tmp_path / "rem"
    first = tmp_path / "first.pdf"
    first.write_bytes(b"%PDF-1.7 ORIGINAL")
    second = tmp_path / "second.pdf"
    second.write_bytes(b"%PDF-1.7 DIFFERENT-BYTES")

    # Same hash (e.g. identical content seen at two URLs) -> one stored file.
    d1 = save_pdf(first, "https://x/a.pdf", "site", "HASH", root=root, template=HASH_TPL)
    d2 = save_pdf(second, "https://x/other-url.pdf", "site", "HASH", root=root, template=HASH_TPL)

    assert d1 == d2
    # Dedup skips the second copy; the original bytes are preserved (no clobber).
    assert d1.read_bytes() == b"%PDF-1.7 ORIGINAL"


def test_save_pdf_distinct_hash_distinct_path(tmp_path):
    root = tmp_path / "rem"
    old = tmp_path / "old.pdf"
    old.write_bytes(b"%PDF-1.7 OLD")
    new = tmp_path / "new.pdf"
    new.write_bytes(b"%PDF-1.7 NEW")

    # Same URL, file replaced -> different hash -> different path, both kept.
    d1 = save_pdf(old, "https://x/doc.pdf", "site", "HASH_OLD", root=root, template=HASH_TPL)
    d2 = save_pdf(new, "https://x/doc.pdf", "site", "HASH_NEW", root=root, template=HASH_TPL)

    assert d1 != d2
    assert d1.read_bytes() == b"%PDF-1.7 OLD"
    assert d2.read_bytes() == b"%PDF-1.7 NEW"
