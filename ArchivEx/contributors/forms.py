import os
from django import forms
from django.db.models import Q
from academics.models import School, Level, Filiere, Semester, Subject
from exams.models import Exam
from content.models import Summary, Guide, Article, CloudFile, STATUS_CHOICES, ACCESS_CHOICES


class ContextSelectForm(forms.Form):
    """Formulaire de sélection du contexte académique actif (Université + Filière)."""
    school = forms.ModelChoiceField(
        queryset=School.objects.filter(is_active=True),
        label="Université active",
        widget=forms.Select(attrs={
            "class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-semibold text-[#071A49] focus:ring-2 focus:ring-[#2563EB] outline-none"
        })
    )
    filiere = forms.ModelChoiceField(
        queryset=Filiere.objects.all(),
        required=False,
        label="Filière d'études active",
        widget=forms.Select(attrs={
            "class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-semibold text-[#071A49] focus:ring-2 focus:ring-[#2563EB] outline-none"
        })
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user and not user.is_superuser:
            profile = getattr(user, "contributor_profile", None)
            if profile and profile.assigned_schools.exists():
                self.fields["school"].queryset = profile.assigned_schools.filter(is_active=True)


class CloudFileAdminForm(forms.ModelForm):
    """Formulaire pour le dépôt direct d'un fichier dans la Bibliothèque Cloud avec sélection sélective de l'UE."""
    subject = forms.ModelChoiceField(
        queryset=Subject.objects.none(),
        required=False,
        label="Matière / Unité d'Enseignement (UE)",
        widget=forms.Select(attrs={
            "class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49] focus:ring-2 focus:ring-blue-500 outline-none",
            "id": "id_cloud_subject"
        }),
        empty_label="-- Sélectionner l'UE disponible --"
    )

    year = forms.CharField(
        max_length=20,
        required=False,
        label="Année académique (ex: 2024-2025)",
        widget=forms.TextInput(attrs={
            "class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49] focus:ring-2 focus:ring-blue-500 outline-none",
            "placeholder": "Ex: 2024-2025",
            "id": "id_cloud_year"
        })
    )

    class Meta:
        model = CloudFile
        fields = ["title", "file_type", "file", "school", "filiere", "semester"]
        labels = {
            "title": "Libellé / Nom du document PDF",
            "file_type": "Type de document",
            "file": "Fichier PDF (Stockage Cloud)",
            "school": "Université associée (optionnelle)",
            "filiere": "Filière associée (optionnelle)",
            "semester": "Semestre associé (optionnel)",
        }
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49] focus:ring-2 focus:ring-blue-500 outline-none",
                "placeholder": "Le libellé est généré automatiquement au choix de l'UE",
                "id": "id_cloud_title"
            }),
            "file_type": forms.Select(attrs={
                "class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49] focus:ring-2 focus:ring-blue-500 outline-none",
                "id": "id_cloud_file_type"
            }),
            "file": forms.FileInput(attrs={"class": "w-full px-4 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs font-semibold text-slate-700"}),
            "school": forms.Select(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]"}),
            "filiere": forms.Select(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]"}),
            "semester": forms.Select(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]"}),
        }

    def __init__(self, *args, active_school=None, active_filiere=None, active_semester=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Proposer UNIQUEMENT les UE disponibles pour le contexte actif
        subj_qs = Subject.objects.select_related("semester", "semester__filiere", "semester__filiere__school").filter(is_active=True)
        if active_semester:
            subj_qs = subj_qs.filter(semester=active_semester)
        elif active_filiere:
            subj_qs = subj_qs.filter(semester__filiere=active_filiere)
        elif active_school:
            subj_qs = subj_qs.filter(semester__filiere__school=active_school)
        self.fields["subject"].queryset = subj_qs.order_by("name")

        if active_school and not self.fields["school"].initial:
            self.fields["school"].initial = active_school
        if active_filiere and not self.fields["filiere"].initial:
            self.fields["filiere"].initial = active_filiere
        if active_semester and not self.fields["semester"].initial:
            self.fields["semester"].initial = active_semester

        # Si un fichier existant est édité, détecter l'UE
        if self.instance and self.instance.pk and self.instance.title:
            from academics.parser import parse_exam_filename
            parsed = parse_exam_filename(self.instance.title, available_subjects=subj_qs)
            if parsed.get("matched_subject"):
                self.fields["subject"].initial = parsed["matched_subject"]
            if parsed.get("detected_academic_year"):
                self.fields["year"].initial = parsed["detected_academic_year"]

    def clean_file(self):
        file = self.cleaned_data.get("file")
        if file:
            ext = os.path.splitext(file.name)[1].lower()
            if ext != ".pdf":
                raise forms.ValidationError("Seuls les fichiers PDF (.pdf) sont autorisés.")
            if file.size > 20 * 1024 * 1024:
                raise forms.ValidationError("La taille du fichier ne doit pas dépasser 20 Mo.")
        return file

    def clean(self):
        cleaned_data = super().clean()
        subject = cleaned_data.get("subject")
        year = str(cleaned_data.get("year", "")).strip()
        file_type = cleaned_data.get("file_type")
        title = str(cleaned_data.get("title", "")).strip()

        # Si le libellé n'est pas saisi manuellement mais qu'une UE est sélectionnée
        if subject and not title:
            type_suffix = ""
            if file_type == "CORRECTION":
                type_suffix = " - Corrigé"
            elif file_type == "SUMMARY":
                type_suffix = " - Résumé"
            year_part = f" {year}" if year else ""
            cleaned_data["title"] = f"{subject.name}{year_part}{type_suffix}.pdf"
        elif not title and not subject:
            self.add_error("title", "Veuillez sélectionner une UE disponible ou saisir un libellé.")

        return cleaned_data


class ExamAdminForm(forms.ModelForm):
    """Formulaire d'édition/publication rapide d'une épreuve d'examen."""
    ACCESS_CHOICES = [
        ("False", "Pass Semestre (Premium)"),
        ("True", "Gratuit (Accès libre)"),
    ]

    PUBLICATION_CHOICES = [
        ("True", "Publié (Visible par les étudiants)"),
        ("False", "Brouillon (Dépublié)"),
    ]

    subject = forms.ModelChoiceField(
        queryset=Subject.objects.all(),
        required=False,
        label="Matière / Unité d'Enseignement (UE)",
        widget=forms.Select(attrs={
            "class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49] focus:ring-2 focus:ring-blue-500 outline-none",
            "id": "id_subject_select"
        }),
        empty_label="-- Sélectionner une matière existante --"
    )

    new_subject_name = forms.CharField(
        max_length=150,
        required=False,
        label="Ou ajouter une nouvelle matière (si non listée)",
        widget=forms.TextInput(attrs={
            "class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49] focus:ring-2 focus:ring-blue-500 outline-none",
            "placeholder": "Tapez le nom de la nouvelle matière...",
            "id": "id_new_subject_name"
        })
    )

    subject_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.HiddenInput()
    )

    year = forms.CharField(
        max_length=20,
        required=True,
        label="Année académique",
        widget=forms.TextInput(attrs={
            "class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]",
            "placeholder": "Ex: 2025-2026"
        })
    )

    is_free = forms.ChoiceField(
        choices=ACCESS_CHOICES,
        label="Niveau d'accès",
        widget=forms.Select(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]"})
    )
    is_published = forms.ChoiceField(
        choices=PUBLICATION_CHOICES,
        label="Statut de publication",
        widget=forms.Select(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]"})
    )

    cloud_file = forms.ModelChoiceField(
        queryset=CloudFile.objects.all(),
        required=False,
        label="Sélectionner depuis la Bibliothèque Cloud (Optionnel)",
        widget=forms.Select(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]"})
    )
    cloud_correction_file = forms.ModelChoiceField(
        queryset=CloudFile.objects.all(),
        required=False,
        label="Sélectionner la correction depuis le Cloud (Optionnel)",
        widget=forms.Select(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]"})
    )
    cloud_summary_file = forms.ModelChoiceField(
        queryset=CloudFile.objects.all(),
        required=False,
        label="Sélectionner le résumé depuis le Cloud (Optionnel)",
        widget=forms.Select(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]"})
    )

    file = forms.FileField(
        required=False,
        label="Nouveau document PDF (Téléversement direct)",
        widget=forms.FileInput(attrs={"class": "w-full px-4 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs font-semibold text-slate-700"})
    )

    correction_file = forms.FileField(
        required=False,
        label="Nouvelle correction PDF (Téléversement direct)",
        widget=forms.FileInput(attrs={"class": "w-full px-4 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs font-semibold text-slate-700"})
    )

    summary_file = forms.FileField(
        required=False,
        label="Nouveau résumé / fiche PDF (Téléversement direct)",
        widget=forms.FileInput(attrs={"class": "w-full px-4 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs font-semibold text-slate-700"})
    )

    semester = forms.ModelChoiceField(
        queryset=Semester.objects.all(),
        required=False,
        label="Semestre (hérité du contexte actif par défaut)",
        widget=forms.Select(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]"})
    )

    class Meta:
        model = Exam
        fields = ["title", "year", "exam_type", "cloud_file", "cloud_correction_file", "cloud_summary_file", "file", "correction_file", "summary_file", "description", "semester"]
        labels = {
            "title": "Titre de l'épreuve",
            "year": "Année académique",
            "exam_type": "Type d'épreuve",
            "description": "Description / Remarques optionnelles",
        }
        widgets = {
            "title": forms.TextInput(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]", "placeholder": "Ex: Examen d'analyse S1 2025-2026"}),
            "year": forms.TextInput(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]", "placeholder": "Ex: 2025-2026"}),
            "exam_type": forms.Select(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]"}),
            "description": forms.Textarea(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-medium text-[#071A49]", "rows": 3}),
        }

    def __init__(self, *args, active_filiere=None, active_semester=None, **kwargs):
        super().__init__(*args, **kwargs)
        subj_qs = Subject.objects.all()
        if active_semester:
            subj_qs = Subject.objects.filter(semester=active_semester)
        elif active_filiere:
            subj_qs = Subject.objects.filter(semester__filiere=active_filiere)
        self.fields["subject"].queryset = subj_qs.order_by("name")

        if not self.instance or not self.instance.pk:
            self.fields["exam_type"].initial = "examen"
            self.fields["is_published"].initial = "True"
        else:
            self.fields["is_free"].initial = "true" if self.instance.is_free else "false"
            self.fields["is_published"].initial = "true" if self.instance.is_published else "false"
            if self.instance.subject:
                self.fields["subject"].initial = self.instance.subject
                self.fields["subject_name"].initial = self.instance.subject.name
            if self.instance.semester:
                self.fields["semester"].initial = self.instance.semester
            if self.instance.academic_year:
                self.fields["year"].initial = self.instance.academic_year.label

        if active_filiere:
            self.fields["semester"].queryset = Semester.objects.filter(filiere=active_filiere)
            self.fields["cloud_file"].queryset = CloudFile.objects.filter(Q(filiere=active_filiere) | Q(filiere__isnull=True))
            self.fields["cloud_correction_file"].queryset = CloudFile.objects.filter(Q(filiere=active_filiere) | Q(filiere__isnull=True))
            self.fields["cloud_summary_file"].queryset = CloudFile.objects.filter(Q(filiere=active_filiere) | Q(filiere__isnull=True))

        if active_semester and not self.fields["semester"].initial:
            self.fields["semester"].initial = active_semester

    def clean_year(self):
        import re
        val = str(self.cleaned_data.get("year", "")).strip()
        if not val:
            raise forms.ValidationError("L'année académique est obligatoire.")
        if "-" in val:
            pattern = r"^\d{4}-\d{4}$"
            if not re.match(pattern, val):
                raise forms.ValidationError("L'année académique doit respecter le format YYYY-YYYY (ex: 2025-2026).")
            start_yr, end_yr = map(int, val.split("-"))
            if end_yr != start_yr + 1:
                raise forms.ValidationError("L'année académique doit couvrir deux années consécutives (ex: 2025-2026).")
            return start_yr
        elif val.isdigit():
            return int(val)
        else:
            raise forms.ValidationError("Veuillez saisir une année académique valide au format YYYY-YYYY (ex: 2025-2026).")

    def clean_file(self):
        file = self.cleaned_data.get("file")
        if file:
            ext = os.path.splitext(file.name)[1].lower()
            if ext != ".pdf":
                raise forms.ValidationError("Seuls les fichiers au format PDF (.pdf) sont autorisés.")
            if file.size > 20 * 1024 * 1024:
                raise forms.ValidationError("La taille du fichier ne doit pas dépasser 20 Mo.")
        return file

    def clean_correction_file(self):
        file = self.cleaned_data.get("correction_file")
        if file:
            ext = os.path.splitext(file.name)[1].lower()
            if ext != ".pdf":
                raise forms.ValidationError("Seuls les fichiers au format PDF (.pdf) sont autorisés pour la correction.")
            if file.size > 20 * 1024 * 1024:
                raise forms.ValidationError("La taille du fichier ne doit pas dépasser 20 Mo.")
        return file

    def clean_summary_file(self):
        file = self.cleaned_data.get("summary_file")
        if file:
            ext = os.path.splitext(file.name)[1].lower()
            if ext != ".pdf":
                raise forms.ValidationError("Seuls les fichiers au format PDF (.pdf) sont autorisés pour le résumé.")
            if file.size > 20 * 1024 * 1024:
                raise forms.ValidationError("La taille du fichier ne doit pas dépasser 20 Mo.")
        return file

    def clean_is_free(self):
        val = self.cleaned_data.get("is_free")
        return str(val).lower() in ["true", "1"]

    def clean_is_published(self):
        val = self.cleaned_data.get("is_published")
        return str(val).lower() in ["true", "1"]

    def clean(self):
        cleaned_data = super().clean()
        file = cleaned_data.get("file")
        cloud_file = cleaned_data.get("cloud_file")

        has_file = bool(file or cloud_file or (self.instance and self.instance.pk and (self.instance.file or self.instance.cloud_file)))
        if not has_file:
            self.add_error("file", "Veuillez sélectionner un fichier depuis la Bibliothèque Cloud ou téléverser un fichier PDF.")

        # Validation de la matière
        subject = cleaned_data.get("subject")
        new_subject_name = cleaned_data.get("new_subject_name", "").strip()
        subject_name = cleaned_data.get("subject_name", "").strip()

        if not subject and not new_subject_name and not subject_name:
            self.add_error("subject", "Veuillez sélectionner une matière dans la liste ou renseigner un nouveau nom de matière.")
        elif subject:
            cleaned_data["subject_name"] = subject.name
        elif new_subject_name:
            cleaned_data["subject_name"] = new_subject_name

        return cleaned_data


class SummaryAdminForm(forms.ModelForm):
    """Formulaire d'édition/publication d'un résumé de cours 100% PDF."""
    HUMAN_STATUS_CHOICES = [
        ("PUBLISHED", "Publié"),
        ("DRAFT", "Brouillon"),
    ]
    HUMAN_ACCESS_CHOICES = [
        ("PREMIUM", "Pass Semestre (Premium)"),
        ("FREE", "Gratuit (Accès libre)"),
    ]

    publication_status = forms.ChoiceField(
        choices=HUMAN_STATUS_CHOICES,
        label="Statut de publication",
        widget=forms.Select(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]"})
    )
    access_type = forms.ChoiceField(
        choices=HUMAN_ACCESS_CHOICES,
        label="Niveau d'accès",
        widget=forms.Select(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]"})
    )
    file = forms.FileField(
        required=False,
        label="Fichier PDF du résumé",
        widget=forms.FileInput(attrs={"class": "w-full px-4 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs font-semibold text-slate-700"})
    )

    content = forms.CharField(
        required=False,
        widget=forms.HiddenInput(),
    )

    class Meta:
        model = Summary
        fields = ["title", "subject", "file", "access_type", "publication_status", "introduction", "content"]
        labels = {
            "title": "Titre du résumé",
            "subject": "Unité d'Enseignement (UE) / Matière",
            "file": "Fichier PDF du résumé",
            "introduction": "Description courte (optionnelle)",
        }
        widgets = {
            "title": forms.TextInput(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]", "placeholder": "Ex: Fiche de synthèse — Chapitre 1 & 2"}),
            "subject": forms.Select(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]"}),
            "introduction": forms.Textarea(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-medium text-[#071A49]", "rows": 2, "placeholder": "Points clés abordés (optionnel)..."}),
        }

    def __init__(self, *args, active_filiere=None, active_semester=None, **kwargs):
        super().__init__(*args, **kwargs)
        subj_qs = Subject.objects.all()
        if active_semester:
            subj_qs = Subject.objects.filter(semester=active_semester)
        elif active_filiere:
            subj_qs = Subject.objects.filter(semester__filiere=active_filiere)
        self.fields["subject"].queryset = subj_qs.order_by("name")
        self.fields["subject"].empty_label = "-- Sélectionner l'UE / Matière --"

    def clean_file(self):
        file = self.cleaned_data.get("file")
        if file:
            ext = os.path.splitext(file.name)[1].lower()
            if ext != ".pdf":
                raise forms.ValidationError("Seuls les fichiers au format PDF (.pdf) sont autorisés.")
            if file.size > 25 * 1024 * 1024:
                raise forms.ValidationError("La taille du fichier ne doit pas dépasser 25 Mo.")
        return file

    def clean(self):
        cleaned_data = super().clean()
        file = cleaned_data.get("file")
        has_file_or_content = bool(
            file or
            (self.instance and self.instance.pk and self.instance.file) or
            cleaned_data.get("content")
        )
        if not has_file_or_content:
            self.add_error("file", "Veuillez joindre le document PDF du résumé de cours.")
        return cleaned_data


class GuideAdminForm(forms.ModelForm):
    """Formulaire d'édition/publication d'un guide méthodologique."""
    HUMAN_STATUS_CHOICES = [
        ("DRAFT", "Brouillon"),
        ("PUBLISHED", "Publié"),
    ]
    HUMAN_ACCESS_CHOICES = [
        ("FREE", "Gratuit (Accès libre)"),
        ("PREMIUM", "Pass Semestre (Premium)"),
    ]

    publication_status = forms.ChoiceField(
        choices=HUMAN_STATUS_CHOICES,
        label="Statut de publication",
        widget=forms.Select(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]"})
    )
    access_type = forms.ChoiceField(
        choices=HUMAN_ACCESS_CHOICES,
        label="Niveau d'accès",
        widget=forms.Select(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]"})
    )

    class Meta:
        model = Guide
        fields = ["title", "subject", "introduction", "objectives", "how_to_study", "key_concepts", "file", "access_type", "publication_status"]
        labels = {
            "title": "Titre du guide",
            "subject": "Unité d'Enseignement / Matière",
            "introduction": "Introduction au guide",
            "objectives": "Objectifs pédagogiques",
            "how_to_study": "Méthode de travail recommandée",
            "key_concepts": "Notions clés fondamentales",
            "file": "Document PDF optionnel",
        }
        widgets = {
            "title": forms.TextInput(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]"}),
            "subject": forms.Select(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]"}),
            "introduction": forms.Textarea(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-medium text-[#071A49]", "rows": 3}),
            "objectives": forms.Textarea(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-medium text-[#071A49]", "rows": 3}),
            "how_to_study": forms.Textarea(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-medium text-[#071A49]", "rows": 3}),
            "key_concepts": forms.Textarea(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-medium text-[#071A49]", "rows": 3}),
            "file": forms.FileInput(attrs={"class": "w-full px-4 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs font-semibold text-slate-700"}),
        }

    def __init__(self, *args, active_filiere=None, **kwargs):
        super().__init__(*args, **kwargs)
        if active_filiere:
            self.fields["subject"].queryset = Subject.objects.filter(semester__filiere=active_filiere)


class ArticleAdminForm(forms.ModelForm):
    """Formulaire d'édition/publication d'un conseil d'étude / article."""
    HUMAN_STATUS_CHOICES = [
        ("DRAFT", "Brouillon"),
        ("PUBLISHED", "Publié"),
    ]

    publication_status = forms.ChoiceField(
        choices=HUMAN_STATUS_CHOICES,
        label="Statut de publication",
        widget=forms.Select(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]"})
    )

    class Meta:
        model = Article
        fields = ["title", "category", "summary", "content", "publication_status"]
        labels = {
            "title": "Titre du conseil",
            "category": "Catégorie",
            "summary": "Résumé succinct",
            "content": "Contenu complet rédigé",
        }
        widgets = {
            "title": forms.TextInput(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]"}),
            "category": forms.Select(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]"}),
            "summary": forms.Textarea(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-medium text-[#071A49]", "rows": 2}),
            "content": forms.Textarea(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-medium text-[#071A49]", "rows": 8}),
        }


class SubjectAdminForm(forms.ModelForm):
    """Formulaire de création/édition d'une Matière / Unité d'Enseignement."""
    class Meta:
        model = Subject
        fields = ["name", "semester", "image"]
        labels = {
            "name": "Nom de la matière / UE",
            "semester": "Semestre d'études",
            "image": "Image de la matière (couverture)",
        }
        widgets = {
            "name": forms.TextInput(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]", "placeholder": "Ex: Algorithmique & Programmation"}),
            "semester": forms.Select(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]"}),
            "image": forms.FileInput(attrs={"class": "w-full px-4 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs font-medium text-[#071A49]", "accept": "image/*"}),
        }

    def __init__(self, *args, active_filiere=None, **kwargs):
        super().__init__(*args, **kwargs)
        if active_filiere:
            self.fields["semester"].queryset = Semester.objects.filter(filiere=active_filiere)
        self.fields["image"].required = False


class NotificationAdminForm(forms.Form):
    """Formulaire d'envoi de notification ciblée aux étudiants."""
    SCOPE_CHOICES = [
        ("ALL", "Tous les étudiants inscrits"),
        ("SCHOOL", "Étudiants de l'université active"),
        ("FILIERE", "Étudiants de la filière active"),
    ]

    title = forms.CharField(
        max_length=150,
        label="Titre de la notification",
        widget=forms.TextInput(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]", "placeholder": "Nouvelle épreuve disponible"})
    )
    message = forms.CharField(
        label="Message de la notification",
        widget=forms.Textarea(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-medium text-[#071A49]", "rows": 4, "placeholder": "Une nouvelle épreuve d'analyse mathématique vient d'être publiée..."})
    )
    scope = forms.ChoiceField(
        choices=SCOPE_CHOICES,
        label="Destinataires",
        widget=forms.Select(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]"})
    )



