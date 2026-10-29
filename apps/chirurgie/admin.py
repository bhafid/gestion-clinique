"""
Administration Django pour le Pôle Chirurgie & Bloc Opératoire.
Supervision du bloc opératoire, des interventions, de la checklist OMS et des CRO.
"""

from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import (
    InterventionStatus,
    OperativeReport,
    OperatingRoom,
    SafetyChecklistOMS,
    SurgicalIntervention,
    SurgicalPriority,
)


class SafetyChecklistOMSInline(admin.StackedInline):
    model = SafetyChecklistOMS
    can_delete = False
    max_num = 1
    verbose_name = "Checklist Sécurité OMS (Bloc)"
    verbose_name_plural = "Checklist Sécurité OMS (Bloc)"


class OperativeReportInline(admin.StackedInline):
    model = OperativeReport
    can_delete = False
    max_num = 1
    verbose_name = "Compte-Rendu Opératoire (CRO)"
    verbose_name_plural = "Compte-Rendu Opératoire (CRO)"


@admin.register(OperatingRoom)
class OperatingRoomAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "is_septic", "is_available"]
    list_filter = ["is_available", "is_septic"]
    search_fields = ["code", "name"]


@admin.register(SurgicalIntervention)
class SurgicalInterventionAdmin(admin.ModelAdmin):
    list_display = [
        "procedure_name",
        "patient",
        "operating_room",
        "lead_surgeon",
        "scheduled_start",
        "priority_badge",
        "status_badge",
        "checklist_status",
    ]
    list_filter = ["status", "priority", "operating_room", "scheduled_start"]
    search_fields = ["procedure_name", "patient__last_name", "patient__ipp", "lead_surgeon__last_name"]
    date_hierarchy = "scheduled_start"
    inlines = [SafetyChecklistOMSInline, OperativeReportInline]

    def priority_badge(self, obj: SurgicalIntervention) -> str:
        colors = {
            SurgicalPriority.PROGRAMMEE: "#2563eb",
            SurgicalPriority.URGENCE_RELATIVE: "#f59e0b",
            SurgicalPriority.URGENCE_VITALE: "#dc2626",
        }
        color = colors.get(obj.priority, "#6b7280")
        return format_html(
            '<span style="padding: 3px 8px; border-radius: 4px; font-weight: bold; background: {}; color: white;">{}</span>',
            color,
            obj.get_priority_display(),
        )
    priority_badge.short_description = "Priorité"

    def status_badge(self, obj: SurgicalIntervention) -> str:
        colors = {
            InterventionStatus.PLANIFIEE: "#6b7280",
            InterventionStatus.EN_SALLE: "#8b5cf6",
            InterventionStatus.EN_COURS: "#f59e0b",
            InterventionStatus.TERMINEE: "#10b981",
            InterventionStatus.ANNULEE: "#ef4444",
        }
        color = colors.get(obj.status, "#6b7280")
        return format_html(
            '<span style="padding: 3px 8px; border-radius: 4px; font-weight: bold; background: {}; color: white;">{}</span>',
            color,
            obj.get_status_display(),
        )
    status_badge.short_description = "Statut"

    def checklist_status(self, obj: SurgicalIntervention) -> str:
        if hasattr(obj, "safety_checklist") and obj.safety_checklist.is_fully_validated:
            return mark_safe('<span style="color: #10b981; font-weight: bold;">✔ OMS Validée</span>')
        return mark_safe('<span style="color: #ef4444; font-weight: bold;">⚠ OMS Incomplète</span>')
    checklist_status.short_description = "Checklist OMS"


@admin.register(SafetyChecklistOMS)
class SafetyChecklistOMSAdmin(admin.ModelAdmin):
    list_display = ["intervention", "is_fully_validated", "signin_completed_by", "timeout_completed_by", "signout_completed_by"]
    list_filter = ["is_fully_validated"]
    search_fields = ["intervention__procedure_name", "intervention__patient__last_name"]


@admin.register(OperativeReport)
class OperativeReportAdmin(admin.ModelAdmin):
    list_display = ["intervention", "author_surgeon", "report_date", "surgical_approach", "estimated_blood_loss_ml"]
    list_filter = ["report_date", "surgical_approach"]
    search_fields = ["intervention__procedure_name", "intervention__patient__last_name", "findings"]

