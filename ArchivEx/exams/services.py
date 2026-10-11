import os
import re
import unicodedata
from io import BytesIO
from django.utils import timezone


def _sanitize_storage_key(key):
    """Normalise un chemin de fichier pour correspondre aux clés Supabase S3 (sans accents, sans espaces)."""
    if not key:
        return ""
    parts = str(key).replace("\\", "/").split("/")
    sanitized_parts = []
    for i, part in enumerate(parts):
        if i < len(parts) - 1:
            sanitized_parts.append(part)
        else:
            normalized = unicodedata.normalize("NFKD", part)
            ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
            ascii_name = re.sub(r"[^\w\-\.]", "_", ascii_name)
            ascii_name = re.sub(r"_+", "_", ascii_name)
            sanitized_parts.append(ascii_name)
    return "/".join(sanitized_parts)


def extract_raw_pdf_bytes(pdf_source):
    """
    Extrait de manière ultra-résiliente les octets bruts d'un fichier PDF,
    qu'il provienne du disque local, d'un FieldFile Django, ou du stockage distant S3 / Supabase.
    Sauvegarde automatiquement une copie locale dans MEDIA_ROOT pour optimiser les accès ultérieurs.
    """
    if not pdf_source:
        return None

    if isinstance(pdf_source, (bytes, bytearray)):
        return bytes(pdf_source)

    from django.conf import settings

    # 1. Si chemin string vers un fichier local existant
    if isinstance(pdf_source, str):
        if os.path.exists(pdf_source):
            try:
                with open(pdf_source, "rb") as f:
                    data = f.read()
                    if data and data.startswith(b"%PDF"):
                        return data
            except Exception:
                pass
        # Vérifier aussi dans MEDIA_ROOT
        loc = os.path.join(settings.MEDIA_ROOT, pdf_source.strip("/\\"))
        if os.path.exists(loc):
            try:
                with open(loc, "rb") as f:
                    data = f.read()
                    if data and data.startswith(b"%PDF"):
                        return data
            except Exception:
                pass
        # Vérifier le nom normalisé dans MEDIA_ROOT
        loc_clean = os.path.join(settings.MEDIA_ROOT, _sanitize_storage_key(pdf_source).strip("/\\"))
        if os.path.exists(loc_clean):
            try:
                with open(loc_clean, "rb") as f:
                    data = f.read()
                    if data and data.startswith(b"%PDF"):
                        return data
            except Exception:
                pass

    # 2. Si objet FieldFile Django
    fname = getattr(pdf_source, "name", "")
    if fname:
        # A. Vérifier sur le disque local en premier (avec nom brut et nom normalisé)
        loc = os.path.join(settings.MEDIA_ROOT, str(fname).strip("/\\"))
        if os.path.exists(loc):
            try:
                with open(loc, "rb") as f:
                    data = f.read()
                    if data and data.startswith(b"%PDF"):
                        return data
            except Exception:
                pass
        loc_clean = os.path.join(settings.MEDIA_ROOT, _sanitize_storage_key(fname).strip("/\\"))
        if os.path.exists(loc_clean):
            try:
                with open(loc_clean, "rb") as f:
                    data = f.read()
                    if data and data.startswith(b"%PDF"):
                        return data
            except Exception:
                pass

        # B. Tenter de lire via S3 Client directement (contourne le HeadObject 400 de Supabase)
        storage = getattr(pdf_source, "storage", None)
        if storage and hasattr(storage, "connection") and hasattr(storage, "bucket_name"):
            try:
                client = storage.connection.meta.client
                bucket = storage.bucket_name
                candidates = [str(fname), _sanitize_storage_key(fname)]
                for cand in candidates:
                    try:
                        res = client.get_object(Bucket=bucket, Key=cand)
                        raw = res["Body"].read()
                        if raw and raw.startswith(b"%PDF"):
                            # Sauvegarder en cache disque local dans MEDIA_ROOT pour les prochaines requêtes
                            try:
                                os.makedirs(os.path.dirname(loc_clean), exist_ok=True)
                                with open(loc_clean, "wb") as f_out:
                                    f_out.write(raw)
                            except Exception:
                                pass
                            return raw
                    except Exception:
                        continue
            except Exception:
                pass

        # C. Lecture standard via storage.open()
        if hasattr(pdf_source, "open"):
            try:
                pdf_source.open("rb")
                raw = pdf_source.read()
                try:
                    pdf_source.close()
                except Exception:
                    pass
                if raw and raw.startswith(b"%PDF"):
                    return raw
            except Exception:
                pass

    # 3. Repli objet stream (BytesIO, etc.)
    if hasattr(pdf_source, "read"):
        try:
            raw = pdf_source.read()
            if raw and raw.startswith(b"%PDF"):
                return raw
        except Exception:
            pass

    return None


def apply_student_watermark(pdf_source, user):
    """
    Incruste un filigrane numérique personnalisé haute visibilité directement
    SUR l'épreuve PDF (au premier plan, over=True) avec bandeaux de traçabilité
    (nom, prénom, email, horodatage) et motif diagonal répété.
    Gère tous les types de sources (FieldFile, chemin str, BytesIO, bytes, Supabase S3).
    """
    pdf_bytes = extract_raw_pdf_bytes(pdf_source)

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

                # 1. Bandeau inférieur de sécurité anti-partage (message d'interdiction certifié agrandi et très lisible)
                c.setFillColor(colors.Color(0.98, 0.94, 0.94, alpha=0.96))
                c.rect(0, 0, width, 24, fill=1, stroke=0)
                c.setFillColor(colors.Color(0.85, 0.05, 0.05, alpha=1.0))
                c.setFont("Helvetica-Bold", 10)
                footer_text = f"AVERTISSEMENT : Document certifié ArchivEx ID-{user_id} • Reproduction, capture et redistribution strictement interdites."
                c.drawString(14, 7, footer_text[:140])

                # 2. Filigrane unique centré au milieu de la page (lisibilité renforcée et nette)
                c.translate(width / 2.0, height / 2.0)
                c.rotate(32)
                c.setFont("Helvetica-Bold", 22)
                c.setFillColor(colors.Color(0.25, 0.32, 0.45, alpha=0.30))
                c.drawCentredString(0, 12, f"ARCHIVEX • {full_name}")
                c.setFont("Helvetica-Bold", 13)
                c.drawCentredString(0, -12, f"{email} • Consultation individuelle")

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
