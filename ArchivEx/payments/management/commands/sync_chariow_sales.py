import logging
import re
import requests
from django.core.management.base import BaseCommand
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from academics.models import Semester
from payments.models import Payment
from payments.services import _chariow_headers, activate_pass_for_payment

logger = logging.getLogger(__name__)
User = get_user_model()


class Command(BaseCommand):
    help = "Synchronise et réconcilie les ventes Chariow avec les paiements et abonnements ArchivEx."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sale-id",
            type=str,
            help="ID spécifique de vente Chariow à forcer (ex: SALE52OXEL0A0SCYBID)",
        )
        parser.add_argument(
            "--email",
            type=str,
            help="Email de l'utilisateur à réconcilier",
        )

    def handle(self, *args, **options):
        base_url = getattr(settings, "CHARIOW_BASE_URL", "https://api.chariow.com/v1").rstrip("/")
        headers = _chariow_headers()

        sale_id_arg = options.get("sale_id")
        email_arg = options.get("email")

        self.stdout.write(self.style.NOTICE("Interrogation de l'API Chariow..."))

        sales_to_process = []

        if sale_id_arg:
            res = requests.get(f"{base_url}/sales/{sale_id_arg}", headers=headers, timeout=20)
            if res.status_code == 200:
                data = res.json().get("data", {})
                sales_to_process.append(data)
            else:
                self.stdout.write(self.style.ERROR(f"Impossible de récupérer la vente {sale_id_arg} (HTTP {res.status_code})"))
                return
        else:
            res = requests.get(f"{base_url}/sales?per_page=50", headers=headers, timeout=20)
            if res.status_code == 200:
                sales_to_process = res.json().get("data", [])
            else:
                self.stdout.write(self.style.ERROR(f"Erreur API Chariow lors de la récupération des ventes : {res.status_code}"))
                return

        self.stdout.write(f"{len(sales_to_process)} vente(s) analysees depuis Chariow.")

        activated_count = 0

        for sale in sales_to_process:
            sale_id = sale.get("id")
            sale_status = sale.get("status")
            payment_obj = sale.get("payment") if isinstance(sale.get("payment"), dict) else {}
            pay_status = payment_obj.get("status")

            # On ne traite que les ventes confirmées
            if sale_status not in ["completed", "success"] and pay_status not in ["success", "completed"]:
                continue

            cust = sale.get("customer") or {}
            c_email = (cust.get("email") or "").strip().lower()
            c_phone = ""
            if isinstance(cust.get("phone"), dict):
                c_phone = str(cust.get("phone", {}).get("number", ""))
            elif cust.get("phone"):
                c_phone = str(cust.get("phone"))
            c_phone_clean = re.sub(r"[^\d]", "", c_phone)

            s_metadata = sale.get("custom_metadata") or {}
            ext_ref = s_metadata.get("external_reference") or sale.get("external_reference")

            # Filtrage par email si demandé
            if email_arg and c_email != email_arg.strip().lower():
                continue

            # Recherche d'un Payment existant
            payment = None
            if ext_ref:
                payment = Payment.objects.filter(external_reference=ext_ref).first()
            if not payment and sale_id:
                payment = Payment.objects.filter(chariow_sale_id=sale_id).first()

            if not payment and c_email:
                payment = Payment.objects.filter(
                    user__email__iexact=c_email,
                    status=Payment.STATUS_PENDING
                ).order_by("-created_at").first()

            if not payment and c_phone_clean:
                payment = Payment.objects.filter(
                    phone_number__endswith=c_phone_clean[-8:],
                    status=Payment.STATUS_PENDING
                ).order_by("-created_at").first()

            if payment:
                if not payment.is_approved:
                    payment.chariow_sale_id = str(sale_id)
                    payment.status = Payment.STATUS_APPROVED
                    payment.save(update_fields=["chariow_sale_id", "status"])
                    activate_pass_for_payment(payment)
                    activated_count += 1
                    self.stdout.write(self.style.SUCCESS(
                        f"Pass active pour {payment.user.email or payment.user.username} (Paiement {payment.external_reference}, Vente {sale_id})"
                    ))
                else:
                    self.stdout.write(self.style.WARNING(
                        f"Vente {sale_id} deja validee pour {payment.user.email or payment.user.username}."
                    ))
            else:
                # Aucun objet Payment trouvé en base : tentons de trouver l'utilisateur pour lui attribuer le pass
                matched_user = None
                if c_email:
                    matched_user = User.objects.filter(email__iexact=c_email).first()
                if not matched_user and c_phone_clean:
                    matched_user = User.objects.filter(username__iexact=c_email).first()

                if matched_user:
                    semester = Semester.objects.first()
                    if semester:
                        new_pay = Payment.objects.create(
                            user=matched_user,
                            semester=semester,
                            amount=sale.get("amount", {}).get("value", 3800) if isinstance(sale.get("amount"), dict) else 3800,
                            currency="XOF",
                            phone_number=c_phone_clean or "22900000000",
                            external_reference=f"CHARIOW-{sale_id}",
                            chariow_sale_id=str(sale_id),
                            status=Payment.STATUS_APPROVED,
                            paid_at=timezone.now(),
                        )
                        activate_pass_for_payment(new_pay)
                        activated_count += 1
                        self.stdout.write(self.style.SUCCESS(
                            f"Nouveau paiement cree et Pass active pour {matched_user.email or matched_user.username} (Vente {sale_id})"
                        ))
                else:
                    self.stdout.write(self.style.NOTICE(
                        f"Vente {sale_id} ({c_email}, {c_phone_clean}) confirmee sur Chariow mais aucun compte utilisateur local trouve."
                    ))

        self.stdout.write(self.style.SUCCESS(f"Termine : {activated_count} Pass active(s) avec succes."))
