"""
Formulaires Django du socle transversal (Core).
Intègrent la validation automatique des règles métier : anti-collision de rendez-vous,
validation d'admission hospitalière et verrouillage des permutations de gardes.
"""

from django import forms
from .models import (
    Patient,
    Appointment,
    Bed,
    Hospitalization,
    DutyShift,
    ShiftReplacement,
    CustomUser,
    Department,
    UserRole,
)


class PatientForm(forms.ModelForm):
    class Meta:
        model = Patient
        fields = [
            "nir",
            "last_name",
            "first_name",
            "maiden_name",
            "birth_date",
            "gender",
            "blood_group",
            "known_allergies",
            "major_medical_history",
            "ongoing_treatments",
            "trusted_person_name",
            "trusted_person_phone",
            "phone",
            "email",
        ]
        widgets = {
            "birth_date": forms.DateInput(attrs={"type": "date", "class": "form-input rounded-md border-gray-300 shadow-sm"}),
            "known_allergies": forms.Textarea(attrs={"rows": 2, "class": "form-textarea rounded-md border-gray-300 shadow-sm"}),
            "major_medical_history": forms.Textarea(attrs={"rows": 2, "class": "form-textarea rounded-md border-gray-300 shadow-sm"}),
            "ongoing_treatments": forms.Textarea(attrs={"rows": 2, "class": "form-textarea rounded-md border-gray-300 shadow-sm"}),
        }


class AppointmentForm(forms.ModelForm):
    class Meta:
        model = Appointment
        fields = [
            "patient",
            "practitioner",
            "department",
            "start_datetime",
            "end_datetime",
            "reason",
            "status",
            "clinical_notes",
        ]
        widgets = {
            "start_datetime": forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-input rounded-md border-gray-300"}),
            "end_datetime": forms.DateTimeInput(attrs={"type": "datetime-local", "class": "form-input rounded-md border-gray-300"}),
            "clinical_notes": forms.Textarea(attrs={"rows": 3, "class": "form-textarea rounded-md border-gray-300"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Limiter le choix des praticiens aux médecins et chirurgiens
        self.fields["practitioner"].queryset = CustomUser.objects.filter(
            role__in=[UserRole.MEDECIN, UserRole.CHIRURGIEN, UserRole.SAGE_FEMME]
        )


class HospitalizationForm(forms.ModelForm):
    class Meta:
        model = Hospitalization
        fields = [
            "patient",
            "bed",
            "admission_date",
            "expected_discharge_date",
            "actual_discharge_date",
            "admission_reason",
            "entry_diagnosis",
        ]
        widgets = {
            "admission_date": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "expected_discharge_date": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "actual_discharge_date": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "admission_reason": forms.Textarea(attrs={"rows": 2}),
        }


class DutyShiftForm(forms.ModelForm):
    class Meta:
        model = DutyShift
        fields = [
            "staff_member",
            "department",
            "shift_date",
            "shift_type",
            "start_time",
            "end_time",
            "is_cancelled",
        ]
        widgets = {
            "shift_date": forms.DateInput(attrs={"type": "date"}),
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
        }


class ShiftReplacementForm(forms.ModelForm):
    class Meta:
        model = ShiftReplacement
        fields = [
            "duty_shift",
            "original_caregiver",
            "substitute_caregiver",
            "reason",
        ]
        widgets = {
            "reason": forms.Textarea(attrs={"rows": 3}),
        }

