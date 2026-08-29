from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="SupportRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("category", models.CharField(
                    choices=[
                        ("question", "Question"),
                        ("probleme_epreuve", "Problème avec une épreuve"),
                        ("probleme_compte", "Problème de compte"),
                        ("paiement", "Paiement"),
                        ("suggestion", "Suggestion"),
                        ("signaler_erreur", "Signaler une erreur"),
                        ("autre", "Autre"),
                    ],
                    default="question",
                    max_length=30,
                    verbose_name="Catégorie / Motif",
                )),
                ("message", models.TextField(verbose_name="Message")),
                ("status", models.CharField(
                    choices=[
                        ("non_lu", "Non lu"),
                        ("en_cours", "En cours"),
                        ("repondu", "Répondu"),
                        ("cloture", "Clôturé"),
                    ],
                    default="non_lu",
                    max_length=20,
                    verbose_name="Statut",
                )),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Date de soumission")),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="support_requests",
                    to="accounts.user",
                    verbose_name="Étudiant",
                )),
            ],
            options={
                "verbose_name": "Demande de support",
                "verbose_name_plural": "Demandes de support",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="SupportReply",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("message", models.TextField(verbose_name="Réponse")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Date de réponse")),
                ("admin_user", models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="support_replies",
                    to="accounts.user",
                    verbose_name="Administrateur",
                )),
                ("request", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="replies",
                    to="support.supportrequest",
                    verbose_name="Demande",
                )),
            ],
            options={
                "verbose_name": "Réponse support",
                "verbose_name_plural": "Réponses support",
                "ordering": ["created_at"],
            },
        ),
    ]
