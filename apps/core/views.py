"""
Vues de l'application Core : Dashboard hospitalier hebdomadaire en temps réel.
Extraction de la capacité des lits par service et matrice des gardes et astreintes.
"""

from datetime import date, datetime, timedelta
from typing import Any, Dict, List

from django.contrib.auth import logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.generic import TemplateView

from .models import (
    Bed,
    BedStatus,
    CustomUser,
    Department,
    DutyShift,
    Hospitalization,
    ShiftReplacement,
    ShiftReplacementStatus,
    ShiftType,
    UserRole,
)


class HospitalLoginView(LoginView):
    """
    Portail d'authentification unifié pour tous les utilisateurs du SIH
    (Administrateur, Chirurgien, Médecin, Sage-Femme, Infirmier, Secrétaire).
    """

    template_name = "registration/login.html"
    redirect_authenticated_user = True

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
        "description": "Supervision intégrale du SIH : Gestion du personnel, tous les pôles cliniques, DPI, lits et validation des remplacements.",
        "actions": [
            {"label": "Gestion du Personnel & Rôles", "url": "/admin/core/customuser/"},
            {"label": "Dossiers Patients (DPI)", "url": "/admin/core/patient/"},
            {"label": "Pôle Chirurgie & Bloc", "url": "/chirurgie/intervention/"},
            {"label": "Pôle Pédiatrie", "url": "/pediatrie/anthropometry/"},
            {"label": "Pôle Urologie", "url": "/urologie/intervention/"},
            {"label": "Gynéco & Maternité", "url": "/admin/gynecologie_maternite/"},
            {"label": "Validation Remplacements", "url": "/admin/core/shiftreplacement/"},
        ],
    },
    UserRole.CHIRURGIEN: {
        "badge_class": "bg-rose-100 text-rose-800 border-rose-200",
        "description": "Accès Chirurgical & Bloc Opératoire : Interventions, Checklists OMS, Comptes-rendus opératoires (CRO), Urologie et DPI.",
        "actions": [
            {"label": "Bloc & Interventions", "url": "/chirurgie/intervention/"},
            {"label": "Nouvelle Intervention", "url": "/chirurgie/intervention/create/"},
            {"label": "Actes Urologiques", "url": "/urologie/intervention/"},
            {"label": "Dossiers Patients (DPI)", "url": "/admin/core/patient/"},
            {"label": "Mes Rendez-vous", "url": "/admin/core/appointment/"},
            {"label": "Demander Remplacement", "url": "/admin/core/shiftreplacement/add/"},
        ],
    },
    UserRole.MEDECIN: {
        "badge_class": "bg-sky-100 text-sky-800 border-sky-200",
        "description": "Accès Médical Praticien : Consultations spécialisées, Dossiers Patients (DPI), Hospitalisations, Pédiatrie, Maternité et Urologie.",
        "actions": [
            {"label": "Dossiers Patients (DPI)", "url": "/admin/core/patient/"},
            {"label": "Consultations & RDV", "url": "/admin/core/appointment/"},
            {"label": "Hospitalisations", "url": "/admin/core/hospitalization/"},
            {"label": "Suivi Pédiatrique", "url": "/pediatrie/anthropometry/"},
            {"label": "Bilans Urodynamiques", "url": "/urologie/assessment/"},
            {"label": "Suivi Grossesses", "url": "/admin/gynecologie_maternite/pregnancytracking/"},
        ],
    },
    UserRole.SAGE_FEMME: {
        "badge_class": "bg-pink-100 text-pink-800 border-pink-200",
        "description": "Accès Gynécologie-Obstétrique & Salle de Naissance : Suivi de grossesse, Registre d'accouchements (APGAR) et Néonatalogie.",
        "actions": [
            {"label": "Registre Accouchements", "url": "/admin/gynecologie_maternite/deliveryregistry/"},
            {"label": "Suivi des Grossesses", "url": "/admin/gynecologie_maternite/pregnancytracking/"},
            {"label": "Consultations Maternité", "url": "/admin/gynecologie_maternite/routineconsultation/"},
            {"label": "Biométrie Nouveau-nés", "url": "/pediatrie/anthropometry/"},
            {"label": "Dossiers Patientes (DPI)", "url": "/admin/core/patient/"},
        ],
    },
    UserRole.INFIRMIER: {
        "badge_class": "bg-emerald-100 text-emerald-800 border-emerald-200",
        "description": "Accès Soins Infirmiers (IDE / IBODE) : Gestion de l'état des lits (Désinfection/Disponible), Checklists OMS, Vaccinations et Soins.",
        "actions": [
            {"label": "Statut & Désinfection des Lits", "url": "/admin/core/bed/"},
            {"label": "Séjours & Hospitalisations", "url": "/admin/core/hospitalization/"},
            {"label": "Calendrier Vaccinal", "url": "/pediatrie/vaccination/"},
            {"label": "Relevés Anthropométriques", "url": "/pediatrie/anthropometry/"},
            {"label": "Checklists Bloc OMS", "url": "/admin/chirurgie/safetychecklistoms/"},
            {"label": "Demander Remplacement", "url": "/admin/core/shiftreplacement/add/"},
        ],
    },
    UserRole.SECRETAIRE: {
        "badge_class": "bg-amber-100 text-amber-800 border-amber-200",
        "description": "Accès Secrétariat Médical & Admissions : Création des Dossiers Patients (DPI), Planification des Rendez-vous et Admissions.",
        "actions": [
            {"label": "Nouveau Patient (DPI)", "url": "/admin/core/patient/add/"},
            {"label": "Liste des Patients", "url": "/admin/core/patient/"},
            {"label": "Planifier un Rendez-vous", "url": "/admin/core/appointment/add/"},
            {"label": "Agenda des Rendez-vous", "url": "/admin/core/appointment/"},
            {"label": "Nouvelle Admission", "url": "/admin/core/hospitalization/add/"},
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
            dept_beds = dept.beds.all()
            dept_total = dept_beds.count()
            dept_occupied = sum(1 for b in dept_beds if b.status == BedStatus.OCCUPE)
            dept_cleaning = sum(1 for b in dept_beds if b.status == BedStatus.NETTOYAGE)
            dept_available = sum(1 for b in dept_beds if b.status == BedStatus.DISPONIBLE)

            # Détail des lits du département avec patient si occupé
            beds_list = []
            for b in dept_beds:
                active_hosp = None
                if b.status == BedStatus.OCCUPE:
                    active_hosp = Hospitalization.objects.filter(
                        bed=b, actual_discharge_date__isnull=True
                    ).select_related("patient").first()

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
            "departments_data": departments_data,
            "all_departments": Department.objects.filter(is_active=True),
            "selected_dept_id": int(selected_dept_id) if selected_dept_id and selected_dept_id.isdigit() else None,
            "planning_matrix": matrix_rows,
            "BedStatus": BedStatus,
            "ShiftType": ShiftType,
            "role_config": role_config,
        })
        return context

