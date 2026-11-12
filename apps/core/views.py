"""
Vues de l'application Core : Dashboard hospitalier hebdomadaire en temps réel.
Extraction de la capacité des lits par service et matrice des gardes et astreintes.
"""

from datetime import date, datetime, timedelta
import json
from typing import Any, Dict, List

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import ListView, TemplateView

from .excel_utils import (
    build_csv_bytes,
    build_xlsx_bytes,
    first_non_empty,
    generate_valid_nir_for_patient,
    parse_excel_or_csv_bytes,
    parse_flexible_date,
)
from .models import (
    AuditActionType,
    Bed,
    BedStatus,
    BloodGroup,
    CustomUser,
    Department,
    DutyShift,
    Hospitalization,
    Patient,
    PatientStatusColor,
    PatientStatusConfig,
    PatientStatusHistory,
    SecurityAuditLog,
    ShiftReplacement,
    ShiftReplacementStatus,
    ShiftType,
    UserRole,
)
from .pdf_consent_service import generate_admission_consent_pdf


def ensure_specialized_role_accounts() -> None:
    """
    Garantit l'existence des comptes de démonstration RBAC pour :
    - Gestionnaire de la Pharmacie (`pharm_salim` / `HospitalPass123!`)
    - Gestionnaire de la Facturation (`fact_amina` / `HospitalPass123!`)
    """
    accounts = [
        {
            "username": "pharm_salim",
            "first_name": "Dr Salim",
            "last_name": "Boudiaf (Pharmacien Chef)",
            "email": "s.boudiaf@clinique-sidiyahia2.dz",
            "role": UserRole.GESTIONNAIRE_PHARMACIE,
        },
        {
            "username": "fact_amina",
            "first_name": "Amina",
            "last_name": "Khelifi (Resp. Facturation & CNAS)",
            "role": UserRole.GESTIONNAIRE_FACTURATION,
            "email": "a.khelifi@clinique-sidiyahia2.dz",
        },
    ]
    for acc in accounts:
        user, created = CustomUser.objects.get_or_create(
            username=acc["username"],
            defaults={
                "first_name": acc["first_name"],
                "last_name": acc["last_name"],
                "email": acc["email"],
                "role": acc["role"],
                "is_staff": True,
                "is_active": True,
            },
        )
        if created or user.role != acc["role"]:
            user.role = acc["role"]
            user.is_staff = True
            user.is_active = True
            user.set_password("HospitalPass123!")
            user.save()
            user.sync_role_permissions()


class HospitalLoginView(LoginView):
    """
    Portail d'authentification unifié pour tous les utilisateurs du SIH
    (Administrateur, Chirurgien, Médecin, Sage-Femme, Infirmier, Secrétaire,
    Gestionnaire Admission, Gestionnaire Pharmacie, Gestionnaire Facturation).
    """

    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        try:
            ensure_specialized_role_accounts()
        except Exception:
            pass
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["role_choices"] = UserRole.choices
        return context


def hospital_logout_view(request: HttpRequest) -> HttpResponse:
    """Déconnecte l'utilisateur et redirige vers la page de login."""
    logout(request)
    return redirect("login")


ROLE_PORTAL_CONFIG: Dict[str, Dict[str, Any]] = {
    UserRole.ADMIN: {
        "badge_class": "bg-purple-100 text-purple-800 border-purple-200",
        "description": "Supervision intégrale du SIH : Gestion du personnel, Pharmacie (FEFO), Facturation Algérienne (NGAP/CNAS/DGI), tous les pôles cliniques, DPI et lits.",
        "actions": [
            {"label": "⚙️ Paramètres de la Clinique", "url": "/core/clinic-settings/"},
            {"label": "Suivi & Statuts Patients", "url": "/core/patients/"},
            {"label": "Facturation & Tiers-Payant", "url": "/facturation/"},
            {"label": "Paramétrage Facturation", "url": "/facturation/?tab=fiscalite_dz"},
            {"label": "Pharmacie & Stocks (FEFO)", "url": "/pharmacie/"},
            {"label": "Gestion du Personnel & Rôles", "url": "/admin/core/customuser/"},
            {"label": "Pôle Chirurgie & Bloc", "url": "/chirurgie/intervention/"},
            {"label": "Pôle Pédiatrie", "url": "/pediatrie/anthropometry/"},
            {"label": "Pôle Urologie", "url": "/urologie/intervention/"},
            {"label": "Validation Remplacements", "url": "/admin/core/shiftreplacement/"},
        ],
    },
    UserRole.CHIRURGIEN: {
        "badge_class": "bg-rose-100 text-rose-800 border-rose-200",
        "description": "Accès Chirurgical & Bloc Opératoire : Interventions, Checklists OMS, Comptes-rendus opératoires (CRO), Urologie et Statuts Patients.",
        "actions": [
            {"label": "Suivi & Statuts Patients", "url": "/core/patients/"},
            {"label": "Patients au Bloc", "url": "/core/patients/?status=BLOC"},
            {"label": "Bloc & Interventions", "url": "/chirurgie/intervention/"},
            {"label": "Nouvelle Intervention", "url": "/chirurgie/intervention/create/"},
            {"label": "Actes Urologiques", "url": "/urologie/intervention/"},
            {"label": "Mes Rendez-vous", "url": "/admin/core/appointment/"},
        ],
    },
    UserRole.MEDECIN: {
        "badge_class": "bg-sky-100 text-sky-800 border-sky-200",
        "description": "Accès Médical Praticien : Suivi des Statuts Patients, Consultations, DPI, Hospitalisations, Pédiatrie, Maternité et Urologie.",
        "actions": [
            {"label": "Suivi & Statuts Patients", "url": "/core/patients/"},
            {"label": "Consultations & RDV", "url": "/admin/core/appointment/"},
            {"label": "Hospitalisations", "url": "/admin/core/hospitalization/"},
            {"label": "Suivi Pédiatrique", "url": "/pediatrie/anthropometry/"},
            {"label": "Bilans Urodynamiques", "url": "/urologie/assessment/"},
            {"label": "Suivi Grossesses", "url": "/admin/gynecologie_maternite/pregnancytracking/"},
        ],
    },
    UserRole.SAGE_FEMME: {
        "badge_class": "bg-pink-100 text-pink-800 border-pink-200",
        "description": "Accès Gynécologie-Obstétrique & Salle de Naissance : Suivi de grossesse, Registre d'accouchements (APGAR) et Statuts Patientes.",
        "actions": [
            {"label": "Suivi & Statuts Patientes", "url": "/core/patients/"},
            {"label": "Registre Accouchements", "url": "/admin/gynecologie_maternite/deliveryregistry/"},
            {"label": "Suivi des Grossesses", "url": "/admin/gynecologie_maternite/pregnancytracking/"},
            {"label": "Consultations Maternité", "url": "/admin/gynecologie_maternite/routineconsultation/"},
            {"label": "Biométrie Nouveau-nés", "url": "/pediatrie/anthropometry/"},
        ],
    },
    UserRole.INFIRMIER: {
        "badge_class": "bg-emerald-100 text-emerald-800 border-emerald-200",
        "description": "Accès Soins Infirmiers (IDE / IBODE) : Mise à jour des statuts patients (Service / Bloc / Réveil), État des lits et Soins.",
        "actions": [
            {"label": "Suivi & Statuts Patients", "url": "/core/patients/"},
            {"label": "Patients en Réveil (SSPI)", "url": "/core/patients/?status=REVEIL"},
            {"label": "Statut & Désinfection des Lits", "url": "/admin/core/bed/"},
            {"label": "Calendrier Vaccinal", "url": "/pediatrie/vaccination/"},
            {"label": "Relevés Anthropométriques", "url": "/pediatrie/anthropometry/"},
            {"label": "Checklists Bloc OMS", "url": "/admin/chirurgie/safetychecklistoms/"},
        ],
    },
    UserRole.SECRETAIRE: {
        "badge_class": "bg-amber-100 text-amber-800 border-amber-200",
        "description": "Accès Secrétariat Médical & Admissions : Création des Dossiers Patients (DPI), Statuts d'Admission/Sortie et Rendez-vous.",
        "actions": [
            {"label": "Suivi & Statuts Patients", "url": "/core/patients/"},
            {"label": "Nouveau Patient (DPI)", "url": "/admin/core/patient/add/"},
            {"label": "Planifier un Rendez-vous", "url": "/admin/core/appointment/add/"},
            {"label": "Agenda des Rendez-vous", "url": "/admin/core/appointment/"},
            {"label": "Nouvelle Admission", "url": "/admin/core/hospitalization/add/"},
        ],
    },
    UserRole.GESTIONNAIRE_ADMISSION: {
        "badge_class": "bg-indigo-100 text-indigo-800 border-indigo-200",
        "description": "Gestionnaire des Admissions et Hospitalisations (Moindre Privilège HDS/RGPD) : Dossier administratif (CRU sans suppression), Admissions, Transferts de lits, Sorties et Occupation des lits en temps réel.",
        "actions": [
            {"label": "Suivi & Statuts Patients", "url": "/core/patients/"},
            {"label": "Nouveau Dossier Administratif", "url": "/admin/core/patient/add/"},
            {"label": "Nouvelle Admission / Séjour", "url": "/admin/core/hospitalization/add/"},
            {"label": "Transferts & Sorties", "url": "/admin/core/hospitalization/"},
            {"label": "Occupation des Lits (Lecture seule)", "url": "/admin/core/bed/"},
        ],
    },
    UserRole.GESTIONNAIRE_PHARMACIE: {
        "badge_class": "bg-teal-100 text-teal-800 border-teal-300",
        "description": "Gestionnaire de la Pharmacie Hospitalière & Achats : Pilotage des stocks par lots (FEFO), consommation de médicaments par malade (report automatique sur facture), bons de commande, réceptions douchette (PMP) et inventaire tournant.",
        "actions": [
            {"label": "💊 Cockpit Pharmacie & Stocks (FEFO)", "url": "/pharmacie/"},
            {"label": "🏥 Consommation Médicament Malade", "url": "/pharmacie/?tab=catalogue&open_conso=1"},
            {"label": "🛒 Suggestions & Bons de Commande", "url": "/pharmacie/?tab=achats"},
            {"label": "🔫 Réception Livraisons (Douchette)", "url": "/pharmacie/?tab=reception"},
            {"label": "📋 Inventaire Tournant & Audit Stupéfiants", "url": "/pharmacie/?tab=inventaire"},
            {"label": "🧾 Consulter Factures Patients", "url": "/facturation/"},
        ],
    },
    UserRole.GESTIONNAIRE_FACTURATION: {
        "badge_class": "bg-emerald-100 text-emerald-800 border-emerald-300",
        "description": "Gestionnaire de la Facturation & Tiers-Payant Algérie : Facturation NGAP & Pharmacie PPA (FEFO), TVA 9%/19%, Droit de Timbre Espèces vs CIB/Edahabia, conventions CNAS/CASNOS, bordereaux caisses et paramétrage fiscal DGI (NIF/NIS/RC/AI).",
        "actions": [
            {"label": "🧾 Cockpit Facturation Algérie", "url": "/facturation/"},
            {"label": "⚙️ Paramétrage Facturation & Fiscalité DGI", "url": "/facturation/?tab=fiscalite_dz"},
            {"label": "🩺 Paramétrage NGAP & Rétrocession Médecins", "url": "/facturation/?tab=ngap_retro"},
            {"label": "🏛️ Tiers-Payant CNAS/CASNOS & Bordereaux", "url": "/facturation/?tab=tiers_payant"},
            {"label": "💊 Pharmacie & Tarifs PPA", "url": "/pharmacie/"},
            {"label": "👤 Suivi Patients", "url": "/core/patients/"},
        ],
    },
}


class WeeklyDashboardView(LoginRequiredMixin, TemplateView):
    """
    Tableau de bord hospitalier interactif :
    1. État en temps réel de la capacité des lits (Total, Disponibles, Occupés, En nettoyage).
    2. Planning dynamique des gardes et astreintes de la semaine courante avec remplacements validés.
    """

    template_name = "dashboard/weekly_dashboard.html"

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)
        request = self.request

        # -------------------------------------------------------------------------
        # 1. Gestion du calendrier hebdomadaire (Lundi -> Dimanche)
        # -------------------------------------------------------------------------
        week_param = request.GET.get("week")
        if week_param:
            try:
                ref_date = datetime.strptime(week_param, "%Y-%m-%d").date()
            except ValueError:
                ref_date = timezone.now().date()
        else:
            ref_date = timezone.now().date()

        # Calcul du lundi et du dimanche de la semaine demandée
        monday = ref_date - timedelta(days=ref_date.weekday())
        sunday = monday + timedelta(days=6)

        prev_week_str = (monday - timedelta(days=7)).strftime("%Y-%m-%d")
        next_week_str = (monday + timedelta(days=7)).strftime("%Y-%m-%d")
        today = timezone.now().date()

        # Liste des 7 jours de la semaine
        french_day_names = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
        week_days: List[Dict[str, Any]] = []
        for i in range(7):
            current_day = monday + timedelta(days=i)
            week_days.append({
                "date": current_day,
                "date_str": current_day.strftime("%Y-%m-%d"),
                "name": french_day_names[i],
                "short_name": french_day_names[i][:3],
                "formatted": current_day.strftime("%d/%m"),
                "is_today": current_day == today,
            })

        # -------------------------------------------------------------------------
        # 2. Capacité des Lits en Temps Réel
        # -------------------------------------------------------------------------
        total_beds = Bed.objects.count()
        occupied_beds = Bed.objects.filter(status=BedStatus.OCCUPE).count()
        cleaning_beds = Bed.objects.filter(status=BedStatus.NETTOYAGE).count()
        available_beds = Bed.objects.filter(status=BedStatus.DISPONIBLE).count()
        maintenance_beds = Bed.objects.filter(status=BedStatus.MAINTENANCE).count()

        occupancy_rate = round((occupied_beds / total_beds * 100), 1) if total_beds > 0 else 0.0

        # Répartition des lits par département avec détails
        departments_data = []
        departments = Department.objects.filter(is_active=True).prefetch_related("beds")

        selected_dept_id = request.GET.get("department")

        for dept in departments:
            dept_beds = list(dept.beds.all())
            dept_total = len(dept_beds)
            dept_occupied = sum(1 for b in dept_beds if b.status == BedStatus.OCCUPE)
            dept_cleaning = sum(1 for b in dept_beds if b.status == BedStatus.NETTOYAGE)
            dept_available = sum(1 for b in dept_beds if b.status == BedStatus.DISPONIBLE)

            occupied_pct = round((dept_occupied / dept_total * 100), 1) if dept_total > 0 else 0.0
            cleaning_pct = round((dept_cleaning / dept_total * 100), 1) if dept_total > 0 else 0.0
            available_pct = round((dept_available / dept_total * 100), 1) if dept_total > 0 else 0.0

            if occupied_pct >= 85:
                tension_level = "CRITIQUE"
                tension_label = "Tension Élevée"
                tension_badge = "bg-rose-100 text-rose-800 border-rose-200"
            elif occupied_pct >= 60:
                tension_level = "MODERE"
                tension_label = "Charge Modérée"
                tension_badge = "bg-amber-100 text-amber-800 border-amber-200"
            else:
                tension_level = "NORMAL"
                tension_label = "Capacité Fluide"
                tension_badge = "bg-emerald-100 text-emerald-800 border-emerald-200"

            today_staff_count = DutyShift.objects.filter(
                department=dept,
                shift_date=today,
                is_cancelled=False,
            ).count()

            # Détail des lits du département avec patient si occupé
            beds_list = []
            for b in dept_beds:
                active_hosp = None
                if b.status == BedStatus.OCCUPE:
                    active_hosp = Hospitalization.objects.filter(
                        bed=b, actual_discharge_date__isnull=True
                    ).select_related("patient", "practitioner", "patient__current_status").first()

                beds_list.append({
                    "bed": b,
                    "active_hospitalization": active_hosp,
                })

            departments_data.append({
                "department": dept,
                "total": dept_total,
                "occupied": dept_occupied,
                "cleaning": dept_cleaning,
                "available": dept_available,
                "occupied_pct": occupied_pct,
                "cleaning_pct": cleaning_pct,
                "available_pct": available_pct,
                "tension_level": tension_level,
                "tension_label": tension_label,
                "tension_badge": tension_badge,
                "today_staff_count": today_staff_count,
                "beds": beds_list,
            })

        # -------------------------------------------------------------------------
        # 3. Matrice Hebdomadaire des Gardes et Astreintes
        # -------------------------------------------------------------------------
        shifts_query = (
            DutyShift.objects.filter(
                shift_date__range=[monday, sunday],
                is_cancelled=False,
            )
            .select_related("staff_member", "department")
            .prefetch_related("replacement_requests__substitute_caregiver")
            .order_by("department__name", "start_time")
        )

        if selected_dept_id and selected_dept_id.isdigit():
            shifts_query = shifts_query.filter(department_id=int(selected_dept_id))

        # Indexer les shifts par département et par date
        # planning_matrix: Dict[dept_id, {'dept': Department, 'days': {date: [shifts]}}]
        planning_matrix: Dict[int, Dict[str, Any]] = {}

        all_active_depts = Department.objects.filter(is_active=True)
        if selected_dept_id and selected_dept_id.isdigit():
            all_active_depts = all_active_depts.filter(id=int(selected_dept_id))

        for dept in all_active_depts:
            planning_matrix[dept.id] = {
                "department": dept,
                "days": {day["date_str"]: [] for day in week_days},
            }

        for shift in shifts_query:
            d_str = shift.shift_date.strftime("%Y-%m-%d")
            if shift.department_id in planning_matrix and d_str in planning_matrix[shift.department_id]["days"]:
                # Vérification s'il y a un remplacement validé
                validated_replacement = next(
                    (r for r in shift.replacement_requests.all() if r.status == ShiftReplacementStatus.VALIDE),
                    None,
                )
                pending_replacement = next(
                    (r for r in shift.replacement_requests.all() if r.status == ShiftReplacementStatus.DEMANDE),
                    None,
                )

                planning_matrix[shift.department_id]["days"][d_str].append({
                    "shift": shift,
                    "validated_replacement": validated_replacement,
                    "pending_replacement": pending_replacement,
                })

        # Transformation de la matrice en lignes ordonnées avec liste de jours
        matrix_rows = []
        for dept_id, data in planning_matrix.items():
            days_list = []
            for day in week_days:
                d_str = day["date_str"]
                days_list.append({
                    "day": day,
                    "shifts": data["days"].get(d_str, []),
                })
            matrix_rows.append({
                "department": data["department"],
                "days_list": days_list,
            })

        user_role = getattr(request.user, "role", UserRole.MEDECIN)
        role_config = ROLE_PORTAL_CONFIG.get(user_role, ROLE_PORTAL_CONFIG[UserRole.MEDECIN])

        PatientStatusConfig.ensure_default_statuses()
        status_summary = (
            PatientStatusConfig.objects.filter(is_active=True)
            .annotate(patient_count=Count("patients"))
            .order_by("display_order", "label")
        )

        # Colonnes Kanban de flux patients pour la supervision visuelle
        kanban_columns = []
        all_patients_with_status = (
            Patient.objects.select_related("current_status")
            .prefetch_related("hospitalizations__bed__service", "hospitalizations__practitioner")
            .order_by("-status_updated_at", "last_name")
        )
        for st_cfg in status_summary:
            col_patients = [p for p in all_patients_with_status if p.current_status_id == st_cfg.id]
            kanban_columns.append({
                "status": st_cfg,
                "patients": col_patients,
                "count": len(col_patients),
            })

        # Demandes de remplacement de garde en attente d'arbitrage
        pending_replacements = (
            ShiftReplacement.objects.filter(status=ShiftReplacementStatus.DEMANDE)
            .select_related("duty_shift__department", "original_caregiver", "substitute_caregiver")
            .order_by("duty_shift__shift_date")
        )

        # Sorties prévues aujourd'hui & effectifs de garde du jour
        expected_discharges_today = Hospitalization.objects.filter(
            actual_discharge_date__isnull=True,
            expected_discharge_date__date=today,
        ).count()
        today_shifts_count = DutyShift.objects.filter(shift_date=today, is_cancelled=False).count()

        # Calcul du stroke-dashoffset pour la jauge circulaire SVG (circonférence = 251.2 pour r=40)
        donut_circumference = 251.2
        donut_offset = round(donut_circumference - (donut_circumference * occupancy_rate / 100.0), 1)

        context.update({
            "monday": monday,
            "sunday": sunday,
            "week_days": week_days,
            "prev_week_str": prev_week_str,
            "next_week_str": next_week_str,
            "current_week_str": today.strftime("%Y-%m-%d"),
            "ref_date": ref_date,
            "total_beds": total_beds,
            "occupied_beds": occupied_beds,
            "cleaning_beds": cleaning_beds,
            "available_beds": available_beds,
            "maintenance_beds": maintenance_beds,
            "occupancy_rate": occupancy_rate,
            "donut_offset": donut_offset,
            "departments_data": departments_data,
            "all_departments": Department.objects.filter(is_active=True),
            "selected_dept_id": int(selected_dept_id) if selected_dept_id and selected_dept_id.isdigit() else None,
            "planning_matrix": matrix_rows,
            "BedStatus": BedStatus,
            "ShiftType": ShiftType,
            "role_config": role_config,
            "status_summary": status_summary,
            "kanban_columns": kanban_columns,
            "pending_replacements": pending_replacements,
            "expected_discharges_today": expected_discharges_today,
            "today_shifts_count": today_shifts_count,
            "is_chief_or_admin": request.user.is_superuser or user_role in (UserRole.ADMIN, UserRole.CHIRURGIEN, UserRole.MEDECIN),
        })
        return context


class PatientListView(LoginRequiredMixin, ListView):
    """
    Page principale de Liste des Patients et Gestion Dynamique des Statuts :
    - Colonne 'Statut Actuel' avec badge coloré distinctif.
    - Filtre instantané par 'Statut' (simple ou multi-sélection) + compteurs rapides.
    - Recherche globale combinée (Nom, Prénom, IPP, NIR).
    - Changement de statut en temps réel et consultation de l'historique HDS.
    """

    model = Patient
    template_name = "core/patient_list.html"
    context_object_name = "patients"
    paginate_by = 20

    def get_selected_status_codes(self) -> List[str]:
        raw_list = self.request.GET.getlist("status")
        codes: List[str] = []
        for item in raw_list:
            for part in item.split(","):
                cleaned = part.strip().upper()
                if cleaned and cleaned not in codes:
                    codes.append(cleaned)
        return codes

    def get_queryset(self):
        PatientStatusConfig.ensure_default_statuses()
        qs = (
            Patient.objects.select_related("current_status")
            .prefetch_related(
                "status_history__old_status",
                "status_history__new_status",
                "status_history__changed_by",
                "hospitalizations__bed__service",
            )
            .order_by("-status_updated_at", "last_name", "first_name")
        )

        # 1. Filtre par Statut Actuel (Simple ou Multi-sélection)
        selected_codes = self.get_selected_status_codes()
        if selected_codes:
            qs = qs.filter(current_status__code__in=selected_codes)

        # 2. Recherche globale par texte (Nom, Prénom, Nom de naissance, IPP, NIR)
        search_q = self.request.GET.get("q", "").strip()
        if search_q:
            qs = qs.filter(
                Q(last_name__icontains=search_q)
                | Q(first_name__icontains=search_q)
                | Q(maiden_name__icontains=search_q)
                | Q(ipp__icontains=search_q)
                | Q(nir__icontains=search_q)
            )

        return qs

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)
        active_statuses = (
            PatientStatusConfig.objects.filter(is_active=True)
            .annotate(patient_count=Count("patients"))
            .order_by("display_order", "label")
        )
        all_statuses = (
            PatientStatusConfig.objects.all()
            .annotate(patient_count=Count("patients"))
            .order_by("display_order", "label")
        )
        selected_codes = self.get_selected_status_codes()
        user_role = getattr(self.request.user, "role", UserRole.MEDECIN)

        context.update({
            "active_statuses": active_statuses,
            "all_statuses": all_statuses,
            "total_patients_count": Patient.objects.count(),
            "selected_status_codes": selected_codes,
            "selected_status_single": selected_codes[0] if len(selected_codes) == 1 else "",
            "search_query": self.request.GET.get("q", "").strip(),
            "color_choices": PatientStatusColor.choices,
            "is_admin_user": self.request.user.is_superuser or user_role == UserRole.ADMIN,
            "role_config": ROLE_PORTAL_CONFIG.get(user_role, ROLE_PORTAL_CONFIG[UserRole.MEDECIN]),
        })
        return context


@login_required
def patient_change_status_view(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Endpoint (Form POST & API JSON) pour modifier le statut actuel d'un patient
    et enregistrer automatiquement l'historique HDS (Date/Heure, Ancien, Nouveau, Utilisateur).
    """
    if request.method != "POST":
        return JsonResponse({"error": "Méthode POST requise."}, status=405)

    patient = get_object_or_404(Patient.objects.select_related("current_status"), pk=pk)
    is_json = request.content_type == "application/json" or request.headers.get("Accept") == "application/json"

    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"error": "Payload JSON invalide."}, status=400)
        new_status_code = str(payload.get("new_status_code") or payload.get("status_code") or "").strip().upper()
        new_status_id = payload.get("new_status_id")
        comment = str(payload.get("comment") or "").strip()
    else:
        new_status_code = request.POST.get("new_status_code", "").strip().upper()
        new_status_id = request.POST.get("new_status_id", "").strip()
        comment = request.POST.get("comment", "").strip()

    if new_status_id and str(new_status_id).isdigit():
        new_status = get_object_or_404(PatientStatusConfig, pk=int(new_status_id))
    elif new_status_code:
        new_status = get_object_or_404(PatientStatusConfig, code=new_status_code)
    else:
        if is_json:
            return JsonResponse({"error": "Veuillez spécifier le nouveau statut."}, status=400)
        messages.error(request, "Veuillez sélectionner un nouveau statut valide.")
        return redirect("core:patient_list")

    old_status = patient.current_status
    try:
        history_entry = patient.change_status(
            new_status=new_status,
            changed_by=request.user,
            comment=comment,
        )
    except ValidationError as exc:
        if is_json:
            return JsonResponse({"error": str(exc)}, status=400)
        messages.error(request, str(exc))
        return redirect("core:patient_list")

    SecurityAuditLog.log_action(
        user=request.user,
        action_type=AuditActionType.UPDATE,
        patient=patient,
        resource_name="PatientStatus",
        details=f"Changement de statut : {old_status.code if old_status else 'INIT'} -> {new_status.code}",
        ip_address=request.META.get("REMOTE_ADDR"),
    )

    if is_json:
        return JsonResponse({
            "status": "success",
            "patient_id": patient.id,
            "ipp": patient.ipp,
            "old_status": {
                "code": old_status.code,
                "label": old_status.label,
                "color_theme": old_status.color_theme,
            } if old_status else None,
            "current_status": {
                "code": new_status.code,
                "label": new_status.label,
                "color_theme": new_status.color_theme,
                "hex_color": new_status.hex_color,
            },
            "changed_at": history_entry.changed_at.isoformat(),
            "changed_by": str(request.user),
        })

    old_label = old_status.label if old_status else "Non défini"
    messages.success(
        request,
        f"Statut de {patient.last_name.upper()} {patient.first_name} ({patient.ipp}) mis à jour : {old_label} → {new_status.label}.",
    )

    next_url = request.POST.get("next") or reverse("core:patient_list")
    return redirect(next_url)


@login_required
def status_config_manage_view(request: HttpRequest) -> HttpResponse:
    """
    Permet aux administrateurs d'ajouter, modifier ou activer/désactiver des statuts
    directement depuis l'interface de gestion des patients.
    """
    user_role = getattr(request.user, "role", "")
    if not (request.user.is_superuser or user_role == UserRole.ADMIN):
        raise PermissionDenied("Seuls les administrateurs peuvent modifier le paramétrage général des statuts.")

    if request.method != "POST":
        return redirect("core:patient_list")

    action = request.POST.get("action", "create")

    if action == "toggle":
        status_id = request.POST.get("status_id")
        cfg = get_object_or_404(PatientStatusConfig, pk=status_id)
        cfg.is_active = not cfg.is_active
        cfg.save(update_fields=["is_active", "updated_at"])
        state_str = "activé" if cfg.is_active else "désactivé"
        messages.success(request, f"Le statut « {cfg.label} » ({cfg.code}) a été {state_str}.")
        return redirect("core:patient_list")

    if action == "create":
        code = request.POST.get("code", "").strip().upper().replace(" ", "_")
        label = request.POST.get("label", "").strip()
        description = request.POST.get("description", "").strip()
        color_theme = request.POST.get("color_theme", PatientStatusColor.SKY)
        display_order = request.POST.get("display_order", "10")
        is_terminal = request.POST.get("is_terminal") == "on"

        hex_map = {
            PatientStatusColor.SKY: "#0284C7",
            PatientStatusColor.INDIGO: "#4F46E5",
            PatientStatusColor.ROSE: "#E11D48",
            PatientStatusColor.AMBER: "#D97706",
            PatientStatusColor.EMERALD: "#059669",
            PatientStatusColor.PURPLE: "#9333EA",
            PatientStatusColor.SLATE: "#64748B",
        }

        if not code or not label:
            messages.error(request, "Le code et le libellé du statut sont obligatoires.")
            return redirect("core:patient_list")

        obj, created = PatientStatusConfig.objects.update_or_create(
            code=code,
            defaults={
                "label": label,
                "description": description,
                "color_theme": color_theme,
                "hex_color": hex_map.get(color_theme, "#0284C7"),
                "display_order": int(display_order) if str(display_order).isdigit() else 10,
                "is_terminal": is_terminal,
                "is_active": True,
            },
        )
        verb = "créé" if created else "mis à jour"
        messages.success(request, f"Statut « {obj.label} » ({obj.code}) {verb} avec succès.")

    return redirect("core:patient_list")


@login_required
def api_status_configs_view(request: HttpRequest) -> JsonResponse:
    """API REST pour lister les statuts configurés ou en créer un (ADMIN)."""
    PatientStatusConfig.ensure_default_statuses()
    if request.method == "GET":
        include_inactive = request.GET.get("include_inactive", "false").lower() == "true"
        qs = PatientStatusConfig.objects.annotate(patients_count=Count("patients")).order_by("display_order", "label")
        if not include_inactive:
            qs = qs.filter(is_active=True)
        data = [
            {
                "id": s.id,
                "code": s.code,
                "label": s.label,
                "description": s.description,
                "color_theme": s.color_theme,
                "hex_color": s.hex_color,
                "display_order": s.display_order,
                "is_terminal": s.is_terminal,
                "is_active": s.is_active,
                "patients_count": s.patients_count,
            }
            for s in qs
        ]
        return JsonResponse({"count": len(data), "results": data})

    if request.method == "POST":
        user_role = getattr(request.user, "role", "")
        if not (request.user.is_superuser or user_role == UserRole.ADMIN):
            return JsonResponse({"error": "Accès réservé aux administrateurs."}, status=403)
        try:
            payload = json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"error": "JSON invalide."}, status=400)

        code = str(payload.get("code", "")).strip().upper().replace(" ", "_")
        label = str(payload.get("label", "")).strip()
        if not code or not label:
            return JsonResponse({"error": "Les champs 'code' et 'label' sont requis."}, status=400)

        obj, created = PatientStatusConfig.objects.update_or_create(
            code=code,
            defaults={
                "label": label,
                "description": str(payload.get("description", "")),
                "color_theme": payload.get("color_theme", PatientStatusColor.SKY),
                "hex_color": payload.get("hex_color", "#0284C7"),
                "display_order": int(payload.get("display_order", 10)),
                "is_terminal": bool(payload.get("is_terminal", False)),
                "is_active": bool(payload.get("is_active", True)),
            },
        )
        return JsonResponse(
            {
                "id": obj.id,
                "code": obj.code,
                "label": obj.label,
                "color_theme": obj.color_theme,
                "is_active": obj.is_active,
                "created": created,
            },
            status=201 if created else 200,
        )

    return JsonResponse({"error": "Méthode non supportée."}, status=405)


@login_required
def api_patient_status_history_view(request: HttpRequest, pk: int) -> JsonResponse:
    """API REST retournant l'historique complet des changements de statut d'un patient."""
    patient = get_object_or_404(Patient.objects.select_related("current_status"), pk=pk)
    SecurityAuditLog.log_action(
        user=request.user,
        action_type=AuditActionType.READ,
        patient=patient,
        resource_name="PatientStatusHistory",
        details=f"Consultation de l'historique des statuts du patient {patient.ipp}",
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    history_qs = patient.status_history.select_related("old_status", "new_status", "changed_by").order_by("-changed_at", "-id")
    history_data = [
        {
            "id": h.id,
            "changed_at": h.changed_at.strftime("%d/%m/%Y %H:%M"),
            "changed_at_iso": h.changed_at.isoformat(),
            "old_status": {
                "code": h.old_status.code,
                "label": h.old_status.label,
                "color_theme": h.old_status.color_theme,
            } if h.old_status else None,
            "new_status": {
                "code": h.new_status.code,
                "label": h.new_status.label,
                "color_theme": h.new_status.color_theme,
                "hex_color": h.new_status.hex_color,
            },
            "changed_by": {
                "username": h.changed_by.username,
                "full_name": h.changed_by.get_full_name() or h.changed_by.username,
                "role": h.changed_by.get_role_display(),
            },
            "comment": h.comment,
        }
        for h in history_qs
    ]
    return JsonResponse({
        "patient_id": patient.id,
        "patient_ipp": patient.ipp,
        "patient_name": f"{patient.last_name.upper()} {patient.first_name}",
        "current_status": patient.current_status.code if patient.current_status else None,
        "history": history_data,
    })


@login_required
def admission_consent_pdf_view(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Génère et retourne le document PDF officiel « FORMULAIRE DE CONSENTEMENT AUX SOINS ET DÉCHARGE »
    pour une admission (Hospitalization) donnée, avec journalisation dans SecurityAuditLog.
    """
    hosp = get_object_or_404(
        Hospitalization.objects.select_related("patient", "bed__service", "practitioner"),
        pk=pk,
    )
    pdf_bytes = generate_admission_consent_pdf(hosp, agent_user=request.user)

    SecurityAuditLog.log_action(
        user=request.user,
        action_type=AuditActionType.READ,
        patient=hosp.patient,
        resource_name="ConsentementPDF (Hospitalization)",
        details=f"Édition du PDF de Consentement aux soins et décharge pour l'admission #{hosp.id} ({hosp.patient.ipp})",
        ip_address=request.META.get("REMOTE_ADDR"),
    )

    filename = f"Consentement_Admission_{hosp.patient.ipp}_ADM{hosp.id:05d}.pdf"
    disposition = "attachment" if request.GET.get("download") == "1" else "inline"
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    return response


@login_required
def patient_consent_pdf_view(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Génère et retourne le document PDF officiel « FORMULAIRE DE CONSENTEMENT AUX SOINS ET DÉCHARGE »
    à partir du Dossier Patient Unique (DPI) et de son séjour actif ou récent.
    """
    patient = get_object_or_404(Patient, pk=pk)
    pdf_bytes = generate_admission_consent_pdf(patient, agent_user=request.user)

    SecurityAuditLog.log_action(
        user=request.user,
        action_type=AuditActionType.READ,
        patient=patient,
        resource_name="ConsentementPDF (Patient)",
        details=f"Édition du PDF de Consentement aux soins et décharge pour le patient {patient.ipp}",
        ip_address=request.META.get("REMOTE_ADDR"),
    )

    filename = f"Consentement_Soins_Decharge_{patient.ipp}.pdf"
    disposition = "attachment" if request.GET.get("download") == "1" else "inline"
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    return response


@login_required
def quick_bed_status_action_view(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Action rapide 1-clic depuis le Cockpit de Supervision :
    Permet de marquer un lit en 'NETTOYAGE' comme 'DISPONIBLE' (Désinfection validée)
    ou de basculer son état opérationnel sans quitter le tableau de bord.
    """
    if request.method != "POST":
        return redirect("home_dashboard")

    user_role = getattr(request.user, "role", "")
    if user_role == UserRole.GESTIONNAIRE_ADMISSION and not request.user.is_superuser:
        raise PermissionDenied("Le Gestionnaire des Admissions dispose d'un accès en lecture seule sur le statut technique des lits.")

    bed = get_object_or_404(Bed.objects.select_related("service"), pk=pk)
    target_status = request.POST.get("target_status", BedStatus.DISPONIBLE).strip().upper()

    if target_status in dict(BedStatus.choices):
        old_status = bed.status
        bed.status = target_status
        bed.save(update_fields=["status", "updated_at"])

        SecurityAuditLog.log_action(
            user=request.user,
            action_type=AuditActionType.UPDATE,
            resource_name="Bed",
            details=f"Mise à jour rapide du lit {bed.service.code} Ch.{bed.room_number}-L{bed.bed_number} : {old_status} -> {target_status}",
            ip_address=request.META.get("REMOTE_ADDR"),
        )
        messages.success(
            request,
            f"Lit {bed.service.code} — Chambre {bed.room_number} (Lit {bed.bed_number}) passé au statut « {bed.get_status_display()} ».",
        )

    next_url = request.POST.get("next") or reverse("home_dashboard")
    return redirect(next_url)


@login_required
def quick_replacement_validation_view(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Action rapide 1-clic pour les Chefs de Pôles et Directeurs :
    Approuver ou refuser une demande de remplacement de garde directement depuis le Cockpit.
    """
    if request.method != "POST":
        return redirect("home_dashboard")

    user_role = getattr(request.user, "role", "")
    if not (request.user.is_superuser or user_role in (UserRole.ADMIN, UserRole.CHIRURGIEN, UserRole.MEDECIN)):
        raise PermissionDenied("Seuls la Direction et les Chefs de Pôles peuvent valider un remplacement de garde.")

    replacement = get_object_or_404(
        ShiftReplacement.objects.select_related("duty_shift__department", "original_caregiver", "substitute_caregiver"),
        pk=pk,
    )
    decision = request.POST.get("decision", "VALIDE").strip().upper()
    if decision in (ShiftReplacementStatus.VALIDE, ShiftReplacementStatus.REFUSE):
        replacement.status = decision
        if decision == ShiftReplacementStatus.VALIDE:
            replacement.validation_date = timezone.now()
        replacement.save()

        SecurityAuditLog.log_action(
            user=request.user,
            action_type=AuditActionType.UPDATE,
            resource_name="ShiftReplacement",
            details=f"Décision remplacement garde #{replacement.id} ({replacement.duty_shift.department.code}) : {decision}",
            ip_address=request.META.get("REMOTE_ADDR"),
        )
        messages.success(
            request,
            f"Remplacement de garde ({replacement.original_caregiver.last_name} → {replacement.substitute_caregiver.last_name}) marqué comme « {replacement.get_status_display()} ».",
        )

    next_url = request.POST.get("next") or reverse("home_dashboard")
    return redirect(next_url)


# ==============================================================================
# IMPORTATION & EXPORTATION EXCEL (.XLSX / .CSV) DE LA LISTE DES MALADES
# ==============================================================================

class ExportPatientsExcelView(LoginRequiredMixin, View):
    """
    Exporte la liste complète des malades (Patients / DPI) au format Excel (.xlsx) ou CSV (.csv).
    Si `?template=1`, génère un fichier modèle Excel pré-formaté pour l'importation de malades.
    """

    def get(self, request: HttpRequest) -> HttpResponse:
        fmt = request.GET.get("format", "xlsx").strip().lower()
        is_template = request.GET.get("template", "0") == "1"

        headers = [
            "IPP",
            "Nom",
            "Prenom",
            "Nom_Naissance",
            "Date_Naissance",
            "Sexe",
            "Groupe_Sanguin",
            "NIR_Securite_Sociale",
            "Numero_CNI_PC",
            "Telephone",
            "Email",
            "Adresse",
            "Commune_Ville",
            "Wilaya",
            "Statut_Actuel",
            "Allergies_Connues",
            "Antecedents_Majeurs",
            "Traitements_En_Cours",
            "Personne_Confiance",
            "Tel_Personne_Confiance",
        ]

        rows: List[List[Any]] = []
        if is_template:
            rows.append([
                "",
                "BENALI",
                "Karim",
                "",
                "1982-05-14",
                "M",
                "O+",
                "",
                "109820514001",
                "0550123456",
                "k.benali@example.dz",
                "Cité 200 Logements Bt B",
                "Hydra",
                "16 - Alger",
                "ADMISSION",
                "Pénicilline",
                "HTA équilibrée",
                "Amlodipine 5mg 1cp/j",
                "BENALI Samira (Épouse)",
                "0550654321",
            ])
            rows.append([
                "",
                "MANSOURI",
                "Meriem",
                "KHELIFI",
                "1990-11-22",
                "F",
                "A+",
                "",
                "209901122004",
                "0661987654",
                "m.mansouri@example.dz",
                "Rue Didouche Mourad",
                "Alger Centre",
                "16 - Alger",
                "CONSULTATION",
                "Aucune",
                "RAS",
                "Aucun",
                "MANSOURI Reda",
                "0661112233",
            ])
        else:
            patients = Patient.objects.select_related("current_status").order_by("last_name", "first_name")
            for p in patients:
                rows.append([
                    p.ipp,
                    p.last_name,
                    p.first_name,
                    p.maiden_name or "",
                    p.birth_date.strftime("%Y-%m-%d") if p.birth_date else "",
                    p.gender,
                    p.blood_group,
                    p.nir,
                    p.national_id_number or "",
                    p.phone or "",
                    p.email or "",
                    p.address or "",
                    p.city or "",
                    p.state_province or "",
                    p.current_status.code if p.current_status else "ADMISSION",
                    p.known_allergies or "",
                    p.major_medical_history or "",
                    p.ongoing_treatments or "",
                    p.trusted_person_name or "",
                    p.trusted_person_phone or "",
                ])

        SecurityAuditLog.log_action(
            user=request.user,
            action_type=AuditActionType.READ,
            resource_name="Patient (Export Excel)",
            details=f"Exportation Excel/CSV de la liste des malades ({len(rows)} lignes, format={fmt}, template={is_template})",
            ip_address=request.META.get("REMOTE_ADDR"),
        )

        date_str = timezone.now().strftime("%Y%m%d_%H%M")
        base_name = "Modele_Import_Malades" if is_template else f"Liste_Malades_Clinique_{date_str}"

        if fmt == "csv":
            csv_bytes = build_csv_bytes(headers, rows)
            response = HttpResponse(csv_bytes, content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = f'attachment; filename="{base_name}.csv"'
            return response

        xlsx_bytes = build_xlsx_bytes("Malades_Patients", headers, rows)
        response = HttpResponse(
            xlsx_bytes,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{base_name}.xlsx"'
        return response


class ImportPatientsExcelView(LoginRequiredMixin, View):
    """
    Importe une liste de malades (Patients) depuis un fichier Excel (.xlsx) ou CSV (.csv).
    - Met à jour le dossier existant si l'IPP, le NIR ou le triplet (Nom, Prénom, Date de naissance) existe déjà.
    - Génère automatiquement l'IPP (`IPP-YYYY-XXXXXX`) et un NIR valide à 15 chiffres avec clé modulo 97
      si non fourni dans le fichier Excel.
    """

    @staticmethod
    def _get_redirect_url(request: HttpRequest) -> str:
        next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or ""
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return next_url
        return "/admin/core/patient/"

    def post(self, request: HttpRequest) -> HttpResponse:
        redirect_url = self._get_redirect_url(request)
        uploaded_file = request.FILES.get("excel_file")
        if not uploaded_file:
            messages.error(request, "Veuillez sélectionner un fichier Excel (.xlsx) ou CSV (.csv) à importer.")
            return redirect(redirect_url)

        try:
            raw_bytes = uploaded_file.read()
            records = parse_excel_or_csv_bytes(raw_bytes, uploaded_file.name)
        except Exception as exc:
            messages.error(request, f"Erreur de lecture du fichier « {uploaded_file.name} » : {exc}")
            return redirect(redirect_url)

        if not records:
            messages.error(request, "Le fichier importé ne contient aucune ligne de malade exploitable.")
            return redirect(redirect_url)

        created_count = 0
        updated_count = 0
        skipped_count = 0

        valid_blood_groups = {choice[0].upper(): choice[0] for choice in BloodGroup.choices}
        status_map = {
            st.code.upper(): st
            for st in PatientStatusConfig.objects.filter(is_active=True)
        }
        default_status = status_map.get("ADMISSION") or PatientStatusConfig.objects.filter(is_active=True).first()

        for idx, rec in enumerate(records, start=1):
            last_name = first_non_empty(rec, ["nom", "last_name", "nom_usuel", "nom_de_famille", "famille"]).strip().upper()
            first_name = first_non_empty(rec, ["prenom", "first_name", "prenoms"]).strip().title()

            # Si une seule colonne "nom_complet" / "patient" / "malade" est fournie
            if not last_name and not first_name:
                full_name_raw = first_non_empty(rec, ["nom_complet", "patient", "malade", "nom_prenom"])
                if full_name_raw:
                    parts = full_name_raw.split(None, 1)
                    last_name = parts[0].upper()
                    first_name = parts[1].title() if len(parts) > 1 else "Patient"

            if not last_name:
                skipped_count += 1
                continue
            if not first_name:
                first_name = "Patient"

            ipp_raw = first_non_empty(rec, ["ipp", "identifiant_ipp", "code_patient", "id_patient"]).strip().upper()
            maiden_name = first_non_empty(rec, ["nom_naissance", "maiden_name", "nom_jeune_fille"]).strip().upper()
            birth_date_raw = first_non_empty(rec, ["date_naissance", "birth_date", "ddn", "naissance", "date_de_naissance"])
            birth_date = parse_flexible_date(birth_date_raw, default_date=date(1985, 1, 1))

            gender_raw = first_non_empty(rec, ["sexe", "gender", "genre"], default="M").strip().upper()
            if gender_raw.startswith(("F", "FEM")):
                gender = "F"
            elif gender_raw.startswith(("M", "H", "MASC")):
                gender = "M"
            else:
                gender = "I"

            bg_raw = first_non_empty(rec, ["groupe_sanguin", "blood_group", "groupe", "gs"], default="IND").strip().upper()
            blood_group = valid_blood_groups.get(bg_raw, BloodGroup.INDETERMINE)

            nir_raw = first_non_empty(
                rec,
                [
                    "nir_securite_sociale",
                    "nir",
                    "nss",
                    "securite_sociale",
                    "num_securite_sociale",
                    "numero_carte_identite",
                ],
            ).strip()
            nir_clean = nir_raw.replace(" ", "")
            nir_is_present = bool(nir_clean)

            cni_raw = first_non_empty(rec, ["numero_cni_pc", "cni", "piece_identite", "national_id_number", "nin"]).strip()
            phone = first_non_empty(rec, ["telephone", "tel", "phone", "mobile", "gsm"]).strip()
            email = first_non_empty(rec, ["email", "courriel", "mail"]).strip()
            address = first_non_empty(rec, ["adresse", "address", "rue", "domicile"]).strip()
            city = first_non_empty(rec, ["commune_ville", "ville", "commune", "city"]).strip()
            wilaya = first_non_empty(rec, ["wilaya", "state_province", "departement", "province"]).strip()

            status_raw = first_non_empty(rec, ["statut_actuel", "statut", "status", "current_status"], default="ADMISSION").strip().upper()
            target_status = status_map.get(status_raw, default_status)

            allergies = first_non_empty(rec, ["allergies_connues", "allergies", "known_allergies"]).strip()
            antecedents = first_non_empty(rec, ["antecedents_majeurs", "antecedents", "major_medical_history"]).strip()
            traitements = first_non_empty(rec, ["traitements_en_cours", "traitements", "ongoing_treatments"]).strip()
            trusted_name = first_non_empty(rec, ["personne_confiance", "trusted_person_name", "contact_urgence"]).strip()
            trusted_phone = first_non_empty(rec, ["tel_personne_confiance", "trusted_person_phone", "tel_urgence"]).strip()

            # Recherche d'un dossier patient existant pour éviter tout doublon
            existing_patient = None
            if ipp_raw:
                existing_patient = Patient.objects.filter(ipp__iexact=ipp_raw).first()
            if not existing_patient and nir_is_present:
                existing_patient = Patient.objects.filter(nir=nir_clean).first()
            if not existing_patient:
                existing_patient = Patient.objects.filter(
                    last_name__iexact=last_name,
                    first_name__iexact=first_name,
                    birth_date=birth_date,
                ).first()

            if existing_patient:
                existing_patient.last_name = last_name
                existing_patient.first_name = first_name
                if maiden_name:
                    existing_patient.maiden_name = maiden_name
                existing_patient.birth_date = birth_date
                existing_patient.gender = gender
                if blood_group != BloodGroup.INDETERMINE or not existing_patient.blood_group:
                    existing_patient.blood_group = blood_group
                if cni_raw:
                    existing_patient.national_id_number = cni_raw
                if phone:
                    existing_patient.phone = phone
                if email:
                    existing_patient.email = email
                if address:
                    existing_patient.address = address
                if city:
                    existing_patient.city = city
                if wilaya:
                    existing_patient.state_province = wilaya
                if target_status:
                    existing_patient.current_status = target_status
                if allergies:
                    existing_patient.known_allergies = allergies
                if antecedents:
                    existing_patient.major_medical_history = antecedents
                if traitements:
                    existing_patient.ongoing_treatments = traitements
                if trusted_name:
                    existing_patient.trusted_person_name = trusted_name
                if trusted_phone:
                    existing_patient.trusted_person_phone = trusted_phone
                existing_patient.save()
                updated_count += 1
            else:
                # Utiliser le N° Sécurité Sociale / Carte d'identité fourni (s'il n'est pas déjà pris), sinon en générer un unique
                final_nir = nir_clean if (nir_is_present and not Patient.objects.filter(nir=nir_clean).exists()) else ""
                seed_offset = Patient.objects.count() + idx + 100
                while not final_nir:
                    candidate_nir = generate_valid_nir_for_patient(birth_date, gender, unique_seed=seed_offset)
                    if not Patient.objects.filter(nir=candidate_nir).exists():
                        final_nir = candidate_nir
                    seed_offset += 1

                new_patient = Patient(
                    nir=final_nir,
                    last_name=last_name,
                    first_name=first_name,
                    maiden_name=maiden_name,
                    birth_date=birth_date,
                    gender=gender,
                    blood_group=blood_group,
                    current_status=target_status,
                    status_updated_at=timezone.now(),
                    national_id_number=cni_raw,
                    phone=phone,
                    email=email,
                    address=address,
                    city=city,
                    state_province=wilaya,
                    known_allergies=allergies,
                    major_medical_history=antecedents,
                    ongoing_treatments=traitements,
                    trusted_person_name=trusted_name,
                    trusted_person_phone=trusted_phone,
                )
                if ipp_raw and not Patient.objects.filter(ipp__iexact=ipp_raw).exists():
                    new_patient.ipp = ipp_raw
                new_patient.save()
                created_count += 1

        SecurityAuditLog.log_action(
            user=request.user,
            action_type=AuditActionType.CREATE,
            resource_name="Patient (Import Excel)",
            details=(
                f"Importation Excel/CSV malades ({uploaded_file.name}) : "
                f"{created_count} créé(s), {updated_count} mis à jour, {skipped_count} ignoré(s)."
            ),
            ip_address=request.META.get("REMOTE_ADDR"),
        )

        messages.success(
            request,
            f"Importation Excel des malades terminée ({uploaded_file.name}) : "
            f"{created_count} nouveau(x) patient(s) créé(s), {updated_count} dossier(s) mis à jour"
            + (f", {skipped_count} ligne(s) ignorée(s)." if skipped_count else "."),
        )
        return redirect(redirect_url)


class ClinicSettingsView(LoginRequiredMixin, View):
    """
    Module dédié aux Paramètres Généraux, Coordonnées Officielles et Identité Légale de la Clinique :
    - Nom de la Clinique & Raison Sociale (SARL CLINIQUE MÉDICO-CHIRURGICALE SIDI YAHIA 2)
    - Adresse : 27 chemin Ahmed KARA - Bir Mourad Rais - Alger, Algerie
    - Téléphone : +213 770 79 46 30
    - Email : sidiyahiaclinique2@gmail.com
    - Identifiants Fiscaux & Agréments (NIF, NIS, RC, AI, RIB, N° Convention CNAS)
    """

    template_name = "core/clinic_settings.html"

    def _get_or_init_etablissement(self, user: Any):
        from apps.facturation.models import EtablissementFiscal
        from apps.facturation.services import initialiser_donnees_demo_facturation_algerie

        initialiser_donnees_demo_facturation_algerie(utilisateur=user)
        etab = EtablissementFiscal.objects.first()
        if not etab:
            etab = EtablissementFiscal.objects.create(
                nom_clinique="Clinique Sidi Yahia 2",
                raison_sociale="SARL CLINIQUE MÉDICO-CHIRURGICALE SIDI YAHIA 2",
                forme_juridique="SARL au capital social de 50 000 000,00 DA",
                adresse_complete="27 chemin Ahmed KARA - Bir Mourad Rais - Alger, Algerie",
                wilaya="16 - Alger",
                telephone="+213 770 79 46 30",
                email="sidiyahiaclinique2@gmail.com",
            )
        return etab

    def get(self, request: HttpRequest) -> HttpResponse:
        from apps.facturation.models import TypeEtablissementSanteChoices

        etab = self._get_or_init_etablissement(request.user)
        user_role = getattr(request.user, "role", UserRole.MEDECIN)
        role_config = ROLE_PORTAL_CONFIG.get(user_role, ROLE_PORTAL_CONFIG[UserRole.MEDECIN])
        context = {
            "etablissement": etab,
            "types_etablissement": TypeEtablissementSanteChoices.choices,
            "role_config": role_config,
        }
        return render(request, self.template_name, context)

    def post(self, request: HttpRequest) -> HttpResponse:
        etab = self._get_or_init_etablissement(request.user)

        etab.nom_clinique = request.POST.get("nom_clinique", etab.nom_clinique).strip()
        etab.raison_sociale = request.POST.get("raison_sociale", etab.raison_sociale).strip()
        etab.type_etablissement = request.POST.get("type_etablissement", etab.type_etablissement).strip()
        etab.forme_juridique = request.POST.get("forme_juridique", etab.forme_juridique).strip()
        etab.adresse_complete = request.POST.get("adresse_complete", etab.adresse_complete).strip()
        etab.wilaya = request.POST.get("wilaya", etab.wilaya).strip()
        etab.telephone = request.POST.get("telephone", etab.telephone).strip()
        etab.email = request.POST.get("email", etab.email).strip()
        etab.site_web = request.POST.get("site_web", etab.site_web).strip()
        etab.directeur_etablissement = request.POST.get(
            "directeur_etablissement", etab.directeur_etablissement
        ).strip()
        etab.nif = request.POST.get("nif", etab.nif).strip()
        etab.nis = request.POST.get("nis", etab.nis).strip()
        etab.rc = request.POST.get("rc", etab.rc).strip()
        etab.article_imposition = request.POST.get("article_imposition", etab.article_imposition).strip()
        etab.rib_bancaire = request.POST.get("rib_bancaire", etab.rib_bancaire).strip()
        etab.numero_convention_cnas = request.POST.get(
            "numero_convention_cnas", etab.numero_convention_cnas
        ).strip()
        exo_str = request.POST.get("exercice_fiscal_courant", "").strip()
        if exo_str.isdigit():
            etab.exercice_fiscal_courant = int(exo_str)

        etab.save()

        SecurityAuditLog.log_action(
            user=request.user,
            action_type=AuditActionType.UPDATE,
            resource_name="Paramètres de la Clinique (EtablissementFiscal)",
            details=(
                f"Mise à jour des paramètres de la clinique : {etab.raison_sociale} | "
                f"Adresse : {etab.adresse_complete} | Tél : {etab.telephone} | Email : {etab.email}"
            ),
            ip_address=request.META.get("REMOTE_ADDR"),
        )

        messages.success(
            request,
            f"Paramètres de la clinique enregistrés avec succès ({etab.nom_clinique} — "
            f"{etab.adresse_complete} — Tél : {etab.telephone} — Email : {etab.email}).",
        )
        return redirect("/core/clinic-settings/")


class PatientReadmitView(LoginRequiredMixin, View):
    """
    Réadmission d'un patient déjà enregistré dans le système :
    - Affiche l'identité du patient, ses séjours précédents et les lits disponibles.
    - Crée un nouveau séjour hospitalier (Hospitalization) sans dupliquer le dossier patient,
      bascule le lit à OCCUPÉ, met à jour le statut du patient à ADMISSION et journalise l'action HDS.
    """

    template_name = "core/patient_readmit.html"

    @staticmethod
    def _get_safe_next_url(request: HttpRequest, fallback: str) -> str:
        candidate = request.POST.get("next") or request.GET.get("next") or ""
        if candidate and url_has_allowed_host_and_scheme(
            candidate,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            return candidate
        return fallback

    @staticmethod
    def _is_discharged_status(patient: Patient) -> bool:
        return bool(
            patient.current_status
            and (patient.current_status.code == "SORTIE" or patient.current_status.is_terminal)
        )

    def _build_context(self, request: HttpRequest, patient: Patient) -> Dict[str, Any]:
        active_hospitalization = (
            None
            if self._is_discharged_status(patient)
            else patient.hospitalizations.filter(actual_discharge_date__isnull=True)
            .select_related("bed__service", "practitioner")
            .first()
        )
        available_beds = (
            Bed.objects.filter(status=BedStatus.DISPONIBLE)
            .select_related("service")
            .order_by("service__name", "room_number", "bed_number")
        )
        practitioners = CustomUser.objects.filter(
            role__in=[UserRole.MEDECIN, UserRole.CHIRURGIEN, UserRole.ADMIN],
            is_active=True,
        ).order_by("last_name", "first_name")
        past_hospitalizations = (
            patient.hospitalizations.select_related("bed__service", "practitioner")
            .order_by("-admission_date")
        )
        now_local = timezone.localtime(timezone.now())
        default_expected_discharge = (now_local + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M")

        return {
            "patient": patient,
            "active_hospitalization": active_hospitalization,
            "available_beds": available_beds,
            "practitioners": practitioners,
            "past_hospitalizations": past_hospitalizations,
            "hide_entry_diagnosis": getattr(request.user, "role", None) == UserRole.GESTIONNAIRE_ADMISSION,
            "default_admission_date": now_local.strftime("%Y-%m-%dT%H:%M"),
            "default_expected_discharge": default_expected_discharge,
            "next_url": self._get_safe_next_url(request, reverse("core:patient_list")),
        }

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        patient = get_object_or_404(Patient.objects.select_related("current_status"), pk=pk)
        return render(request, self.template_name, self._build_context(request, patient))

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        patient = get_object_or_404(Patient.objects.select_related("current_status"), pk=pk)
        next_url = self._get_safe_next_url(request, reverse("core:patient_list"))

        is_discharged = self._is_discharged_status(patient)
        if patient.hospitalizations.filter(actual_discharge_date__isnull=True).exists() and not is_discharged:
            messages.error(
                request,
                f"Le patient {patient.last_name.upper()} {patient.first_name} ({patient.ipp}) "
                f"a déjà une hospitalisation en cours. Clôturez le séjour actuel avant une réadmission.",
            )
            return redirect(request.path + (f"?next={next_url}" if next_url else ""))

        bed_id = request.POST.get("bed_id", "").strip()
        practitioner_id = request.POST.get("practitioner_id", "").strip()
        admission_date_raw = request.POST.get("admission_date", "").strip()
        expected_discharge_raw = request.POST.get("expected_discharge_date", "").strip()
        admission_reason = request.POST.get("admission_reason", "").strip()
        entry_diagnosis = ""
        if getattr(request.user, "role", None) != UserRole.GESTIONNAIRE_ADMISSION:
            entry_diagnosis = request.POST.get("entry_diagnosis", "").strip()

        bed = Bed.objects.select_related("service").filter(pk=bed_id).first() if bed_id.isdigit() else None
        if not bed:
            messages.error(request, "Veuillez sélectionner un lit disponible pour la réadmission.")
            return render(request, self.template_name, self._build_context(request, patient), status=400)

        if not admission_reason:
            messages.error(request, "Veuillez renseigner le motif de réadmission.")
            return render(request, self.template_name, self._build_context(request, patient), status=400)

        practitioner = (
            CustomUser.objects.filter(pk=practitioner_id, is_active=True).first()
            if practitioner_id.isdigit()
            else None
        )

        now_dt = timezone.now()
        try:
            admission_dt = datetime.fromisoformat(admission_date_raw) if admission_date_raw else now_dt
            if timezone.is_naive(admission_dt):
                admission_dt = timezone.make_aware(admission_dt, timezone.get_current_timezone())
        except ValueError:
            admission_dt = now_dt

        try:
            expected_dt = (
                datetime.fromisoformat(expected_discharge_raw)
                if expected_discharge_raw
                else admission_dt + timedelta(days=3)
            )
            if timezone.is_naive(expected_dt):
                expected_dt = timezone.make_aware(expected_dt, timezone.get_current_timezone())
        except ValueError:
            expected_dt = admission_dt + timedelta(days=3)

        hosp = Hospitalization(
            patient=patient,
            bed=bed,
            practitioner=practitioner,
            admission_date=admission_dt,
            expected_discharge_date=expected_dt,
            admission_reason=admission_reason,
            entry_diagnosis=entry_diagnosis,
        )

        try:
            with transaction.atomic():
                if is_discharged:
                    for old_hosp in patient.hospitalizations.filter(actual_discharge_date__isnull=True):
                        old_hosp.actual_discharge_date = admission_dt
                        old_hosp.save()

                hosp.full_clean()
                hosp.save()

                PatientStatusConfig.ensure_default_statuses()
                admission_status = PatientStatusConfig.objects.filter(code="ADMISSION", is_active=True).first()
                old_status = patient.current_status
                if admission_status:
                    patient.current_status = admission_status
                    patient.status_updated_at = timezone.now()
                    patient.save(update_fields=["current_status", "status_updated_at", "updated_at"])

                    PatientStatusHistory.objects.create(
                        patient=patient,
                        old_status=old_status,
                        new_status=admission_status,
                        changed_by=request.user,
                        comment=f"Réadmission patient — Lit {bed.service.name} (Ch. {bed.room_number} / Lit {bed.bed_number}) : {admission_reason[:150]}",
                    )

                SecurityAuditLog.log_action(
                    user=request.user,
                    action_type=AuditActionType.CREATE,
                    patient=patient,
                    resource_name="Hospitalization (Réadmission)",
                    details=(
                        f"Réadmission du patient {patient.last_name.upper()} {patient.first_name} ({patient.ipp}) "
                        f"sur le lit {bed} (Séjour #{hosp.id})."
                    ),
                    ip_address=request.META.get("REMOTE_ADDR"),
                )
        except ValidationError as exc:
            error_msg = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            messages.error(request, f"Impossible d'enregistrer la réadmission : {error_msg}")
            return render(request, self.template_name, self._build_context(request, patient), status=400)

        messages.success(
            request,
            f"Réadmission enregistrée pour {patient.last_name.upper()} {patient.first_name} ({patient.ipp}) "
            f"— Lit {bed.service.name} • Ch. {bed.room_number} / Lit {bed.bed_number}.",
        )
        return redirect(next_url)







