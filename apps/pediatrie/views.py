from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView

from apps.core.models import UserRole
from .models import AnthropometricRecord, VaccinationRecord


def user_has_pediatrie_role(user):
    return user.is_authenticated and (
        user.is_superuser or user.role in [UserRole.ADMIN, UserRole.MEDECIN, UserRole.INFIRMIER, UserRole.SAGE_FEMME]
    )


class RoleRequiredMixin(UserPassesTestMixin):
    """Mixin restricting access to pediatric roles (MEDECIN, INFIRMIER)."""
    def test_func(self):
        return user_has_pediatrie_role(self.request.user)

    def handle_no_permission(self):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied

# AnthropometricRecord Views
class AnthropometricRecordListView(LoginRequiredMixin, ListView):
    model = AnthropometricRecord
    template_name = "pediatrie/anthropometric_list.html"
    context_object_name = "records"
    paginate_by = 20
    ordering = ["-measurement_date"]

    def get_queryset(self):
        qs = super().get_queryset().select_related("patient", "recorded_by")
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(patient__last_name__icontains=q)
        return qs

class AnthropometricRecordCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    model = AnthropometricRecord
    fields = [
        "patient",
        "recorded_by",
        "measurement_date",
        "age_in_months",
        "weight_kg",
        "height_cm",
        "cranial_perimeter_cm",
        "clinical_observations",
    ]
    template_name = "pediatrie/anthropometric_form.html"

    def get_success_url(self):
        return reverse_lazy("pediatrie:anthro_detail", kwargs={"pk": self.object.pk})

class AnthropometricRecordDetailView(LoginRequiredMixin, DetailView):
    model = AnthropometricRecord
    template_name = "pediatrie/anthropometric_detail.html"
    context_object_name = "record"

class AnthropometricRecordUpdateView(LoginRequiredMixin, RoleRequiredMixin, UpdateView):
    model = AnthropometricRecord
    fields = [
        "measurement_date",
        "age_in_months",
        "weight_kg",
        "height_cm",
        "cranial_perimeter_cm",
        "clinical_observations",
    ]
    template_name = "pediatrie/anthropometric_form.html"

    def get_success_url(self):
        return reverse_lazy("pediatrie:anthro_detail", kwargs={"pk": self.object.pk})

class AnthropometricRecordDeleteView(LoginRequiredMixin, RoleRequiredMixin, DeleteView):
    model = AnthropometricRecord
    template_name = "pediatrie/anthropometric_confirm_delete.html"
    success_url = reverse_lazy("pediatrie:anthro_list")

# VaccinationRecord Views
class VaccinationRecordListView(LoginRequiredMixin, ListView):
    model = VaccinationRecord
    template_name = "pediatrie/vaccination_list.html"
    context_object_name = "vaccinations"
    paginate_by = 20
    ordering = ["-recommended_due_date"]

    def get_queryset(self):
        qs = super().get_queryset().select_related("patient", "administering_doctor")
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(vaccine_name__icontains=q)
        return qs

class VaccinationRecordCreateView(LoginRequiredMixin, RoleRequiredMixin, CreateView):
    model = VaccinationRecord
    fields = [
        "patient",
        "vaccine_name",
        "target_age_months",
        "recommended_due_date",
        "administration_date",
        "batch_number",
        "administering_doctor",
        "injection_site",
        "adverse_reactions",
    ]
    template_name = "pediatrie/vaccination_form.html"

    def get_success_url(self):
        return reverse_lazy("pediatrie:vaccination_detail", kwargs={"pk": self.object.pk})

class VaccinationRecordDetailView(LoginRequiredMixin, DetailView):
    model = VaccinationRecord
    template_name = "pediatrie/vaccination_detail.html"
    context_object_name = "vaccination"

class VaccinationRecordUpdateView(LoginRequiredMixin, RoleRequiredMixin, UpdateView):
    model = VaccinationRecord
    fields = [
        "administration_date",
        "batch_number",
        "administering_doctor",
        "injection_site",
        "adverse_reactions",
        "status",
    ]
    template_name = "pediatrie/vaccination_form.html"

    def get_success_url(self):
        return reverse_lazy("pediatrie:vaccination_detail", kwargs={"pk": self.object.pk})

class VaccinationRecordDeleteView(LoginRequiredMixin, RoleRequiredMixin, DeleteView):
    model = VaccinationRecord
    template_name = "pediatrie/vaccination_confirm_delete.html"
    success_url = reverse_lazy("pediatrie:vaccination_list")

