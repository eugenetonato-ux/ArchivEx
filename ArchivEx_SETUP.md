# ArchivEx — Mise en place du projet (Windows / PowerShell)

Ce guide applique l'architecture définie dans `ArchivEx_skills-app.md` (apps, structure académique, flux gratuit/Premium/paiement) et suit le prompt maître du projet. On garde une structure Django volontairement simple : peu d'apps, bien nommées, pas d'architecture prématurément complexe.

---

## 1. Création du dossier et de l'environnement virtuel

```powershell
mkdir ArchivEx
cd ArchivEx
python -m venv env
env\Scripts\Activate.ps1
```

Tu dois voir `(env)` apparaître devant ton prompt avant de continuer.

---

## 2. Installation des dépendances

```powershell
python -m pip install --upgrade pip

pip install django
pip install mysqlclient
pip install pillow
pip install python-decouple

# Qualité de code
pip install black isort flake8
pip install pytest pytest-django factory-boy
```

> `mysqlclient` nécessite les outils de build MySQL sur Windows. Si l'installation échoue, utiliser en alternative `pip install pymysql` et l'activer dans `manage.py` / `__init__.py` (`pymysql.install_as_MySQLdb()`) le temps de configurer l'environnement de build.

Génère ton `requirements.txt` :

```powershell
pip freeze > requirements.txt
```

---

## 3. Démarrage du projet Django

```powershell
django-admin startproject config .
```

## 4. Création des applications

Conformément au principe « ne pas multiplier les applications Django inutilement », on reste sur 4 apps métier :

```powershell
python manage.py startapp accounts
python manage.py startapp academics
python manage.py startapp exams
python manage.py startapp payments
```

### Corriger le `name` de chaque app

```python
# accounts/apps.py
from django.apps import AppConfig

class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"   # ⚠️ à corriger dans chacune des 4 apps
```

Répète cette correction dans `accounts/apps.py`, `academics/apps.py`, `exams/apps.py`, `payments/apps.py`.

---

## 5. Création des dossiers `templates/` et `static/`

```powershell
mkdir templates
mkdir templates\base
mkdir templates\accounts
mkdir templates\academics
mkdir templates\exams
mkdir templates\payments
mkdir templates\dashboard

type nul > templates\base\base.html
type nul > templates\accounts\login.html
type nul > templates\accounts\register.html
type nul > templates\academics\filieres.html
type nul > templates\academics\semestres.html
type nul > templates\academics\matieres.html
type nul > templates\exams\liste.html
type nul > templates\exams\detail.html
:: detail.html gère l'affichage protégé/déverrouillé d'une épreuve
type nul > templates\payments\pass_semestre.html
type nul > templates\payments\paiement.html
type nul > templates\dashboard\dashboard.html
type nul > templates\dashboard\favoris.html
type nul > templates\dashboard\profil.html

mkdir static\css, static\js, static\images
New-Item -Path static\css\style.css -ItemType File
New-Item -Path static\js\main.js -ItemType File

mkdir media
mkdir media\exams, media\schools

mkdir logs
mkdir backups
mkdir docs
```

> Tailwind CSS peut être intégré via CDN pour le MVP (rapide, pas de build step), ou via `django-tailwind`/un pipeline Node si une personnalisation plus poussée est nécessaire — à trancher à l'étape UI/UX, pas avant.

---

## 6. Fichier `.env` (racine du projet)

```powershell
New-Item -Path .env -ItemType File
```

Contenu de `.env` :

```
DEBUG=True
SECRET_KEY=change-moi-en-production
ALLOWED_HOSTS=127.0.0.1,localhost

DB_NAME=archivex
DB_USER=root
DB_PASSWORD=
DB_HOST=127.0.0.1
DB_PORT=3306

PASS_SEMESTRE_PRIX_DEFAUT=2000
```

Ajoute `.env` dans `.gitignore` :

```powershell
New-Item -Path .gitignore -ItemType File
Add-Content .gitignore "env/`n.env`n__pycache__/`n*.pyc`nmedia/`nlogs/"
```

---

## 7. Configuration `config/settings.py`

### a) Imports en haut du fichier

```python
from pathlib import Path
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent
```

### b) Variables sensibles depuis `.env`

```python
SECRET_KEY = config("SECRET_KEY")
DEBUG = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="").split(",")
```

### c) `INSTALLED_APPS`

```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Apps ArchivEx
    "accounts",
    "academics",
    "exams",
    "payments",
]
```

### d) Authentification

```python
LOGIN_URL = "/connexion/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/"

AUTH_USER_MODEL = "accounts.User"
```

> Contrairement à un back-office interne, ArchivEx a une **partie publique** (landing page, navigation académique, épreuves gratuites) accessible sans compte. Seuls le dashboard, les favoris, le profil et le déblocage de contenu Premium exigent une session étudiante valide.

### e) Fuseau horaire et langue

```python
LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Africa/Porto-Novo"
USE_I18N = True
USE_TZ = True
```

### f) Templates

```python
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]
```

### g) Static / Media

```python
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
```

### h) Base de données MySQL

```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": config("DB_NAME"),
        "USER": config("DB_USER"),
        "PASSWORD": config("DB_PASSWORD", default=""),
        "HOST": config("DB_HOST", default="127.0.0.1"),
        "PORT": config("DB_PORT", default="3306"),
    }
}
```

Créer la base côté MySQL avant `migrate` :

```powershell
mysql -u root -p -e "CREATE DATABASE archivex CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

---

## 8. Configuration `config/urls.py`

```python
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("", include("academics.urls")),          # accueil + navigation académique publique
    path("", include("accounts.urls")),            # connexion / inscription / dashboard / profil
    path("epreuves/", include("exams.urls")),
    path("pass/", include("payments.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
```

---

## 9. Migrations et super utilisateur

```powershell
python manage.py makemigrations
python manage.py migrate

python manage.py createsuperuser
```

**Réinitialiser les super users si besoin** :

```powershell
python manage.py shell -c "from django.contrib.auth import get_user_model; get_user_model().objects.filter(is_superuser=True).delete()"
```

⚠️ Une fois tous les superusers supprimés, tu n'auras plus accès à l'admin Django.

---

## 10. Lancement du serveur

```powershell
python manage.py runserver
```

- Accueil : `http://127.0.0.1:8000/`
- Django admin (technique) : `http://127.0.0.1:8000/django-admin/`

---

## 11. Ordre de développement recommandé (aligné sur les 16 étapes du prompt maître)

1. `accounts` — modèle `User`/`StudentProfile`, inscription, connexion *(étape 1-2 déjà en cours d'analyse)*
2. `academics` — modèles School, Level, Filiere, AcademicYear, Semester, Subject
3. Django Admin configuré pour la gestion académique
4. `exams` — modèle Exam, upload PDF, pages liste/détail
5. Favoris
6. `payments` — Pass Semestre + paiement en mode test/simulé
7. Dashboard étudiant
8. Finalisation responsive et UI/UX (Tailwind)
9. Tests de sécurité (permissions Premium, contournement URL)
10. Tests du parcours complet
11. Préparation au déploiement

---

## 12. Commandes utiles

```powershell
# Vérifier les utilisateurs enregistrés
python manage.py shell
>>> from django.contrib.auth import get_user_model
>>> User = get_user_model()
>>> User.objects.count()
>>> exit()

# Mise à jour GitHub
git status
git add .
git commit -m "mise a jour"
git push origin main
```
