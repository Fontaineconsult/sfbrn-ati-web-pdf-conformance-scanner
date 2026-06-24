from __future__ import annotations

from pdfscan.storage.layout import render_storage_path

TPL = "{root}/{site}/{path}/{filename}"


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
