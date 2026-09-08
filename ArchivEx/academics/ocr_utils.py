import io
import logging
import os
import re
from django.conf import settings

logger = logging.getLogger(__name__)

try:
    import pypdf
except ImportError:
    pypdf = None

try:
    import pytesseract
    from PIL import Image
except ImportError:
    pytesseract = None
    Image = None

try:
    import pdf2image
except ImportError:
    pdf2image = None


def extract_text_from_pdf(pdf_source, force_ocr=False, max_pages=10):
    """
    Extrait le texte d'un fichier PDF (chemin, objet fichier, bytes).
    1. Essaie d'abord l'extraction native pypdf.
    2. Si le texte extrait est vide/trop court (< 50 caractères) ou si force_ocr=True,
       exécute l'OCR serveur via pytesseract/pdf2image ou pypdf image extraction.
    """
    extracted_text = ""
    used_ocr = False
    error_msg = None
    reader = None

    # Etape 1: Lecture directe via PyPDF
    try:
        if isinstance(pdf_source, (str, os.PathLike)):
            if os.path.exists(pdf_source):
                reader = pypdf.PdfReader(pdf_source)
        elif hasattr(pdf_source, "read"):
            if hasattr(pdf_source, "seek"):
                pdf_source.seek(0)
            reader = pypdf.PdfReader(pdf_source)
            if hasattr(pdf_source, "seek"):
                pdf_source.seek(0)
        elif isinstance(pdf_source, bytes):
            reader = pypdf.PdfReader(io.BytesIO(pdf_source))

        if reader:
            pages_to_read = min(len(reader.pages), max_pages)
            for i in range(pages_to_read):
                page_text = reader.pages[i].extract_text() or ""
                extracted_text += page_text + "\n"
    except Exception as e:
        logger.warning(f"Erreur d'extraction de texte via pypdf: {e}")
        error_msg = str(e)

    clean_native_text = re.sub(r"\s+", " ", extracted_text).strip()

    # Etape 2: Recours à l'OCR si le texte natif est trop court ou si force_ocr est demandé
    if (len(clean_native_text) < 50 or force_ocr) and pytesseract and Image:
        ocr_text = ""
        try:
            images = []
            if pdf2image:
                try:
                    if isinstance(pdf_source, (str, os.PathLike)) and os.path.exists(pdf_source):
                        images = pdf2image.convert_from_path(pdf_source, first_page=1, last_page=max_pages)
                    elif hasattr(pdf_source, "read"):
                        if hasattr(pdf_source, "seek"):
                            pdf_source.seek(0)
                        pdf_bytes = pdf_source.read()
                        if hasattr(pdf_source, "seek"):
                            pdf_source.seek(0)
                        images = pdf2image.convert_from_bytes(pdf_bytes, first_page=1, last_page=max_pages)
                    elif isinstance(pdf_source, bytes):
                        images = pdf2image.convert_from_bytes(pdf_source, first_page=1, last_page=max_pages)
                except Exception as img_err:
                    logger.info(f"pdf2image non disponible ou erreur de conversion: {img_err}")

            if not images and reader:
                # Extraction secours des images incorporées aux pages du PDF via pypdf
                for page_idx in range(min(len(reader.pages), max_pages)):
                    try:
                        for img_file in reader.pages[page_idx].images:
                            try:
                                pil_img = Image.open(io.BytesIO(img_file.data))
                                images.append(pil_img)
                            except Exception:
                                pass
                    except Exception:
                        pass

            for img in images[:max_pages]:
                try:
                    txt = pytesseract.image_to_string(img, lang="fra+eng")
                    ocr_text += txt + "\n"
                except Exception:
                    try:
                        txt = pytesseract.image_to_string(img)
                        ocr_text += txt + "\n"
                    except Exception as t_err:
                        logger.warning(f"Tesseract OCR image error: {t_err}")

            clean_ocr_text = re.sub(r"\s+", " ", ocr_text).strip()
            if len(clean_ocr_text) > len(clean_native_text):
                extracted_text = ocr_text
                used_ocr = True
        except Exception as ocr_e:
            logger.warning(f"Erreur globale lors de l'exécution OCR: {ocr_e}")

    final_text = re.sub(r"\s+", " ", extracted_text).strip()
    return {
        "text": final_text,
        "used_ocr": used_ocr,
        "char_count": len(final_text),
        "word_count": len(final_text.split()) if final_text else 0,
        "error": error_msg,
    }


def _build_short_summary(extracted_text, subject=None, year=None, exam_type="examen", filename="", used_ocr=False, tags=None):
    """Génère un résumé récapitulatif clair et court du document PDF."""
    if not extracted_text:
        return "Aucun contenu textuel n'a pu être extrait de ce document PDF. Le fichier est peut-être protégé ou ne contient que des images."

    subj_label = subject.name if subject else "Matière non spécifiée dans le nom"
    year_label = year or "Période récents"
    type_label = exam_type.capitalize() if isinstance(exam_type, str) else "Examen"

    # Extraction des phrases significatives
    sentences_raw = re.split(r"[.!?]\s+", extracted_text)
    meaningful = [s.strip() for s in sentences_raw if len(s.strip()) > 20 and not re.match(r"^Page \d+", s.strip(), re.IGNORECASE)]
    
    parts = []
    parts.append(f"Document d'évaluation académique ({type_label}) pour l'UE {subj_label} ({year_label}).")

    if meaningful:
        sample_snippet = ". ".join(meaningful[:2])
        if len(sample_snippet) > 220:
            sample_snippet = sample_snippet[:220] + "..."
        parts.append(f"Aperçu extrait : « {sample_snippet} ».")

    word_count = len(extracted_text.split())
    if used_ocr:
        parts.append(f"Résumé généré automatiquement via extraction OCR Python ({word_count} mots analysés).")
    else:
        parts.append(f"Résumé généré automatiquement par analyse de texte serveur ({word_count} mots analysés).")

    if tags:
        parts.append(f"Mots-clés & Thématiques : {' '.join(tags)}")

    return " ".join(parts)


FRENCH_STOP_WORDS = {
    "dans", "sur", "pour", "avec", "sans", "sous", "entre", "pendant", "après", "avant",
    "cette", "cet", "ces", "mon", "ton", "son", "notre", "votre", "leur", "leurs",
    "plus", "moins", "aussi", "bien", "tout", "tous", "toute", "toutes", "autre", "autres",
    "ainsi", "alors", "donc", "car", "mais", "comme", "quand", "lorsque", "puisque",
    "page", "pages", "exercice", "exercices", "question", "questions", "partie", "parties",
    "durée", "duree", "heure", "heures", "minute", "minutes", "points", "point", "barème",
    "bareme", "document", "documents", "autorisé", "autorise", "interdit", "calculatrice",
    "session", "normal", "normale", "examen", "épreuve", "epreuve", "étudiant", "etudiant",
    "nom", "prénom", "prenom", "note", "notes", "correction", "sujet", "sujets", "universite",
    "université", "faculte", "faculté", "departement", "département", "licence", "master",
    "remarque", "remarques", "attention", "conseil", "consigne", "consignes", "voir", "faut",
    "fait", "faire", "donné", "donne", "donnee", "donnees", "trouver", "calculer", "montrer",
    "justifier", "déterminer", "determiner", "expliquer", "soit", "soient", "égal", "égale",
}

DOMAIN_THESAURUS = {
    "physique": "Physique",
    "thermodynamique": "Thermodynamique",
    "mécanique": "Mécanique",
    "mecanique": "Mécanique",
    "électromagnétisme": "Électromagnétisme",
    "electromagnetisme": "Électromagnétisme",
    "optique": "Optique",
    "chimie": "Chimie",
    "organique": "ChimieOrganique",
    "algèbre": "Algèbre",
    "algebres": "Algèbre",
    "algebre": "Algèbre",
    "analyse": "AnalyseMath",
    "analyse numérique": "AnalyseNumérique",
    "probabilités": "Probabilités",
    "probabilite": "Probabilités",
    "statistiques": "Statistiques",
    "statistique": "Statistiques",
    "geometrie": "Géométrie",
    "géométrie": "Géométrie",
    "informatique": "Informatique",
    "algorithme": "Algorithmique",
    "algorithmique": "Algorithmique",
    "programmation": "Programmation",
    "python": "Python",
    "java": "Java",
    "base de données": "BaseDeDonnées",
    "base de donnees": "BaseDeDonnées",
    "sql": "SQL",
    "réseaux": "Réseaux",
    "reseaux": "Réseaux",
    "système": "Systèmes",
    "systeme": "Systèmes",
    "biologie": "Biologie",
    "génétique": "Génétique",
    "genetique": "Génétique",
    "biochimie": "Biochimie",
    "géologie": "Géologie",
    "geologie": "Géologie",
    "droit": "Droit",
    "constitutionnel": "DroitConstitutionnel",
    "civil": "DroitCivil",
    "administratif": "DroitAdministratif",
    "économie": "Économie",
    "economie": "Économie",
    "microéconomie": "Microéconomie",
    "macroéconomie": "Macroéconomie",
    "gestion": "Gestion",
    "comptabilité": "Comptabilité",
    "comptabilite": "Comptabilité",
    "marketing": "Marketing",
    "finance": "Finance",
    "signal": "TraitementSignal",
    "automatique": "Automatique",
    "électronique": "Électronique",
    "electronique": "Électronique",
    "télécom": "Télécoms",
    "telecom": "Télécoms",
}


def extract_keywords_and_tags(text, filename="", subject_name="", max_tags=8):
    """
    Extrait les mots-clés et génère des tags thématiques (#Thématique)
    à partir du texte du PDF, du nom de fichier et de la matière.
    """
    tags = []
    seen = set()

    def add_tag(tag_str):
        clean = re.sub(r"[^\w\-_]", "", tag_str.strip())
        if clean and len(clean) >= 3 and clean.lower() not in seen:
            seen.add(clean.lower())
            tags.append(f"#{clean}")

    # 1. Nom de matière comme tag principal
    if subject_name:
        for part in re.split(r"[\s\-_]+", subject_name):
            if len(part) >= 3 and part.lower() not in FRENCH_STOP_WORDS:
                add_tag(part.capitalize())

    # 2. Thésaurus disciplinaire
    combined_source = f"{filename} {subject_name} {text}".lower()
    for kw, tag_val in DOMAIN_THESAURUS.items():
        if kw in combined_source:
            add_tag(tag_val)

    # 3. Mots fréquents caractéristiques (> 4 caractères)
    words = re.findall(r"\b[a-zA-Zà-ÿÀ-Ÿ]{4,}\b", text.lower())
    freq = {}
    for w in words:
        if w not in FRENCH_STOP_WORDS and len(w) >= 4:
            freq[w] = freq.get(w, 0) + 1

    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    for word, count in sorted_words:
        if len(tags) >= max_tags:
            break
        if count >= 2:
            add_tag(word.capitalize())

    return tags[:max_tags]


def generate_pdf_summary_and_metadata(pdf_source, filename="", available_subjects=None, force_ocr=False):
    """
    Extrait le texte du PDF via PyPDF/OCR, analyse le contenu et génère :
    1. Un résumé court et structuré du document.
    2. Les méta-données détectées (Matière/UE, Année académique, Type d'épreuve, Semestre).
    3. Les mots-clés et tags thématiques automatiques (#MotsClés).
    """
    extraction_res = extract_text_from_pdf(pdf_source, force_ocr=force_ocr)
    extracted_text = extraction_res["text"]
    used_ocr = extraction_res["used_ocr"]

    # Analyse préalable du nom de fichier si disponible
    parsed_filename = None
    if filename:
        from academics.parser import parse_exam_filename
        parsed_filename = parse_exam_filename(filename, available_subjects=available_subjects)

    detected_subject = parsed_filename["matched_subject"] if parsed_filename else None
    detected_year = parsed_filename["detected_academic_year"] if parsed_filename else None
    detected_exam_type = "examen"
    detected_semester = None

    text_lower = extracted_text.lower()

    # Si la matière n'est pas détectée via le nom, recherche dans le texte extrait
    if not detected_subject:
        from academics.models import Subject
        if available_subjects is None:
            available_subjects = Subject.objects.select_related("semester", "semester__filiere").all()

        for subj in available_subjects:
            s_name = subj.name.strip().lower()
            s_code = subj.code.strip().lower() if subj.code else ""
            if len(s_name) >= 3 and (s_name in text_lower or (s_code and s_code in text_lower)):
                detected_subject = subj
                break

    # Si l'année n'est pas détectée via le nom, recherche dans le texte extrait
    if not detected_year:
        year_match = re.search(r"\b(20\d{2}-20\d{2})\b", extracted_text)
        if year_match:
            start_yr, end_yr = map(int, year_match.group(1).split("-"))
            if end_yr == start_yr + 1:
                detected_year = year_match.group(1)

        if not detected_year:
            single_yr = re.search(r"\b(201[5-9]|202[0-9])\b", extracted_text)
            if single_yr:
                yr_i = int(single_yr.group(1))
                detected_year = f"{yr_i-1}-{yr_i}"

    # Détection du type d'épreuve
    if "rattrapage" in text_lower or "session 2" in text_lower:
        detected_exam_type = "rattrapage"
    elif "devoir" in text_lower or "contrôle continu" in text_lower or "cc" in text_lower:
        detected_exam_type = "devoir"
    elif "travaux dirigés" in text_lower or "td " in text_lower:
        detected_exam_type = "td"
    elif "travaux pratiques" in text_lower or "tp " in text_lower:
        detected_exam_type = "tp"
    elif "concours" in text_lower:
        detected_exam_type = "concours"

    if detected_subject and detected_subject.semester:
        detected_semester = detected_subject.semester

    # Extraction des tags et mots-clés
    subj_name = detected_subject.name if detected_subject else ""
    detected_tags = extract_keywords_and_tags(
        text=extracted_text,
        filename=filename,
        subject_name=subj_name,
        max_tags=8
    )

    summary_text = _build_short_summary(
        extracted_text=extracted_text,
        subject=detected_subject,
        year=detected_year,
        exam_type=detected_exam_type,
        filename=filename,
        used_ocr=used_ocr,
        tags=detected_tags,
    )

    return {
        "extracted_text": extracted_text[:1500],
        "extracted_text_length": len(extracted_text),
        "used_ocr": used_ocr,
        "summary": summary_text,
        "detected_subject": detected_subject,
        "detected_subject_name": subj_name,
        "detected_year": detected_year or "2025-2026",
        "detected_exam_type": detected_exam_type,
        "detected_semester": detected_semester,
        "detected_tags": detected_tags,
        "tags_str": " ".join(detected_tags),
        "has_metadata": bool(detected_subject and detected_year),
    }
