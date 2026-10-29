"""
Administration Django pour le Pôle Urologie & Néphrologie.
Supervision des antécédents, bilans urodynamiques chiffrés et actes spécialisés.
"""

from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import (
    SpecializedInterventionReport,
    UrodynamicAssessment,
    UrologicalHistory,
    UrologicalInterventionType,
)


@admin.register(UrologicalHistory)
class UrologicalHistoryAdmin(admin.ModelAdmin):
    list_display = ["patient", "has_urolithiasis_history", "has_bph", "macroscopic_hematuria", "baseline_egfr_ml_min"]
    list_filter = ["has_urolithiasis_history", "has_bph", "macroscopic_hematuria"]
    search_fields = ["patient__last_name", "patient__first_name", "patient__ipp"]


@admin.register(UrodynamicAssessment)
class UrodynamicAssessmentAdmin(admin.ModelAdmin):
    list_display = [
        "patient",
        "assessment_date",
        "urologist",
        "qmax_flow_rate_ml_s",
        "voided_volume_ml",
        "post_void_residual_ml",
        "maximum_cystometric_capacity_ml",
        "qmax_status",
    ]
    list_filter = ["assessment_date", "urologist"]
    search_fields = ["patient__last_name", "patient__ipp", "clinical_indication"]
    date_hierarchy = "assessment_date"

    def qmax_status(self, obj: UrodynamicAssessment) -> str:
        if obj.qmax_flow_rate_ml_s and obj.qmax_flow_rate_ml_s < 15:
            return mark_safe('<span style="color: #dc2626; font-weight: bold;">⚠ Qmax abaissé (< 15 mL/s)</span>')
        return mark_safe('<span style="color: #10b981;">Qmax normal</span>')
    qmax_status.short_description = "Débitmétrie"


@admin.register(SpecializedInterventionReport)
class SpecializedInterventionReportAdmin(admin.ModelAdmin):
    list_display = [
        "intervention_type",
        "patient",
        "surgeon",
        "intervention_date",
        "double_j_stent_inserted",
        "stent_side",
        "stent_removal_scheduled_date",
    ]
    list_filter = ["intervention_type", "double_j_stent_inserted", "intervention_date"]
    search_fields = ["patient__last_name", "patient__ipp", "surgeon__last_name"]
    date_hierarchy = "intervention_date"

