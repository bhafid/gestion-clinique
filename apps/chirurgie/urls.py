"""Routage pour le Pôle Chirurgie."""
from django.urls import path
from . import views

app_name = "chirurgie"

urlpatterns = [
    # Interventions
    path("intervention/", views.InterventionListView.as_view(), name="intervention_list"),
    path("intervention/create/", views.InterventionCreateView.as_view(), name="intervention_create"),
    path("intervention/<int:pk>/", views.InterventionDetailView.as_view(), name="intervention_detail"),
    path("intervention/<int:pk>/update/", views.InterventionUpdateView.as_view(), name="intervention_update"),
    path("intervention/<int:pk>/delete/", views.InterventionDeleteView.as_view(), name="intervention_delete"),
    # Checklist
    path("checklist/<int:intervention_pk>/create/", views.ChecklistCreateView.as_view(), name="checklist_create"),
    path("checklist/<int:pk>/", views.ChecklistDetailView.as_view(), name="checklist_detail"),
    # Operative Report
    path("report/<int:intervention_pk>/create/", views.ReportCreateView.as_view(), name="report_create"),
    path("report/<int:pk>/", views.ReportDetailView.as_view(), name="report_detail"),
]

