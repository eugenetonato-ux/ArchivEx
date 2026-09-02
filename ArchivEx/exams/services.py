from io import BytesIO
from django.utils import timezone
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas


def apply_student_watermark(pdf_source, user):
    """
    Overlays a dynamic, personalized watermark on every page of a PDF document.
    Watermark lines:
    1. Student Full Name (or username/email)
    2. "ArchivEx — Consultation personnelle"
    3. Date & Time (DD/MM/YYYY • HH:MM)
    """
    if hasattr(pdf_source, "read"):
        pdf_bytes = pdf_source.read()
    elif isinstance(pdf_source, bytes):
        pdf_bytes = pdf_source
    else:
        with open(pdf_source, "rb") as f:
            pdf_bytes = f.read()

    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        writer = PdfWriter()

        full_name = ""
        if hasattr(user, "get_full_name"):
            full_name = user.get_full_name().strip()
        if not full_name:
            full_name = getattr(user, "username", "Étudiant ArchivEx")

        email = getattr(user, "email", "")
        now_str = timezone.now().strftime("%d/%m/%Y • %H:%M")

        text_lines = [
            full_name,
        ]
        if email:
            text_lines.append(email)
        text_lines.extend([
            "ArchivEx — Consultation personnelle",
            now_str,
        ])

        for page in reader.pages:
            width = float(page.mediabox.width)
            height = float(page.mediabox.height)

            wm_buf = BytesIO()
            c = canvas.Canvas(wm_buf, pagesize=(width, height))
            c.saveState()
            c.setFont("Helvetica-Bold", 9)
            from reportlab.lib import colors
            c.setFillColor(colors.Color(0.5, 0.5, 0.5, alpha=0.28))
            c.rotate(32)

            step_x = 240
            step_y = 140
            for x in range(-250, int(width + 450), step_x):
                for y in range(-250, int(height + 450), step_y):
                    curr_y = y
                    for line in text_lines:
                        c.drawString(x, curr_y, line)
                        curr_y -= 11

            c.restoreState()
            c.save()
            wm_buf.seek(0)

            wm_page = PdfReader(wm_buf).pages[0]
            page.merge_page(wm_page)
            writer.add_page(page)

        output_buf = BytesIO()
        writer.write(output_buf)
        output_buf.seek(0)
        return output_buf
    except Exception:
        # Graceful fallback for non-standard or raw PDF streams
        buf = BytesIO(pdf_bytes)
        buf.seek(0)
        return buf
