"""
Modèles du Pôle Pédiatrie.
Suivi anthropométrique de croissance (poids, taille, périmètre crânien, IMC)
et calendrier vaccinal automatisé avec traçabilité stricte des lots (HDS / Pharmacovigilance).
"""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import AuditableModel, CustomUser, Patient, UserRole


class AnthropometricRecord(AuditableModel):
    """
    Relevé de croissance pédiatrique périodique.
    Permet l'établissement des courbes de croissance AFPA/OMS.
    """

    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name="anthropometric_records",
        verbose_name="Enfant (DPI)",
    )
    recorded_by = models.ForeignKey(
        CustomUser,
        on_delete=models.PROTECT,
        verbose_name="Praticien / Soignant ayant mesuré",
    )
    measurement_date = models.DateField(default=date.today, verbose_name="Date de mesure")
    age_in_months = models.PositiveIntegerField(verbose_name="Âge de l'enfant (en mois)")
    weight_kg = models.DecimalField(max_digits=5, decimal_places=2, verbose_name="Poids (kg)")
    height_cm = models.DecimalField(max_digits=5, decimal_places=1, verbose_name="Taille (cm)")
    cranial_perimeter_cm = models.DecimalField(
        max_digits=4, decimal_places=1, verbose_name="Périmètre crânien (cm)"
    )
    body_mass_index = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True, verbose_name="IMC calculé (kg/m²)"
    )
    percentiles_notes = models.CharField(
        max_length=150, blank=True, verbose_name="Positionnement sur courbe (ex: Médiane, +1 DS)"
    )
    clinical_observations = models.TextField(blank=True, verbose_name="Observations cliniques")

    class Meta:
        verbose_name = "Relevé Anthropométrique Pédiatrique"
        verbose_name_plural = "Relevés Anthropométriques Pédiatriques"
        ordering = ["-measurement_date"]

    def __str__(self) -> str:
        return f"{self.patient.first_name} {self.patient.last_name} ({self.age_in_months} mois) : {self.weight_kg} kg, {self.height_cm} cm"

    def clean(self) -> None:
        super().clean()
        if self.height_cm and self.weight_kg:
            height_m = self.height_cm / Decimal("100.0")
            if height_m > 0:
                self.body_mass_index = round(self.weight_kg / (height_m * height_m), 1)


class VaccineStatus(models.TextChoices):
    A_FAIRE = "A_FAIRE", "À administrer"
    EFFECTUE = "EFFECTUE", "Vaccin administré"
    EN_RETARD = "EN_RETARD", "En retard par rapport au calendrier"
    CONTRE_INDIQUE = "CONTRE_INDIQUE", "Contre-indication médicale temporaire ou définitive"


class VaccinationRecord(AuditableModel):
    """
    Dossier de vaccination pédiatrique automatisé.
    Gère le cycle de vie du statut vaccinal et impose le numéro de lot pour la traçabilité.
    """

    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name="vaccinations",
        verbose_name="Enfant (DPI)",
    )
    vaccine_name = models.CharField(
        max_length=150,
        verbose_name="Nom de la valence vaccinale",
        help_text="Ex: Hexavalent (DTP-Coq-Hib-HBV), ROR, Méningocoque C/B, Pneumocoque 13-val",
    )
    target_age_months = models.PositiveIntegerField(
        verbose_name="Âge cible recommandé (en mois)",
        help_text="Ex: 2, 4, 11, 12, 16 mois...",
    )
    recommended_due_date = models.DateField(
        verbose_name="Date d'échéance recommandée",
        help_text="Calculée à partir de la date de naissance",
    )
    administration_date = models.DateField(
        null=True, blank=True, verbose_name="Date d'injection réelle"
    )
    batch_number = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="Numéro de lot du vaccin",
        help_text="Obligatoire dès que le vaccin est administré (Pharmacovigilance HDS)",
    )
    administering_doctor = models.ForeignKey(
        CustomUser,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        limit_choices_to={"role__in": [UserRole.MEDECIN, UserRole.INFIRMIER, UserRole.SAGE_FEMME]},
        related_name="administered_vaccines",
        verbose_name="Professionnel ayant réalisé l'injection",
    )
    injection_site = models.CharField(
        max_length=60,
        blank=True,
        verbose_name="Site anatomique d'injection (ex: Cuisse antérolatérale gauche)",
    )
    status = models.CharField(
        max_length=25,
        choices=VaccineStatus.choices,
        default=VaccineStatus.A_FAIRE,
        verbose_name="Statut vaccinal",
    )
    adverse_reactions = models.TextField(blank=True, verbose_name="Effets indésirables / Tolérance")

    class Meta:
        verbose_name = "Ligne du Calendrier Vaccinal"
        verbose_name_plural = "Lignes du Calendrier Vaccinal"
        ordering = ["recommended_due_date"]

    def __str__(self) -> str:
        return f"{self.vaccine_name} - {self.patient.last_name} [{self.get_status_display()}]"

    def clean(self) -> None:
        """Contrôles stricts de traçabilité des lots et calcul automatisé du statut."""
        super().clean()
        today = date.today()

        if self.administration_date:
            if not self.batch_number or not self.batch_number.strip():
                raise ValidationError(
                    {"batch_number": "Le numéro de lot est strictement obligatoire pour tout vaccin administré."}
                )
            self.status = VaccineStatus.EFFECTUE
        else:
            if self.status != VaccineStatus.CONTRE_INDIQUE:
                if self.recommended_due_date and self.recommended_due_date < today:
                    self.status = VaccineStatus.EN_RETARD
                else:
                    self.status = VaccineStatus.A_FAIRE

    def save(self, *args, **kwargs) -> None:
        self.clean()
        super().save(*args, **kwargs)

