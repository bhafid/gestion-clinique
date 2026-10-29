from django import forms
from .models import UrologicalHistory, UrodynamicAssessment, SpecializedInterventionReport

class UrologicalHistoryForm(forms.ModelForm):
    class Meta:
        model = UrologicalHistory
        fields = [
            "patient",
            "has_urolithiasis_history",
            "stone_composition",
            "has_bph",
            "prostate_volume_cc",
            "macroscopic_hematuria",
            "urinary_incontinence",
            "recurrent_uti",
            "baseline_creatinine_micromol_l",
            "baseline_egfr_ml_min",
        ]
        widgets = {
            # example: add date widgets if any date fields existed
        }

class UrodynamicAssessmentForm(forms.ModelForm):
    class Meta:
        model = UrodynamicAssessment
        fields = [
            "patient",
            "urologist",
            "assessment_date",
            "clinical_indication",
            "qmax_flow_rate_ml_s",
            "voided_volume_ml",
            "post_void_residual_ml",
            "maximum_cystometric_capacity_ml",
            "pdet_qmax_cmh2o",
            "uninhibited_detrusor_contractions",
            "compliance_normal",
            "conclusion_diagnosis",
        ]
        widgets = {
            "assessment_date": forms.DateInput(attrs={"type": "date"}),
        }

class SpecializedInterventionReportForm(forms.ModelForm):
    class Meta:
        model = SpecializedInterventionReport
        fields = [
            "patient",
            "surgeon",
            "intervention_date",
            "intervention_type",
            "double_j_stent_inserted",
            "stent_side",
            "stent_removal_scheduled_date",
            "stone_fragmentation_method",
            "stone_size_mm",
            "postop_drainage",
            "operative_notes",
        ]
        widgets = {
            "intervention_date": forms.DateInput(attrs={"type": "date"}),
            "stent_removal_scheduled_date": forms.DateInput(attrs={"type": "date"}),
        }

