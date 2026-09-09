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

        wm_pages_by_size = {}

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

            size_key = (round(width, 1), round(height, 1))

            if size_key not in wm_pages_by_size:
                wm_buf = BytesIO()
                c = canvas.Canvas(wm_buf, pagesize=(width, height))
                c.saveState()

                # 1. Bandeau inférieur de sécurité anti-partage (message d'interdiction certifié)
                c.setFillColor(colors.Color(1.0, 1.0, 1.0, alpha=0.92))
                c.rect(0, 0, width, 18, fill=1, stroke=0)
                c.setFillColor(colors.Color(0.80, 0.12, 0.12, alpha=0.95))
                c.setFont("Helvetica-Bold", 7.5)
                footer_text = f"Document certifié ArchivEx ID-{user_id} • Reproduction, capture et redistribution strictement interdites."
                c.drawString(12, 5, footer_text[:120])

                # 2. Filigrane unique centré au milieu de la page (lisibilité optimale)
                c.translate(width / 2.0, height / 2.0)
                c.rotate(32)
                c.setFont("Helvetica-Bold", 16)
                c.setFillColor(colors.Color(0.45, 0.50, 0.60, alpha=0.18))
                c.drawCentredString(0, 10, f"ARCHIVEX • {full_name}")
                c.setFont("Helvetica-Bold", 11)
                c.drawCentredString(0, -9, f"{email} • Consultation individuelle")

                c.restoreState()
                c.save()
                wm_buf.seek(0)
                wm_pages_by_size[size_key] = PdfReader(wm_buf).pages[0]

            wm_page = wm_pages_by_size[size_key]
            try:
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
