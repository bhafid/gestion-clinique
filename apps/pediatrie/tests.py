"""
Tests unitaires pour le Pôle Pédiatrie.
Vérification des relevés anthropométriques et du calendrier vaccinal automatisé avec numéros de lots.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.core.models import CustomUser, Department, Patient, UserRole
from apps.pediatrie.models import AnthropometricRecord, VaccinationRecord, VaccineStatus


class PediatrieModuleTestCase(TestCase):
    def setUp(self) -> None:
        self.dept = Department.objects.create(code="PED", name="Pédiatrie Générale")
        self.pediatrician = CustomUser.objects.create_user(
            username="dr_pediatre",
            password="Password123!",
            role=UserRole.MEDECIN,
            department=self.dept,
        )
        # Enfant né en 2025
        self.child = Patient.objects.create(
            nir="185057511504248",
            last_name="Petit",
            first_name="Lucas",
            birth_date=date(2025, 6, 1),
            gender="M",
        )

    def test_anthropometric_record_bmi_calculation(self) -> None:
        """Vérifie le calcul automatique de l'IMC pédiatrique."""
        record = AnthropometricRecord(
            patient=self.child,
            recorded_by=self.pediatrician,
            measurement_date=date.today(),
            age_in_months=12,
            weight_kg=Decimal("10.00"),
            height_cm=Decimal("75.0"),
            cranial_perimeter_cm=Decimal("46.5"),
        )
        record.full_clean()
        record.save()

        # BMI = 10 / (0.75 * 0.75) = 17.77 -> 17.8
        self.assertAlmostEqual(float(record.body_mass_index), 17.8, delta=0.1)

    def test_vaccination_schedule_status_and_lot_enforcement(self) -> None:
        """
        Vérifie :
        1. Le statut 'EN_RETARD' si la date d'échéance est passée sans injection.
        2. L'obligation du numéro de lot lors de l'administration.
        3. Le passage au statut 'EFFECTUE' lors de la saisie complète.
        """
        past_date = date.today() - timedelta(days=60)
        vaccine = VaccinationRecord(
            patient=self.child,
            vaccine_name="Hexavalent (Infanrix Hexa)",
            target_age_months=2,
            recommended_due_date=past_date,
        )
        vaccine.full_clean()
        vaccine.save()
        # Statut automatique : EN_RETARD
        self.assertEqual(vaccine.status, VaccineStatus.EN_RETARD)

        # Tentative d'administrer sans numéro de lot -> Doit échouer
        vaccine.administration_date = date.today()
        vaccine.administering_doctor = self.pediatrician
        vaccine.batch_number = ""  # Vide

        with self.assertRaises(ValidationError) as ctx:
            vaccine.full_clean()
        self.assertIn("Le numéro de lot est strictement obligatoire", str(ctx.exception))

        # Avec numéro de lot -> Doit passer et passer au statut EFFECTUE
        vaccine.batch_number = "LOT-HX-2026-991"
        vaccine.full_clean()
        vaccine.save()
        self.assertEqual(vaccine.status, VaccineStatus.EFFECTUE)

