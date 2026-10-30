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
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.generic import ListView, TemplateView

from .models import (
    AuditActionType,
    Bed,
    BedStatus,
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
        "description": "Supervision intégrale du SIH : Gestion du personnel, tous les pôles cliniques, DPI, statuts patients, lits et validation des remplacements.",
        "actions": [
            {"label": "Suivi & Statuts Patients", "url": "/core/patients/"},
            {"label": "Paramétrage Statuts", "url": "/admin/core/patientstatusconfig/"},
            {"label": "Gestion du Personnel & Rôles", "url": "/admin/core/customuser/"},
            {"label": "Pôle Chirurgie & Bloc", "url": "/chirurgie/intervention/"},
            {"label": "Pôle Pédiatrie", "url": "/pediatrie/anthropometry/"},
            {"label": "Pôle Urologie", "url": "/urologie/intervention/"},
            {"label": "Gynéco & Maternité", "url": "/admin/gynecologie_maternite/"},
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




