# ArchivEx — Cahier des Charges Technique & Guide de Développement

**Stack technologique** : Django / MySQL / HTML5, CSS3, JavaScript, Tailwind CSS
**Objectif** : MVP d'une plateforme web éducative de banque d'épreuves universitaires — centraliser les anciennes épreuves d'école, dispersées entre WhatsApp, Telegram, Drive et téléphones, et les rendre accessibles via un parcours simple : École → Niveau → Filière → Semestre → Matière → Épreuve → PDF.
**Authentification** : compte étudiant (inscription rapide : prénom, nom, email, mot de passe, puis école/niveau/filière) + espace administrateur pour la gestion académique et le contenu.
**Monétisation** : Pass Semestre (accès forfaitaire par semestre, ex. 2 000 FCFA), pas d'abonnement mensuel dans ce MVP.

---

## 🎯 1. Stratégie MVP

Périmètre de lancement volontairement limité :

- une seule école/université ;
- principalement le niveau L1 ;
- plusieurs filières, semestres, matières ;
- anciennes épreuves au format PDF.

L'architecture doit néanmoins permettre plus tard, **sans être construite maintenant** : L2, L3, Master, d'autres écoles, d'autres universités, d'autres pays.

---

## 🛠️ 2. Installation & Configuration Initiale

```bash
django-admin startproject config .
python -m venv env && env\Scripts\Activate.ps1
```

### Dépendances principales

```bash
pip install django mysqlclient pillow python-decouple \
  pytest pytest-django factory-boy black isort flake8
```

### Variables d'environnement (`.env`)

```
DEBUG=False
SECRET_KEY=
DB_NAME=
DB_USER=
DB_PASSWORD=
DB_HOST=
DB_PORT=
```

---

## 🏗️ 3. Architecture des dossiers

Structure volontairement simple — ne pas multiplier les applications Django :

```
ArchivEx/
│
├── manage.py
├── requirements.txt
├── .env
├── .gitignore
│
├── config/
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py / asgi.py
│
├── accounts/        # User, StudentProfile, inscription, connexion, dashboard, profil, favoris
├── academics/        # School, Level, Filiere, AcademicYear, Semester, Subject, landing page
├── exams/             # Exam, upload/diffusion PDF, recherche, filtres
├── payments/          # Pass Semestre, SemesterAccess, Payment (mode simulé)
│
├── templates/
├── static/
├── media/
└── docs/
```

### Détail des apps

**`accounts/`** : `User` (Django ou custom si justifié) et `StudentProfile` (utilisateur, école, niveau, filière, avatar éventuel, date de création). Gère inscription, connexion, déconnexion, dashboard étudiant, profil, favoris.

**`academics/`** : structure académique complète — `School`, `Level`, `Filiere`, `AcademicYear`, `Semester`, `Subject`. Sert aussi la landing page et les pages de navigation publique (filières, semestres, matières).

**`exams/`** : modèle `Exam`, stockage des PDF sur le système de fichiers (media, avec architecture prête pour un stockage cloud plus tard), page liste avec recherche/filtres/pagination, page détail avec logique d'accès (aperçu, téléchargement, verrouillage Premium).

**`payments/`** : `Pass`/`SemesterAccess` (accès activé par semestre) et `Payment` (historique des transactions). Architecture abstraite/service pour brancher plus tard un vrai fournisseur (Mobile Money, autre passerelle locale, carte). Mode simulé/test pour le développement.

---

## 🔄 4. Flux clés de la plateforme

### Parcours étudiant principal
```
Accueil
   ↓
Créer un compte
   ↓
École → Niveau → Filière → Semestre → Matière
   ↓
Épreuves (recherche, filtres)
   ↓
Épreuve gratuite → PDF (aperçu / téléchargement)
   ↓
Épreuve Premium → 🔒
   ↓
Pass Semestre → Paiement → Confirmation serveur
   ↓
🔓 Accès débloqué → PDF
```

### Ajout d'une épreuve (administrateur)
```
Connexion admin
   ↓
Créer filière / semestre / matière si besoin
   ↓
Ajouter une épreuve (titre, matière, semestre, filière, niveau, année, type)
   ↓
Uploader le PDF
   ↓
Définir Gratuit / Premium
   ↓
Publier
   ↓
L'épreuve apparaît sur la plateforme
```

### Logique de déblocage (contrôle serveur obligatoire)
```
Utilisateur
      ↓
A-t-il un Pass Semestre actif pour cette école/niveau/filière/année/semestre ?
      ↓
   ┌──┴──┐
   │     │
  NON   OUI
   │     │
   ↓     ↓
 🔒     🔓
   │     │
   ↓     ↓
Paiement Accès
```

Le contrôle est **toujours effectué côté serveur**. Ne jamais se contenter de masquer le contenu avec du JavaScript ; un utilisateur ne doit pas pouvoir contourner la restriction en modifiant le frontend ou l'URL.

---

## 📚 5. Modèles de données (extraits clés)

### `User` / `StudentProfile` (accounts)
```python
class StudentProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    school = models.ForeignKey("academics.School", on_delete=models.PROTECT)
    level = models.ForeignKey("academics.Level", on_delete=models.PROTECT)
    filiere = models.ForeignKey("academics.Filiere", on_delete=models.PROTECT)
    avatar = models.ImageField(upload_to="avatars/", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

### Structure académique (academics)
```python
class School(models.Model):
    name = models.CharField(max_length=150)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    logo = models.ImageField(upload_to="schools/", blank=True)
    is_active = models.BooleanField(default=True)


class Level(models.Model):
    name = models.CharField(max_length=20)  # L1, L2, L3, M1, M2


class Filiere(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="filieres")
    level = models.ForeignKey(Level, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)


class AcademicYear(models.Model):
    label = models.CharField(max_length=20, unique=True)  # ex. "2026-2027"


class Semester(models.Model):
    filiere = models.ForeignKey(Filiere, on_delete=models.CASCADE, related_name="semesters")
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.CASCADE)
    label = models.CharField(max_length=50)  # "Semestre 1"


class Subject(models.Model):
    semester = models.ForeignKey(Semester, on_delete=models.CASCADE, related_name="subjects")
    name = models.CharField(max_length=150)
    is_free = models.BooleanField(default=False)
```

### `Exam` (exams)
```python
class Exam(models.Model):
    EXAM_TYPE_CHOICES = [
        ("examen", "Examen"), ("rattrapage", "Rattrapage"), ("devoir", "Devoir"),
        ("td", "TD"), ("tp", "TP"), ("concours", "Concours"), ("autre", "Autre"),
    ]

    title = models.CharField(max_length=200)
    subject = models.ForeignKey("academics.Subject", on_delete=models.PROTECT, related_name="exams")
    semester = models.ForeignKey("academics.Semester", on_delete=models.PROTECT)
    filiere = models.ForeignKey("academics.Filiere", on_delete=models.PROTECT)
    level = models.ForeignKey("academics.Level", on_delete=models.PROTECT)
    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT)
    exam_type = models.CharField(max_length=20, choices=EXAM_TYPE_CHOICES)
    year = models.PositiveIntegerField()
    description = models.TextField(blank=True)
    file = models.FileField(upload_to="exams/")
    is_free = models.BooleanField(default=False)
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

### `Favorite` (accounts ou exams)
```python
class Favorite(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favorites")
    exam = models.ForeignKey("exams.Exam", on_delete=models.CASCADE, related_name="favorited_by")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "exam")
```

### `SemesterAccess` / `Payment` (payments)
```python
class SemesterAccess(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="accesses")
    school = models.ForeignKey("academics.School", on_delete=models.PROTECT)
    level = models.ForeignKey("academics.Level", on_delete=models.PROTECT)
    filiere = models.ForeignKey("academics.Filiere", on_delete=models.PROTECT)
    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT)
    semester = models.ForeignKey("academics.Semester", on_delete=models.PROTECT)
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("user", "semester")


class Payment(models.Model):
    STATUT_CHOICES = [("en_attente", "En attente"), ("reussi", "Réussi"), ("echoue", "Échoué"), ("annule", "Annulé")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments")
    semester_access = models.ForeignKey(SemesterAccess, on_delete=models.PROTECT, related_name="payments")
    amount = models.PositiveIntegerField()  # défini côté serveur, jamais reçu du client
    status = models.CharField(max_length=20, choices=STATUT_CHOICES, default="en_attente")
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

---

## 🗄️ 6. Schéma MySQL — relations principales

```
users
  │
  ├──────────────┐
  │              │
  ↓              ↓
profiles      favorites
                  │
                  ↓
                exams
                  │
                  ↓
               subjects
                  │
                  ↓
              semesters
                  │
                  ↓
               filieres
                  │
                  ↓
                levels
                  │
                  ↓
                schools

users → semester_access → semesters
users → payments → semester_access
```

---

## 🧠 7. Règles de développement (à respecter strictement)

- ❌ **INTERDIT** : logique métier dans les vues — privilégier des fonctions/services dédiés par app.
- ❌ **INTERDIT** : déterminer côté frontend le statut gratuit/Premium ou le prix du Pass.
- ❌ **INTERDIT** : activer un `SemesterAccess` uniquement parce que le frontend indique que le paiement a réussi.
- ❌ **INTERDIT** : servir un PDF protégé via une URL statique publique prévisible sans vérification serveur.
- ✅ **OBLIGATOIRE** : le prix et le produit (quel Pass, pour quel semestre) sont déterminés côté serveur à chaque paiement.
- ✅ **OBLIGATOIRE** : chaque vue d'épreuve protégée revérifie les droits d'accès à chaque requête.
- ✅ **OBLIGATOIRE** : un favori est unique par couple utilisateur/épreuve.
- ✅ **OBLIGATOIRE** : `select_related()`/`prefetch_related()` sur les listes d'épreuves et de matières pour éviter les requêtes N+1.

---

## 🚀 8. Checklist de développement (alignée sur les 16 étapes)

### Étape 1 — Analyse & architecture
- [x] Analyse du MVP, structure académique et parcours utilisateur *(en cours)*
- [ ] Schéma MySQL complet présenté et validé

### Étape 2-3 — Socle technique
- [ ] Environnement Python, Django, MySQL, `.env`, `requirements.txt`
- [ ] Modèles `User`/`StudentProfile`, `School`, `Level`, `Filiere`, `AcademicYear`, `Semester`, `Subject`

### Étape 4-6 — Authentification & Admin
- [ ] Migrations
- [ ] Django Admin configuré (gestion académique, épreuves, utilisateurs, pass, paiements)
- [ ] Inscription / connexion / déconnexion étudiantes

### Étape 7-9 — Contenu académique
- [ ] Pages École → Niveau → Filière → Semestre → Matière
- [ ] Modèle `Exam`, upload PDF, page liste + détail
- [ ] Favoris

### Étape 10-12 — Monétisation & suivi
- [ ] Système de Pass Semestre
- [ ] Paiement en mode test/simulé (aucune activation sans confirmation serveur)
- [ ] Dashboard étudiant

### Étape 13-16 — Finalisation
- [ ] Responsive et UI/UX (mobile-first, Tailwind)
- [ ] Tests de sécurité (permissions Premium, contournement URL, manipulation de prix)
- [ ] Tests du parcours complet (inscription → paiement → accès → téléchargement)
- [ ] Préparation au déploiement (`DEBUG=False`, `ALLOWED_HOSTS`, HTTPS, statics/media, MySQL prod)

---

## 🚫 9. Fonctionnalités à ne pas faire maintenant

IA, chatbot, XP/badges/classement/streak, réseau social, commentaires, abonnement mensuel/annuel, marketplace, application mobile native, recommandations IA, système complexe de notifications — à envisager uniquement après validation du MVP par de vrais étudiants (V2 à V6).

---

## 🧠 10. Philosophie du projet

1. **Commencer petit** — pas d'usine à fonctionnalités avant d'avoir des utilisateurs.
2. **Tester avec de vrais étudiants** — les décisions futures sont guidées par l'usage réel.
3. **Construire une base solide** — code et base de données propres même pour un MVP réduit.

Priorité absolue : **simplicité → fonctionnement → sécurité → expérience utilisateur → évolutivité.**
