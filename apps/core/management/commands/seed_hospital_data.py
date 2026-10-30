"""
Commande Django de peuplement de données de démonstration (Seeding).
Génère une structure hospitalière complète, réaliste et conforme HDS :
- Départements hospitaliers
- Personnel médical typé (RBAC)
- Lits avec statuts variés (Disponible, Occupé, Nettoyage)
- Patients (DPI) avec NIR valides
- Hospitalisations actives
- Planning des gardes pour la semaine courante avec remplacements
- Données médicales pour Chirurgie, Gynéco-Maternité, Pédiatrie et Urologie
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core.models import (
    Appointment,
    AppointmentStatus,
    Bed,
    BedStatus,
    BloodGroup,
    CustomUser,
    Department,
    DutyShift,
    Hospitalization,
    HospitalizationStatus,
    Patient,
    PatientStatusConfig,
    PatientStatusHistory,
    ShiftReplacement,
    ShiftReplacementStatus,
    ShiftType,
    UserRole,
)
from apps.chirurgie.models import (
    InterventionStatus,
    OperatingRoom,
    OperativeReport,
    SafetyChecklistOMS,
    SurgicalIntervention,
    SurgicalPriority,
)
from apps.gynecologie_maternite.models import (
    DeliveryMode,
    DeliveryRegistry,
    GynecologicalHistory,
    PregnancyStatus,
    PregnancyTracking,
    RoutineConsultation,
)
from apps.pediatrie.models import (
    AnthropometricRecord,
    VaccinationRecord,
    VaccineStatus,
)
from apps.urologie.models import (
    SpecializedInterventionReport,
    UrodynamicAssessment,
    UrologicalHistory,
    UrologicalInterventionType,
)


class Command(BaseCommand):
    help = "Peuple la base de données hospitalière avec des jeux de données réalistes."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Initialisation du peuplement des données hospitalières..."))

        # 1. Départements
        depts_def = [
            {"code": "CHIR", "name": "Pôle Chirurgie Viscérale & Bloc", "building": "Bâtiment A", "floor": 2},
            {"code": "MAT", "name": "Gynécologie & Maternité", "building": "Bâtiment B", "floor": 1},
            {"code": "PED", "name": "Pôle Pédiatrie & Néonatalogie", "building": "Bâtiment B", "floor": 2},
            {"code": "URO", "name": "Pôle Urologie & Néphrologie", "building": "Bâtiment C", "floor": 3},
            {"code": "URG", "name": "Service des Urgences Médico-Chirurgicales", "building": "Bâtiment A", "floor": 0},
        ]
        departments = {}
        for d in depts_def:
            dept, _ = Department.objects.get_or_create(code=d["code"], defaults=d)
            departments[d["code"]] = dept

        # 2. Superutilisateur & Personnel Médical
        if not CustomUser.objects.filter(username="admin").exists():
            CustomUser.objects.create_superuser(
                username="admin",
                email="admin.sih@chu-hopital.fr",
                password="AdminPassword123!",
                first_name="Directeur",
                last_name="Médical",
                role=UserRole.ADMIN,
                department=departments["CHIR"],
            )
            self.stdout.write(self.style.SUCCESS("Superadministrateur créé : admin / AdminPassword123!"))

        users_def = [
            ("dr_alain_chir", "Alain", "Rousseau", UserRole.CHIRURGIEN, "CHIR", "RPPS-1010101"),
            ("dr_sophie_chir", "Sophie", "Mercier", UserRole.CHIRURGIEN, "CHIR", "RPPS-1010102"),
            ("inf_paul_chir", "Paul", "Lefevre", UserRole.INFIRMIER, "CHIR", "RPPS-1010103"),
            ("dr_claire_mat", "Claire", "Dufour", UserRole.MEDECIN, "MAT", "RPPS-2020201"),
            ("sf_elodie_mat", "Élodie", "Giraud", UserRole.SAGE_FEMME, "MAT", "RPPS-2020202"),
            ("dr_marc_ped", "Marc", "Fontaine", UserRole.MEDECIN, "PED", "RPPS-3030301"),
            ("inf_julie_ped", "Julie", "Boucher", UserRole.INFIRMIER, "PED", "RPPS-3030302"),
            ("dr_yves_uro", "Yves", "Carpentier", UserRole.CHIRURGIEN, "URO", "RPPS-4040401"),
            ("dr_anne_uro", "Anne", "Lambert", UserRole.MEDECIN, "URO", "RPPS-4040402"),
            ("sec_nadia", "Nadia", "Benali", UserRole.SECRETAIRE, "URG", "ADELI-5050501"),
            ("adm_karim", "Karim", "Mansouri", UserRole.GESTIONNAIRE_ADMISSION, "URG", "ADELI-6060601"),
        ]

        users = {}
        for uname, fn, ln, role, dcode, rpps in users_def:
            u, _ = CustomUser.objects.update_or_create(
                username=uname,
                defaults={
                    "first_name": fn,
                    "last_name": ln,
                    "role": role,
                    "department": departments[dcode],
                    "license_number": rpps,
                    "email": f"{uname}@chu-hopital.fr",
                    "is_active": True,
                    "is_staff": True,
                },
            )
            u.set_password("HospitalPass123!")
            u.save()
            u.sync_role_permissions()
            users[uname] = u

        # Synchroniser également tous les autres utilisateurs existants dans la base
        for existing_user in CustomUser.objects.all():
            existing_user.save()
            existing_user.sync_role_permissions()

        # 3. Lits par service
        for dept_code, dept in departments.items():
            for room in ["101", "102", "103"]:
                for bed_idx in ["1", "2"]:
                    Bed.objects.get_or_create(
                        service=dept,
                        room_number=room,
                        bed_number=bed_idx,
                        defaults={"status": BedStatus.DISPONIBLE},
                    )

        # 4. Paramétrage des 7 Statuts Patients par défaut & Patients (DPI)
        status_map = PatientStatusConfig.ensure_default_statuses()

        patients_def = [
            ("185057511504248", "Dubois", "Mathieu", "Dubois", date(1985, 5, 12), "M", BloodGroup.A_POS, "Pénicilline", "REVEIL", "12 Rue Didouche Mourad", "Sidi Yahia", "Alger", "CI-10948271", "Claire Dubois", "Épouse"),
            ("292037511504291", "Martin", "Aurélie", "Laurent", date(1992, 3, 14), "F", BloodGroup.O_POS, "Iode", "SERVICE", "45 Boulevard Krim Belkacem", "Hydra", "Alger", "CI-20849103", "Thomas Martin", "Conjoint"),
            ("160047511504229", "Bernard", "Christian", "Bernard", date(1960, 4, 20), "M", BloodGroup.B_POS, "Aucune", "SORTIE", "8 Chemin Mackley", "Ben Aknoun", "Alger", "CI-30491822", "Nadia Bernard", "Fille majeure"),
            ("125067511504261", "Petit", "Tom", "Petit", date(2025, 6, 1), "M", BloodGroup.A_NEG, "Aucune", "ADMISSION", "22 Lotissement Sidi Yahia", "Bir Mourad Raïs", "Alger", "CI-40192834", "Sophie Petit", "Mère / Représentante légale"),
        ]
        patients = []
        for nir, ln, fn, mname, bdate, gender, bg, allergies, target_st_code, addr, city, state_prov, cid, tp_name, tp_rel in patients_def:
            p, _ = Patient.objects.update_or_create(
                nir=nir,
                defaults={
                    "last_name": ln,
                    "first_name": fn,
                    "maiden_name": mname,
                    "birth_date": bdate,
                    "gender": gender,
                    "blood_group": bg,
                    "known_allergies": allergies,
                    "phone": "0612345678",
                    "address": addr,
                    "city": city,
                    "state_province": state_prov,
                    "national_id_number": cid,
                    "trusted_person_name": tp_name,
                    "trusted_person_relation": tp_rel,
                },
            )
            if not p.status_history.exists():
                PatientStatusHistory.objects.create(
                    patient=p,
                    old_status=None,
                    new_status=status_map["ADMISSION"],
                    changed_by=users["sec_nadia"],
                    comment="Admission administrative et création du bracelet patient.",
                    changed_at=timezone.now() - timedelta(hours=6),
                )
                if target_st_code == "REVEIL":
                    p.change_status(status_map["SERVICE"], users["inf_paul_chir"], "Installation en Chambre 101 (Chirurgie).")
                    p.change_status(status_map["BLOC"], users["dr_alain_chir"], "Entrée en Salle BLOC-1 (Cholécystectomie).")
                    p.change_status(status_map["REVEIL"], users["dr_alain_chir"], "Transfert SSPI après intervention sans incident.")
                elif target_st_code == "SERVICE":
                    p.change_status(status_map["SERVICE"], users["sf_elodie_mat"], "Installation en Chambre 101 (Maternité).")
                elif target_st_code == "SORTIE":
                    p.change_status(status_map["SERVICE"], users["dr_yves_uro"], "Prise en charge service Urologie.")
                    p.change_status(status_map["SORTIE"], users["dr_yves_uro"], "Sortie médicale validée avec ordonnance.")
            elif not p.current_status_id:
                p.current_status = status_map[target_st_code]
                p.status_updated_at = timezone.now()
                p.save(update_fields=["current_status", "status_updated_at"])

            patients.append(p)

        # 5. Hospitalisations & Statut des Lits
        # Lit 1 Chirurgie -> OCCUPÉ
        bed_chir_1 = Bed.objects.filter(service=departments["CHIR"], room_number="101", bed_number="1").first()
        if bed_chir_1 and not Hospitalization.objects.filter(bed=bed_chir_1, actual_discharge_date__isnull=True).exists():
            hosp_active = Hospitalization(
                patient=patients[0],
                bed=bed_chir_1,
                practitioner=users["dr_alain_chir"],
                admission_date=timezone.now() - timedelta(days=1),
                expected_discharge_date=timezone.now() + timedelta(days=3),
                admission_reason="Chirurgie programmée (Cholécystectomie)",
                entry_diagnosis="Lithiase biliaire compliquée",
            )
            hosp_active.full_clean()
            hosp_active.save()

        # Lit 2 Chirurgie -> Clôturé et passé en NETTOYAGE
        bed_chir_2 = Bed.objects.filter(service=departments["CHIR"], room_number="101", bed_number="2").first()
        if bed_chir_2 and not Hospitalization.objects.filter(bed=bed_chir_2).exists():
            hosp_past = Hospitalization(
                patient=patients[2],
                bed=bed_chir_2,
                practitioner=users["dr_yves_uro"],
                admission_date=timezone.now() - timedelta(days=4),
                expected_discharge_date=timezone.now() - timedelta(days=1),
                actual_discharge_date=timezone.now() - timedelta(hours=3),
                admission_reason="Hospitalisation programmée Urologie",
                entry_diagnosis="Colique néphrétique résolutive",
            )
            hosp_past.full_clean()
            hosp_past.save()

        # Lit 1 Maternité -> OCCUPÉ
        bed_mat_1 = Bed.objects.filter(service=departments["MAT"], room_number="101", bed_number="1").first()
        if bed_mat_1 and not Hospitalization.objects.filter(bed=bed_mat_1, actual_discharge_date__isnull=True).exists():
            hosp_mat = Hospitalization(
                patient=patients[1],
                bed=bed_mat_1,
                practitioner=users["dr_claire_mat"],
                admission_date=timezone.now() - timedelta(hours=18),
                expected_discharge_date=timezone.now() + timedelta(days=2),
                admission_reason="Séjour Maternité programmé",
                entry_diagnosis="Suivi post-partum",
            )
            hosp_mat.full_clean()
            hosp_mat.save()

        # Mise à jour des médecins référents sur les séjours existants
        Hospitalization.objects.filter(patient=patients[0], practitioner__isnull=True).update(practitioner=users["dr_alain_chir"])
        Hospitalization.objects.filter(patient=patients[1], practitioner__isnull=True).update(practitioner=users["dr_claire_mat"])
        Hospitalization.objects.filter(patient=patients[2], practitioner__isnull=True).update(practitioner=users["dr_yves_uro"])

        # 6. Planning hebdomadaire des gardes
        today = timezone.now().date()
        monday = today - timedelta(days=today.weekday())

        for day_offset in range(7):
            current_day = monday + timedelta(days=day_offset)

            # Gardes Chirurgie
            s_chir_jour, _ = DutyShift.objects.get_or_create(
                staff_member=users["dr_alain_chir"],
                department=departments["CHIR"],
                shift_date=current_day,
                shift_type=ShiftType.JOUR,
                defaults={"start_time": time(8, 0), "end_time": time(18, 0)},
            )
            s_chir_nuit, _ = DutyShift.objects.get_or_create(
                staff_member=users["dr_sophie_chir"],
                department=departments["CHIR"],
                shift_date=current_day,
                shift_type=ShiftType.NUIT,
                defaults={"start_time": time(18, 0), "end_time": time(8, 0)},
            )

            # Remplacement le mercredi en Chirurgie (Validé entre soignants du même département)
            if day_offset == 2:
                ShiftReplacement.objects.get_or_create(
                    duty_shift=s_chir_jour,
                    original_caregiver=users["dr_alain_chir"],
                    substitute_caregiver=users["dr_sophie_chir"],
                    defaults={
                        "status": ShiftReplacementStatus.VALIDE,
                        "validation_date": timezone.now(),
                        "reason": "Permutation acceptée pour congrès médical",
                    },
                )

            # Gardes Maternité
            DutyShift.objects.get_or_create(
                staff_member=users["dr_claire_mat"],
                department=departments["MAT"],
                shift_date=current_day,
                shift_type=ShiftType.JOUR,
                defaults={"start_time": time(8, 0), "end_time": time(18, 0)},
            )
            DutyShift.objects.get_or_create(
                staff_member=users["sf_elodie_mat"],
                department=departments["MAT"],
                shift_date=current_day,
                shift_type=ShiftType.GARDE_24H,
                defaults={"start_time": time(8, 0), "end_time": time(8, 0)},
            )

            # Gardes Pédiatrie
            DutyShift.objects.get_or_create(
                staff_member=users["dr_marc_ped"],
                department=departments["PED"],
                shift_date=current_day,
                shift_type=ShiftType.ASTREINTE,
                defaults={"start_time": time(18, 0), "end_time": time(8, 0)},
            )

            # Gardes Urologie
            DutyShift.objects.get_or_create(
                staff_member=users["dr_yves_uro"],
                department=departments["URO"],
                shift_date=current_day,
                shift_type=ShiftType.JOUR,
                defaults={"start_time": time(8, 0), "end_time": time(18, 0)},
            )

        # 7. Chirurgie : Bloc et Checklist OMS
        op_room, _ = OperatingRoom.objects.get_or_create(
            code="BLOC-1",
            defaults={"name": "Salle Laparoscopique 1", "equipment_summary": "Tour vidéo 4K, Colonne cœlio"},
        )
        intervention, _ = SurgicalIntervention.objects.get_or_create(
            patient=patients[0],
            operating_room=op_room,
            lead_surgeon=users["dr_alain_chir"],
            defaults={
                "scheduled_start": timezone.now() - timedelta(hours=5),
                "scheduled_end": timezone.now() - timedelta(hours=3),
                "procedure_name": "Cholécystectomie sous cœlioscopie",
                "surgical_indication": "Lithiase vésiculaire symptomatique",
                "priority": SurgicalPriority.PROGRAMMEE,
                "status": InterventionStatus.TERMINEE,
            },
        )
        if not hasattr(intervention, "safety_checklist"):
            SafetyChecklistOMS.objects.create(
                intervention=intervention,
                signin_patient_identity_confirmed=True,
                signin_site_marked=True,
                signin_consent_verified=True,
                signin_allergy_risk_checked=True,
                signin_airway_risk_evaluated=True,
                signin_bleeding_risk_evaluated=True,
                signin_completed_by="Dr Rousseau / IADE",
                timeout_team_introduced=True,
                timeout_reconfirmation_procedure=True,
                timeout_antibiotic_prophylaxis=True,
                timeout_critical_steps_reviewed=True,
                timeout_sterility_confirmed=True,
                timeout_imaging_displayed=True,
                timeout_completed_by="Dr Rousseau",
                signout_procedure_confirmed=True,
                signout_instrument_count_correct=True,
                signout_specimen_labeled=True,
                signout_postop_plan_reviewed=True,
                signout_completed_by="IBODE",
                is_fully_validated=True,
            )
        if not hasattr(intervention, "operative_report"):
            OperativeReport.objects.create(
                intervention=intervention,
                author_surgeon=users["dr_alain_chir"],
                surgical_approach="Cœlioscopie 4 trocarts",
                findings="Vésicule alithiasique distendue avec calculs infundibulaires",
                procedure_description="Dissection du triangle de Calot, clip du canal cystique et de l'artère, extraction.",
                estimated_blood_loss_ml=30,
                implanted_devices_lot_numbers="Clips titane Hem-o-lok Lot 2026-T99",
                postoperative_instructions="Surveillance SSPI 2 heures, reprise alimentation H+4.",
            )

        # 8. Maternité : Grossesse & Accouchement
        preg, _ = PregnancyTracking.objects.get_or_create(
            patient=patients[1],
            defaults={
                "last_menstrual_period": date(2025, 11, 20),
                "estimated_due_date": date(2025, 11, 20) + timedelta(days=280),
                "status": PregnancyStatus.ACCOUCHEE,
            },
        )
        if not DeliveryRegistry.objects.filter(pregnancy=preg).exists():
            DeliveryRegistry.objects.create(
                pregnancy=preg,
                patient=patients[1],
                attending_obstetrician=users["dr_claire_mat"],
                midwife=users["sf_elodie_mat"],
                delivery_datetime=timezone.now() - timedelta(hours=18),
                delivery_mode=DeliveryMode.VOIE_BASSE_SPONTANEE,
                infant_gender="F",
                birth_weight_grams=3420,
                birth_length_cm=Decimal("51.0"),
                cranial_perimeter_cm=Decimal("35.5"),
                apgar_1min=10,
                apgar_5min=10,
            )

        # 9. Pédiatrie : Relevé et vaccins
        AnthropometricRecord.objects.get_or_create(
            patient=patients[3],
            measurement_date=date.today(),
            defaults={
                "recorded_by": users["dr_marc_ped"],
                "age_in_months": 15,
                "weight_kg": Decimal("10.80"),
                "height_cm": Decimal("78.5"),
                "cranial_perimeter_cm": Decimal("47.2"),
                "body_mass_index": Decimal("17.5"),
            },
        )
        VaccinationRecord.objects.get_or_create(
            patient=patients[3],
            vaccine_name="ROR (Rougeole-Oreillons-Rubéole)",
            defaults={
                "target_age_months": 12,
                "recommended_due_date": date.today() - timedelta(days=90),
                "administration_date": date.today() - timedelta(days=85),
                "batch_number": "ROR-2026-V88",
                "administering_doctor": users["dr_marc_ped"],
                "status": VaccineStatus.EFFECTUE,
            },
        )

        # 10. Urologie : BUD & Acte
        UrodynamicAssessment.objects.get_or_create(
            patient=patients[2],
            defaults={
                "urologist": users["dr_yves_uro"],
                "clinical_indication": "Dysurie et débitmétrie faible",
                "qmax_flow_rate_ml_s": Decimal("8.7"),
                "voided_volume_ml": 210,
                "post_void_residual_ml": 75,
                "maximum_cystometric_capacity_ml": 380,
                "pdet_qmax_cmh2o": Decimal("70.0"),
                "conclusion_diagnosis": "Syndrome obstructif prostatique net (HBP)",
            },
        )
        SpecializedInterventionReport.objects.get_or_create(
            patient=patients[2],
            defaults={
                "surgeon": users["dr_yves_uro"],
                "intervention_type": UrologicalInterventionType.URETEROSCOPIE_SOUPLE,
                "double_j_stent_inserted": True,
                "stent_side": "DROITE",
                "stent_removal_scheduled_date": date.today() + timedelta(days=21),
                "stone_fragmentation_method": "Laser Holmium 30W",
                "stone_size_mm": 12,
                "postop_drainage": "Sonde vésicale CH16 maintenue 24h",
                "operative_notes": "Urétéroscopie droite rétrograde, fragmentation complète de la lithiase pyélique.",
            },
        )

        self.stdout.write(self.style.SUCCESS("Peuplement complet de la base de données hospitalière achevé avec succès !"))

