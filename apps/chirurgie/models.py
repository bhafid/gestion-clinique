"""
Modèles du Pôle Chirurgie & Bloc Opératoire.
Conforme aux standards de sécurité sanitaire : Gestion des salles de bloc,
planification des interventions, Checklist de Sécurité au Bloc Opératoire
normée OMS (Haute Autorité de Santé - HAS) et Compte-Rendu Opératoire (CRO).
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import AuditableModel, CustomUser, Patient, UserRole


class OperatingRoom(AuditableModel):
    """Salle d'intervention du bloc opératoire."""

    code = models.CharField(max_length=20, unique=True, verbose_name="Code salle")
    name = models.CharField(max_length=100, verbose_name="Désignation de la salle")
    is_septic = models.BooleanField(default=False, verbose_name="Salle dédiée septique")
    is_available = models.BooleanField(default=True, verbose_name="Opérationnelle")
    equipment_summary = models.TextField(blank=True, verbose_name="Équipements intégrés (Coloscopie, Laser, etc.)")

    class Meta:
        verbose_name = "Salle de Bloc Opératoire"
        verbose_name_plural = "Salles de Bloc Opératoire"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"Bloc {self.code} - {self.name}"


class SurgicalPriority(models.TextChoices):
    PROGRAMMEE = "PROGRAMMEE", "Chirurgie Programmée Régulée"
    URGENCE_RELATIVE = "URGENCE_RELATIVE", "Urgence Relative (< 6 heures)"
    URGENCE_VITALE = "URGENCE_VITALE", "Urgence Vitale Immédiate"


class InterventionStatus(models.TextChoices):
    PLANIFIEE = "PLANIFIEE", "Planifiée"
    EN_SALLE = "EN_SALLE", "Patient en salle d'opération"
    EN_COURS = "EN_COURS", "Intervention en cours"
    TERMINEE = "TERMINEE", "Intervention terminée / En SSPI"
    ANNULEE = "ANNULEE", "Intervention déprogrammée"


class SurgicalIntervention(AuditableModel):
    """
    Intervention chirurgicale planifiée ou urgente rattachée au DPI unique du patient.
    """

    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name="surgical_interventions",
        verbose_name="Patient (DPI)",
    )
    operating_room = models.ForeignKey(
        OperatingRoom,
        on_delete=models.PROTECT,
        related_name="interventions",
        verbose_name="Salle d'opération",
    )
    lead_surgeon = models.ForeignKey(
        CustomUser,
        on_delete=models.PROTECT,
        limit_choices_to={"role__in": [UserRole.CHIRURGIEN, UserRole.MEDECIN]},
        related_name="lead_surgeries",
        verbose_name="Chirurgien principal",
    )
    anesthesiologist = models.ForeignKey(
        CustomUser,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        limit_choices_to={"role__in": [UserRole.MEDECIN, UserRole.CHIRURGIEN]},
        related_name="anesthesia_surgeries",
        verbose_name="Médecin Anesthésiste-Réanimateur (MAR)",
    )
    scheduled_start = models.DateTimeField(verbose_name="Début d'intervention prévu")
    scheduled_end = models.DateTimeField(verbose_name="Fin d'intervention prévue")
    procedure_name = models.CharField(max_length=255, verbose_name="Intitulé de l'acte chirurgical")
    surgical_indication = models.TextField(verbose_name="Indication opératoire")
    priority = models.CharField(
        max_length=25,
        choices=SurgicalPriority.choices,
        default=SurgicalPriority.PROGRAMMEE,
        verbose_name="Niveau d'urgence",
    )
    status = models.CharField(
        max_length=20,
        choices=InterventionStatus.choices,
        default=InterventionStatus.PLANIFIEE,
        verbose_name="Statut opératoire",
    )

    class Meta:
        verbose_name = "Intervention Chirurgicale"
        verbose_name_plural = "Interventions Chirurgicales"
        ordering = ["scheduled_start"]

    def __str__(self) -> str:
        return f"{self.procedure_name} - {self.patient.last_name} ({self.scheduled_start.strftime('%d/%m/%Y %H:%M')})"

    def clean(self) -> None:
        super().clean()
        if self.scheduled_start and self.scheduled_end:
            if self.scheduled_end <= self.scheduled_start:
                raise ValidationError({"scheduled_end": "La fin d'intervention doit être postérieure au début."})

            # Anti-collision en salle de bloc
            if self.operating_room_id and self.status != InterventionStatus.ANNULEE:
                conflicts = (
                    SurgicalIntervention.objects.filter(operating_room=self.operating_room)
                    .exclude(id=self.id)
                    .exclude(status=InterventionStatus.ANNULEE)
                    .filter(
                        scheduled_start__lt=self.scheduled_end,
                        scheduled_end__gt=self.scheduled_start,
                    )
                )
                if conflicts.exists():
                    conf = conflicts.first()
                    raise ValidationError(
                        {
                            "operating_room": (
                                f"Conflit de salle : Le bloc {self.operating_room.code} est déjà réservé pour "
                                f"'{conf.procedure_name}' de {conf.scheduled_start.strftime('%H:%M')} à {conf.scheduled_end.strftime('%H:%M')}."
                            )
                        }
                    )


class SafetyChecklistOMS(AuditableModel):
    """
    Checklist de Sécurité au Bloc Opératoire (Norme OMS / HAS).
    Vérification obligatoire en 3 phases pour prévenir les événements indésirables graves (EIG).
    """

    intervention = models.OneToOneField(
        SurgicalIntervention,
        on_delete=models.CASCADE,
        related_name="safety_checklist",
        verbose_name="Intervention chirurgicale",
    )

    # ------------------ Phase 1 : SIGN-IN (Avant l'induction anesthésique) ------------------
    signin_patient_identity_confirmed = models.BooleanField(
        default=False, verbose_name="1. Identité du patient confirmée (Nom, Date de naissance, Bracelet)"
    )
    signin_site_marked = models.BooleanField(
        default=False, verbose_name="2. Site opératoire clairement marqué / ou non applicable"
    )
    signin_consent_verified = models.BooleanField(
        default=False, verbose_name="3. Consentement éclairé et dossier d'anesthésie vérifiés"
    )
    signin_allergy_risk_checked = models.BooleanField(
        default=False, verbose_name="4. Risque d'allergie vérifié et documenté"
    )
    signin_airway_risk_evaluated = models.BooleanField(
        default=False, verbose_name="5. Risque d'inhalation / intubation difficile évalué et matériel prêt"
    )
    signin_bleeding_risk_evaluated = models.BooleanField(
        default=False, verbose_name="6. Risque hémorragique évalué (> 500 mL) et abord veineux sécurisé"
    )
    signin_completed_by = models.CharField(
        max_length=120, blank=True, verbose_name="Sign-in validé par (Nom & Qualité)"
    )

    # ------------------ Phase 2 : TIME-OUT (Avant l'incision cutanée) ------------------
    timeout_team_introduced = models.BooleanField(
        default=False, verbose_name="7. Présentation des membres de l'équipe (Chirurgien, MAR, IADE, IBODE)"
    )
    timeout_reconfirmation_procedure = models.BooleanField(
        default=False, verbose_name="8. Reconfirmation orale : Patient, Intervention et Installation"
    )
    timeout_antibiotic_prophylaxis = models.BooleanField(
        default=False, verbose_name="9. Antibioprophylaxie administrée dans les 60 min (ou sans objet)"
    )
    timeout_critical_steps_reviewed = models.BooleanField(
        default=False, verbose_name="10. Étapes critiques et durée estimée partagées par l'équipe"
    )
    timeout_sterility_confirmed = models.BooleanField(
        default=False, verbose_name="11. Stérilité du matériel chirurgical confirmée par l'IBODE"
    )
    timeout_imaging_displayed = models.BooleanField(
        default=False, verbose_name="12. Imagerie médicale requise affichée en salle"
    )
    timeout_completed_by = models.CharField(
        max_length=120, blank=True, verbose_name="Time-out validé par (Nom & Qualité)"
    )

    # ------------------ Phase 3 : SIGN-OUT (Avant la sortie du bloc opératoire) ------------------
    signout_procedure_confirmed = models.BooleanField(
        default=False, verbose_name="13. Confirmation orale du geste effectivement réalisé"
    )
    signout_instrument_count_correct = models.BooleanField(
        default=False, verbose_name="14. Compte final des compresses, aiguilles et instruments exact"
    )
    signout_specimen_labeled = models.BooleanField(
        default=False, verbose_name="15. Étiquetage des prélèvements anatomopathologiques vérifié à haute voix"
    )
    signout_postop_plan_reviewed = models.BooleanField(
        default=False, verbose_name="16. Consignes postopératoires de surveillance SSPI validées"
    )
    signout_completed_by = models.CharField(
        max_length=120, blank=True, verbose_name="Sign-out validé par (Nom & Qualité)"
    )

    is_fully_validated = models.BooleanField(
        default=False, verbose_name="Checklist OMS 100% conforme et complète"
    )

    class Meta:
        verbose_name = "Checklist Sécurité OMS (Bloc)"
        verbose_name_plural = "Checklists Sécurité OMS (Bloc)"

    def __str__(self) -> str:
        return f"Checklist OMS [{ 'VALIDÉE' if self.is_fully_validated else 'EN COURS' }] - {self.intervention.procedure_name}"

    def clean(self) -> None:
        super().clean()
        all_signin = all([
            self.signin_patient_identity_confirmed,
            self.signin_site_marked,
            self.signin_consent_verified,
            self.signin_allergy_risk_checked,
            self.signin_airway_risk_evaluated,
            self.signin_bleeding_risk_evaluated,
        ])
        all_timeout = all([
            self.timeout_team_introduced,
            self.timeout_reconfirmation_procedure,
            self.timeout_antibiotic_prophylaxis,
            self.timeout_critical_steps_reviewed,
            self.timeout_sterility_confirmed,
            self.timeout_imaging_displayed,
        ])
        all_signout = all([
            self.signout_procedure_confirmed,
            self.signout_instrument_count_correct,
            self.signout_specimen_labeled,
            self.signout_postop_plan_reviewed,
        ])

        self.is_fully_validated = all_signin and all_timeout and all_signout


class OperativeReport(AuditableModel):
    """
    Compte-Rendu Opératoire (CRO) médical officiel.
    Traçabilité des implants (matériovigilance) et détails opératoires.
    """

    intervention = models.OneToOneField(
        SurgicalIntervention,
        on_delete=models.CASCADE,
        related_name="operative_report",
        verbose_name="Intervention chirurgicale",
    )
    author_surgeon = models.ForeignKey(
        CustomUser,
        on_delete=models.PROTECT,
        related_name="written_operative_reports",
        verbose_name="Chirurgien rédacteur",
    )
    report_date = models.DateTimeField(default=timezone.now, verbose_name="Date et heure de rédaction")
    surgical_approach = models.CharField(
        max_length=150,
        verbose_name="Voie d'abord chirurgicale",
        help_text="Ex: Laparoscopie / Cœlioscopie, Laparotomie médiane, Endoscopie, etc.",
    )
    findings = models.TextField(verbose_name="Constatations opératoires")
    procedure_description = models.TextField(verbose_name="Description détaillée du geste chirurgical")
    estimated_blood_loss_ml = models.PositiveIntegerField(
        default=0, verbose_name="Pertes sanguines estimées (mL)"
    )
    implanted_devices_lot_numbers = models.TextField(
        blank=True,
        verbose_name="Matériovigilance : Numéros de lots des prothèses / implants",
        help_text="Traçabilité réglementaire HDS des dispositifs médicaux implantables.",
    )
    intraoperative_complications = models.TextField(
        blank=True, verbose_name="Incidents / Complications peropératoires"
    )
    postoperative_instructions = models.TextField(
        verbose_name="Consignes de surveillance et de réhabilitation précoce (SSPI)"
    )

    class Meta:
        verbose_name = "Compte-Rendu Opératoire (CRO)"
        verbose_name_plural = "Comptes-Rendus Opératoires (CRO)"

    def __str__(self) -> str:
        return f"CRO - {self.intervention.procedure_name} ({self.intervention.patient.last_name})"

