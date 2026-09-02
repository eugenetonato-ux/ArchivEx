import os
from django import forms
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
    """Formulaire pour le dépôt direct d'un fichier dans la Bibliothèque Cloud."""
    class Meta:
        model = CloudFile
        fields = ["title", "file_type", "file", "school", "filiere", "semester"]
        labels = {
            "title": "Nom / Titre du document",
            "file_type": "Type de ressource",
            "file": "Fichier PDF (Stockage Cloud)",
            "school": "Université associée (optionnelle)",
            "filiere": "Filière associée (optionnelle)",
            "semester": "Semestre associé (optionnel)",
        }
        widgets = {
            "title": forms.TextInput(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]", "placeholder": "Ex: Sujet Examen Math 2025.pdf"}),
            "file_type": forms.Select(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]"}),
            "file": forms.FileInput(attrs={"class": "w-full px-4 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs font-semibold text-slate-700"}),
            "school": forms.Select(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]"}),
            "filiere": forms.Select(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]"}),
            "semester": forms.Select(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]"}),
        }

    def clean_file(self):
        file = self.cleaned_data.get("file")
        if file:
            ext = os.path.splitext(file.name)[1].lower()
            if ext != ".pdf":
                raise forms.ValidationError("Seuls les fichiers PDF (.pdf) sont autorisés.")
            if file.size > 20 * 1024 * 1024:
                raise forms.ValidationError("La taille du fichier ne doit pas dépasser 20 Mo.")
        return file


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

    subject_name = forms.CharField(
        max_length=150,
        required=True,
        label="Matière / UE (Saisie libre)",
        widget=forms.TextInput(attrs={
            "class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49] focus:ring-2 focus:ring-blue-500 outline-none",
            "placeholder": "Ex: Analyse Mathématique, Comptabilité, Droit Commercial...",
            "list": "subjects-list",
            "autocomplete": "off"
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
        if self.instance and self.instance.pk:
            self.fields["is_free"].initial = "true" if self.instance.is_free else "false"
            self.fields["is_published"].initial = "true" if self.instance.is_published else "false"
            if self.instance.subject:
                self.fields["subject_name"].initial = self.instance.subject.name
            if self.instance.semester:
                self.fields["semester"].initial = self.instance.semester
            if self.instance.academic_year:
                self.fields["year"].initial = self.instance.academic_year.label

        if active_filiere:
            self.fields["semester"].queryset = Semester.objects.filter(filiere=active_filiere)
            self.fields["cloud_file"].queryset = CloudFile.objects.filter(filiere=active_filiere)
            self.fields["cloud_correction_file"].queryset = CloudFile.objects.filter(filiere=active_filiere)
            self.fields["cloud_summary_file"].queryset = CloudFile.objects.filter(filiere=active_filiere)

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

        return cleaned_data



class SummaryAdminForm(forms.ModelForm):
    """Formulaire d'édition/publication d'un résumé de cours."""
    HUMAN_STATUS_CHOICES = [
        ("DRAFT", "Brouillon"),
        ("PUBLISHED", "Publié"),
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

    class Meta:
        model = Summary
        fields = ["title", "subject", "introduction", "content", "file", "access_type", "publication_status"]
        labels = {
            "title": "Titre du résumé",
            "subject": "Unité d'Enseignement / Matière",
            "introduction": "Présentation succincte",
            "content": "Contenu détaillé rédigé",
            "file": "Fichier PDF optionnel",
        }
        widgets = {
            "title": forms.TextInput(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]", "placeholder": "Fiche de synthèse..."}),
            "subject": forms.Select(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]"}),
            "introduction": forms.Textarea(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-medium text-[#071A49]", "rows": 2}),
            "content": forms.Textarea(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-medium text-[#071A49]", "rows": 8}),
            "file": forms.FileInput(attrs={"class": "w-full px-4 py-2 bg-slate-50 border border-slate-200 rounded-xl text-xs font-semibold text-slate-700"}),
        }

    def __init__(self, *args, active_filiere=None, **kwargs):
        super().__init__(*args, **kwargs)
        if active_filiere:
            self.fields["subject"].queryset = Subject.objects.filter(semester__filiere=active_filiere)

    def clean(self):
        cleaned_data = super().clean()
        content = cleaned_data.get("content", "").strip() if cleaned_data.get("content") else ""
        file = cleaned_data.get("file")
        status = cleaned_data.get("publication_status")

        has_file = bool(file or (self.instance and self.instance.pk and self.instance.file))
        if status == "PUBLISHED" and not content and not has_file:
            self.add_error("file", "Un résumé publié doit comporter au moins du texte rédigé ou un fichier PDF.")

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
        fields = ["name", "semester"]
        labels = {
            "name": "Nom de la matière / UE",
            "semester": "Semestre d'études",
        }
        widgets = {
            "name": forms.TextInput(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]", "placeholder": "Ex: Algorithmique & Programmation"}),
            "semester": forms.Select(attrs={"class": "w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl text-xs font-bold text-[#071A49]"}),
        }

    def __init__(self, *args, active_filiere=None, **kwargs):
        super().__init__(*args, **kwargs)
        if active_filiere:
            self.fields["semester"].queryset = Semester.objects.filter(filiere=active_filiere)


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
