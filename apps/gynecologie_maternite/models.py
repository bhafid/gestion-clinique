"""
Modèles du Pôle Gynécologie & Maternité.
Suivi complet de la santé de la femme, consultations obstétricales,
suivi de grossesse par trimestre avec détection des risques et registre normé des accouchements.
"""

from datetime import date, timedelta
from typing import Optional

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import AuditableModel, CustomUser, Patient, UserRole


class GynecologicalHistory(AuditableModel):
    """Historique gynécologique et obstétrical de la patiente."""

    patient = models.OneToOneField(
        Patient,
        on_delete=models.CASCADE,
        related_name="gynecological_history",
        verbose_name="Patiente (DPI)",
    )
    gravidity = models.PositiveIntegerField(default=0, verbose_name="Gestité (G) - Nombre total de grossesses")
    parity = models.PositiveIntegerField(default=0, verbose_name="Parité (P) - Nombre d'accouchements viables")
    previous_cesareans = models.PositiveIntegerField(default=0, verbose_name="Nombre d'antécédents de césarienne")
    miscarriages = models.PositiveIntegerField(default=0, verbose_name="Fausses couches spontanées / IVG")
    rhesus_incompatibility_risk = models.BooleanField(
        default=False, verbose_name="Risque d'incompatibilité Rhésus fœto-maternelle"
    )
    gynecological_surgeries = models.TextField(blank=True, verbose_name="Antécédents chirurgicaux gynécologiques")
    notes = models.TextField(blank=True, verbose_name="Notes obstétricales particulières")

    class Meta:
        verbose_name = "Historique Gynéco-Obstétrique"
        verbose_name_plural = "Historiques Gynéco-Obstétriques"

    def __str__(self) -> str:
        return f"Historique G{self.gravidity}P{self.parity} - {self.patient.last_name}"


class RoutineConsultation(AuditableModel):
    """Consultation de suivi gynécologique régulier."""

    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name="gyneco_consultations",
        verbose_name="Patiente (DPI)",
    )
    practitioner = models.ForeignKey(
        CustomUser,
        on_delete=models.PROTECT,
        limit_choices_to={"role__in": [UserRole.MEDECIN, UserRole.CHIRURGIEN, UserRole.SAGE_FEMME]},
        related_name="gyneco_consultations",
        verbose_name="Praticien / Sage-Femme",
    )
    consultation_date = models.DateField(default=date.today, verbose_name="Date de consultation")
    reason = models.CharField(max_length=200, verbose_name="Motif de consultation")
    uterine_height_cm = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True, verbose_name="Hauteur utérine (cm)"
    )
    cervix_examination = models.CharField(
        max_length=150, blank=True, verbose_name="Examen du col utérin (long, fermé, tonique, etc.)"
    )
    pap_smear_date = models.DateField(null=True, blank=True, verbose_name="Date du dernier frottis cervico-utérin")
    ultrasound_summary = models.TextField(blank=True, verbose_name="Compte-rendu échographique rapide")
    conclusion_and_treatment = models.TextField(verbose_name="Conclusion et prescriptions")

    class Meta:
        verbose_name = "Consultation de Routine Gynécologique"
        verbose_name_plural = "Consultations de Routine Gynécologique"
        ordering = ["-consultation_date"]

    def __str__(self) -> str:
        return f"Consultation Gynéco {self.patient.last_name} le {self.consultation_date.strftime('%d/%m/%Y')}"


class PregnancyStatus(models.TextChoices):
    EN_COURS = "EN_COURS", "Grossesse en cours"
    ACCOUCHEE = "ACCOUCHEE", "Accouchement effectué"
    INTERROMPUE = "INTERROMPUE", "Interruption médicale / spontanée"


class PregnancyTracking(AuditableModel):
    """
    Suivi longitudinal de la grossesse avec calcul automatique
    du terme théorique et monitoring des facteurs de risque.
    """

    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name="pregnancies",
        verbose_name="Patiente (DPI)",
    )
    last_menstrual_period = models.DateField(
        verbose_name="Date des Dernières Règles (DDR)",
        help_text="Point de référence pour le calcul de l'âge gestationnel",
    )
    estimated_due_date = models.DateField(
        blank=True,
        null=True,
        verbose_name="Date Présumée d'Accouchement (DPA)",
        help_text="Calculée automatiquement à DDR + 280 jours (40 SA) si non renseignée",
    )
    risk_factors = models.TextField(
        blank=True,
        verbose_name="Facteurs de risque (Diabète gestationnel, HTA gravidique, Pré-éclampsie, etc.)",
    )
    t1_ultrasound_date = models.DateField(null=True, blank=True, verbose_name="Échographie T1 (11-13 SA)")
    t1_nuchal_translucency_mm = models.DecimalField(
        max_digits=4, decimal_places=2, null=True, blank=True, verbose_name="Clarté nucale T1 (mm)"
    )
    t2_morphological_ultrasound_date = models.DateField(
        null=True, blank=True, verbose_name="Échographie morphologique T2 (20-24 SA)"
    )
    t3_growth_ultrasound_date = models.DateField(
        null=True, blank=True, verbose_name="Échographie de croissance T3 (32-34 SA)"
    )
    status = models.CharField(
        max_length=20,
        choices=PregnancyStatus.choices,
        default=PregnancyStatus.EN_COURS,
        verbose_name="Statut de la grossesse",
    )

    class Meta:
        verbose_name = "Suivi de Grossesse"
        verbose_name_plural = "Suivis de Grossesse"
        ordering = ["-last_menstrual_period"]

    def __str__(self) -> str:
        return f"Grossesse {self.patient.last_name} (DPA: {self.estimated_due_date or 'N/C'})"

    def clean(self) -> None:
        super().clean()
        if self.last_menstrual_period and not self.estimated_due_date:
            # Règle de Naegele standard : DDR + 280 jours (40 semaines d'aménorrhée)
            self.estimated_due_date = self.last_menstrual_period + timedelta(days=280)


class DeliveryMode(models.TextChoices):
    VOIE_BASSE_SPONTANEE = "VOIE_BASSE_SPONTANEE", "Voie basse spontanée eutocique"
    VENTOUSE = "VENTOUSE", "Extraction instrumentale par ventouse"
    FORCEPS = "FORCEPS", "Extraction instrumentale par forceps"
    CESARIENNE_PROGRAMMEE = "CESARIENNE_PROGRAMMEE", "Césarienne programmée"
    CESARIENNE_URGENCE = "CESARIENNE_URGENCE", "Césarienne en urgence"


class DeliveryRegistry(AuditableModel):
    """
    Registre officiel d'accouchement médicalisé.
    Enregistre les données périnatales, le mode de délivrance et les scores néonataux.
    """

    pregnancy = models.ForeignKey(
        PregnancyTracking,
        on_delete=models.CASCADE,
        related_name="deliveries",
        verbose_name="Dossier de grossesse associé",
    )
    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name="deliveries",
        verbose_name="Mère (DPI)",
    )
    attending_obstetrician = models.ForeignKey(
        CustomUser,
        on_delete=models.PROTECT,
        limit_choices_to={"role__in": [UserRole.MEDECIN, UserRole.CHIRURGIEN]},
        related_name="performed_deliveries",
        verbose_name="Médecin Obstétricien",
    )
    midwife = models.ForeignKey(
        CustomUser,
        on_delete=models.PROTECT,
        limit_choices_to={"role": UserRole.SAGE_FEMME},
        related_name="midwife_deliveries",
        verbose_name="Sage-femme référente",
    )
    delivery_datetime = models.DateTimeField(default=timezone.now, verbose_name="Date et heure de délivrance")
    delivery_mode = models.CharField(
        max_length=30,
        choices=DeliveryMode.choices,
        default=DeliveryMode.VOIE_BASSE_SPONTANEE,
        verbose_name="Mode d'accouchement",
    )
    placenta_delivery = models.CharField(
        max_length=100,
        default="Complète spontanée",
        verbose_name="Modalités de délivrance placentaire",
    )
    infant_gender = models.CharField(
        max_length=1,
        choices=[("M", "Garçon"), ("F", "Fille"), ("I", "Indéterminé")],
        verbose_name="Sexe du nouveau-né",
    )
    birth_weight_grams = models.PositiveIntegerField(
        verbose_name="Poids de naissance (grammes)",
        help_text="Poids mesuré immédiatement à la naissance",
    )
    birth_length_cm = models.DecimalField(
        max_digits=4, decimal_places=1, verbose_name="Taille à la naissance (cm)"
    )
    cranial_perimeter_cm = models.DecimalField(
        max_digits=4, decimal_places=1, verbose_name="Périmètre crânien (cm)"
    )
    apgar_1min = models.PositiveIntegerField(verbose_name="Score d'APGAR à 1 min (0-10)")
    apgar_5min = models.PositiveIntegerField(verbose_name="Score d'APGAR à 5 min (0-10)")
    apgar_10min = models.PositiveIntegerField(
        null=True, blank=True, verbose_name="Score d'APGAR à 10 min (optionnel)"
    )
    maternal_complications = models.TextField(blank=True, verbose_name="Complications maternelles")
    neonatal_complications = models.TextField(blank=True, verbose_name="Complications néonatales / Transfert néonat")

    class Meta:
        verbose_name = "Registre d'Accouchement"
        verbose_name_plural = "Registre des Accouchements"
        ordering = ["-delivery_datetime"]

    def __str__(self) -> str:
        return (
            f"Accouchement {self.patient.last_name} ({self.get_delivery_mode_display()}) - "
            f"Bébé {self.birth_weight_grams}g [APGAR 5m: {self.apgar_5min}/10]"
        )

    def clean(self) -> None:
        super().clean()
        for score, label in [(self.apgar_1min, "1 min"), (self.apgar_5min, "5 min")]:
            if score is not None and not (0 <= score <= 10):
                raise ValidationError(f"Le score d'APGAR à {label} doit être compris entre 0 et 10.")
        if self.apgar_10min is not None and not (0 <= self.apgar_10min <= 10):
            raise ValidationError("Le score d'APGAR à 10 min doit être compris entre 0 et 10.")

    def save(self, *args, **kwargs) -> None:
        """Clôture automatique de la grossesse lors de l'enregistrement de l'accouchement."""
        super().save(*args, **kwargs)
        if self.pregnancy.status == PregnancyStatus.EN_COURS:
            self.pregnancy.status = PregnancyStatus.ACCOUCHEE
            self.pregnancy.save(update_fields=["status", "updated_at"])

