"""
Administration Django pour le Pôle Gynécologie & Maternité.
Supervision des dossiers de suivi de grossesse, des consultations et du registre d'accouchements.
"""

from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import (
    DeliveryMode,
    DeliveryRegistry,
    GynecologicalHistory,
    PregnancyStatus,
    PregnancyTracking,
    RoutineConsultation,
)


@admin.register(GynecologicalHistory)
class GynecologicalHistoryAdmin(admin.ModelAdmin):
    list_display = ["patient", "gravidity", "parity", "previous_cesareans", "miscarriages", "rhesus_incompatibility_risk"]
    list_filter = ["rhesus_incompatibility_risk"]
    search_fields = ["patient__last_name", "patient__first_name", "patient__ipp"]


@admin.register(RoutineConsultation)
class RoutineConsultationAdmin(admin.ModelAdmin):
    list_display = ["patient", "practitioner", "consultation_date", "reason", "uterine_height_cm"]
    list_filter = ["consultation_date", "practitioner"]
    search_fields = ["patient__last_name", "patient__ipp", "reason"]
    date_hierarchy = "consultation_date"


@admin.register(PregnancyTracking)
class PregnancyTrackingAdmin(admin.ModelAdmin):
    list_display = ["patient", "last_menstrual_period", "estimated_due_date", "status_badge", "has_risks"]
    list_filter = ["status", "estimated_due_date"]
    search_fields = ["patient__last_name", "patient__ipp", "risk_factors"]
    date_hierarchy = "estimated_due_date"

    def status_badge(self, obj: PregnancyTracking) -> str:
        colors = {
            PregnancyStatus.EN_COURS: "#2563eb",
            PregnancyStatus.ACCOUCHEE: "#10b981",
            PregnancyStatus.INTERROMPUE: "#ef4444",
        }
        color = colors.get(obj.status, "#6b7280")
        return format_html(
            '<span style="padding: 3px 8px; border-radius: 4px; font-weight: bold; background: {}; color: white;">{}</span>',
            color,
            obj.get_status_display(),
        )
    status_badge.short_description = "Statut"

    def has_risks(self, obj: PregnancyTracking) -> str:
        if obj.risk_factors:
            return mark_safe('<span style="color: #dc2626; font-weight: bold;">⚠ Facteurs de risque</span>')
        return mark_safe('<span style="color: #10b981;">Grossesse physiologique</span>')
    has_risks.short_description = "Risque"


@admin.register(DeliveryRegistry)
class DeliveryRegistryAdmin(admin.ModelAdmin):
    list_display = [
        "patient",
        "delivery_datetime",
        "delivery_mode_badge",
        "infant_gender",
        "birth_weight_grams",
        "apgar_scores",
        "attending_obstetrician",
        "midwife",
    ]
    list_filter = ["delivery_mode", "infant_gender", "delivery_datetime"]
    search_fields = ["patient__last_name", "patient__ipp"]
    date_hierarchy = "delivery_datetime"

    def delivery_mode_badge(self, obj: DeliveryRegistry) -> str:
        colors = {
            DeliveryMode.VOIE_BASSE_SPONTANEE: "#10b981",
            DeliveryMode.VENTOUSE: "#f59e0b",
            DeliveryMode.FORCEPS: "#f97316",
            DeliveryMode.CESARIENNE_PROGRAMMEE: "#2563eb",
            DeliveryMode.CESARIENNE_URGENCE: "#dc2626",
        }
        color = colors.get(obj.delivery_mode, "#6b7280")
        return format_html(
            '<span style="padding: 3px 8px; border-radius: 4px; font-weight: bold; background: {}; color: white;">{}</span>',
            color,
            obj.get_delivery_mode_display(),
        )
    delivery_mode_badge.short_description = "Mode"

    def apgar_scores(self, obj: DeliveryRegistry) -> str:
        return f"{obj.apgar_1min} / {obj.apgar_5min} / {obj.apgar_10min or '-'}"
    apgar_scores.short_description = "APGAR (1'/5'/10')"

