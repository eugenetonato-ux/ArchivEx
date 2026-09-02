import os
import re
from academics.models import Subject, AcademicYear


def parse_exam_filename(filename, available_subjects=None):
    """
    Analyse un nom de fichier d'épreuve pour extraire :
    1. L'UE (Subject) correspondante dans la base de données.
    2. L'année académique au format YYYY-YYYY.

    Exemples valides :
    - "Analyse 2025-2026.pdf" -> UE = "Analyse", Année = "2025-2026"
    - "Algèbre 2024-2025.pdf" -> UE = "Algèbre", Année = "2024-2025"

    Exemples invalides :
    - "epreuve.pdf"
    - "Analyse.pdf"
    - "Analyse 2026.pdf"
    """
    if not filename:
        return {
            "raw_filename": "",
            "clean_title": "",
            "subject_candidate": "",
            "matched_subject": None,
            "detected_academic_year": None,
            "is_valid": False,
            "errors": ["Aucun nom de fichier fourni."],
        }

    clean_name = os.path.basename(filename)
    if clean_name.lower().endswith(".pdf"):
        clean_name = clean_name[:-4]

    clean_name = clean_name.strip()

    # Clean potential prefix like "Épreuve — " or "ArchivEx_"
    clean_name = re.sub(r"^(Épreuve — |ArchivEx_)", "", clean_name, flags=re.IGNORECASE).strip()

    # Match academic year YYYY-YYYY
    year_match = re.search(r"\b(\d{4}-\d{4})\b", clean_name)
    detected_year_str = None
    if year_match:
        start_yr, end_yr = map(int, year_match.group(1).split("-"))
        if end_yr == start_yr + 1:
            detected_year_str = year_match.group(1)

    # Extract potential subject title by removing the year pattern
    subject_raw_candidate = re.sub(r"\b\d{4}-\d{4}\b", "", clean_name).strip(" -_")

    matched_subject = None
    if subject_raw_candidate:
        if available_subjects is None:
            available_subjects = Subject.objects.all()

        cand_lower = subject_raw_candidate.lower()

        # 1. Exact match (case-insensitive) on name or code
        for s in available_subjects:
            if s.name.strip().lower() == cand_lower or (s.code and s.code.strip().lower() == cand_lower):
                matched_subject = s
                break

        # 2. Alias / prefix matching (e.g. "Analyse" <-> "Analyse Mathématique")
        if not matched_subject:
            for s in available_subjects:
                s_name_lower = s.name.strip().lower()
                if len(cand_lower) >= 3 and (cand_lower in s_name_lower or s_name_lower in cand_lower):
                    matched_subject = s
                    break

    is_valid = bool(matched_subject and detected_year_str)
    errors = []
    if not detected_year_str:
        errors.append("Format d'année académique non détecté (attendu: YYYY-YYYY, ex: 2025-2026).")
    if not matched_subject:
        if subject_raw_candidate:
            errors.append(f"Matière / UE non reconnue dans la base : « {subject_raw_candidate} ».")
        else:
            errors.append("Nom d'UE / Matière non spécifié dans le fichier.")

    return {
        "raw_filename": filename,
        "clean_title": clean_name,
        "subject_candidate": subject_raw_candidate,
        "matched_subject": matched_subject,
        "detected_academic_year": detected_year_str,
        "is_valid": is_valid,
        "errors": errors,
    }
