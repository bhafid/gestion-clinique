"""Routage pour le Pôle Urologie & Néphrologie."""
from django.urls import path
from . import views

app_name = "urologie"

urlpatterns = [
    # UrologicalHistory
    path("history/", views.UrologicalHistoryListView.as_view(), name="history_list"),
    path("history/create/", views.UrologicalHistoryCreateView.as_view(), name="history_create"),
    path("history/<int:pk>/", views.UrologicalHistoryDetailView.as_view(), name="history_detail"),
    path("history/<int:pk>/update/", views.UrologicalHistoryUpdateView.as_view(), name="history_update"),
    path("history/<int:pk>/delete/", views.UrologicalHistoryDeleteView.as_view(), name="history_delete"),
    # UrodynamicAssessment
    path("assessment/", views.UrodynamicAssessmentListView.as_view(), name="assessment_list"),
    path("assessment/create/", views.UrodynamicAssessmentCreateView.as_view(), name="assessment_create"),
    path("assessment/<int:pk>/", views.UrodynamicAssessmentDetailView.as_view(), name="assessment_detail"),
    path("assessment/<int:pk>/update/", views.UrodynamicAssessmentUpdateView.as_view(), name="assessment_update"),
    path("assessment/<int:pk>/delete/", views.UrodynamicAssessmentDeleteView.as_view(), name="assessment_delete"),
    # SpecializedInterventionReport
    path("intervention/", views.SpecializedInterventionReportListView.as_view(), name="intervention_list"),
    path("intervention/create/", views.SpecializedInterventionReportCreateView.as_view(), name="intervention_create"),
    path("intervention/<int:pk>/", views.SpecializedInterventionReportDetailView.as_view(), name="intervention_detail"),
    path("intervention/<int:pk>/update/", views.SpecializedInterventionReportUpdateView.as_view(), name="intervention_update"),
    path("intervention/<int:pk>/delete/", views.SpecializedInterventionReportDeleteView.as_view(), name="intervention_delete"),
]


