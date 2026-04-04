from studyvault_backend_common.responses import build_attachment_content_disposition


def test_content_disposition_uses_ascii_fallback_for_plain_filename() -> None:
    header = build_attachment_content_disposition("lecture.txt")

    assert header == 'attachment; filename="lecture.txt"; filename*=UTF-8\'\'lecture.txt'


def test_content_disposition_strips_control_chars_and_quotes() -> None:
    header = build_attachment_content_disposition('bad"\r\nname.txt')

    assert "\r" not in header
    assert "\n" not in header
    assert 'filename="badname.txt"' in header
    assert "filename*=UTF-8''badname.txt" in header


def test_content_disposition_emits_rfc5987_filename_for_non_ascii_name() -> None:
    header = build_attachment_content_disposition("žetón notes.pdf")

    assert 'filename="zeton notes.pdf"' in header
    assert "filename*=UTF-8''%C5%BEet%C3%B3n%20notes.pdf" in header
