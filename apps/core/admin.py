"""
Administration Django pour le socle transversal (Core).
Interface sécurisée avec filtres avancés, badges de statuts et audit trails.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html

from .models import (
    Appointment,
    Bed,
    BedStatus,
    CustomUser,
    Department,
    DutyShift,
    Hospitalization,
    HospitalizationStatus,
    Patient,
    ShiftReplacement,
    ShiftReplacementStatus,
)


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = ["username", "email", "last_name", "first_name", "role", "department", "license_number", "is_active"]
    list_filter = ["role", "department", "is_active", "is_staff"]
    search_fields = ["username", "last_name", "first_name", "email", "license_number"]
    fieldsets = UserAdmin.fieldsets + (
        ("Affectation Médicale & RBAC (HDS)", {"fields": ("role", "department", "license_number", "phone_number")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Affectation Médicale & RBAC (HDS)", {"fields": ("role", "department", "license_number", "phone_number")}),
    )

    def save_model(self, request, obj: CustomUser, form, change) -> None:
        super().save_model(request, obj, form, change)
        obj.sync_role_permissions()


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "building", "floor", "is_active"]
    list_filter = ["is_active", "building"]
    search_fields = ["name", "code"]


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ["ipp", "last_name", "first_name", "birth_date", "gender", "blood_group", "nir_masked", "created_at"]
    list_filter = ["blood_group", "gender", "created_at"]
    search_fields = ["ipp", "last_name", "first_name", "nir", "email"]
    readonly_fields = ["ipp", "created_at", "updated_at"]

    def nir_masked(self, obj: Patient) -> str:
        """Masquage HDS/RGPD du numéro de sécurité sociale dans les listes."""
        if obj.nir and len(obj.nir) >= 5:
            return f"{obj.nir[:3]}*****{obj.nir[-2:]}"
        return "-"
    nir_masked.short_description = "NIR (Sécurisé)"


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ["patient", "practitioner", "department", "start_datetime", "end_datetime", "reason", "status_badge"]
    list_filter = ["status", "department", "start_datetime"]
    search_fields = ["patient__last_name", "practitioner__last_name", "reason"]
    date_hierarchy = "start_datetime"

    def status_badge(self, obj: Appointment) -> str:
        colors = {
            "PLANIFIE": "blue",
            "CONFIRME": "green",
            "EN_COURS": "purple",
            "HONORE": "emerald",
            "ANNULE": "gray",
            "ABSENT": "red",
        }
        color = colors.get(obj.status, "gray")
        return format_html(
            '<span style="padding: 3px 8px; border-radius: 4px; font-weight: bold; background: {}; color: white;">{}</span>',
            color,
            obj.get_status_display(),
        )
    status_badge.short_description = "Statut"


@admin.register(Bed)
class BedAdmin(admin.ModelAdmin):
    list_display = ["__str__", "service", "room_number", "bed_number", "status_badge"]
    list_filter = ["status", "service"]
    search_fields = ["room_number", "bed_number", "service__name"]

    def status_badge(self, obj: Bed) -> str:
        colors = {
            BedStatus.DISPONIBLE: "#10b981",  # Vert
            BedStatus.OCCUPE: "#ef4444",      # Rouge
            BedStatus.NETTOYAGE: "#f59e0b",   # Orange
            BedStatus.MAINTENANCE: "#6b7280", # Gris
        }
        color = colors.get(obj.status, "#6b7280")
        return format_html(
            '<span style="padding: 4px 10px; border-radius: 9999px; font-weight: bold; background: {}; color: white;">{}</span>',
            color,
            obj.get_status_display(),
        )
    status_badge.short_description = "État du lit"


@admin.register(Hospitalization)
class HospitalizationAdmin(admin.ModelAdmin):
    list_display = ["patient", "bed", "admission_date", "expected_discharge_date", "actual_discharge_date", "status_badge"]
    list_filter = ["status", "bed__service"]
    search_fields = ["patient__last_name", "patient__ipp", "entry_diagnosis"]
    date_hierarchy = "admission_date"

    def status_badge(self, obj: Hospitalization) -> str:
        colors = {
            HospitalizationStatus.EN_COURS: "#2563eb",
            HospitalizationStatus.CLOTUREE: "#10b981",
            HospitalizationStatus.TRANSFEREE: "#8b5cf6",
        }
        color = colors.get(obj.status, "#6b7280")
        return format_html(
            '<span style="padding: 3px 8px; border-radius: 4px; font-weight: bold; background: {}; color: white;">{}</span>',
            color,
            obj.get_status_display(),
        )
    status_badge.short_description = "Statut Séjour"


@admin.register(DutyShift)
class DutyShiftAdmin(admin.ModelAdmin):
    list_display = ["shift_date", "staff_member", "department", "shift_type", "start_time", "end_time", "is_cancelled"]
    list_filter = ["shift_type", "department", "shift_date", "is_cancelled"]
    search_fields = ["staff_member__last_name", "staff_member__first_name", "department__name"]
    date_hierarchy = "shift_date"


@admin.register(ShiftReplacement)
class ShiftReplacementAdmin(admin.ModelAdmin):
    list_display = ["duty_shift", "original_caregiver", "substitute_caregiver", "status_badge", "created_at"]
    list_filter = ["status", "duty_shift__department"]
    search_fields = ["original_caregiver__last_name", "substitute_caregiver__last_name"]

    def status_badge(self, obj: ShiftReplacement) -> str:
        colors = {
            ShiftReplacementStatus.DEMANDE: "#f59e0b",
            ShiftReplacementStatus.VALIDE: "#10b981",
            ShiftReplacementStatus.REFUSE: "#ef4444",
            ShiftReplacementStatus.ANNULE: "#9ca3af",
        }
        color = colors.get(obj.status, "#6b7280")
        return format_html(
            '<span style="padding: 3px 8px; border-radius: 4px; font-weight: bold; background: {}; color: white;">{}</span>',
            color,
            obj.get_status_display(),
        )
    status_badge.short_description = "Statut Remplacement"

