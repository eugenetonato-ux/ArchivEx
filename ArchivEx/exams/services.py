from io import BytesIO
from django.utils import timezone


def apply_student_watermark(pdf_source, user):
    """
    Incruste un filigrane numérique personnalisé sur chaque page d'un document PDF.
    Gère sereinement tous les types de fichiers (FieldFile, path str, BytesIO, bytes).
    SI pypdf ou reportlab n'est pas installé sur le serveur, renvoie le PDF d'origine sans erreur 500.
    """
    pdf_bytes = None

    # 1. Extraction sécurisée des octets bruts du PDF
    try:
        if isinstance(pdf_source, bytes):
            pdf_bytes = pdf_source
        elif isinstance(pdf_source, str) and os.path.exists(pdf_source):
            with open(pdf_source, "rb") as f:
                pdf_bytes = f.read()
        elif hasattr(pdf_source, "open"):
            try:
                pdf_source.open("rb")
            except Exception:
                pass
            pdf_bytes = pdf_source.read()
            try:
                pdf_source.close()
            except Exception:
                pass
        elif hasattr(pdf_source, "read"):
            pdf_bytes = pdf_source.read()
    except Exception:
        pdf_bytes = None

    if not pdf_bytes or len(pdf_bytes) < 20 or not pdf_bytes.startswith(b"%PDF"):
        raise ValueError("Le fichier PDF est inexistant, incomplet ou corrompu.")

    # 2. Application du filigrane avec pypdf et reportlab (lazy import sécurisé)
    try:
        from pypdf import PdfReader, PdfWriter
        from reportlab.pdfgen import canvas
        from reportlab.lib import colors

        reader = PdfReader(BytesIO(pdf_bytes))
        writer = PdfWriter()

        full_name = ""
        if hasattr(user, "get_full_name"):
            full_name = user.get_full_name().strip()
        if not full_name:
            full_name = getattr(user, "username", "Étudiant ArchivEx")

        email = getattr(user, "email", "")
        now_str = timezone.now().strftime("%d/%m/%Y • %H:%M")

        text_lines = [full_name]
        if email:
            text_lines.append(email)
        text_lines.extend(["ArchivEx — Consultation personnelle", now_str])

        for page in reader.pages:
            width = 595.27
            height = 841.89
            try:
                if hasattr(page, "mediabox") and page.mediabox:
                    width = float(page.mediabox.width)
                    height = float(page.mediabox.height)
            except Exception:
                try:
                    if hasattr(page, "cropbox") and page.cropbox:
                        width = float(page.cropbox.width)
                        height = float(page.cropbox.height)
                except Exception:
                    pass

            if not width or width <= 0:
                width = 595.27
            if not height or height <= 0:
                height = 841.89

            wm_buf = BytesIO()
            c = canvas.Canvas(wm_buf, pagesize=(width, height))
            c.saveState()
            c.setFont("Helvetica-Bold", 10)
            c.setFillColor(colors.Color(0.75, 0.2, 0.2, alpha=0.32))
            c.rotate(32)

            step_x = 260
            step_y = 150
            for x in range(-250, int(width + 450), step_x):
                for y in range(-250, int(height + 450), step_y):
                    curr_y = y
                    for line in text_lines:
                        c.drawString(x, curr_y, line)
                        curr_y -= 12

            c.restoreState()
            c.save()
            wm_buf.seek(0)

            wm_page = PdfReader(wm_buf).pages[0]
            try:
                page.merge_page(wm_page, over=True)
            except Exception:
                wm_page.merge_page(page)
                page = wm_page
            writer.add_page(page)

        output_buf = BytesIO()
        writer.write(output_buf)
        output_buf.seek(0)
        return output_buf

    except Exception:
        # Repli de secours : renvoyer le flux PDF brut d'origine sans tatouage si pypdf/reportlab est absent ou plante
        buf = BytesIO(pdf_bytes)
        buf.seek(0)
        return buf
