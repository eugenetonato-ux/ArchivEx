import os
import re
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings
from academics.models import School, Filiere, Level, AcademicYear, Semester, Subject
from exams.models import Exam
from content.models import CloudFile, Summary


def clean_subject_name(raw_name):
    """Nettoie et normalise le nom de matière extrait du nom de fichier."""
    name = raw_name.replace(".pdf", "").strip()
    # Supprimer les préfixes numériques ex: 01_, 02_
    name = re.sub(r"^\d+_", "", name)
    # Remplacer underscores par espaces
    name = name.replace("_", " ").strip()
    return name


class Command(BaseCommand):
    help = "Scanne le dossier media/ et importe/synchronise toutes les épreuves, corrigés et résumés dans la base de données avec détection multi-filières."

    def add_arguments(self, parser):
        parser.add_argument(
            "--filiere",
            type=str,
            default=None,
            help="Code ou nom de la filière cible par défaut (ex: PLAN, GL, FC).",
        )
        parser.add_argument(
            "--school",
            type=str,
            default=None,
            help="Nom de l'université / école cible.",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("[+] Début de l'indexation automatique des fichiers médias..."))

        target_school_name = options.get("school")
        if target_school_name:
            school = School.objects.filter(name__icontains=target_school_name, is_active=True).first()
        else:
            school = School.objects.filter(is_active=True).first()

        if not school:
            school = School.objects.create(name="ENEAM — École Nationale d'Économie Appliquée et de Management", is_active=True)

        target_filiere_arg = options.get("filiere")
        default_filiere = None
        if target_filiere_arg:
            default_filiere = Filiere.objects.filter(
                Q(code__iexact=target_filiere_arg) | Q(name__icontains=target_filiere_arg),
                school=school
            ).first()

        if not default_filiere:
            default_filiere = Filiere.objects.filter(school=school).first()

        if not default_filiere:
            level, _ = Level.objects.get_or_create(name="L1")
            default_filiere = Filiere.objects.create(name="PLAN", code="PLAN", school=school, level=level)

        all_filieres = list(Filiere.objects.filter(school=school).select_related("level", "school"))
        if default_filiere not in all_filieres:
            all_filieres.append(default_filiere)

        # Années académiques
        ay_2024, _ = AcademicYear.objects.get_or_create(label="2024-2025")
        ay_2025, _ = AcademicYear.objects.get_or_create(label="2025-2026")

        media_dir = Path(settings.MEDIA_ROOT)
        exams_dir = media_dir / "exams"
        corrections_dir = media_dir / "corrections"
        summaries_dir = media_dir / "summaries_pdf"

        KNOWN_FILIERES_INFO = {
            "stat": ("Statistique", "STAT"),
            "plan": ("PLAN", "PLAN"),
            "gl": ("Génie Logiciel", "GL"),
            "fc": ("Finance et Comptabilité", "FC"),
            "grh": ("Gestion des Ressources Humaines", "GRH"),
        }

        def detect_filiere_from_path(rel_path_str):
            """Détecte la filière depuis les dossiers du chemin relatif (ex: exams/STAT/2024-2025/S1/...)."""
            parts = [p.lower() for p in rel_path_str.replace("\\", "/").split("/")]
            for fil in all_filieres:
                if (fil.code and fil.code.lower() in parts) or (fil.name and fil.name.lower() in parts):
                    return fil

            # Auto-création dynamique si un dossier de filière connu est rencontré
            for part in parts:
                if part in KNOWN_FILIERES_INFO:
                    f_name, f_code = KNOWN_FILIERES_INFO[part]
                    level_obj = Level.objects.first() or Level.objects.create(name="L1", code="L1")
                    new_fil, _ = Filiere.objects.get_or_create(
                        code=f_code,
                        school=school,
                        defaults={"name": f_name, "level": level_obj, "is_active": True}
                    )
                    if new_fil not in all_filieres:
                        all_filieres.append(new_fil)
                    return new_fil

            return default_filiere

        # 1. Scanner les corrections pour pouvoir les mapper par (filiere_id, année, semestre, mot-clé UE)
        corrections_map = {}
        if corrections_dir.exists():
            for root, _, files in os.walk(corrections_dir):
                for f in files:
                    if f.lower().endswith(".pdf"):
                        full_p = Path(root) / f
                        rel_p = full_p.relative_to(media_dir).as_posix()
                        
                        filiere_corr = detect_filiere_from_path(rel_p)
                        yr_match = re.search(r"(\d{4}-\d{4})", rel_p)
                        sem_match = re.search(r"/(S[12])/", rel_p, re.IGNORECASE)
                        yr_key = yr_match.group(1) if yr_match else ""
                        sem_key = sem_match.group(1).upper() if sem_match else ""
                        
                        clean_corr_name = f.lower().replace("corrige_type_", "").replace("corrige_", "").replace(".pdf", "")
                        clean_corr_name = re.sub(r"^\d+_", "", clean_corr_name).replace("_", " ").strip()
                        
                        corrections_map[(filiere_corr.id if filiere_corr else None, yr_key, sem_key, clean_corr_name)] = rel_p

        created_count = 0
        updated_count = 0

        # Mapping des matières pour normaliser les variations d'écriture
        SUBJECT_NORMALIZATION = {
            "statistiques descriptives": "Statistique descriptive",
            "statistique descriptive": "Statistique descriptive",
            "statistiques descriptive": "Statistique descriptive",
            "introduction au droit": "Introduction au droit",
            "introduction au droit cive": "Introduction au droit",
            "cadre juridique des affaires cive": "CIVE",
            "cive": "CIVE",
            "sociologie des organisations": "Sociologie des organisations",
            "gestion de la qualite": "Gestion de la qualité",
            "introduction a la gestion de la qualite": "Gestion de la qualité",
            "analyse mathematique": "Analyse mathématique",
            "analyse mathématique": "Analyse mathématique",
            "microeconomie": "Microéconomie",
            "microéconomie": "Microéconomie",
            "comptabilite financiere": "Comptabilité financière",
            "introduction a la comptabilite financiere": "Comptabilité financière",
            "entrepreneuriat et innovation": "Entrepreneuriat et innovation",
            "entrepreneuriat innovation": "Entrepreneuriat et innovation",
            "histoire de la pensee economique": "Histoire de la pensée économique",
            "algebre lineaire": "Algèbre linéaire",
            "comptabilite nationale": "Comptabilité nationale",
            "developpement personnel": "Développement personnel",
            "informatique": "Informatique",
            "introduction a la planification": "Introduction à la planification",
            "macroeconomie": "Macroéconomie",
            "theorie des probabilites": "Probabilités",
            "probabilites": "Probabilités",
        }

        # 2. Scanner les épreuves
        if exams_dir.exists():
            for root, _, files in os.walk(exams_dir):
                for f in sorted(files):
                    if not f.lower().endswith(".pdf"):
                        continue

                    full_path = Path(root) / f
                    rel_path = full_path.relative_to(media_dir).as_posix()

                    # Identifier l'année
                    ay_obj = ay_2025
                    yr_int = 2025
                    if "2024-2025" in rel_path:
                        ay_obj = ay_2024
                        yr_int = 2024
                    elif "2025-2026" in rel_path:
                        ay_obj = ay_2025
                        yr_int = 2025

                    # Identifier la filière et le niveau
                    target_filiere = detect_filiere_from_path(rel_path)
                    target_level = target_filiere.level or Level.objects.first()

                    # Identifier le semestre
                    sem_num = 2 if ("/S2/" in rel_path.upper() or "\\S2\\" in str(full_path).upper()) else 1
                    target_sem, _ = Semester.objects.get_or_create(
                        filiere=target_filiere,
                        number=sem_num,
                        defaults={"label": f"S{sem_num}"}
                    )

                    # Nettoyer le nom de la matière
                    raw_subj = clean_subject_name(f)
                    lookup_key = raw_subj.lower().replace("é", "e").replace("è", "e").replace("ê", "e").replace("à", "a")
                    
                    # Trouver le nom normalisé
                    subj_name = raw_subj
                    for k, norm in SUBJECT_NORMALIZATION.items():
                        k_clean = k.replace("é", "e").replace("è", "e").replace("ê", "e").replace("à", "a")
                        if k_clean in lookup_key or lookup_key in k_clean:
                            subj_name = norm
                            break

                    # Détecter le type d'examen
                    exam_type = "examen"
                    if "rattrapage" in f.lower():
                        exam_type = "rattrapage"

                    # Créer ou récupérer l'UE dans le semestre
                    subject, _ = Subject.objects.get_or_create(
                        semester=target_sem,
                        name=subj_name,
                        defaults={
                            "code": subj_name[:6].upper().replace(" ", ""),
                            "is_active": True,
                            "is_free": True if (subj_name in ["CIVE", "Statistique descriptive"]) else False,
                        }
                    )

                    # Titre clair et élégant
                    title = f"Examen {subj_name} — {ay_obj.label}"
                    if exam_type == "rattrapage":
                        title = f"Rattrapage {subj_name} — {ay_obj.label}"

                    # Chercher la correction correspondante
                    corr_file_rel = None
                    yr_key = ay_obj.label
                    sem_key = f"S{sem_num}"
                    
                    # 1. Chercher d'abord avec la même filière
                    for (c_fil_id, c_yr, c_sem, c_name), c_path in corrections_map.items():
                        if c_fil_id == target_filiere.id and (c_yr == yr_key or not c_yr) and (c_sem == sem_key or not c_sem):
                            c_name_clean = c_name.replace("é", "e").replace("è", "e").replace("à", "a")
                            s_name_clean = subj_name.lower().replace("é", "e").replace("è", "e").replace("à", "a")
                            if (c_name_clean in s_name_clean) or (s_name_clean in c_name_clean) or (lookup_key in c_name_clean):
                                corr_file_rel = c_path
                                break
                    # 2. Si non trouvée, fallback sur corrections sans filière stricte
                    if not corr_file_rel:
                        for (c_fil_id, c_yr, c_sem, c_name), c_path in corrections_map.items():
                            if (c_fil_id is None or c_fil_id == target_filiere.id) and (c_yr == yr_key or not c_yr) and (c_sem == sem_key or not c_sem):
                                c_name_clean = c_name.replace("é", "e").replace("è", "e").replace("à", "a")
                                s_name_clean = subj_name.lower().replace("é", "e").replace("è", "e").replace("à", "a")
                                if (c_name_clean in s_name_clean) or (s_name_clean in c_name_clean) or (lookup_key in c_name_clean):
                                    corr_file_rel = c_path
                                    break

                    # Créer le CloudFile correspondant
                    cf, _ = CloudFile.objects.get_or_create(
                        title=f"Épreuve — {title}",
                        file=rel_path,
                        defaults={
                            "file_type": "EXAM",
                            "school": school,
                            "filiere": target_filiere,
                            "semester": target_sem,
                        }
                    )

                    # Créer ou mettre à jour l'objet Exam
                    exam, is_created = Exam.objects.get_or_create(
                        subject=subject,
                        semester=target_sem,
                        academic_year=ay_obj,
                        year=yr_int,
                        exam_type=exam_type,
                        defaults={
                            "title": title,
                            "filiere": target_filiere,
                            "level": target_level,
                            "file": rel_path,
                            "correction_file": corr_file_rel,
                            "cloud_file": cf,
                            "is_free": subject.is_free,
                            "is_published": True,
                        }
                    )

                    if not is_created:
                        exam.file = rel_path
                        if corr_file_rel:
                            exam.correction_file = corr_file_rel
                        exam.cloud_file = cf
                        exam.is_published = True
                        exam.save()
                        updated_count += 1
                    else:
                        created_count += 1

                    self.stdout.write(f"  [+] {title} (Correction: {'OUI' if corr_file_rel else 'NON'})")

        # 3. Traiter les résumés/fiches de cours
        if summaries_dir.exists():
            for f in os.listdir(summaries_dir):
                if f.lower().endswith(".pdf"):
                    rel_sum_path = f"summaries_pdf/{f}"
                    sum_title = f.replace("Fiche_", "Fiche de synthèse ").replace(".pdf", "").replace("_", " ")
                    
                    matched_subj = None
                    for s in Subject.objects.all():
                        if "droit" in f.lower() and "droit" in s.name.lower():
                            matched_subj = s
                            break
                        if "qualite" in f.lower() and "qualit" in s.name.lower():
                            matched_subj = s
                            break

                    if matched_subj:
                        sm, _ = Summary.objects.get_or_create(
                            subject=matched_subj,
                            title=sum_title,
                            defaults={
                                "file": rel_sum_path,
                                "introduction": f"Fiche de cours et synthèse essentielle pour {matched_subj.name}.",
                                "access_type": "FREE" if matched_subj.is_free else "PREMIUM",
                                "publication_status": "PUBLISHED",
                            }
                        )
                        self.stdout.write(f"  [+] Fiche résumé créée : {sum_title} ({matched_subj.name})")

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS(f"[SUCCÈS] Indexation terminée : {created_count} épreuves créées, {updated_count} mises à jour."))
        self.stdout.write(self.style.SUCCESS(f"Total épreuves désormais en base : {Exam.objects.count()}"))
        self.stdout.write(self.style.SUCCESS(f"Total fichiers Cloud désormais en base : {CloudFile.objects.count()}"))
        self.stdout.write("=" * 60)
