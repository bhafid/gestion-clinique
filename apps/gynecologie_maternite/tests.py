"""
Tests unitaires pour le Pôle Gynécologie & Maternité.
Vérification du suivi de grossesse (DPA), des consultations et du registre d'accouchement.
"""

from datetime import date, timedelta
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.core.models import CustomUser, Department, Patient, UserRole
from apps.gynecologie_maternite.models import (
    DeliveryMode,
    DeliveryRegistry,
    GynecologicalHistory,
    PregnancyStatus,
    PregnancyTracking,
    RoutineConsultation,
)


class GynecologieMaterniteModuleTestCase(TestCase):
    def setUp(self) -> None:
        self.dept = Department.objects.create(code="MAT", name="Maternité & Obstétrique")
        self.obstetrician = CustomUser.objects.create_user(
            username="dr_obstetrique",
            password="Password123!",
            role=UserRole.MEDECIN,
            department=self.dept,
        )
        self.midwife = CustomUser.objects.create_user(
            username="sf_maternite",
            password="Password123!",
            role=UserRole.SAGE_FEMME,
            department=self.dept,
        )
        # Femme née en 1992 (2 92 03 75 115 042 -> 2920375115042 % 97 = 6 -> 97 - 6 = 91)
        self.patient = Patient.objects.create(
            nir="292037511504291",
            last_name="Moreau",
            first_name="Camille",
            birth_date=date(1992, 3, 14),
            gender="F",
        )

    def test_pregnancy_tracking_and_automatic_due_date(self) -> None:
        """Vérifie le calcul automatique de la DPA (DDR + 280 jours)."""
        ddr = date(2026, 1, 10)
        pregnancy = PregnancyTracking(
            patient=self.patient,
            last_menstrual_period=ddr,
        )
        pregnancy.full_clean()
        pregnancy.save()

        expected_dpa = ddr + timedelta(days=280)
        self.assertEqual(pregnancy.estimated_due_date, expected_dpa)
        self.assertEqual(pregnancy.status, PregnancyStatus.EN_COURS)

    def test_delivery_registry_and_pregnancy_closure(self) -> None:
        """Vérifie l'enregistrement d'un accouchement avec score APGAR et clôture de grossesse."""
        ddr = date(2025, 12, 1)
        pregnancy = PregnancyTracking.objects.create(
            patient=self.patient,
            last_menstrual_period=ddr,
            estimated_due_date=ddr + timedelta(days=280),
        )

        delivery = DeliveryRegistry(
            pregnancy=pregnancy,
            patient=self.patient,
            attending_obstetrician=self.obstetrician,
            midwife=self.midwife,
            delivery_datetime=timezone.now(),
            delivery_mode=DeliveryMode.VOIE_BASSE_SPONTANEE,
            infant_gender="F",
            birth_weight_grams=3350,
            birth_length_cm=50.5,
            cranial_perimeter_cm=35.0,
            apgar_1min=9,
            apgar_5min=10,
        )
        delivery.full_clean()
        delivery.save()

        # La grossesse doit être automatiquement passée au statut ACCOUCHEE
        pregnancy.refresh_from_db()
        self.assertEqual(pregnancy.status, PregnancyStatus.ACCOUCHEE)

