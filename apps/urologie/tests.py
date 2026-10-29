"""
Tests unitaires pour le Pôle Urologie & Néphrologie.
Vérification des antécédents, des bilans urodynamiques chiffrés et des actes spécialisés.
"""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.core.models import CustomUser, Department, Patient, UserRole
from apps.urologie.models import (
    SpecializedInterventionReport,
    UrodynamicAssessment,
    UrologicalHistory,
    UrologicalInterventionType,
)


class UrologieModuleTestCase(TestCase):
    def setUp(self) -> None:
        self.dept = Department.objects.create(code="URO", name="Urologie & Andrologie")
        self.urologist = CustomUser.objects.create_user(
            username="dr_urologue",
            password="Password123!",
            role=UserRole.CHIRURGIEN,
            department=self.dept,
        )
        self.patient = Patient.objects.create(
            nir="185057511504248",
            last_name="Bertrand",
            first_name="Michel",
            birth_date=date(1960, 4, 20),
            gender="M",
        )

    def test_urodynamic_assessment_quantitative_data(self) -> None:
        """Vérifie l'enregistrement et les contrôles de cohérence du bilan urodynamique."""
        bud = UrodynamicAssessment(
            patient=self.patient,
            urologist=self.urologist,
            clinical_indication="Dysurie avec suspicion de sténose ou obstacle prostatique",
            qmax_flow_rate_ml_s=Decimal("9.5"),  # Qmax abaissé
            voided_volume_ml=220,
            post_void_residual_ml=60,
            maximum_cystometric_capacity_ml=350,
            pdet_qmax_cmh2o=Decimal("65.0"),
            conclusion_diagnosis="Obstacle sous-vésical obstructif sans hypocontractilité détrusorienne",
        )
        bud.full_clean()
        bud.save()

        self.assertEqual(bud.qmax_flow_rate_ml_s, Decimal("9.5"))
        self.assertEqual(bud.post_void_residual_ml, 60)

    def test_specialized_urological_intervention_stent_validation(self) -> None:
        """Vérifie la validation lors de la pose d'une sonde JJ (côté obligatoire)."""
        report = SpecializedInterventionReport(
            patient=self.patient,
            surgeon=self.urologist,
            intervention_type=UrologicalInterventionType.URETEROSCOPIE_SOUPLE,
            double_j_stent_inserted=True,
            stent_side="",  # Manquant
            operative_notes="Fragmentation de calcul pyélique au laser Holmium",
        )
        with self.assertRaises(ValidationError) as ctx:
            report.full_clean()
        self.assertIn("Veuillez préciser le côté", str(ctx.exception))

        # Correction avec côté précisé
        report.stent_side = "DROITE"
        report.full_clean()
        report.save()
        self.assertEqual(report.stent_side, "DROITE")

