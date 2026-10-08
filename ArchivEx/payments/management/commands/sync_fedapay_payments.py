import logging
from django.core.management.base import BaseCommand
from payments.models import Payment
from payments.services import verify_and_sync_fedapay_transaction, activate_pass_for_payment

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Synchronise et valide automatiquement les transactions FedaPay en direct avec l'API."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reference",
            type=str,
            help="Référence externe spécifique à synchroniser",
        )
        parser.add_argument(
            "--tx-id",
            type=str,
            help="Identifiant de transaction FedaPay spécifique",
        )

    def handle(self, *args, **options):
        ref = options.get("reference")
        tx_id = options.get("tx_id")

        if ref:
            payments = Payment.objects.filter(external_reference=ref)
        elif tx_id:
            payments = Payment.objects.filter(fedapay_transaction_id=tx_id)
        else:
            # Traiter les paiements en attente et ceux approuvés sans SemesterAccess lié
            payments = Payment.objects.filter(
                fedapay_transaction_id__isnull=False
            ).exclude(fedapay_transaction_id="")

        self.stdout.write(f"Vérification de {payments.count()} paiements FedaPay...")

        activated_count = 0
        for p in payments:
            self.stdout.write(f"Traitement du paiement #{p.id} ({p.external_reference}, tx #{p.fedapay_transaction_id})...")
            
            # Si le paiement est déjà approuvé mais sans SemesterAccess lié
            if p.is_approved:
                if not p.semester_access:
                    self.stdout.write(f"  Paiement déjà approuvé mais non lié : activation en cours...")
                    activate_pass_for_payment(p)
                    activated_count += 1
                else:
                    self.stdout.write(f"  Paiement déjà approuvé et lié.")
                continue

            # Sinon, synchroniser avec l'API FedaPay
            res = verify_and_sync_fedapay_transaction(p)
            p.refresh_from_db()
            if p.is_approved:
                self.stdout.write(self.style.SUCCESS(f"  Paiement validé et Pass activé avec succès !"))
                activated_count += 1
            else:
                self.stdout.write(f"  Statut FedaPay actuel : {p.status} (résultat API: {res.get('status')})")

        self.stdout.write(self.style.SUCCESS(f"Synchronisation terminée. {activated_count} Pass activés."))
