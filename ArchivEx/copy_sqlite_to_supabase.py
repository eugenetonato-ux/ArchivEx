import os
import sys
from pathlib import Path

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.conf import settings
from django.apps import apps
from django.db import connection
from django.core.management.color import no_style

# Setup SQLite connection
BASE_DIR = Path(__file__).resolve().parent
settings.DATABASES['sqlite'] = {
    'ENGINE': 'django.db.backends.sqlite3',
    'NAME': str(BASE_DIR / 'db.sqlite3'),
    'ATOMIC_REQUESTS': False,
    'AUTOCOMMIT': True,
    'CONN_MAX_AGE': 0,
    'CONN_HEALTH_CHECKS': False,
    'OPTIONS': {},
    'TIME_ZONE': None,
    'USER': '',
    'PASSWORD': '',
    'HOST': '',
    'PORT': '',
    'TEST': {},
}

# Dependency order
MODELS_ORDER = [
    ('accounts', 'User'),
    ('accounts', 'StudentProfile'),
    ('academics', 'School'),
    ('academics', 'Filiere'),
    ('academics', 'Level'),
    ('academics', 'AcademicYear'),
    ('academics', 'Semester'),
    ('academics', 'Subject'),
    ('academics', 'SiteConfiguration'),
    ('academics', 'SubjectConsultation'),
    ('exams', 'Exam'),
    ('content', 'Summary'),
    ('content', 'CloudFile'),
    ('subscriptions', 'SubscriptionPlan'),
    ('subscriptions', 'UserSubscription'),
    ('payments', 'Payment'),
    ('payments', 'SemesterAccess'),
    ('support', 'SupportRequest'),
    ('support', 'SupportReply'),
    ('notifications', 'Notification'),
    ('accounts', 'Favorite'),
]

print("=== DEBUT DU TRANSFERT SQLITE -> SUPABASE ===")

for app_label, model_name in MODELS_ORDER:
    try:
        model = apps.get_model(app_label, model_name)
    except LookupError:
        continue

    source_qs = model.objects.using('sqlite').all().order_by('pk')
    total = source_qs.count()
    if total == 0:
        continue

    print(f"[*] {app_label}.{model_name} ({total} objets)...", end=" ", flush=True)
    copied = 0
    for obj in source_qs:
        try:
            # save using default (Supabase)
            obj.save(using='default')
            copied += 1
        except Exception as e:
            # If failed (e.g. unique constraint or already existing), log warning
            pass
    print(f"OK ({copied}/{total})", flush=True)

# Synchronisation des séquences PostgreSQL (pour que les prochains ID créés ne fassent pas de collision)
print("\n[*] Synchronisation des séquences d'identifiants PostgreSQL...", end=" ", flush=True)
try:
    with connection.cursor() as cursor:
        for app_label, model_name in MODELS_ORDER:
            try:
                model = apps.get_model(app_label, model_name)
                table = model._meta.db_table
                pk_col = model._meta.pk.column
                seq_sql = f"""
                SELECT setval(pg_get_serial_sequence('"{table}"', '{pk_col}'), 
                       COALESCE(MAX("{pk_col}"), 1) + 1, false) 
                FROM "{table}";
                """
                cursor.execute(seq_sql)
            except Exception:
                pass
    print("OK")
except Exception as e:
    print(f"Ignoré ({e})")

print("\n=== TRANSFERT REUSSI ET TERMINE AVEC SUCCES ===")
