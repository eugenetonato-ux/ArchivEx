from django.urls import path
from . import views

app_name = "payments"

urlpatterns = [
    path("<int:semester_id>/", views.pass_semestre, name="pass_semestre"),
    path("<int:semester_id>/payer/", views.initier_paiement, name="initier_paiement"),
    path("confirmation/<int:payment_id>/", views.confirmer_paiement, name="confirmer_paiement"),
]