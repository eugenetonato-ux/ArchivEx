import unicodedata
from django.db.models import Q
from academics.models import Subject
from exams.models import Exam
from content.models import Summary, Guide, Article
from subscriptions.services import can_user_access


def remove_accents(text):
    """Supprime les accents d'une chaîne de caractères."""
    if not text:
        return ""
    nfkd_form = unicodedata.normalize("NFD", text)
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)])


COMMON_ACADEMIC_SYNONYMS = {
    "math": ["math", "maths", "mathematique", "mathématique", "mathématiques", "mathematiques"],
    "mat": ["math", "maths", "mathematique", "mathématique", "mathématiques", "mathematiques"],
    "mathematique": ["math", "maths", "mathematique", "mathématique", "mathématiques", "mathematiques"],
    "mathématique": ["math", "maths", "mathematique", "mathématique", "mathématiques", "mathematiques"],
    "mathématiques": ["math", "maths", "mathematique", "mathématique", "mathématiques", "mathematiques"],
    "stat": ["stat", "stats", "statistique", "statistiques"],
    "statistique": ["stat", "stats", "statistique", "statistiques"],
    "statistiques": ["stat", "stats", "statistique", "statistiques"],
    "prob": ["prob", "proba", "probabilite", "probabilité", "probabilités", "probabilites"],
    "proba": ["prob", "proba", "probabilite", "probabilité", "probabilités", "probabilites"],
    "probabilite": ["prob", "proba", "probabilite", "probabilité", "probabilités", "probabilites"],
    "probabilité": ["prob", "proba", "probabilite", "probabilité", "probabilités", "probabilites"],
    "probabilités": ["prob", "proba", "probabilite", "probabilité", "probabilités", "probabilites"],
    "droit": ["droit", "droits", "juridique"],
    "droits": ["droit", "droits", "juridique"],
    "epreuve": ["epreuve", "épreuve", "epreuves", "épreuves", "examen", "annale"],
    "épreuve": ["epreuve", "épreuve", "epreuves", "épreuves", "examen", "annale"],
    "épreuves": ["epreuve", "épreuve", "epreuves", "épreuves", "examen", "annale"],
    "epreuves": ["epreuve", "épreuve", "epreuves", "épreuves", "examen", "annale"],
    "eco": ["eco", "économie", "economie", "économies", "economies"],
    "economie": ["eco", "économie", "economie", "économies", "economies"],
    "économie": ["eco", "économie", "economie", "économies", "economies"],
    "gestion": ["gestion", "gestions", "management"],
    "algo": ["algo", "algorithme", "algorithmes", "algorithmique"],
    "algorithme": ["algo", "algorithme", "algorithmes", "algorithmique"],
    "algorithmique": ["algo", "algorithme", "algorithmes", "algorithmique"],
    "resume": ["resume", "résumé", "resumes", "résumés", "fiche"],
    "résumé": ["resume", "résumé", "resumes", "résumés", "fiche"],
    "guide": ["guide", "guides", "methode", "méthodologie"],
    "conseil": ["conseil", "conseils", "astuce", "astuces"],
}


def get_token_variants(token):
    """Génère les variantes de recherche pour un jeton (accents, pluriel/singulier, synonymes)."""
    norm_token = remove_accents(token.lower().strip())
    raw_token = token.lower().strip()
    variants = set([raw_token, norm_token])

    if norm_token in COMMON_ACADEMIC_SYNONYMS:
        variants.update(COMMON_ACADEMIC_SYNONYMS[norm_token])
    if raw_token in COMMON_ACADEMIC_SYNONYMS:
        variants.update(COMMON_ACADEMIC_SYNONYMS[raw_token])

    # Singular / Plural variation
    if norm_token.endswith("s") and len(norm_token) > 3:
        variants.add(norm_token[:-1])
    elif len(norm_token) > 3:
        variants.add(norm_token + "s")

    return list(variants)


def compute_relevance_score(item_title, item_subject_name, item_desc, q_raw, tokens, is_priority):
    """Calcule le score de pertinence d'un résultat."""
    score = 0
    q_clean = q_raw.strip().lower()
    q_unaccented = remove_accents(q_clean)
    title_clean = item_title.strip().lower()
    title_unaccented = remove_accents(title_clean)
    subject_clean = (item_subject_name or "").strip().lower()
    subject_unaccented = remove_accents(subject_clean)
    desc_unaccented = remove_accents((item_desc or "").lower())

    # Exact title match
    if q_clean == title_clean or q_unaccented == title_unaccented:
        score += 100
    # Title starts with query
    elif title_clean.startswith(q_clean) or title_unaccented.startswith(q_unaccented):
        score += 60
    # Title contains query
    elif q_clean in title_clean or q_unaccented in title_unaccented:
        score += 40

    # Subject match
    if subject_clean and (q_clean in subject_clean or q_unaccented in subject_unaccented):
        score += 30

    # Token matching
    for tok in tokens:
        tok_u = remove_accents(tok.lower())
        if tok_u in title_unaccented:
            score += 15
        elif tok_u in subject_unaccented:
            score += 10
        elif tok_u in desc_unaccented:
            score += 5

    # Priority match for student's filiere/school
    if is_priority:
        score += 20

    return score


def execute_intelligent_search(query_string, category="all", user=None):
    """
    Moteur de Recherche Intelligente ArchivEx V2 (Serveur-side / Pure Django).
    Prend en charge la correspondance partielle, la tolérance aux fautes d'accents,
    la tolérance singulier/pluriel, le multi-mots et le classement par score de pertinence.
    """
    q_raw = (query_string or "").strip()
    if not q_raw:
        return {
            "q": "",
            "selected_category": category,
            "subjects_results": [],
            "exams_results": [],
            "summaries_results": [],
            "guides_results": [],
            "articles_results": [],
            "total_results_count": 0,
            "used_expanded_search": False,
        }

    raw_tokens = [t for t in q_raw.split() if len(t) > 0]
    all_variants = set()
    for tok in raw_tokens:
        all_variants.update(get_token_variants(tok))
    all_variants.add(q_raw)
    all_variants.add(remove_accents(q_raw))

    extra_variants = set()
    for v in list(all_variants):
        extra_variants.add(v.capitalize())
        extra_variants.add(v.title())
        extra_variants.add(v.upper())
        if v.lower().startswith("e") or v.lower().startswith("é"):
            rest = v[1:]
            extra_variants.add("é" + rest)
            extra_variants.add("É" + rest)
            extra_variants.add("e" + rest)
            extra_variants.add("E" + rest)
    all_variants.update(extra_variants)

    profile = getattr(user, "profile", None) if user and user.is_authenticated else None
    user_school = profile.school if profile else None
    user_filiere = profile.filiere if profile else None

    subjects_results = []
    exams_results = []
    summaries_results = []
    guides_results = []
    articles_results = []
    total_results_count = 0
    used_expanded_search = len(all_variants) > len(raw_tokens)

    # 1. SUBJECTS
    if category in ["all", "subjects"]:
        subj_q = Q()
        for v in all_variants:
            subj_q |= Q(name__icontains=v) | Q(semester__filiere__name__icontains=v)

        subj_qs = list(Subject.objects.filter(subj_q).select_related(
            "semester", "semester__filiere", "semester__filiere__school", "semester__filiere__level"
        ).distinct())

        # Fallback for accent-normalized matching in DBs like SQLite without unicode icontains
        matched_ids = set(s.id for s in subj_qs)
        all_subjs = Subject.objects.select_related(
            "semester", "semester__filiere", "semester__filiere__school", "semester__filiere__level"
        ).all()
        for s in all_subjs:
            if s.id not in matched_ids:
                s_name_norm = remove_accents(s.name.lower())
                if any(remove_accents(v.lower()) in s_name_norm for v in all_variants if len(v) >= 3):
                    subj_qs.append(s)
                    matched_ids.add(s.id)

        for s in subj_qs:
            is_priority = bool(user_filiere and s.semester.filiere_id == user_filiere.id)
            score = compute_relevance_score(
                item_title=s.name,
                item_subject_name=s.semester.filiere.name if s.semester and s.semester.filiere else "",
                item_desc="",
                q_raw=q_raw,
                tokens=raw_tokens,
                is_priority=is_priority,
            )
            subjects_results.append({
                "object": s,
                "is_priority": is_priority,
                "score": score,
            })
        subjects_results.sort(key=lambda x: x["score"], reverse=True)
        total_results_count += len(subjects_results)

    # 2. EXAMS
    if category in ["all", "exams"]:
        exam_q = Q()
        for v in all_variants:
            exam_q |= Q(title__icontains=v) | Q(subject__name__icontains=v) | Q(description__icontains=v)

        exam_qs = Exam.objects.filter(is_published=True).filter(exam_q).select_related(
            "subject", "filiere", "level", "semester", "filiere__school", "summary"
        ).distinct()

        for ex in exam_qs:
            has_access = can_user_access(user, ex)
            is_priority = bool(user_filiere and ex.filiere_id == user_filiere.id)
            score = compute_relevance_score(
                item_title=ex.title,
                item_subject_name=ex.subject.name if ex.subject else "",
                item_desc=ex.description or "",
                q_raw=q_raw,
                tokens=raw_tokens,
                is_priority=is_priority,
            )
            exams_results.append({
                "object": ex,
                "has_access": has_access,
                "is_priority": is_priority,
                "score": score,
                "is_free": ex.is_free,
                "has_correction": ex.has_correction,
                "has_summary": ex.has_summary,
            })
        exams_results.sort(key=lambda x: x["score"], reverse=True)
        total_results_count += len(exams_results)

    # 3. SUMMARIES
    if category in ["all", "summaries"]:
        sum_q = Q()
        for v in all_variants:
            sum_q |= Q(title__icontains=v) | Q(introduction__icontains=v) | Q(subject__name__icontains=v)

        sum_qs = Summary.objects.filter(publication_status="PUBLISHED").filter(sum_q).select_related(
            "subject", "subject__semester", "subject__semester__filiere", "author"
        ).distinct()

        for sm in sum_qs:
            has_access = can_user_access(user, sm)
            is_priority = bool(user_filiere and sm.subject.semester.filiere_id == user_filiere.id)
            score = compute_relevance_score(
                item_title=sm.title,
                item_subject_name=sm.subject.name if sm.subject else "",
                item_desc=sm.introduction or sm.content or "",
                q_raw=q_raw,
                tokens=raw_tokens,
                is_priority=is_priority,
            )
            summaries_results.append({
                "object": sm,
                "has_access": has_access,
                "is_priority": is_priority,
                "score": score,
            })
        summaries_results.sort(key=lambda x: x["score"], reverse=True)
        total_results_count += len(summaries_results)

    # 4. GUIDES
    if category in ["all", "guides"]:
        gd_q = Q()
        for v in all_variants:
            gd_q |= Q(title__icontains=v) | Q(introduction__icontains=v) | Q(subject__name__icontains=v)

        gd_qs = Guide.objects.filter(publication_status="PUBLISHED").filter(gd_q).select_related(
            "subject", "subject__semester", "subject__semester__filiere", "author"
        ).distinct()

        for gd in gd_qs:
            has_access = can_user_access(user, gd)
            is_priority = bool(user_filiere and gd.subject.semester.filiere_id == user_filiere.id)
            score = compute_relevance_score(
                item_title=gd.title,
                item_subject_name=gd.subject.name if gd.subject else "",
                item_desc=gd.introduction or "",
                q_raw=q_raw,
                tokens=raw_tokens,
                is_priority=is_priority,
            )
            guides_results.append({
                "object": gd,
                "has_access": has_access,
                "is_priority": is_priority,
                "score": score,
            })
        guides_results.sort(key=lambda x: x["score"], reverse=True)
        total_results_count += len(guides_results)

    # 5. ARTICLES
    if category in ["all", "articles"]:
        art_q = Q()
        for v in all_variants:
            art_q |= Q(title__icontains=v) | Q(summary__icontains=v) | Q(content__icontains=v)

        art_qs = Article.objects.filter(publication_status="PUBLISHED").filter(art_q).select_related(
            "target_school", "target_filiere", "author"
        ).distinct()

        for art in art_qs:
            is_priority = bool(user_school and art.target_school_id == user_school.id)
            score = compute_relevance_score(
                item_title=art.title,
                item_subject_name=art.target_filiere.name if art.target_filiere else "",
                item_desc=art.summary or art.content or "",
                q_raw=q_raw,
                tokens=raw_tokens,
                is_priority=is_priority,
            )
            articles_results.append({
                "object": art,
                "has_access": True,
                "is_priority": is_priority,
                "score": score,
            })
        articles_results.sort(key=lambda x: x["score"], reverse=True)
        total_results_count += len(articles_results)

    return {
        "q": q_raw,
        "selected_category": category,
        "subjects_results": subjects_results,
        "exams_results": exams_results,
        "summaries_results": summaries_results,
        "guides_results": guides_results,
        "articles_results": articles_results,
        "total_results_count": total_results_count,
        "used_expanded_search": used_expanded_search,
    }
