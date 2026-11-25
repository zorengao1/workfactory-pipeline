"""Source artifact checks without changing source bytes."""
import re
from urllib.parse import urlsplit


def preflight(body, url, content_type=''):
    if not body:
        raise ValueError('empty_download: server returned zero bytes')
    sample = body[:4096].lstrip().lower()
    html = sample.startswith((b'<!doctype html', b'<html')) or 'text/html' in (content_type or '').lower()
    expected_pdf = urlsplit(url).path.lower().endswith('.pdf')
    if expected_pdf and not body.startswith(b'%PDF'):
        kind = 'html_instead_of_pdf' if html else 'invalid_pdf_signature'
        raise ValueError(kind + ': requested PDF was not returned')
    if html and any(marker in sample for marker in (b'<title>access denied', b'<title>403', b'<title>404', b'<title>just a moment')):
        raise ValueError('access_or_error_page: source returned an error/challenge page')


def text_quality(text):
    # Exclude generated page labels from the useful-content count.
    clean = re.sub(r'(?m)^PAGE \d+\s*$', '', text)
    count = sum(c.isalnum() for c in clean)
    if count < 30:
        raise ValueError('no_readable_content: fewer than 30 letters/digits after extraction')
    return {'readable_characters': count, 'short_document': count < 500,
            'semantic_sufficiency': 'not_assessed'}
