"""
Tests unitaires pour le socle transversal (Core).
Vérification des exigences strictes :
- Contrôle d'accès RBAC et modèles de personnel
- Validation algorithmique du NIR (Sécurité Sociale)
- Anti-collision d'agenda pour les rendez-vous
- Cycle de vie automatique des lits (OCCUPÉ -> NETTOYAGE)
- Détection des chevauchements de gardes
- Verrouillage obligatoire de l'appartenance départementale pour les remplacements
- Vue Dashboard hebdomadaire
"""

from datetime import date, datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.core.models import (
    Appointment,
    AppointmentStatus,
    Bed,
    BedStatus,
    CustomUser,
    Department,
    DutyShift,
    Hospitalization,
    HospitalizationStatus,
    Patient,
    ShiftReplacement,
    ShiftReplacementStatus,
    ShiftType,
    UserRole,
    validate_french_nir,
)


class CoreModuleTestCase(TestCase):
    def setUp(self) -> None:
        # Création des départements de test
        self.dept_chir = Department.objects.create(code="CHIR", name="Chirurgie Générale", building="A", floor=2)
        self.dept_uro = Department.objects.create(code="URO", name="Urologie", building="B", floor=3)

        # Création des utilisateurs médicaux
        self.doctor_chir = CustomUser.objects.create_user(
            username="dr_dupont",
            password="StrongPassword123!",
            first_name="Jean",
            last_name="Dupont",
            role=UserRole.CHIRURGIEN,
            department=self.dept_chir,
            license_number="RPPS-10001",
        )
        self.doctor_chir_2 = CustomUser.objects.create_user(
            username="dr_martin",
            password="StrongPassword123!",
            first_name="Sophie",
            last_name="Martin",
            role=UserRole.CHIRURGIEN,
            department=self.dept_chir,
            license_number="RPPS-10002",
        )
        self.doctor_uro = CustomUser.objects.create_user(
            username="dr_bernard",
            password="StrongPassword123!",
            first_name="Luc",
            last_name="Bernard",
            role=UserRole.MEDECIN,
            department=self.dept_uro,
            license_number="RPPS-20001",
        )

        # Calcul d'un NIR valide de test (Homme né en 1985 en mai, Paris 15e...)
        # 1 85 05 75 115 042 -> 1850575115042 % 97 = 49 -> 97 - 49 = 48
        self.valid_nir = "185057511504248"
        self.invalid_nir = "185057511504299"

        # Création d'un patient (DPI)
        self.patient = Patient.objects.create(
            nir=self.valid_nir,
            last_name="Lemoine",
            first_name="Pierre",
            birth_date=date(1985, 5, 12),
            gender="M",
            blood_group="O+",
            phone="0601020304",
        )

        # Création d'un lit
        self.bed_101 = Bed.objects.create(
            service=self.dept_chir,
            room_number="101",
            bed_number="1",
            status=BedStatus.DISPONIBLE,
        )

    def test_nir_validation(self) -> None:
        """Vérifie la validation de la clé de contrôle de sécurité sociale (NIR)."""
        # Le NIR valide ne doit pas lever d'erreur
        validate_french_nir(self.valid_nir)

        # Un NIR avec une mauvaise clé doit lever ValidationError
        with self.assertRaises(ValidationError):
            validate_french_nir(self.invalid_nir)

    def test_dpi_ipp_auto_generation(self) -> None:
        """Vérifie que l'IPP est automatiquement et correctement généré."""
        self.assertTrue(self.patient.ipp.startswith("IPP-"))
        self.assertEqual(len(self.patient.ipp.split("-")), 3)

    def test_appointment_overlap_prevention(self) -> None:
        """Vérifie que le validateur clean() empêche la double réservation d'un médecin."""
        now = timezone.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=2)
        rdv1 = Appointment(
            patient=self.patient,
            practitioner=self.doctor_chir,
            department=self.dept_chir,
            start_datetime=now,
            end_datetime=now + timedelta(minutes=30),
            reason="Consultation préopératoire",
        )
        rdv1.full_clean()
        rdv1.save()

        # Tentative de réserver le même praticien sur un créneau qui chevauche (ex: 15 min après le début)
        rdv_conflict = Appointment(
            patient=self.patient,
            practitioner=self.doctor_chir,
            department=self.dept_chir,
            start_datetime=now + timedelta(minutes=15),
            end_datetime=now + timedelta(minutes=45),
            reason="Deuxième consultation en doublon",
        )
        with self.assertRaises(ValidationError) as ctx:
            rdv_conflict.full_clean()
        self.assertIn("Conflit d'agenda", str(ctx.exception))

    def test_bed_lifecycle_on_admission_and_discharge(self) -> None:
        """
        Vérifie le cycle automatisé du statut du lit :
        1. À l'admission active -> lit passe à OCCUPÉ.
        2. À la saisie de date_sortie_reelle -> lit passe automatiquement à NETTOYAGE.
        """
        self.assertEqual(self.bed_101.status, BedStatus.DISPONIBLE)
        adm_time = timezone.now()

        # Admission
        hosp = Hospitalization(
            patient=self.patient,
            bed=self.bed_101,
            admission_date=adm_time,
            expected_discharge_date=adm_time + timedelta(days=3),
            admission_reason="Surveillance postopératoire",
            entry_diagnosis="Appendicite aiguë",
        )
        hosp.full_clean()
        hosp.save()

        # Le lit doit être passé à OCCUPÉ
        self.bed_101.refresh_from_db()
        self.assertEqual(self.bed_101.status, BedStatus.OCCUPE)
        self.assertEqual(hosp.status, HospitalizationStatus.EN_COURS)

        # Sortie réelle du patient
        hosp.actual_discharge_date = adm_time + timedelta(days=2)
        hosp.full_clean()
        hosp.save()

        # Le lit doit être passé automatiquement à NETTOYAGE
        self.bed_101.refresh_from_db()
        self.assertEqual(self.bed_101.status, BedStatus.NETTOYAGE)
        self.assertEqual(hosp.status, HospitalizationStatus.CLOTUREE)

    def test_duty_shift_overlap_blocking(self) -> None:
        """Vérifie qu'un soignant ne peut pas être affecté à deux gardes se chevauchant."""
        test_date = date.today() + timedelta(days=5)
        shift1 = DutyShift(
            staff_member=self.doctor_chir,
            department=self.dept_chir,
            shift_date=test_date,
            shift_type=ShiftType.JOUR,
            start_time=time(8, 0),
            end_time=time(18, 0),
        )
        shift1.full_clean()
        shift1.save()

        # Shift qui chevauche sur le même praticien
        shift2 = DutyShift(
            staff_member=self.doctor_chir,
            department=self.dept_chir,
            shift_date=test_date,
            shift_type=ShiftType.NUIT,
            start_time=time(17, 0),
            end_time=time(23, 0),
        )
        with self.assertRaises(ValidationError) as ctx:
            shift2.full_clean()
        self.assertIn("Chevauchement d'horaires interdit", str(ctx.exception))

    def test_shift_replacement_department_lock(self) -> None:
        """
        Vérifie le verrouillage strict de la permutation de garde :
        Le remplaçant DOIT obligatoirement appartenir au même département de soin.
        """
        test_date = date.today() + timedelta(days=6)
        shift = DutyShift.objects.create(
            staff_member=self.doctor_chir,
            department=self.dept_chir,
            shift_date=test_date,
            shift_type=ShiftType.JOUR,
            start_time=time(8, 0),
            end_time=time(18, 0),
        )

        # 1. Tentative avec un soignant d'un AUTRE département (Urologie) -> Doit échouer
        replacement_invalid = ShiftReplacement(
            duty_shift=shift,
            original_caregiver=self.doctor_chir,
            substitute_caregiver=self.doctor_uro,
            reason="Congé urgent",
        )
        with self.assertRaises(ValidationError) as ctx:
            replacement_invalid.full_clean()
        self.assertIn("Verrouillage de sécurité départementale", str(ctx.exception))

        # 2. Tentative avec un soignant du MÊME département (Chirurgie) -> Doit réussir
        replacement_valid = ShiftReplacement(
            duty_shift=shift,
            original_caregiver=self.doctor_chir,
            substitute_caregiver=self.doctor_chir_2,
            reason="Permutation de garde accordée",
        )
        replacement_valid.full_clean()
        replacement_valid.save()
        self.assertIsNotNone(replacement_valid.id)

    def test_anonymous_access_blocked(self) -> None:
        """Vérifie qu'aucun accès anonyme n'est autorisé et redirige vers /login/."""
        client = Client()
        response = client.get(reverse("home_dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/login/"))

    def test_weekly_dashboard_view_http(self) -> None:
        """Vérifie l'accès HTTP 200 à la vue du tableau de bord hebdomadaire après connexion."""
        client = Client()
        client.force_login(self.doctor_chir)
        response = client.get(reverse("home_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("total_beds", response.context)
        self.assertIn("planning_matrix", response.context)
        self.assertContains(response, "Capacité Hospitalière")
        self.assertContains(response, "Chirurgie Générale")
        self.assertContains(response, "Chirurgien")


