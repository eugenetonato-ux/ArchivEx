from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from exams.models import Exam
from content.models import Summary, Guide
from .services import generate_publication_notification


# ─── PRE-SAVE : capturer l'état de publication AVANT la sauvegarde ───
# Permet de détecter un changement de statut (brouillon → publié) et
# d'éviter les notifications en double lors de simples éditions.

@receiver(pre_save, sender=Exam)
def _track_exam_published_state(sender, instance, **kwargs):
    """Mémorise l'ancien état is_published avant la sauvegarde."""
    if instance.pk:
        try:
            old = Exam.objects.filter(pk=instance.pk).values_list("is_published", flat=True).first()
            instance._was_published = bool(old)
        except Exception:
            instance._was_published = False
    else:
        instance._was_published = False


@receiver(pre_save, sender=Summary)
def _track_summary_published_state(sender, instance, **kwargs):
    """Mémorise l'ancien publication_status avant la sauvegarde."""
    if instance.pk:
        try:
            old = Summary.objects.filter(pk=instance.pk).values_list("publication_status", flat=True).first()
            instance._was_published = (old == "PUBLISHED")
        except Exception:
            instance._was_published = False
    else:
        instance._was_published = False


@receiver(pre_save, sender=Guide)
def _track_guide_published_state(sender, instance, **kwargs):
    """Mémorise l'ancien publication_status avant la sauvegarde."""
    if instance.pk:
        try:
            old = Guide.objects.filter(pk=instance.pk).values_list("publication_status", flat=True).first()
            instance._was_published = (old == "PUBLISHED")
        except Exception:
            instance._was_published = False
    else:
        instance._was_published = False


# ─── POST-SAVE : ne notifier QUE lors d'un passage à « publié » ───

@receiver(post_save, sender=Exam)
def on_exam_published(sender, instance, created, **kwargs):
    """
    Déclenché lors de la création ou mise à jour d'une épreuve.
    Génère des notifications UNIQUEMENT quand l'épreuve vient d'être publiée
    pour la première fois (création publiée OU passage brouillon → publié).
    Les simples modifications d'une épreuve déjà publiée ne déclenchent rien.
    """
    if not instance.is_published:
        return

    # Si l'épreuve était déjà publiée avant cette sauvegarde, ne pas re-notifier
    was_published = getattr(instance, "_was_published", False)
    if was_published and not created:
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
    Ne notifie que lors du passage initial à PUBLISHED.
    """
    if instance.publication_status != "PUBLISHED":
        return

    was_published = getattr(instance, "_was_published", False)
    if was_published and not created:
        return

    generate_publication_notification(instance, nature="resume")


@receiver(post_save, sender=Guide)
def on_guide_published(sender, instance, created, **kwargs):
    """
    Déclenché lorsqu'un guide méthodologique est publié (publication_status='PUBLISHED').
    Ne notifie que lors du passage initial à PUBLISHED.
    """
    if instance.publication_status != "PUBLISHED":
        return

    was_published = getattr(instance, "_was_published", False)
    if was_published and not created:
        return

    generate_publication_notification(instance, nature="guide")
