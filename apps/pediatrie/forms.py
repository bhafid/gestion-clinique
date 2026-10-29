from django import forms
from .models import AnthropometricRecord, VaccinationRecord

class AnthropometricRecordForm(forms.ModelForm):
    class Meta:
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
        widgets = {
            "measurement_date": forms.DateInput(attrs={"type": "date"}),
        }

class VaccinationRecordForm(forms.ModelForm):
    class Meta:
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
            "status",
        ]
        widgets = {
            "recommended_due_date": forms.DateInput(attrs={"type": "date"}),
            "administration_date": forms.DateInput(attrs={"type": "date"}),
        }

