"""Routage pour le Pôle Pédiatrie."""
from django.urls import path
from . import views

app_name = "pediatrie"

urlpatterns = [
    # Anthropométrie
    path("anthropometry/", views.AnthropometricRecordListView.as_view(), name="anthro_list"),
    path("anthropometry/create/", views.AnthropometricRecordCreateView.as_view(), name="anthro_create"),
    path("anthropometry/<int:pk>/", views.AnthropometricRecordDetailView.as_view(), name="anthro_detail"),
    path("anthropometry/<int:pk>/update/", views.AnthropometricRecordUpdateView.as_view(), name="anthro_update"),
    path("anthropometry/<int:pk>/delete/", views.AnthropometricRecordDeleteView.as_view(), name="anthro_delete"),
    # Vaccinations
    path("vaccination/", views.VaccinationRecordListView.as_view(), name="vaccination_list"),
    path("vaccination/create/", views.VaccinationRecordCreateView.as_view(), name="vaccination_create"),
    path("vaccination/<int:pk>/", views.VaccinationRecordDetailView.as_view(), name="vaccination_detail"),
    path("vaccination/<int:pk>/update/", views.VaccinationRecordUpdateView.as_view(), name="vaccination_update"),
    path("vaccination/<int:pk>/delete/", views.VaccinationRecordDeleteView.as_view(), name="vaccination_delete"),
]

