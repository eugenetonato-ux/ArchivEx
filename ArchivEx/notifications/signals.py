from django.db.models.signals import post_save
from django.dispatch import receiver
from exams.models import Exam
from content.models import Summary, Guide
from .services import generate_publication_notification


@receiver(post_save, sender=Exam)
def on_exam_published(sender, instance, created, **kwargs):
    """
    Déclenché lors de la création ou mise à jour d'une épreuve.
    Si l'épreuve est publiée (is_published=True), génère les notifications
    pour l'épreuve, le corrigé (si présent), ou le résumé (si présent).
    """
    if not instance.is_published:
        return

    # Notification pour l'épreuve
    generate_publication_notification(instance, nature="epreuve")

    # Notification pour le corrigé (si un fichier de correction est rattaché)
    if instance.has_correction:
        generate_publication_notification(instance, nature="corrige")

    # Notification pour le résumé rattaché (si présent)
    if instance.has_summary:
        generate_publication_notification(instance, nature="resume")


@receiver(post_save, sender=Summary)
def on_summary_published(sender, instance, created, **kwargs):
    """
    Déclenché lorsqu'un résumé de cours est publié (publication_status='PUBLISHED').
    """
    if instance.publication_status == "PUBLISHED":
        generate_publication_notification(instance, nature="resume")


@receiver(post_save, sender=Guide)
def on_guide_published(sender, instance, created, **kwargs):
    """
    Déclenché lorsqu'un guide méthodologique est publié (publication_status='PUBLISHED').
    """
    if instance.publication_status == "PUBLISHED":
        generate_publication_notification(instance, nature="guide")
