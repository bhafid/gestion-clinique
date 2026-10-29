"""Routage pour le socle transversal (Core)."""
from django.urls import path
from .views import WeeklyDashboardView

app_name = "core"

urlpatterns = [
    path("", WeeklyDashboardView.as_view(), name="weekly_dashboard"),
    path("dashboard/", WeeklyDashboardView.as_view(), name="dashboard"),
]

