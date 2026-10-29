"""
Modèles du Pôle Urologie & Néphrologie.
Prise en charge des pathologies de l'appareil urinaire et de l'appareil génital masculin :
antécédents urologiques, bilans urodynamiques quantitatifs chiffrés (Qmax, capacité vésicale, RPM)
et comptes-rendus d'interventions spécialisées (Endoscopie, Lithotripsie, Résections).
"""

from datetime import date
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import AuditableModel, CustomUser, Patient, UserRole


class UrologicalHistory(AuditableModel):
    """Antécédents urologiques et rénaux chroniques du patient."""

    patient = models.OneToOneField(
        Patient,
        on_delete=models.CASCADE,
        related_name="urological_history",
        verbose_name="Patient (DPI)",
    )
    has_urolithiasis_history = models.BooleanField(
        default=False, verbose_name="Antécédent de lithiase urinaire (calculs)"
    )
    stone_composition = models.CharField(
        max_length=100, blank=True, verbose_name="Nature des calculs connus (Oxalate, Acide urique, etc.)"
    )
    has_bph = models.BooleanField(
        default=False, verbose_name="Hypertrophie Bénigne de la Prostate (HBP)"
    )
    prostate_volume_cc = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True, verbose_name="Volume prostatique échographique (cc)"
    )
    macroscopic_hematuria = models.BooleanField(
        default=False, verbose_name="Antécédent d'hématurie macroscopique"
    )
    urinary_incontinence = models.CharField(
        max_length=80,
        blank=True,
        verbose_name="Type d'incontinence (Effort, Urgenturie, Mixte)",
    )
    recurrent_uti = models.BooleanField(
        default=False, verbose_name="Infections urinaires récidivantes (> 3 / an)"
    )
    baseline_creatinine_micromol_l = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True, verbose_name="Créatininémie de base (µmol/L)"
    )
    baseline_egfr_ml_min = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True, verbose_name="DFG estimé (CKD-EPI mL/min/1.73m²)"
    )

    class Meta:
        verbose_name = "Historique Urologique"
        verbose_name_plural = "Historiques Urologiques"

    def __str__(self) -> str:
        return f"Historique Uro - {self.patient.last_name}"


class UrodynamicAssessment(AuditableModel):
    """
    Bilan Urodynamique (BUD) chiffré complet.
    Débitmétrie libre, cystomanométrie et profilométrie pression-débit.
    """

    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name="urodynamic_assessments",
        verbose_name="Patient (DPI)",
    )
    urologist = models.ForeignKey(
        CustomUser,
        on_delete=models.PROTECT,
        limit_choices_to={"role__in": [UserRole.MEDECIN, UserRole.CHIRURGIEN]},
        related_name="urodynamic_assessments",
        verbose_name="Médecin Urologue",
    )
    assessment_date = models.DateField(default=date.today, verbose_name="Date de réalisation du bilan")
    clinical_indication = models.CharField(max_length=200, verbose_name="Indication du BUD")

    # Débitmétrie chiffrée
    qmax_flow_rate_ml_s = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        verbose_name="Débit mictionnel maximal Qmax (mL/s)",
        help_text="Valeur pathologique usuelle si < 15 mL/s pour volume > 150 mL",
    )
    voided_volume_ml = models.PositiveIntegerField(
        verbose_name="Volume uriné / mictionné (mL)"
    )
    post_void_residual_ml = models.PositiveIntegerField(
        default=0,
        verbose_name="Résidu Post-Mictionnel (RPM en mL)",
        help_text="Mesuré par échographie ou sondage aller-retour post-miction",
    )

    # Cystomanométrie
    maximum_cystometric_capacity_ml = models.PositiveIntegerField(
        verbose_name="Capacité Vésicale Maximale (CVM en mL)",
        help_text="Capacité physiologique normale : 350 - 500 mL",
    )
    pdet_qmax_cmh2o = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        null=True,
        blank=True,
        verbose_name="Pression détrusorienne à Qmax (cmH2O)",
    )
    uninhibited_detrusor_contractions = models.BooleanField(
        default=False, verbose_name="Contractions involontaires du détrusor (Hyperactivité vésicale)"
    )
    compliance_normal = models.BooleanField(
        default=True, verbose_name="Compliance vésicale normale"
    )
    conclusion_diagnosis = models.TextField(
        verbose_name="Conclusion diagnostique et conduite à tenir"
    )

    class Meta:
        verbose_name = "Bilan Urodynamique (BUD)"
        verbose_name_plural = "Bilans Urodynamiques (BUD)"
        ordering = ["-assessment_date"]

    def __str__(self) -> str:
        return f"BUD {self.patient.last_name} (Qmax: {self.qmax_flow_rate_ml_s} mL/s, RPM: {self.post_void_residual_ml} mL)"

    def clean(self) -> None:
        super().clean()
        if self.voided_volume_ml is not None and self.maximum_cystometric_capacity_ml is not None:
            if self.voided_volume_ml > self.maximum_cystometric_capacity_ml + self.post_void_residual_ml:
                raise ValidationError(
                    "Le volume mictionné ne peut pas être significativement supérieur à la capacité vésicale maximale mesurée."
                )


class UrologicalInterventionType(models.TextChoices):
    CYSTOSCOPIE = "CYSTOSCOPIE", "Cystoscopie diagnostique / biopsie vésicale"
    URETEROSCOPIE_SOUPLE = "URETEROSCOPIE_SOUPLE", "Urétérorénoscopie souple (URSS) laser"
    LITHOTRIPSIE = "LITHOTRIPSIE", "Lithotripsie Extracorporelle (LEC)"
    RESECTION_PROSTATE = "RESECTION_PROSTATE", "Résection Transurétrale de Prostate (RTUP / Laser Enucleation)"
    NEPHRECTOMIE = "NEPHRECTOMIE", "Néphrectomie (partielle ou totale)"
    AUTRE = "AUTRE", "Autre geste urologique spécialisé"


class SpecializedInterventionReport(AuditableModel):
    """
    Compte-rendu d'actes et d'interventions spécialisées d'urologie.
    Suivi matériel (pose de sondes JJ, extraction de lithiases).
    """

    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name="urological_interventions",
        verbose_name="Patient (DPI)",
    )
    surgeon = models.ForeignKey(
        CustomUser,
        on_delete=models.PROTECT,
        limit_choices_to={"role__in": [UserRole.CHIRURGIEN, UserRole.MEDECIN]},
        related_name="performed_urological_interventions",
        verbose_name="Chirurgien Urologue",
    )
    intervention_date = models.DateField(default=date.today, verbose_name="Date de l'acte")
    intervention_type = models.CharField(
        max_length=35,
        choices=UrologicalInterventionType.choices,
        default=UrologicalInterventionType.CYSTOSCOPIE,
        verbose_name="Type d'acte urologique",
    )
    double_j_stent_inserted = models.BooleanField(
        default=False, verbose_name="Pose de sonde double J (JJ)"
    )
    stent_side = models.CharField(
        max_length=15,
        blank=True,
        choices=[("DROITE", "Droite"), ("GAUCHE", "Gauche"), ("BILATERAL", "Bilatérale")],
        verbose_name="Côté d'implantation de la sonde JJ",
    )
    stent_removal_scheduled_date = models.DateField(
        null=True, blank=True, verbose_name="Date limite prévue pour l'ablation de sonde JJ"
    )
    stone_fragmentation_method = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Méthode de fragmentation (ex: Laser Holmium, Ultrasons, LEC)",
    )
    stone_size_mm = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="Taille maximale du calcul traité (mm)"
    )
    postop_drainage = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Drainage postopératoire (Sonde vésicale à demeure, sonde 3 voies, etc.)",
    )
    operative_notes = models.TextField(verbose_name="Compte-rendu technique détaillé de l'intervention")

    class Meta:
        verbose_name = "Compte-Rendu d'Intervention Urologique"
        verbose_name_plural = "Comptes-Rendus d'Interventions Urologiques"
        ordering = ["-intervention_date"]

    def __str__(self) -> str:
        return f"{self.get_intervention_type_display()} - {self.patient.last_name} ({self.intervention_date.strftime('%d/%m/%Y')})"

    def clean(self) -> None:
        super().clean()
        if self.double_j_stent_inserted and not self.stent_side:
            raise ValidationError(
                {"stent_side": "Veuillez préciser le côté (Droite, Gauche ou Bilatérale) lors de la pose d'une sonde JJ."}
            )

