"""
Administration Django pour le Pôle Pédiatrie.
Suivi des mesures anthropométriques et du calendrier vaccinal automatisé.
"""

from django.contrib import admin
from django.utils.html import format_html

from .models import AnthropometricRecord, VaccinationRecord, VaccineStatus


@admin.register(AnthropometricRecord)
class AnthropometricRecordAdmin(admin.ModelAdmin):
    list_display = ["patient", "measurement_date", "age_in_months", "weight_kg", "height_cm", "cranial_perimeter_cm", "body_mass_index"]
    list_filter = ["measurement_date"]
    search_fields = ["patient__last_name", "patient__first_name", "patient__ipp"]
    date_hierarchy = "measurement_date"


@admin.register(VaccinationRecord)
class VaccinationRecordAdmin(admin.ModelAdmin):
    list_display = [
        "patient",
        "vaccine_name",
        "target_age_months",
        "recommended_due_date",
        "administration_date",
        "batch_number",
        "status_badge",
    ]
    list_filter = ["status", "target_age_months", "recommended_due_date"]
    search_fields = ["patient__last_name", "patient__ipp", "vaccine_name", "batch_number"]
    date_hierarchy = "recommended_due_date"

    def status_badge(self, obj: VaccinationRecord) -> str:
        colors = {
            VaccineStatus.A_FAIRE: "#2563eb",
            VaccineStatus.EFFECTUE: "#10b981",
            VaccineStatus.EN_RETARD: "#dc2626",
            VaccineStatus.CONTRE_INDIQUE: "#6b7280",
        }
        color = colors.get(obj.status, "#6b7280")
        return format_html(
            '<span style="padding: 3px 8px; border-radius: 4px; font-weight: bold; background: {}; color: white;">{}</span>',
            color,
            obj.get_status_display(),
        )
    status_badge.short_description = "Statut vaccinal"

