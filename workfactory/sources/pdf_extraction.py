"""Extract PDF text, OCRing low-text pages without modifying the source PDF."""
import json
import subprocess
import tempfile
from pathlib import Path


def extract_pdf(path, diagnostic_stream):
    from pypdf import PdfReader
    reader = PdfReader(path)
    if reader.is_encrypted and not reader.decrypt(''):
        raise ValueError('encrypted_pdf: password required')
    pages = []
    observations = []
    for number, page in enumerate(reader.pages, 1):
        native = page.extract_text() or ''
        record = {'page': number, 'native_characters': sum(c.isalnum() for c in native),
                  'method': 'native'}
        content = native
        if record['native_characters'] < 30:
            record['method'] = 'ocr'
            try:
                with tempfile.TemporaryDirectory(prefix='workfactory-ocr-') as tmp:
                    prefix = str(Path(tmp) / 'page')
                    # One page at a time and bounded pixels keep large scans within memory.
                    subprocess.run(['pdftoppm', '-f', str(number), '-l', str(number),
                                    '-singlefile', '-scale-to', '2400', '-png',
                                    str(path), prefix], check=True, capture_output=True, timeout=60)
                    result = subprocess.run(['tesseract', prefix + '.png', 'stdout',
                                             '-l', 'eng+chi_sim', '--psm', '3'],
                                            check=True, capture_output=True, text=True, timeout=90)
                    recognized = result.stdout.strip()
                    record['ocr_characters'] = sum(c.isalnum() for c in recognized)
                    # Retain sparse native text if OCR returns less usable text.
                    if record['ocr_characters'] >= record['native_characters']:
                        content = recognized
                    else:
                        record['method'] = 'native_after_ocr'
                    record['low_text_after_ocr'] = sum(c.isalnum() for c in content) < 30
            except (OSError, subprocess.SubprocessError) as exc:
                record['error'] = type(exc).__name__
                print(json.dumps({'pdf_page_extraction': record}), file=diagnostic_stream)
                raise RuntimeError('pdf_ocr_failed on page ' + str(number)) from exc
        observations.append(record)
        print(json.dumps({'pdf_page_extraction': record}), file=diagnostic_stream)
        pages.append('PAGE ' + str(number) + '\n' + content)
    print(json.dumps({'pdf_pages': len(pages), 'ocr_performed': any(
        p['method'] != 'native' for p in observations), 'pages': observations}), file=diagnostic_stream)
    if not any(sum(c.isalnum() for c in text.split('\n', 1)[1]) >= 30 for text in pages):
        raise ValueError('pdf_no_text_after_ocr: inspect blank, illegible or unsupported-language pages')
    return '\n'.join(pages)
