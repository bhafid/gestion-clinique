from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView

from apps.core.models import AuditActionType, SecurityAuditLog, UserRole
from .models import UrologicalHistory, UrodynamicAssessment, SpecializedInterventionReport

def user_has_urologie_role(user):
    return user.is_authenticated and (
        user.is_superuser or user.role in [UserRole.ADMIN, UserRole.MEDECIN, UserRole.CHIRURGIEN]
    )

class RoleRequiredMixin(UserPassesTestMixin):
    """Mixin restricting access to urology roles (MEDECIN, CHIRURGIEN)."""
    def test_func(self):
        return user_has_urologie_role(self.request.user)

    def handle_no_permission(self):
        from django.core.exceptions import PermissionDenied
        if self.request.user.is_authenticated:
            SecurityAuditLog.log_action(
                user=self.request.user,
                action_type=AuditActionType.ACCESS_DENIED,
                resource_name="Urologie",
                details=f"Tentative d'accès refusée (Secret Médical) sur {self.request.path}",
                ip_address=self.request.META.get("REMOTE_ADDR"),
            )
        raise PermissionDenied

# UrologicalHistory Views
class UrologicalHistoryListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    model = UrologicalHistory
    template_name = "urologie/urologicalhistory_list.html"
    context_object_name = "histories"
    paginate_by = 20
    ordering = ["-patient__last_name"]

    def get_queryset(self):
        qs = super().get_queryset().select_related("patient")
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(patient__last_name__icontains=q)
        return qs

class UrologicalHistoryCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    model = UrologicalHistory
    fields = ["patient", "has_urolithiasis_history", "stone_composition", "has_bph", "prostate_volume_cc", "macroscopic_hematuria", "urinary_incontinence", "recurrent_uti", "baseline_creatinine_micromol_l", "baseline_egfr_ml_min"]
    template_name = "urologie/urologicalhistory_form.html"

    def get_success_url(self):
        return reverse_lazy("urologie:history_detail", kwargs={"pk": self.object.pk})

class UrologicalHistoryDetailView(LoginRequiredMixin, RoleRequiredMixin, DetailView):
    model = UrologicalHistory
    template_name = "urologie/urologicalhistory_detail.html"
    context_object_name = "history"

class UrologicalHistoryUpdateView(LoginRequiredMixin, RoleRequiredMixin, UpdateView):
    model = UrologicalHistory
    fields = ["has_urolithiasis_history", "stone_composition", "has_bph", "prostate_volume_cc", "macroscopic_hematuria", "urinary_incontinence", "recurrent_uti", "baseline_creatinine_micromol_l", "baseline_egfr_ml_min"]
    template_name = "urologie/urologicalhistory_form.html"

    def get_success_url(self):
        return reverse_lazy("urologie:history_detail", kwargs={"pk": self.object.pk})

class UrologicalHistoryDeleteView(LoginRequiredMixin, RoleRequiredMixin, DeleteView):
    model = UrologicalHistory
    template_name = "urologie/urologicalhistory_confirm_delete.html"
    success_url = reverse_lazy("urologie:history_list")

# UrodynamicAssessment Views
class UrodynamicAssessmentListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    model = UrodynamicAssessment
    template_name = "urologie/urodynamicassessment_list.html"
    context_object_name = "assessments"
    paginate_by = 20
    ordering = ["-assessment_date"]

    def get_queryset(self):
        qs = super().get_queryset().select_related("patient", "urologist")
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(clinical_indication__icontains=q)
        return qs

class UrodynamicAssessmentCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    model = UrodynamicAssessment
    fields = ["patient", "urologist", "assessment_date", "clinical_indication", "qmax_flow_rate_ml_s", "voided_volume_ml", "post_void_residual_ml", "maximum_cystometric_capacity_ml", "pdet_qmax_cmh2o", "uninhibited_detrusor_contractions", "compliance_normal", "conclusion_diagnosis"]
    template_name = "urologie/urodynamicassessment_form.html"

    def get_success_url(self):
        return reverse_lazy("urologie:assessment_detail", kwargs={"pk": self.object.pk})

class UrodynamicAssessmentDetailView(LoginRequiredMixin, RoleRequiredMixin, DetailView):
    model = UrodynamicAssessment
    template_name = "urologie/urodynamicassessment_detail.html"
    context_object_name = "assessment"

class UrodynamicAssessmentUpdateView(LoginRequiredMixin, RoleRequiredMixin, UpdateView):
    model = UrodynamicAssessment
    fields = ["assessment_date", "clinical_indication", "qmax_flow_rate_ml_s", "voided_volume_ml", "post_void_residual_ml", "maximum_cystometric_capacity_ml", "pdet_qmax_cmh2o", "uninhibited_detrusor_contractions", "compliance_normal", "conclusion_diagnosis"]
    template_name = "urologie/urodynamicassessment_form.html"

    def get_success_url(self):
        return reverse_lazy("urologie:assessment_detail", kwargs={"pk": self.object.pk})

class UrodynamicAssessmentDeleteView(LoginRequiredMixin, RoleRequiredMixin, DeleteView):
    model = UrodynamicAssessment
    template_name = "urologie/urodynamicassessment_confirm_delete.html"
    success_url = reverse_lazy("urologie:assessment_list")

# SpecializedInterventionReport Views
class SpecializedInterventionReportListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    model = SpecializedInterventionReport
    template_name = "urologie/specializedinterventionreport_list.html"
    context_object_name = "reports"
    paginate_by = 20
    ordering = ["-intervention_date"]

    def get_queryset(self):
        qs = super().get_queryset().select_related("patient", "surgeon")
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(intervention_type__icontains=q)
        return qs

class SpecializedInterventionReportCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    model = SpecializedInterventionReport
    fields = ["patient", "surgeon", "intervention_date", "intervention_type", "double_j_stent_inserted", "stent_side", "stent_removal_scheduled_date", "stone_fragmentation_method", "stone_size_mm", "postop_drainage", "operative_notes"]
    template_name = "urologie/specializedinterventionreport_form.html"

    def get_success_url(self):
        return reverse_lazy("urologie:intervention_detail", kwargs={"pk": self.object.pk})

class SpecializedInterventionReportDetailView(LoginRequiredMixin, RoleRequiredMixin, DetailView):
    model = SpecializedInterventionReport
    template_name = "urologie/specializedinterventionreport_detail.html"
    context_object_name = "report"

class SpecializedInterventionReportUpdateView(LoginRequiredMixin, RoleRequiredMixin, UpdateView):
    model = SpecializedInterventionReport
    fields = ["intervention_date", "intervention_type", "double_j_stent_inserted", "stent_side", "stent_removal_scheduled_date", "stone_fragmentation_method", "stone_size_mm", "postop_drainage", "operative_notes"]
    template_name = "urologie/specializedinterventionreport_form.html"

    def get_success_url(self):
        return reverse_lazy("urologie:intervention_detail", kwargs={"pk": self.object.pk})

class SpecializedInterventionReportDeleteView(LoginRequiredMixin, RoleRequiredMixin, DeleteView):
    model = SpecializedInterventionReport
    template_name = "urologie/specializedinterventionreport_confirm_delete.html"
    success_url = reverse_lazy("urologie:intervention_list")

