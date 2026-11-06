from datetime import datetime

from fpdf import FPDF
from fastapi import Response

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def certificate_pdf(code: str, result: str, created_at: datetime | None = None) -> Response:
    pdf = FPDF()
    pdf.add_page()
    pdf.add_font("Persian", fname=FONT)
    pdf.set_text_shaping(True)
    pdf.set_font("Persian", size=22)
    pdf.set_fill_color(16, 63, 58)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 24, "گواهی آزمایشی اقدام ادعا", fill=True, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(10)
    pdf.set_text_color(23, 53, 47)
    pdf.set_font("Persian", size=14)
    fields = [("کد پیگیری ادعا", code), ("مرجع نتیجه", result)]
    if created_at is not None:
        fields.append(("زمان ثبت ادعا", created_at.strftime("%Y-%m-%d %H:%M:%S UTC")))
    for label, value in fields:
        pdf.cell(0, 10, label, align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 10, value, align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)
    pdf.multi_cell(0, 10, "این گواهی در محیط شبیه‌سازی صادر شده و اعتبار رسمی ندارد.", align="R")
    return Response(bytes(pdf.output()), media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="claim-{code}.pdf"',
        "Cache-Control": "no-store",
    })
