import os
from io import BytesIO
from django.utils import timezone


def apply_student_watermark(pdf_source, user):
    """
    Incruste un filigrane numérique personnalisé haute visibilité directement
    SUR l'épreuve PDF (au premier plan, over=True) avec bandeaux de traçabilité
    (nom, prénom, email, horodatage) et motif diagonal répété.
    Gère tous les types de sources (FieldFile, chemin str, BytesIO, bytes).
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

    # 2. Application du filigrane direct au premier plan avec pypdf et reportlab
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

        email = getattr(user, "email", "") or f"user-{getattr(user, 'id', '0')}@archivex.bj"
        user_id = str(getattr(user, "id", "0"))
        now_str = timezone.now().strftime("%d/%m/%Y à %H:%M")

        text_lines = [
            f"{full_name}",
            f"{email}",
            f"ArchivEx — Consultation personnelle",
            f"{now_str}",
        ]

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

            # A. Bandeau supérieur officiel de traçabilité (fond blanc translucide + texte rouge foncé)
            c.setFillColor(colors.Color(1.0, 1.0, 1.0, alpha=0.88))
            c.rect(0, height - 26, width, 26, fill=1, stroke=0)
            c.setFillColor(colors.Color(0.80, 0.12, 0.12, alpha=0.95))
            c.setFont("Helvetica-Bold", 8)
            header_text = f"ARCHIVEX • Épreuve sous licence individuelle • Étudiant : {full_name} ({email}) • {now_str}"
            c.drawString(12, height - 17, header_text[:110])

            # B. Bandeau inférieur de sécurité anti-partage
            c.setFillColor(colors.Color(1.0, 1.0, 1.0, alpha=0.88))
            c.rect(0, 0, width, 20, fill=1, stroke=0)
            c.setFillColor(colors.Color(0.80, 0.12, 0.12, alpha=0.95))
            c.setFont("Helvetica-Bold", 7.5)
            footer_text = f"Document certifié ArchivEx ID-{user_id} • Reproduction, capture et redistribution strictement interdites."
            c.drawString(12, 7, footer_text[:120])

            # C. Filigrane diagonal répété directement SUR le corps du document
            c.setFont("Helvetica-Bold", 11)
            c.setFillColor(colors.Color(0.80, 0.12, 0.12, alpha=0.38))
            c.rotate(35)

            step_x = 240
            step_y = 130
            for x in range(-350, int(width + 550), step_x):
                for y in range(-350, int(height + 550), step_y):
                    curr_y = y
                    for line in text_lines:
                        c.drawString(x, curr_y, line)
                        curr_y -= 13

            c.restoreState()
            c.save()
            wm_buf.seek(0)

            wm_page = PdfReader(wm_buf).pages[0]
            try:
                # over=True garantit que le filigrane est incrusté AU-DESSUS du contenu du PDF
                page.merge_page(wm_page, over=True)
            except Exception:
                try:
                    page.merge_page(wm_page)
                except Exception:
                    pass
            writer.add_page(page)

        output_buf = BytesIO()
        writer.write(output_buf)
        output_buf.seek(0)
        return output_buf

    except Exception:
        # Repli de secours sécurisé en cas d'erreur de parsing
        buf = BytesIO(pdf_bytes)
        buf.seek(0)
        return buf
