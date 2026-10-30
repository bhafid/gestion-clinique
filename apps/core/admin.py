"""
Administration Django pour le socle transversal (Core).
Interface sécurisée avec filtres avancés, badges de statuts et audit trails.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.core.exceptions import PermissionDenied
from django.utils.html import format_html

from .models import (
    Appointment,
    AuditActionType,
    Bed,
    BedStatus,
    CustomUser,
    Department,
    DutyShift,
    Hospitalization,
    HospitalizationStatus,
    Patient,
    PatientStatusConfig,
    PatientStatusHistory,
    SecurityAuditLog,
    ShiftReplacement,
    ShiftReplacementStatus,
    UserRole,
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


@admin.register(PatientStatusConfig)
class PatientStatusConfigAdmin(admin.ModelAdmin):
    list_display = [
        "display_order",
        "code",
        "label",
        "color_badge_preview",
        "is_terminal",
        "is_active",
        "is_system_default",
    ]
    list_display_links = ["code", "label"]
    list_editable = ["display_order", "is_active"]
    list_filter = ["is_active", "is_terminal", "color_theme"]
    search_fields = ["code", "label", "description"]

    def color_badge_preview(self, obj: PatientStatusConfig) -> str:
        return format_html(
            '<span style="padding: 4px 10px; border-radius: 9999px; font-weight: bold; background: {}; color: white;">● {}</span>',
            obj.hex_color or "#0284C7",
            obj.label,
        )
    color_badge_preview.short_description = "Aperçu Badge"


class PatientStatusHistoryInline(admin.TabularInline):
    model = PatientStatusHistory
    extra = 0
    can_delete = False
    readonly_fields = ["changed_at", "old_status", "new_status", "changed_by", "comment"]
    verbose_name = "Historique de Changement de Statut"
    verbose_name_plural = "Historique des Changements de Statut (Traçabilité HDS)"

    def has_add_permission(self, request, obj=None) -> bool:
        return False


@admin.register(PatientStatusHistory)
class PatientStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ["changed_at", "patient", "old_status", "new_status_badge", "changed_by", "comment"]
    list_filter = ["new_status", "old_status", "changed_at", "changed_by__role"]
    search_fields = ["patient__last_name", "patient__first_name", "patient__ipp", "changed_by__username", "comment"]
    readonly_fields = ["patient", "old_status", "new_status", "changed_by", "comment", "changed_at"]
    date_hierarchy = "changed_at"

    def new_status_badge(self, obj: PatientStatusHistory) -> str:
        return format_html(
            '<span style="padding: 3px 9px; border-radius: 9999px; font-weight: bold; background: {}; color: white;">{}</span>',
            obj.new_status.hex_color if obj.new_status else "#64748B",
            obj.new_status.label if obj.new_status else "-",
        )
    new_status_badge.short_description = "Nouveau Statut"


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = [
        "ipp",
        "last_name",
        "first_name",
        "birth_date",
        "gender",
        "blood_group",
        "current_status_badge",
        "status_updated_at",
        "nir_masked",
        "consent_pdf_button",
    ]
    list_filter = ["current_status", "blood_group", "gender", "created_at"]
    search_fields = ["ipp", "last_name", "first_name", "nir", "email"]
    readonly_fields = ["ipp", "status_updated_at", "created_at", "updated_at"]
    inlines = [PatientStatusHistoryInline]

    def consent_pdf_button(self, obj: Patient) -> str:
        if not obj.pk:
            return "-"
        return format_html(
            '<a href="/core/patients/{}/consent-pdf/" target="_blank" '
            'style="padding: 4px 8px; border-radius: 6px; font-weight: bold; background: #0c4a6e; color: white; text-decoration: none; font-size: 11px;">'
            '📄 Consentement PDF</a>',
            obj.pk,
        )
    consent_pdf_button.short_description = "Consentement & Décharge"

    def current_status_badge(self, obj: Patient) -> str:
        if not obj.current_status:
            return "-"
        return format_html(
            '<span style="padding: 4px 10px; border-radius: 9999px; font-weight: bold; background: {}; color: white;">● {}</span>',
            obj.current_status.hex_color or "#0284C7",
            obj.current_status.label,
        )
    current_status_badge.short_description = "Statut Actuel"

    def nir_masked(self, obj: Patient) -> str:
        """Masquage HDS/RGPD du numéro de sécurité sociale dans les listes."""
        if obj.nir and len(obj.nir) >= 5:
            return f"{obj.nir[:3]}*****{obj.nir[-2:]}"
        return "-"
    nir_masked.short_description = "NIR (Sécurisé)"

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if getattr(request.user, "role", None) == UserRole.GESTIONNAIRE_ADMISSION:
            # Allergies vitales en lecture seule uniquement (sécurité placement lit)
            if "known_allergies" not in ro:
                ro.append("known_allergies")
        return ro

    def get_exclude(self, request, obj=None):
        excluded = list(super().get_exclude(request, obj) or [])
        if getattr(request.user, "role", None) == UserRole.GESTIONNAIRE_ADMISSION:
            # Secret médical strict : Aucun accès aux antécédents médicaux ni aux traitements/prescriptions
            for field_name in ("major_medical_history", "ongoing_treatments"):
                if field_name not in excluded:
                    excluded.append(field_name)
        return excluded

    def has_delete_permission(self, request, obj=None) -> bool:
        if getattr(request.user, "role", None) == UserRole.GESTIONNAIRE_ADMISSION:
            return False
        return super().has_delete_permission(request, obj)

    def delete_view(self, request, object_id, extra_context=None):
        if getattr(request.user, "role", None) == UserRole.GESTIONNAIRE_ADMISSION:
            patient = Patient.objects.filter(pk=object_id).first()
            SecurityAuditLog.log_action(
                user=request.user,
                action_type=AuditActionType.DELETE_ATTEMPT,
                patient=patient,
                resource_name="Patient (DPI)",
                details=f"Tentative interdite de suppression du dossier patient ID={object_id}",
                ip_address=request.META.get("REMOTE_ADDR"),
            )
            raise PermissionDenied("Sécurité HDS : Suppression de dossier patient strictement interdite pour ce rôle.")
        return super().delete_view(request, object_id, extra_context)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if object_id and request.method == "GET" and request.user.is_authenticated:
            patient = Patient.objects.filter(pk=object_id).first()
            if patient:
                SecurityAuditLog.log_action(
                    user=request.user,
                    action_type=AuditActionType.READ,
                    patient=patient,
                    resource_name="Patient (DPI Administratif)",
                    details=f"Consultation du dossier patient {patient.ipp}",
                    ip_address=request.META.get("REMOTE_ADDR"),
                )
        return super().changeform_view(request, object_id, form_url, extra_context)

    def save_model(self, request, obj: Patient, form, change) -> None:
        old_status = None
        if change and obj.pk:
            prev = Patient.objects.filter(pk=obj.pk).select_related("current_status").first()
            if prev:
                old_status = prev.current_status

        if not change or old_status != obj.current_status:
            from django.utils import timezone
            obj.status_updated_at = timezone.now()

        super().save_model(request, obj, form, change)

        SecurityAuditLog.log_action(
            user=request.user,
            action_type=AuditActionType.UPDATE if change else AuditActionType.CREATE,
            patient=obj,
            resource_name="Patient (DPI Administratif)",
            details=f"{'Mise à jour' if change else 'Création'} du dossier administratif patient {obj.ipp}",
            ip_address=request.META.get("REMOTE_ADDR"),
        )

        if obj.current_status and (not change or old_status != obj.current_status):
            PatientStatusHistory.objects.create(
                patient=obj,
                old_status=old_status,
                new_status=obj.current_status,
                changed_by=request.user,
                comment="Modification depuis le portail d'administration DPI",
            )


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

    def has_add_permission(self, request) -> bool:
        if getattr(request.user, "role", None) == UserRole.GESTIONNAIRE_ADMISSION:
            return False
        return super().has_add_permission(request)

    def has_change_permission(self, request, obj=None) -> bool:
        if getattr(request.user, "role", None) == UserRole.GESTIONNAIRE_ADMISSION:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None) -> bool:
        if getattr(request.user, "role", None) == UserRole.GESTIONNAIRE_ADMISSION:
            return False
        return super().has_delete_permission(request, obj)

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
    list_display = [
        "patient",
        "bed",
        "practitioner",
        "admission_date",
        "expected_discharge_date",
        "actual_discharge_date",
        "status_badge",
        "consent_pdf_button",
    ]
    list_filter = ["status", "bed__service"]
    search_fields = ["patient__last_name", "patient__ipp", "admission_reason"]
    date_hierarchy = "admission_date"

    def consent_pdf_button(self, obj: Hospitalization) -> str:
        if not obj.pk:
            return "-"
        return format_html(
            '<a href="/core/admissions/{}/consent-pdf/" target="_blank" '
            'style="padding: 4px 8px; border-radius: 6px; font-weight: bold; background: #0c4a6e; color: white; text-decoration: none; font-size: 11px;">'
            '📄 Consentement PDF</a>',
            obj.pk,
        )
    consent_pdf_button.short_description = "Consentement & Décharge"

    def get_exclude(self, request, obj=None):
        excluded = list(super().get_exclude(request, obj) or [])
        if getattr(request.user, "role", None) == UserRole.GESTIONNAIRE_ADMISSION:
            # Secret médical strict : Aucun accès au diagnostic médical d'entrée
            if "entry_diagnosis" not in excluded:
                excluded.append("entry_diagnosis")
        return excluded

    def get_readonly_fields(self, request, obj=None):
        ro = list(super().get_readonly_fields(request, obj))
        if getattr(request.user, "role", None) == UserRole.GESTIONNAIRE_ADMISSION and obj is not None:
            # Lecture seule sur le motif d'admission générique et le médecin référent durant le séjour
            for field_name in ("admission_reason", "practitioner"):
                if field_name not in ro:
                    ro.append(field_name)
        return ro

    def has_delete_permission(self, request, obj=None) -> bool:
        if getattr(request.user, "role", None) == UserRole.GESTIONNAIRE_ADMISSION:
            return False
        return super().has_delete_permission(request, obj)

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        if object_id and request.method == "GET" and request.user.is_authenticated:
            hosp = Hospitalization.objects.select_related("patient").filter(pk=object_id).first()
            if hosp:
                SecurityAuditLog.log_action(
                    user=request.user,
                    action_type=AuditActionType.READ,
                    patient=hosp.patient,
                    resource_name="Hospitalization",
                    details=f"Consultation du séjour hospitalier #{hosp.id} (Lit: {hosp.bed})",
                    ip_address=request.META.get("REMOTE_ADDR"),
                )
        return super().changeform_view(request, object_id, form_url, extra_context)

    def save_model(self, request, obj: Hospitalization, form, change) -> None:
        super().save_model(request, obj, form, change)
        SecurityAuditLog.log_action(
            user=request.user,
            action_type=AuditActionType.UPDATE if change else AuditActionType.CREATE,
            patient=obj.patient,
            resource_name="Hospitalization",
            details=f"{'Modification / Transfert / Sortie' if change else 'Création admission'} séjour #{obj.id} (Lit: {obj.bed})",
            ip_address=request.META.get("REMOTE_ADDR"),
        )

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


@admin.register(SecurityAuditLog)
class SecurityAuditLogAdmin(admin.ModelAdmin):
    list_display = ["timestamp", "user", "action_type", "patient_ipp", "patient", "resource_name", "ip_address", "details"]
    list_filter = ["action_type", "resource_name", "timestamp", "user__role"]
    search_fields = ["user__username", "patient_ipp", "patient__last_name", "details"]
    readonly_fields = ["timestamp", "user", "patient", "patient_ipp", "action_type", "resource_name", "details", "ip_address"]
    date_hierarchy = "timestamp"

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


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

