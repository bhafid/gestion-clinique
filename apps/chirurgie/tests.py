"""
Tests unitaires pour le Pôle Chirurgie & Bloc Opératoire.
Vérification de la planification opératoire, de la Checklist de sécurité OMS et des CRO.
"""

from datetime import date, timedelta
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.core.models import CustomUser, Department, Patient, UserRole
from apps.chirurgie.models import (
    OperatingRoom,
    OperativeReport,
    SafetyChecklistOMS,
    SurgicalIntervention,
    SurgicalPriority,
)


class ChirurgieModuleTestCase(TestCase):
    def setUp(self) -> None:
        self.dept = Department.objects.create(code="BLOC", name="Pôle Opératoire")
        self.surgeon = CustomUser.objects.create_user(
            username="chirurgien_test",
            password="Password123!",
            role=UserRole.CHIRURGIEN,
            department=self.dept,
        )
        self.patient = Patient.objects.create(
            nir="185057511504248",
            last_name="Garnier",
            first_name="Thomas",
            birth_date=date(1990, 1, 1),
            gender="M",
        )
        self.room = OperatingRoom.objects.create(
            code="SALLE-1",
            name="Salle de Chirurgie Viscérale",
        )

    def test_surgical_intervention_and_checklist_oms(self) -> None:
        """Vérifie la création d'intervention et la validation complète de la checklist OMS."""
        start = timezone.now() + timedelta(days=1)
        end = start + timedelta(hours=2)

        intervention = SurgicalIntervention.objects.create(
            patient=self.patient,
            operating_room=self.room,
            lead_surgeon=self.surgeon,
            scheduled_start=start,
            scheduled_end=end,
            procedure_name="Cholécystectomie par cœlioscopie",
            surgical_indication="Lithiase vésiculaire symptomatique",
            priority=SurgicalPriority.PROGRAMMEE,
        )

        # Création de la checklist OMS
        checklist = SafetyChecklistOMS(
            intervention=intervention,
            # Sign-in
            signin_patient_identity_confirmed=True,
            signin_site_marked=True,
            signin_consent_verified=True,
            signin_allergy_risk_checked=True,
            signin_airway_risk_evaluated=True,
            signin_bleeding_risk_evaluated=True,
            signin_completed_by="Dr Martin (MAR)",
            # Time-out
            timeout_team_introduced=True,
            timeout_reconfirmation_procedure=True,
            timeout_antibiotic_prophylaxis=True,
            timeout_critical_steps_reviewed=True,
            timeout_sterility_confirmed=True,
            timeout_imaging_displayed=True,
            timeout_completed_by="Dr Garnier (Chir)",
            # Sign-out
            signout_procedure_confirmed=True,
            signout_instrument_count_correct=True,
            signout_specimen_labeled=True,
            signout_postop_plan_reviewed=True,
            signout_completed_by="Mme Lemoine (IBODE)",
        )
        checklist.full_clean()
        checklist.save()

        self.assertTrue(checklist.is_fully_validated)

    def test_operative_report(self) -> None:
        """Vérifie la rédaction du compte-rendu opératoire avec traçabilité des implants."""
        start = timezone.now() + timedelta(days=2)
        intervention = SurgicalIntervention.objects.create(
            patient=self.patient,
            operating_room=self.room,
            lead_surgeon=self.surgeon,
            scheduled_start=start,
            scheduled_end=start + timedelta(hours=1),
            procedure_name="Herniorraphie inguinale",
            surgical_indication="Hernie inguinale droite douloureuse",
        )

        cro = OperativeReport.objects.create(
            intervention=intervention,
            author_surgeon=self.surgeon,
            surgical_approach="Voie inguinale antérieure",
            findings="Présence d'un sac herniaire indirect réductible",
            procedure_description="Dissection du sac, réintégration, renfort prothétique",
            implanted_devices_lot_numbers="Plaque Prolène 3D-Max Lot: 2026-X889",
            postoperative_instructions="Surveillance pansement, lever à H+4",
        )
        self.assertIn("Plaque Prolène", cro.implanted_devices_lot_numbers)

