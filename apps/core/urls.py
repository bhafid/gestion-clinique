"""Routage pour le socle transversal (Core) et Gestion Dynamique des Statuts Patients."""
from django.urls import path
from .views import (
    PatientListView,
    WeeklyDashboardView,
    admission_consent_pdf_view,
    api_patient_status_history_view,
    api_status_configs_view,
    patient_change_status_view,
    patient_consent_pdf_view,
    quick_bed_status_action_view,
    quick_replacement_validation_view,
    status_config_manage_view,
)

app_name = "core"

urlpatterns = [
    path("", WeeklyDashboardView.as_view(), name="weekly_dashboard"),
    path("dashboard/", WeeklyDashboardView.as_view(), name="dashboard"),

    # Actions rapides Cockpit Supervision (Lits & Remplacements de Garde)
    path("beds/<int:pk>/quick-status/", quick_bed_status_action_view, name="quick_bed_status"),
    path("replacements/<int:pk>/quick-validate/", quick_replacement_validation_view, name="quick_replacement_validate"),

    # Liste des Patients, Recherche & Gestion Dynamique des Statuts
    path("patients/", PatientListView.as_view(), name="patient_list"),
    path("patients/<int:pk>/change-status/", patient_change_status_view, name="patient_change_status"),
    path("patients/<int:pk>/consent-pdf/", patient_consent_pdf_view, name="patient_consent_pdf"),
    path("admissions/<int:pk>/consent-pdf/", admission_consent_pdf_view, name="admission_consent_pdf"),
    path("status-configs/manage/", status_config_manage_view, name="status_config_manage"),

    # Endpoints REST API JSON
    path("api/status-configs/", api_status_configs_view, name="api_status_configs"),
    path("api/patients/<int:pk>/status-history/", api_patient_status_history_view, name="api_patient_status_history"),
]

