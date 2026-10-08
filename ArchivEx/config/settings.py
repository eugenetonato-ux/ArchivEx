"""
Django settings for ArchivEx V2 project.

Production-hardened configuration using python-decouple for environment variables.
"""

import os
from pathlib import Path
from decouple import config, Csv

BASE_DIR = Path(__file__).resolve().parent.parent

# Core Security & Environment
SECRET_KEY = config("SECRET_KEY")

DEBUG = config("DEBUG", default=False, cast=bool)

ALLOWED_HOSTS = ["*"]

CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    default="",
    cast=Csv()
)

# HTTPS & Cookie Security
# En production : SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True, SECURE_SSL_REDIRECT=True (dans .env)
SESSION_COOKIE_SECURE = config("SESSION_COOKIE_SECURE", default=False, cast=bool)
CSRF_COOKIE_SECURE = config("CSRF_COOKIE_SECURE", default=False, cast=bool)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = config("SECURE_SSL_REDIRECT", default=False, cast=bool)

# HSTS Configuration
# En production : SECURE_HSTS_SECONDS=31536000, SECURE_HSTS_INCLUDE_SUBDOMAINS=True, SECURE_HSTS_PRELOAD=True (dans .env)
# Commencer avec 300 secondes, puis augmenter progressivement jusqu'à 31536000 (1 an)
SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=0, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = config("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False, cast=bool)
SECURE_HSTS_PRELOAD = config("SECURE_HSTS_PRELOAD", default=False, cast=bool)

# Security Headers
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
# DENY empêche tout framing (clickjacking) — requis pour le check --deploy (W019)
X_FRAME_OPTIONS = "DENY"


# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sitemaps",

    # Apps ArchivEx
    "accounts",
    "academics",
    "exams",
    "payments",
    "subscriptions",
    "content",
    "contributors",
    "notifications",
    "support",

    # Third party
    "storages",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "accounts.middleware.SingleSessionMiddleware",
    "accounts.middleware.SiteLoggingMiddleware",
    "accounts.middleware.MustChangePasswordMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# High performance cache configuration
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "archivex_cache",
        "TIMEOUT": 300,
        "OPTIONS": {
            "MAX_ENTRIES": 2000
        }
    }
}

ROOT_URLCONF = "config.urls"

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
                "notifications.context_processors.notifications_context",
                "contributors.context_processors.admin_academic_context",
                "accounts.context_processors.user_pass_context",
                "academics.context_processors.academic_school_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database
# Supported engines:
#   - django.db.backends.sqlite3     → Développement local
#   - django.db.backends.postgresql  → Production (Supabase)
#   - django.db.backends.mysql       → Fallback hébergeurs partagés (ex: PythonAnywhere)

DB_ENGINE = config("DB_ENGINE", default="django.db.backends.sqlite3")

if DB_ENGINE == "django.db.backends.sqlite3":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / config("DB_NAME", default="db.sqlite3"),
        }
    }

elif DB_ENGINE == "django.db.backends.postgresql":
    # Supabase PostgreSQL — connexion via Transaction Pooler (port 6543)
    # ou Session Pooler (port 5432) selon le plan
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": config("DB_NAME", default="postgres"),
            "USER": config("DB_USER", default="postgres"),
            "PASSWORD": config("DB_PASSWORD", default=""),
            "HOST": config("DB_HOST", default="localhost"),
            "PORT": config("DB_PORT", default="5432"),
            "OPTIONS": {
                "sslmode": config("DB_SSLMODE", default="require"),
            },
            "CONN_MAX_AGE": config("DB_CONN_MAX_AGE", default=60, cast=int),
        }
    }

else:
    # MySQL — Fallback pour hébergeurs partagés (PythonAnywhere, Infomaniak, etc.)
    import pymysql
    pymysql.install_as_MySQLdb()
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": config("DB_NAME", default="archivex"),
            "USER": config("DB_USER", default="root"),
            "PASSWORD": config("DB_PASSWORD", default=""),
            "HOST": config("DB_HOST", default="127.0.0.1"),
            "PORT": config("DB_PORT", default="3306"),
            "OPTIONS": {
                "charset": "utf8mb4",
                "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
            },
        }
    }


# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LOGIN_URL = "/connexion/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/"

AUTH_USER_MODEL = "accounts.User"

# Internationalization

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Africa/Porto-Novo"
USE_I18N = True
USE_TZ = True


# Static & Media Files (WhiteNoise + Supabase Storage / S3 Strategy)

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

USE_SUPABASE_STORAGE = config("USE_SUPABASE_STORAGE", default=False, cast=bool)

if USE_SUPABASE_STORAGE:
    AWS_ACCESS_KEY_ID = config("SUPABASE_STORAGE_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = config("SUPABASE_STORAGE_SECRET_ACCESS_KEY")
    AWS_STORAGE_BUCKET_NAME = config("SUPABASE_STORAGE_BUCKET_NAME", default="archivex-docs")
    AWS_S3_REGION_NAME = config("SUPABASE_STORAGE_REGION", default="eu-west-1")
    AWS_S3_ENDPOINT_URL = config(
        "SUPABASE_STORAGE_ENDPOINT_URL",
        default="https://shqxnsswjffkhywljwzp.supabase.co/storage/v1/s3"
    )
    # file_overwrite=True évite le HeadObject que Supabase S3 ne supporte
    # pas correctement (retourne 400 Bad Request au lieu de 404).
    # Django génère ainsi un nom unique côté client sans interroger Supabase.
    AWS_S3_FILE_OVERWRITE = True
    AWS_DEFAULT_ACL = None
    AWS_QUERYSTRING_AUTH = config("SUPABASE_STORAGE_QUERYSTRING_AUTH", default=False, cast=bool)

    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
            "OPTIONS": {
                "access_key": AWS_ACCESS_KEY_ID,
                "secret_key": AWS_SECRET_ACCESS_KEY,
                "bucket_name": AWS_STORAGE_BUCKET_NAME,
                "endpoint_url": AWS_S3_ENDPOINT_URL,
                "region_name": AWS_S3_REGION_NAME,
                "default_acl": None,
                # True = pas de vérification HeadObject → résout l'erreur 400 Supabase
                "file_overwrite": True,
                "querystring_auth": AWS_QUERYSTRING_AUTH,
                # Paramètres S3 pour Supabase
                "object_parameters": {
                    "ContentType": "application/octet-stream",
                },
            },
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }
    MEDIA_URL = f"{AWS_S3_ENDPOINT_URL}/{AWS_STORAGE_BUCKET_NAME}/"
else:
    MEDIA_URL = "/media/"
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }

MEDIA_ROOT = BASE_DIR / "media"


# Email Configuration

EMAIL_BACKEND = config(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend"
)
EMAIL_HOST = config("EMAIL_HOST", default="")
EMAIL_PORT = config("EMAIL_PORT", default=587, cast=int)
EMAIL_USE_TLS = config("EMAIL_USE_TLS", default=True, cast=bool)
EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default="webmaster@localhost")
SUPPORT_EMAIL = config("SUPPORT_EMAIL", default=config("DEFAULT_FROM_EMAIL", default="support@archivex.bj"))


# Logging Configuration

LOGS_DIR = BASE_DIR / "logs"
os.makedirs(LOGS_DIR, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "file": {
            "class": "logging.FileHandler",
            "filename": LOGS_DIR / "archivex_error.log",
            "formatter": "verbose",
            "level": "ERROR",
        },
    },
    "loggers": {
        "django": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": True,
        },
    },
}

PASS_SEMESTRE_PRIX_DEFAUT = config("PASS_SEMESTRE_PRIX_DEFAUT", default=3800, cast=int)

# FedaPay Payment Gateway Configuration (https://fedapay.com)
FEDAPAY_SECRET_KEY = config("FEDAPAY_SECRET_KEY", default="")
FEDAPAY_PUBLIC_KEY = config("FEDAPAY_PUBLIC_KEY", default="")
FEDAPAY_ENVIRONMENT = config("FEDAPAY_ENVIRONMENT", default="sandbox").strip().lower()  # "sandbox" ou "live"
FEDAPAY_WEBHOOK_SECRET = config("FEDAPAY_WEBHOOK_SECRET", default="")
FEDAPAY_CURRENCY = config("FEDAPAY_CURRENCY", default="XOF")
FEDAPAY_CALLBACK_URL = config("FEDAPAY_CALLBACK_URL", default="")





DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Silence les warnings de sécurité intentionnellement désactivés en local.
# W008 : SECURE_SSL_REDIRECT=False en local (géré par Nginx sur le VPS en prod).
# W021 : SECURE_HSTS_PRELOAD=False — à activer après 6 mois de prod stable.
SILENCED_SYSTEM_CHECKS = ["security.W008", "security.W021"]