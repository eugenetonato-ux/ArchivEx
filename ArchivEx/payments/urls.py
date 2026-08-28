from django.urls import path
from . import views

app_name = "payments"

urlpatterns = [
    path("<int:semester_id>/", views.pass_semestre, name="pass_semestre"),
    path("<int:semester_id>/payer/", views.initier_paiement, name="initier_paiement"),
    path("attente/<str:reference>/", views.payment_pending_view, name="payment_pending"),
    path("status/<str:reference>/", views.payment_status_api_view, name="payment_status_api"),
    path("historique/", views.student_payment_history_view, name="student_history"),
    path("webhook/sebpay/", views.sebpay_webhook_view, name="sebpay_webhook"),
]