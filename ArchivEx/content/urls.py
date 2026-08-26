from django.urls import path
from . import views

app_name = "content"

urlpatterns = [
    path("resumes/", views.summary_list, name="summary_list"),
    path("resumes/<int:pk>/", views.summary_detail, name="summary_detail"),
    path("guides/", views.guide_list, name="guide_list"),
    path("guides/<int:pk>/", views.guide_detail, name="guide_detail"),
    path("conseils/", views.article_list, name="article_list"),
    path("conseils/<int:pk>/", views.article_detail, name="article_detail"),
]
