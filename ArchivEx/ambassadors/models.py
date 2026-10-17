import uuid
import re
import unicodedata
from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


def normalize_str(text):
    """Supprime les accents, tirets et met en minuscule pour comparaison robuste."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFD", text.lower())
    clean = "".join(c for c in nfkd if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", clean)


class Ambassador(models.Model):
    OPERATOR_CHOICES = [
        ("mtn", "MTN Mobile Money"),
        ("moov", "Moov Money"),
        ("celtiis", "Celtiis Cash"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ambassador_profile",
        help_text="Compte ArchivEx optionnel associé à l'ambassadeur"
    )
    first_name = models.CharField(max_length=100, verbose_name="Prénom")
    last_name = models.CharField(max_length=100, blank=True, verbose_name="Nom de famille")
    phone_number = models.CharField(max_length=30, blank=True, verbose_name="Numéro WhatsApp / Contact")
    
    access_token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        editable=False,
        verbose_name="Jeton d'accès privé"
    )
    code = models.CharField(
        max_length=30,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Code promo"
    )

    commission_per_sale = models.PositiveIntegerField(
        default=500,
        verbose_name="Commission par vente (FCFA)"
    )
    discount_amount = models.PositiveIntegerField(
        default=200,
        verbose_name="Réduction pour le filleul (FCFA)"
    )

    payout_operator = models.CharField(
        max_length=20,
        blank=True,
        choices=OPERATOR_CHOICES,
        default="mtn",
        verbose_name="Réseau Mobile Money"
    )
    payout_phone = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Numéro Mobile Money"
    )
    payout_name = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Nom du titulaire Mobile Money"
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Validé / Actif"
    )
    notes = models.TextField(
        blank=True,
        verbose_name="Notes admin (École, filière, promo)"
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Créé le")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Modifié le")

    class Meta:
        verbose_name = "Ambassadeur"
        verbose_name_plural = "Ambassadeurs"
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.access_token:
            self.access_token = uuid.uuid4().hex
        if self.code:
            self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        full_name = f"{self.first_name} {self.last_name}".strip()
        code_str = f"[{self.code}]" if self.code else "[Sans code]"
        return f"{full_name} {code_str}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.first_name

    def validate_code_candidate(self, raw_code):
        """
        Vérifie la conformité du code choisi par l'ambassadeur :
        1. Format valide (lettres, chiffres, tirets, 3 à 25 caractères)
        2. Doit obligatoirement contenir le prénom de l'ambassadeur
        3. Doit être unique sur la plateforme
        Retourne (is_valid: bool, cleaned_or_error: str)
        """
        if not raw_code:
            return False, "Le code ne peut pas être vide."

        candidate = raw_code.strip().upper()
        if not re.match(r"^[A-Z0-9_-]{3,25}$", candidate):
            return False, "Le code doit contenir entre 3 et 25 caractères (lettres, chiffres et tirets uniquement, sans espace)."

        # Vérification de la présence du prénom
        normalized_fn = normalize_str(self.first_name)
        normalized_cand = normalize_str(candidate)

        if not normalized_fn or normalized_fn not in normalized_cand:
            return False, f"Votre code doit obligatoirement inclure votre prénom « {self.first_name} » (ex: {self.first_name.upper()}25, {self.first_name.upper()}-PASS)."

        # Vérification d'unicité
        existing = Ambassador.objects.filter(code__iexact=candidate).exclude(pk=self.pk).exists()
        if existing:
            return False, f"Le code « {candidate} » est déjà utilisé par un autre partenaire. Veuillez en choisir un autre."

        return True, candidate

    # Statistiques
    @property
    def sales_count(self):
        """Nombre de ventes validées (Pass payés)."""
        return self.sales.filter(status__in=["APPROVED", "PAID_OUT"]).count()

    @property
    def total_earnings(self):
        """Total des gains cumulés (validés ou déjà reversés) en FCFA."""
        sales = self.sales.filter(status__in=["APPROVED", "PAID_OUT"])
        return sum(sale.commission_amount for sale in sales)

    @property
    def pending_payout(self):
        """Montant en attente de versement par l'administration en FCFA."""
        sales = self.sales.filter(status="APPROVED")
        return sum(sale.commission_amount for sale in sales)

    @property
    def paid_payout(self):
        """Montant déjà reversé à l'ambassadeur en FCFA."""
        sales = self.sales.filter(status="PAID_OUT")
        return sum(sale.commission_amount for sale in sales)


class AmbassadorSale(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "En attente de paiement FedaPay"),
        ("APPROVED", "Validé (Pass activé - À reverser)"),
        ("PAID_OUT", "Commission reversée à l'ambassadeur"),
        ("CANCELLED", "Annulé / Échoué"),
    ]

    ambassador = models.ForeignKey(
        Ambassador,
        on_delete=models.CASCADE,
        related_name="sales",
        verbose_name="Ambassadeur"
    )
    payment = models.OneToOneField(
        "payments.Payment",
        on_delete=models.CASCADE,
        related_name="ambassador_sale",
        verbose_name="Paiement associé"
    )
    discount_given = models.PositiveIntegerField(
        default=200,
        verbose_name="Réduction appliquée (FCFA)"
    )
    commission_amount = models.PositiveIntegerField(
        default=500,
        verbose_name="Commission gagnée (FCFA)"
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="PENDING",
        db_index=True,
        verbose_name="Statut de la commission"
    )
    paid_out_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Reversé le"
    )
    payout_reference = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Réf. virement MoMo / Chèque"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Date de parrainage"
    )

    class Meta:
        verbose_name = "Vente / Commission Ambassadeur"
        verbose_name_plural = "Ventes / Commissions Ambassadeurs"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Vente {self.ambassador.code} - {self.commission_amount} FCFA [{self.status}]"
