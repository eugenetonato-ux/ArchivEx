#!/usr/bin/env python3
"""
ArchivEx — Script de Contrôle et Gestion du Cycle des Semestres
=============================================================
Usage :
  python manage_semester.py status
  python manage_semester.py activate 2   (Lance le Semestre 2 et publie ses épreuves)
  python manage_semester.py deactivate 2 (Masque le Semestre 2 et dépublie ses épreuves)
"""
import os
import sys
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from academics.models import Semester, Subject
from exams.models import Exam


def show_status():
    print("\n" + "=" * 60)
    print("       ARCHIVEX - ETAT DU CYCLE DES SEMESTRES")
    print("=" * 60)
    for sem in Semester.objects.all().order_by("number"):
        subjects = Subject.objects.filter(semester=sem)
        exams = Exam.objects.filter(semester=sem)
        pub_exams = exams.filter(is_published=True).count()
        status_icon = "[ACTIF - Visible sur le site]" if sem.is_active else "[MASQUE - Invisible du site]"

        print(f"\n* Semestre {sem.label} (Numero {sem.number}, ID: {sem.id}) : {status_icon}")
        print(f"   - Matieres : {subjects.filter(is_active=True).count()}/{subjects.count()} actives")
        print(f"   - Epreuves : {pub_exams}/{exams.count()} publiees sur le site")

    print("\n" + "=" * 60 + "\n")


def activate_semester(number):
    sem = Semester.objects.filter(number=number).first()
    if not sem:
        print(f"[-] Aucun semestre trouve avec le numero {number}.")
        return

    Semester.objects.filter(number=number).update(is_active=True)
    Subject.objects.filter(semester=sem).update(is_active=True)
    Exam.objects.filter(semester=sem).update(is_published=True)

    print(f"\n[+] LE SEMESTRE {sem.label} EST MAINTENANT LANCE ET ACTIF !")
    print(f"   * Matieres activees : {Subject.objects.filter(semester=sem).count()}")
    print(f"   * Epreuves publiees : {Exam.objects.filter(semester=sem).count()}")
    print("   [i] Rappel : Les Pass S1 ne donnent pas acces a S2. Les etudiants doivent payer le Pass S2.")
    show_status()


def deactivate_semester(number):
    sem = Semester.objects.filter(number=number).first()
    if not sem:
        print(f"[-] Aucun semestre trouve avec le numero {number}.")
        return

    Semester.objects.filter(number=number).update(is_active=False)
    Subject.objects.filter(semester=sem).update(is_active=False)
    Exam.objects.filter(semester=sem).update(is_published=False)

    print(f"\n[*] LE SEMESTRE {sem.label} EST DESORMAIS MASQUE DU SITE PUBLIC !")
    print(f"   * Matieres masquées : {Subject.objects.filter(semester=sem).count()}")
    print(f"   * Epreuves depubliees : {Exam.objects.filter(semester=sem).count()}")
    show_status()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        show_status()
        print("Commandes disponibles :")
        print("  python manage_semester.py status")
        print("  python manage_semester.py activate 2")
        print("  python manage_semester.py deactivate 2\n")
        sys.exit(0)

    action = sys.argv[1].lower()

    if action == "status":
        show_status()
    elif action == "activate" and len(sys.argv) >= 3:
        try:
            num = int(sys.argv[2])
            activate_semester(num)
        except ValueError:
            print("❌ Le numéro de semestre doit être un entier (ex: 2).")
    elif action == "deactivate" and len(sys.argv) >= 3:
        try:
            num = int(sys.argv[2])
            deactivate_semester(num)
        except ValueError:
            print("❌ Le numéro de semestre doit être un entier (ex: 2).")
    else:
        print(f"❌ Commande inconnue ou arguments manquants: {' '.join(sys.argv[1:])}")
