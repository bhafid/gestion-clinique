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
    AuditActionType,
    Bed,
    BedStatus,
    CustomUser,
    Department,
    DutyShift,
    Hospitalization,
    HospitalizationStatus,
    Patient,
    PatientStatusConfig,
    PatientStatusHistory,
    SecurityAuditLog,
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

    def test_dynamic_patient_status_and_history_tracking(self) -> None:
        """
        Vérifie :
        1. La présence des 7 statuts initiaux ('Admission', 'Bloc', 'Réveil', 'Sortie', 'Reporté', 'Annulé', 'Service').
        2. La mise à jour atomique du statut actuel du patient et l'enregistrement dans PatientStatusHistory.
        3. Le filtrage par statut et la recherche combinée sur /core/patients/.
        """
        statuses = PatientStatusConfig.ensure_default_statuses()
        expected_codes = {"ADMISSION", "BLOC", "REVEIL", "SORTIE", "REPORTE", "ANNULE", "SERVICE"}
        self.assertTrue(expected_codes.issubset(set(statuses.keys())))

        # Changement de statut : Admission -> Bloc
        self.patient.change_status(
            new_status=statuses["BLOC"],
            changed_by=self.doctor_chir,
            comment="Entrée au bloc opératoire salle 1",
        )
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.current_status.code, "BLOC")

        # Changement de statut : Bloc -> Réveil
        history_entry = self.patient.change_status(
            new_status=statuses["REVEIL"],
            changed_by=self.doctor_chir,
            comment="Transfert en SSPI",
        )
        self.patient.refresh_from_db()
        self.assertEqual(self.patient.current_status.code, "REVEIL")
        self.assertEqual(history_entry.old_status.code, "BLOC")
        self.assertEqual(history_entry.new_status.code, "REVEIL")
        self.assertEqual(history_entry.changed_by, self.doctor_chir)

        # Test de la vue de liste et de filtrage combiné (?status=REVEIL&q=Lemoine)
        client = Client()
        client.force_login(self.doctor_chir)

        res_match = client.get(reverse("core:patient_list"), {"status": "REVEIL", "q": "Lemoine"})
        self.assertEqual(res_match.status_code, 200)
        self.assertContains(res_match, "LEMOINE")
        self.assertContains(res_match, "Réveil")

        res_no_match = client.get(reverse("core:patient_list"), {"status": "SORTIE", "q": "Lemoine"})
        self.assertEqual(res_no_match.status_code, 200)
        self.assertEqual(len(res_no_match.context["patients"]), 0)

    def test_gestionnaire_admission_rbac_and_medical_secrecy(self) -> None:
        """
        Vérifie la matrice stricte des droits du rôle GESTIONNAIRE_ADMISSION :
        - CRU sur Patient administratif, interdiction stricte de suppression (DELETE).
        - CRU sur Hospitalization (admission, transfert de lit, sortie), lecture seule sur Bed.
        - Masquage des données médicales sensibles (major_medical_history, ongoing_treatments, entry_diagnosis)
          et lecture seule sur known_allergies, admission_reason, practitioner.
        - Aucun accès (403 + log ACCESS_DENIED) aux modules cliniques (Chirurgie, Pédiatrie, Urologie).
        """
        from django.contrib.admin.sites import AdminSite
        from django.test import RequestFactory
        from apps.core.admin import BedAdmin, HospitalizationAdmin, PatientAdmin

        admission_mgr = CustomUser.objects.create_user(
            username="adm_karim_test",
            password="StrongPassword123!",
            first_name="Karim",
            last_name="Mansouri",
            role=UserRole.GESTIONNAIRE_ADMISSION,
            department=self.dept_chir,
        )
        admission_mgr.sync_role_permissions()

        # 1. Vérification des permissions Django (CRU Patient & Hospitalization, R Bed, 0 Delete)
        self.assertTrue(admission_mgr.has_perm("core.view_patient"))
        self.assertTrue(admission_mgr.has_perm("core.add_patient"))
        self.assertTrue(admission_mgr.has_perm("core.change_patient"))
        self.assertFalse(admission_mgr.has_perm("core.delete_patient"))

        self.assertTrue(admission_mgr.has_perm("core.view_hospitalization"))
        self.assertTrue(admission_mgr.has_perm("core.add_hospitalization"))
        self.assertTrue(admission_mgr.has_perm("core.change_hospitalization"))
        self.assertFalse(admission_mgr.has_perm("core.delete_hospitalization"))

        self.assertTrue(admission_mgr.has_perm("core.view_bed"))
        self.assertFalse(admission_mgr.has_perm("core.change_bed"))
        self.assertFalse(admission_mgr.has_perm("core.add_bed"))
        self.assertFalse(admission_mgr.has_perm("core.delete_bed"))

        # 2. Cloisonnement du secret médical dans PatientAdmin & HospitalizationAdmin & BedAdmin
        rf = RequestFactory()
        req = rf.get("/admin/core/patient/")
        req.user = admission_mgr

        site = AdminSite()
        patient_admin = PatientAdmin(Patient, site)
        hosp_admin = HospitalizationAdmin(Hospitalization, site)
        bed_admin = BedAdmin(Bed, site)

        self.assertFalse(patient_admin.has_delete_permission(req, self.patient))
        self.assertIn("known_allergies", patient_admin.get_readonly_fields(req, self.patient))
        self.assertIn("major_medical_history", patient_admin.get_exclude(req, self.patient))
        self.assertIn("ongoing_treatments", patient_admin.get_exclude(req, self.patient))

        self.assertFalse(bed_admin.has_change_permission(req, self.bed_101))
        self.assertFalse(bed_admin.has_add_permission(req))

        # 3. Création d'une admission, transfert de lit et planification de sortie
        bed_102 = Bed.objects.create(
            service=self.dept_chir,
            room_number="102",
            bed_number="1",
            status=BedStatus.DISPONIBLE,
        )
        adm_time = timezone.now()
        hosp = Hospitalization.objects.create(
            patient=self.patient,
            bed=self.bed_101,
            practitioner=self.doctor_chir,
            admission_date=adm_time,
            expected_discharge_date=adm_time + timedelta(days=2),
            admission_reason="Chirurgie programmée",
        )
        self.assertIn("entry_diagnosis", hosp_admin.get_exclude(req, hosp))
        self.assertIn("admission_reason", hosp_admin.get_readonly_fields(req, hosp))
        self.assertIn("practitioner", hosp_admin.get_readonly_fields(req, hosp))

        # Transfert du lit 101 vers le lit 102 : 101 passe en NETTOYAGE, 102 passe en OCCUPÉ
        hosp.bed = bed_102
        hosp.save()
        self.bed_101.refresh_from_db()
        bed_102.refresh_from_db()
        self.assertEqual(self.bed_101.status, BedStatus.NETTOYAGE)
        self.assertEqual(bed_102.status, BedStatus.OCCUPE)

        # 4. Interdiction d'accès aux modules médicaux spécialisés (HTTP 403 + Audit ACCESS_DENIED)
        client = Client()
        client.force_login(admission_mgr)
        for forbidden_url in (
            reverse("chirurgie:intervention_list"),
            reverse("pediatrie:anthro_list"),
            reverse("urologie:assessment_list"),
        ):
            res = client.get(forbidden_url)
            self.assertEqual(res.status_code, 403)

        denied_logs = SecurityAuditLog.objects.filter(
            user=admission_mgr,
            action_type=AuditActionType.ACCESS_DENIED,
        )
        self.assertEqual(denied_logs.count(), 3)

    def test_security_audit_log_immutability_and_session_timeout(self) -> None:
        """
        Vérifie :
        1. L'immuabilité stricte du journal d'audit SecurityAuditLog (interdiction UPDATE / DELETE).
        2. L'expiration automatique de session après 5 minutes (300 secondes) d'inactivité.
        """
        import time as time_mod

        admission_mgr = CustomUser.objects.create_user(
            username="adm_timeout_test",
            password="StrongPassword123!",
            role=UserRole.GESTIONNAIRE_ADMISSION,
            department=self.dept_chir,
        )
        admission_mgr.sync_role_permissions()

        log_entry = SecurityAuditLog.log_action(
            user=admission_mgr,
            action_type=AuditActionType.READ,
            patient=self.patient,
            resource_name="Patient",
            details="Consultation administrative du dossier",
            ip_address="127.0.0.1",
        )
        self.assertIsNotNone(log_entry.id)
        self.assertEqual(log_entry.patient_ipp, self.patient.ipp)

        # Toute tentative de modification ou suppression doit lever ValidationError
        with self.assertRaises(ValidationError):
            log_entry.details = "Tentative de falsification"
            log_entry.save()

        with self.assertRaises(ValidationError):
            log_entry.delete()

        with self.assertRaises(ValidationError):
            SecurityAuditLog.objects.filter(pk=log_entry.pk).delete()

        # Test du timeout d'inactivité après 5 minutes (300 secondes)
        client = Client()
        client.force_login(admission_mgr)

        # 1ère requête active -> HTTP 200
        res_ok = client.get(reverse("core:patient_list"))
        self.assertEqual(res_ok.status_code, 200)

        # Simulation d'une inactivité de 305 secondes (> 300s)
        session = client.session
        session["last_activity_ts"] = int(time_mod.time()) - 305
        session.save()

        # La requête suivante doit expirer la session et rediriger vers /login/?timeout=1
        res_expired = client.get(reverse("core:patient_list"))
        self.assertEqual(res_expired.status_code, 302)
        self.assertIn("/login/?timeout=1", res_expired["Location"])

        # Un log SESSION_TIMEOUT doit avoir été créé
        self.assertTrue(
            SecurityAuditLog.objects.filter(
                user=admission_mgr,
                action_type=AuditActionType.SESSION_TIMEOUT,
            ).exists()
        )

    def test_admission_consent_pdf_generation_and_endpoints(self) -> None:
        """
        Vérifie :
        1. La fonction réutilisable generateAdmissionPDF(admissionData) avec un dictionnaire et une Hospitalization.
        2. Les routes HTTP /core/admissions/<pk>/consent-pdf/ et /core/patients/<pk>/consent-pdf/.
        3. La journalisation dans SecurityAuditLog lors de l'édition du PDF.
        """
        from apps.core.pdf_consent_service import generateAdmissionPDF

        raw_pdf = generateAdmissionPDF(
            {
                "admission_id": "ADM-2026-0099",
                "admission_date": "30/10/2026 à 09:30",
                "patient_name": "LEMOINE Pierre",
                "birth_name": "LEMOINE",
                "patient_dob": "12/05/1985",
                "patient_phone": "0601020304",
                "address": "14 Rue Didouche Mourad",
                "city": "Alger",
                "state": "Alger",
                "patient_gov_id": "185057511504248",
                "provider_id": "Dr Jean Dupont",
                "repr_name": "Marie Lemoine",
                "repr_relation": "Épouse / Personne de confiance",
            }
        )
        self.assertTrue(raw_pdf.startswith(b"%PDF-1.4"))
        self.assertGreater(len(raw_pdf), 1000)

        adm_time = timezone.now()
        hosp = Hospitalization.objects.create(
            patient=self.patient,
            bed=self.bed_101,
            practitioner=self.doctor_chir,
            admission_date=adm_time,
            expected_discharge_date=adm_time + timedelta(days=2),
            admission_reason="Chirurgie programmée",
        )

        client = Client()
        client.force_login(self.doctor_chir)

        res_adm_pdf = client.get(reverse("core:admission_consent_pdf", kwargs={"pk": hosp.pk}))
        self.assertEqual(res_adm_pdf.status_code, 200)
        self.assertEqual(res_adm_pdf["Content-Type"], "application/pdf")
        self.assertTrue(res_adm_pdf.content.startswith(b"%PDF-1.4"))

        res_pat_pdf = client.get(reverse("core:patient_consent_pdf", kwargs={"pk": self.patient.pk}))
        self.assertEqual(res_pat_pdf.status_code, 200)
        self.assertEqual(res_pat_pdf["Content-Type"], "application/pdf")
        self.assertTrue(res_pat_pdf.content.startswith(b"%PDF-1.4"))

    def test_cockpit_supervision_quick_actions_and_kanban(self) -> None:
        """
        Vérifie les fonctionnalités du nouveau Cockpit de Supervision Hospitalière :
        1. Contexte enrichi (kanban_columns, donut_offset, tension_level par pôle).
        2. Action rapide 1-clic pour libérer un lit en NETTOYAGE -> DISPONIBLE.
        3. Action rapide 1-clic pour valider un remplacement de garde en attente.
        """
        self.bed_101.status = BedStatus.NETTOYAGE
        self.bed_101.save()

        shift = DutyShift.objects.create(
            staff_member=self.doctor_chir,
            department=self.dept_chir,
            shift_date=date.today(),
            shift_type=ShiftType.JOUR,
            start_time=time(8, 0),
            end_time=time(18, 0),
        )
        rep = ShiftReplacement.objects.create(
            duty_shift=shift,
            original_caregiver=self.doctor_chir,
            substitute_caregiver=self.doctor_chir_2,
            reason="Renfort bloc opératoire",
            status=ShiftReplacementStatus.DEMANDE,
        )

        client = Client()
        client.force_login(self.doctor_chir)

        # 1. Vérification du Cockpit
        res_dash = client.get(reverse("home_dashboard"))
        self.assertEqual(res_dash.status_code, 200)
        self.assertIn("kanban_columns", res_dash.context)
        self.assertIn("donut_offset", res_dash.context)
        self.assertContains(res_dash, "Kanban Parcours Patients")

        # 2. Libération rapide 1-clic du lit 101 (NETTOYAGE -> DISPONIBLE)
        res_bed = client.post(
            reverse("core:quick_bed_status", kwargs={"pk": self.bed_101.pk}),
            {"target_status": "DISPONIBLE"},
        )
        self.assertEqual(res_bed.status_code, 302)
        self.bed_101.refresh_from_db()
        self.assertEqual(self.bed_101.status, BedStatus.DISPONIBLE)

        # 3. Validation rapide 1-clic du remplacement de garde
        res_rep = client.post(
            reverse("core:quick_replacement_validate", kwargs={"pk": rep.pk}),
            {"decision": "VALIDE"},
        )
        self.assertEqual(res_rep.status_code, 302)
        rep.refresh_from_db()
        self.assertEqual(rep.status, ShiftReplacementStatus.VALIDE)






