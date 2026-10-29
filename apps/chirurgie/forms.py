from django import forms
from .models import SurgicalIntervention, SafetyChecklistOMS, OperativeReport


class SurgicalInterventionForm(forms.ModelForm):
    class Meta:
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
        widgets = {
            "scheduled_start": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "scheduled_end": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }


class SafetyChecklistOMSForm(forms.ModelForm):
    class Meta:
        model = SafetyChecklistOMS
        fields = "__all__"
        exclude = ["intervention"]


class OperativeReportForm(forms.ModelForm):
    class Meta:
        model = OperativeReport
        fields = "__all__"
        exclude = ["intervention", "author_surgeon"]

