from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView

from apps.core.models import AuditActionType, SecurityAuditLog, UserRole
from .models import SurgicalIntervention, SafetyChecklistOMS, OperativeReport


def user_has_chirurgien_or_medecin(user):
    return user.is_authenticated and (
        user.is_superuser or user.role in [UserRole.ADMIN, UserRole.CHIRURGIEN, UserRole.MEDECIN, UserRole.INFIRMIER]
    )


class RoleRequiredMixin(UserPassesTestMixin):
    """Mixin to restrict access to clinical surgical roles and deny administrative roles."""
    def test_func(self):
        return user_has_chirurgien_or_medecin(self.request.user)

    def handle_no_permission(self):
        from django.core.exceptions import PermissionDenied
        if self.request.user.is_authenticated:
            SecurityAuditLog.log_action(
                user=self.request.user,
                action_type=AuditActionType.ACCESS_DENIED,
                resource_name="Chirurgie / Bloc Opératoire",
                details=f"Tentative d'accès refusée (Secret Médical) sur {self.request.path}",
                ip_address=self.request.META.get("REMOTE_ADDR"),
            )
        raise PermissionDenied


class InterventionListView(LoginRequiredMixin, RoleRequiredMixin, ListView):
    model = SurgicalIntervention
    template_name = "chirurgie/intervention_list.html"
    context_object_name = "interventions"
    paginate_by = 20

    def get_queryset(self):
        qs = super().get_queryset().select_related("patient", "operating_room", "lead_surgeon")
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(procedure_name__icontains=q)
        return qs.order_by("-scheduled_start")


class InterventionCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    model = SurgicalIntervention
    fields = [
        "patient",
        "operating_room",
        "lead_surgeon",
        "anesthesiologist",
        "scheduled_start",
        "scheduled_end",
        "procedure_name",
        "surgical_indication",
        "priority",
        "status",
    ]
    template_name = "chirurgie/intervention_form.html"

    def get_success_url(self):
        return reverse_lazy("chirurgie:checklist_create", kwargs={"intervention_pk": self.object.pk})


class InterventionDetailView(LoginRequiredMixin, RoleRequiredMixin, DetailView):
    model = SurgicalIntervention
    template_name = "chirurgie/intervention_detail.html"
    context_object_name = "intervention"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["checklist"] = getattr(self.object, "safety_checklist", None)
        context["report"] = getattr(self.object, "operative_report", None)
        return context


class InterventionUpdateView(LoginRequiredMixin, RoleRequiredMixin, UpdateView):
    model = SurgicalIntervention
    fields = [
        "operating_room",
        "lead_surgeon",
        "anesthesiologist",
        "scheduled_start",
        "scheduled_end",
        "procedure_name",
        "surgical_indication",
        "priority",
        "status",
    ]
    template_name = "chirurgie/intervention_form.html"

    def get_success_url(self):
        return reverse_lazy("chirurgie:intervention_detail", kwargs={"pk": self.object.pk})


class InterventionDeleteView(LoginRequiredMixin, RoleRequiredMixin, DeleteView):
    model = SurgicalIntervention
    template_name = "chirurgie/intervention_confirm_delete.html"
    success_url = reverse_lazy("chirurgie:intervention_list")


class ChecklistCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    model = SafetyChecklistOMS
    fields = "__all__"
    template_name = "chirurgie/checklist_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.intervention = SurgicalIntervention.objects.get(pk=kwargs["intervention_pk"])
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.intervention = self.intervention
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("chirurgie:checklist_detail", kwargs={"pk": self.object.pk})


class ChecklistDetailView(LoginRequiredMixin, RoleRequiredMixin, DetailView):
    model = SafetyChecklistOMS
    template_name = "chirurgie/checklist_detail.html"
    context_object_name = "checklist"


class ReportCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    model = OperativeReport
    fields = "__all__"
    template_name = "chirurgie/report_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.intervention = SurgicalIntervention.objects.get(pk=kwargs["intervention_pk"])
        if self.intervention.status != "TERMINEE":
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied("Report can only be created after the intervention is marked TERMINEE.")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.intervention = self.intervention
        form.instance.author_surgeon = self.request.user
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("chirurgie:report_detail", kwargs={"pk": self.object.pk})


class ReportDetailView(LoginRequiredMixin, RoleRequiredMixin, DetailView):
    model = OperativeReport
    template_name = "chirurgie/report_detail.html"
    context_object_name = "report"

