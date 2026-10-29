"""Создаёт вымышленные вложения мини-чата в tests/fixtures/mini_chat/files/.

Запуск из корня репозитория: python tests/fixtures/make_mini_chat_files.py
Файлы детерминированы (фиксированное время в архиве), поэтому повторный запуск ничего не меняет.
Внутри только вымышленный текст на латинице, настоящих данных нет.
"""
import io
import pathlib
import zipfile

OUT = pathlib.Path(__file__).resolve().parent / "mini_chat" / "files"

PDFS = ["lab2_elektro.pdf", "metodichka_lab3.pdf", "lab2_elektro_v2.pdf", "lab1_algo_v2.pdf"]
DOCXS = ["report_example.docx", "template_report.docx", "hw1_condition.docx", "kursach_template.docx",
         "hw1_template_algo.docx", "hw2_condition_algo.docx"]


def make_pdf(title: str) -> bytes:
    """Минимальный валидный PDF на одну страницу."""
    stream = f"BT /F1 14 Tf 72 720 Td (Synthetic test file: {title}. Not real data.) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def make_docx(title: str) -> bytes:
    """Минимальный валидный DOCX (zip с тремя частями)."""
    parts = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        "word/document.xml": f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Synthetic test file: {title}. Not real data.</w:t></w:r></w:p></w:body></w:document>',
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in parts.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, text)
    return buf.getvalue()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name in PDFS:
        (OUT / name).write_bytes(make_pdf(name))
    for name in DOCXS:
        (OUT / name).write_bytes(make_docx(name))


if __name__ == "__main__":
    main()
