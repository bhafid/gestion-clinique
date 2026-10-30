"""
Modèles du Socle Transversal (Core) - Système d'Information Hospitalier (SIH).
Conformité HDS / RGPD : Gestion du personnel (RBAC), DPI unifié,
gestion des rendez-vous avec anti-collision, cycle de vie automatisé des lits,
et gestion des gardes médicales avec verrouillage strict des permutations.
"""

from datetime import date, datetime, timedelta
import re
from typing import Dict, Optional

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone


# -----------------------------------------------------------------------------
# Modèle Abstrait pour la Traçabilité et l'Audit (HDS / RGPD)
# -----------------------------------------------------------------------------
class AuditableModel(models.Model):
    """
    Modèle de base abstrait assurant la traçabilité complète des modifications
    conformément aux référentiels de sécurité des données de santé (HDS).
    """

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Date de création",
        help_text="Horodatage immuable de l'enregistrement",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Dernière mise à jour",
        help_text="Horodatage automatique de la dernière modification",
    )

    class Meta:
        abstract = True


# -----------------------------------------------------------------------------
# 1. Département Hospitalier & Personnel Médical (RBAC)
# -----------------------------------------------------------------------------
class Department(AuditableModel):
    """Département ou pôle de soins hospitalier."""

    code = models.CharField(max_length=20, unique=True, verbose_name="Code département")
    name = models.CharField(max_length=100, verbose_name="Nom du service")
    building = models.CharField(max_length=50, blank=True, verbose_name="Bâtiment / Aile")
    floor = models.IntegerField(default=0, verbose_name="Étage")
    is_active = models.BooleanField(default=True, verbose_name="Service actif")

    class Meta:
        verbose_name = "Département Hospitalier"
        verbose_name_plural = "Départements Hospitaliers"
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


class UserRole(models.TextChoices):
    """Rôles stricts pour le contrôle d'accès basé sur les rôles (RBAC)."""

    ADMIN = "ADMIN", "Administrateur Système / Directeur Médical"
    MEDECIN = "MEDECIN", "Médecin Praticien"
    CHIRURGIEN = "CHIRURGIEN", "Chirurgien"
    INFIRMIER = "INFIRMIER", "Infirmier(e) D.E."
    SAGE_FEMME = "SAGE_FEMME", "Sage-Femme"
    SECRETAIRE = "SECRETAIRE", "Secrétaire Médicale"
    GESTIONNAIRE_ADMISSION = (
        "GESTIONNAIRE_ADMISSION",
        "Gestionnaire des Admissions et Hospitalisations",
    )


class CustomUser(AbstractUser):
    """
    Modèle utilisateur personnalisé pour l'ensemble du personnel hospitalier.
    Intègre les rôles stricts et l'affectation par département.
    """

    role = models.CharField(
        max_length=30,
        choices=UserRole.choices,
        default=UserRole.MEDECIN,
        verbose_name="Rôle hospitalier",
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="staff_members",
        verbose_name="Département d'affectation",
    )
    license_number = models.CharField(
        max_length=30,
        blank=True,
        verbose_name="Numéro RPPS / ADELI",
        help_text="Identifiant national des professionnels de santé",
    )
    phone_number = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="Numéro de téléphone d'urgence / Bip",
    )

    class Meta:
        verbose_name = "Personnel Médical / Utilisateur"
        verbose_name_plural = "Personnel Médical / Utilisateurs"

    def __str__(self) -> str:
        dept_str = f" - {self.department.code}" if self.department else ""
        return f"{self.get_full_name() or self.username} [{self.get_role_display()}]{dept_str}"

    @property
    def is_medical_doctor(self) -> bool:
        return self.role in (UserRole.MEDECIN, UserRole.CHIRURGIEN)

    def save(self, *args, **kwargs) -> None:
        """
        Active automatiquement l'accès au portail métier (is_staff) pour le personnel actif
        et les droits superutilisateur pour le rôle ADMIN.
        """
        if self.is_active:
            self.is_staff = True
        if self.role == UserRole.ADMIN:
            self.is_superuser = True
        super().save(*args, **kwargs)

    def sync_role_permissions(self) -> None:
        """
        Attribue automatiquement les permissions Django (RBAC) correspondant au rôle hospitalier.
        Permet à chaque profil (Médecin, Chirurgien, Sage-Femme, Infirmier, Secrétaire, Admin)
        d'accéder uniquement aux modules autorisés dans le portail métier.
        """
        from django.contrib.auth.models import Permission

        if self.role == UserRole.ADMIN:
            self.is_superuser = True
            self.is_staff = True
            super().save(update_fields=["is_superuser", "is_staff"])
            return

        role_codenames = {
            UserRole.CHIRURGIEN: [
                # Core
                "view_department", "view_patient", "add_patient", "change_patient",
                "view_patientstatusconfig", "view_patientstatushistory", "add_patientstatushistory",
                "view_appointment", "add_appointment", "change_appointment",
                "view_bed", "view_hospitalization", "add_hospitalization", "change_hospitalization",
                "view_dutyshift", "view_shiftreplacement", "add_shiftreplacement",
                # Chirurgie
                "view_operatingroom", "view_surgicalintervention", "add_surgicalintervention", "change_surgicalintervention",
                "view_safetychecklistoms", "add_safetychecklistoms", "change_safetychecklistoms",
                "view_operativereport", "add_operativereport", "change_operativereport",
                # Urologie
                "view_urologicalhistory", "add_urologicalhistory", "change_urologicalhistory",
                "view_urodynamicassessment", "add_urodynamicassessment", "change_urodynamicassessment",
                "view_specializedinterventionreport", "add_specializedinterventionreport", "change_specializedinterventionreport",
            ],
            UserRole.MEDECIN: [
                # Core
                "view_department", "view_patient", "add_patient", "change_patient",
                "view_patientstatusconfig", "view_patientstatushistory", "add_patientstatushistory",
                "view_appointment", "add_appointment", "change_appointment",
                "view_bed", "view_hospitalization", "add_hospitalization", "change_hospitalization",
                "view_dutyshift", "view_shiftreplacement", "add_shiftreplacement",
                # Spécialités médicales
                "view_gynecologicalhistory", "add_gynecologicalhistory", "change_gynecologicalhistory",
                "view_routineconsultation", "add_routineconsultation", "change_routineconsultation",
                "view_pregnancytracking", "add_pregnancytracking", "change_pregnancytracking",
                "view_deliveryregistry", "add_deliveryregistry", "change_deliveryregistry",
                "view_anthropometricrecord", "add_anthropometricrecord", "change_anthropometricrecord",
                "view_vaccinationrecord", "add_vaccinationrecord", "change_vaccinationrecord",
                "view_urologicalhistory", "add_urologicalhistory", "change_urologicalhistory",
                "view_urodynamicassessment", "add_urodynamicassessment", "change_urodynamicassessment",
                "view_specializedinterventionreport",
                "view_surgicalintervention", "view_operativereport",
            ],
            UserRole.SAGE_FEMME: [
                # Core
                "view_department", "view_patient", "add_patient", "change_patient",
                "view_patientstatusconfig", "view_patientstatushistory", "add_patientstatushistory",
                "view_appointment", "add_appointment", "change_appointment",
                "view_bed", "change_bed", "view_hospitalization", "add_hospitalization", "change_hospitalization",
                "view_dutyshift", "view_shiftreplacement", "add_shiftreplacement",
                # Maternité & Nouveau-nés
                "view_gynecologicalhistory", "add_gynecologicalhistory", "change_gynecologicalhistory",
                "view_routineconsultation", "add_routineconsultation", "change_routineconsultation",
                "view_pregnancytracking", "add_pregnancytracking", "change_pregnancytracking",
                "view_deliveryregistry", "add_deliveryregistry", "change_deliveryregistry",
                "view_anthropometricrecord", "add_anthropometricrecord", "change_anthropometricrecord",
                "view_vaccinationrecord", "add_vaccinationrecord",
            ],
            UserRole.INFIRMIER: [
                # Core (Soins, Lits & Gardes)
                "view_department", "view_patient", "change_patient", "view_appointment",
                "view_patientstatusconfig", "view_patientstatushistory", "add_patientstatushistory",
                "view_bed", "change_bed", "view_hospitalization", "change_hospitalization",
                "view_dutyshift", "view_shiftreplacement", "add_shiftreplacement",
                # Bloc & Pédiatrie
                "view_surgicalintervention", "view_safetychecklistoms", "add_safetychecklistoms", "change_safetychecklistoms",
                "view_anthropometricrecord", "add_anthropometricrecord", "change_anthropometricrecord",
                "view_vaccinationrecord", "add_vaccinationrecord", "change_vaccinationrecord",
            ],
            UserRole.SECRETAIRE: [
                # Accueil, DPI, Rendez-vous & Admissions
                "view_department", "view_patient", "add_patient", "change_patient",
                "view_patientstatusconfig", "view_patientstatushistory", "add_patientstatushistory",
                "view_appointment", "add_appointment", "change_appointment", "delete_appointment",
                "view_bed", "view_hospitalization", "add_hospitalization", "change_hospitalization",
                "view_dutyshift",
            ],
            UserRole.GESTIONNAIRE_ADMISSION: [
                # A. Gestion des Patients (Identitovigilance) : CRU uniquement (Suppression interdite)
                "view_patient", "add_patient", "change_patient",
                "view_patientstatusconfig", "view_patientstatushistory", "add_patientstatushistory",
                # B. Mouvements et Hospitalisations : CRU sur les séjours, Lecture seule sur l'occupation des lits
                "view_hospitalization", "add_hospitalization", "change_hospitalization",
                "view_department", "view_bed",
            ],
        }

        codenames = role_codenames.get(self.role, [])
        perms = Permission.objects.filter(codename__in=codenames)
        self.user_permissions.set(perms)


# -----------------------------------------------------------------------------
# 2. Dossier Patient Unique (DPI)
# -----------------------------------------------------------------------------
def validate_french_nir(nir: str) -> None:
    """
    Valide la structure et la clé de contrôle modulo 97 d'un NIR français
    (Numéro de Sécurité Sociale à 13 chiffres + 2 chiffres de clé).
    """
    if not nir:
        return
    cleaned = nir.strip().replace(" ", "").upper()
    if len(cleaned) != 15:
        raise ValidationError("Le NIR doit comporter exactement 15 caractères (13 chiffres + 2 chiffres de clé).")

    base = cleaned[:13]
    key_str = cleaned[13:]

    if not key_str.isdigit():
        raise ValidationError("La clé du NIR doit être numérique.")

    # Gestion de la Corse (2A -> 19, 2B -> 18)
    base_numeric = base.replace("2A", "19").replace("2B", "18")
    if not base_numeric.isdigit():
        raise ValidationError("Le corps du NIR contient des caractères invalides.")

    nir_num = int(base_numeric)
    expected_key = 97 - (nir_num % 97)
    actual_key = int(key_str)

    if expected_key != actual_key:
        raise ValidationError(
            f"Clé de contrôle du NIR invalide (calculée: {expected_key:02d}, fournie: {actual_key:02d})."
        )


class BloodGroup(models.TextChoices):
    A_POS = "A+", "A RhD positif (A+)"
    A_NEG = "A-", "A RhD négatif (A-)"
    B_POS = "B+", "B RhD positif (B+)"
    B_NEG = "B-", "B RhD négatif (B-)"
    AB_POS = "AB+", "AB RhD positif (AB+)"
    AB_NEG = "AB-", "AB RhD négatif (AB-)"
    O_POS = "O+", "O RhD positif (O+)"
    O_NEG = "O-", "O RhD négatif (O-)"
    INDETERMINE = "IND", "Indéterminé"


class PatientStatusColor(models.TextChoices):
    """Palette de couleurs normée pour les badges de statut patient."""

    SKY = "sky", "Bleu Ciel (Admission / Accueil)"
    INDIGO = "indigo", "Indigo (Service / Unité de soin)"
    ROSE = "rose", "Rouge Corail (Bloc Opératoire / Urgence)"
    AMBER = "amber", "Ambre / Orange (Réveil / Surveillance SSPI)"
    EMERALD = "emerald", "Vert Émeraude (Sortie / Validé)"
    PURPLE = "purple", "Violet (Reporté / En attente)"
    SLATE = "slate", "Gris Ardoise (Annulé / Clôturé)"


DEFAULT_PATIENT_STATUSES = [
    {
        "code": "ADMISSION",
        "label": "Admission",
        "description": "Patient enregistré à l'accueil / en préparation pré-hospitalière",
        "color_theme": PatientStatusColor.SKY,
        "hex_color": "#0284C7",
        "display_order": 1,
        "is_terminal": False,
        "is_system_default": True,
    },
    {
        "code": "SERVICE",
        "label": "Service",
        "description": "Patient installé en chambre dans son unité d'hospitalisation",
        "color_theme": PatientStatusColor.INDIGO,
        "hex_color": "#4F46E5",
        "display_order": 2,
        "is_terminal": False,
        "is_system_default": True,
    },
    {
        "code": "BLOC",
        "label": "Bloc",
        "description": "Patient actuellement en salle d'intervention au bloc opératoire",
        "color_theme": PatientStatusColor.ROSE,
        "hex_color": "#E11D48",
        "display_order": 3,
        "is_terminal": False,
        "is_system_default": True,
    },
    {
        "code": "REVEIL",
        "label": "Réveil",
        "description": "Patient en Salle de Surveillance Post-Interventionnelle (SSPI)",
        "color_theme": PatientStatusColor.AMBER,
        "hex_color": "#D97706",
        "display_order": 4,
        "is_terminal": False,
        "is_system_default": True,
    },
    {
        "code": "REPORTE",
        "label": "Reporté",
        "description": "Acte ou prise en charge reportée à une date ultérieure",
        "color_theme": PatientStatusColor.PURPLE,
        "hex_color": "#9333EA",
        "display_order": 5,
        "is_terminal": False,
        "is_system_default": True,
    },
    {
        "code": "SORTIE",
        "label": "Sortie",
        "description": "Patient ayant quitté l'établissement après validation médicale",
        "color_theme": PatientStatusColor.EMERALD,
        "hex_color": "#059669",
        "display_order": 6,
        "is_terminal": True,
        "is_system_default": True,
    },
    {
        "code": "ANNULE",
        "label": "Annulé",
        "description": "Admission ou venue annulée avant prise en charge",
        "color_theme": PatientStatusColor.SLATE,
        "hex_color": "#64748B",
        "display_order": 7,
        "is_terminal": True,
        "is_system_default": True,
    },
]


class PatientStatusConfig(AuditableModel):
    """
    Table de paramétrage général des statuts de parcours patient après admission.
    Permet aux administrateurs d'ajouter, modifier ou désactiver dynamiquement des statuts.
    """

    code = models.CharField(
        max_length=40,
        unique=True,
        verbose_name="Code technique",
        help_text="Identifiant unique en majuscules (ex: ADMISSION, BLOC, REVEIL)",
    )
    label = models.CharField(max_length=80, verbose_name="Libellé du statut")
    description = models.CharField(max_length=255, blank=True, verbose_name="Description fonctionnelle")
    color_theme = models.CharField(
        max_length=20,
        choices=PatientStatusColor.choices,
        default=PatientStatusColor.SKY,
        verbose_name="Thème de couleur (Badge UI)",
    )
    hex_color = models.CharField(
        max_length=7,
        default="#0284C7",
        verbose_name="Couleur HEX (#RRGGBB)",
    )
    display_order = models.PositiveIntegerField(default=10, verbose_name="Ordre d'affichage")
    is_terminal = models.BooleanField(
        default=False,
        verbose_name="Statut de fin de parcours (Sortie / Annulé)",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Statut actif",
        help_text="Désactivez pour masquer ce statut sans perdre l'historique des patients.",
    )
    is_system_default = models.BooleanField(
        default=False,
        verbose_name="Statut initial par défaut du système",
    )

    class Meta:
        verbose_name = "Paramétrage Statut Patient"
        verbose_name_plural = "Paramétrage des Statuts Patients"
        ordering = ["display_order", "label"]

    def __str__(self) -> str:
        return f"{self.label}"

    def clean(self) -> None:
        super().clean()
        if self.code:
            self.code = self.code.strip().upper().replace(" ", "_")

    @property
    def badge_classes(self) -> str:
        mapping = {
            PatientStatusColor.SKY: "bg-sky-50 text-sky-700 border-sky-200",
            PatientStatusColor.INDIGO: "bg-indigo-50 text-indigo-700 border-indigo-200",
            PatientStatusColor.ROSE: "bg-rose-50 text-rose-700 border-rose-200",
            PatientStatusColor.AMBER: "bg-amber-50 text-amber-800 border-amber-200",
            PatientStatusColor.EMERALD: "bg-emerald-50 text-emerald-700 border-emerald-200",
            PatientStatusColor.PURPLE: "bg-purple-50 text-purple-700 border-purple-200",
            PatientStatusColor.SLATE: "bg-slate-100 text-slate-600 border-slate-300",
        }
        return mapping.get(self.color_theme, "bg-slate-100 text-slate-700 border-slate-300")

    @property
    def dot_classes(self) -> str:
        mapping = {
            PatientStatusColor.SKY: "bg-sky-500",
            PatientStatusColor.INDIGO: "bg-indigo-500",
            PatientStatusColor.ROSE: "bg-rose-500 animate-pulse",
            PatientStatusColor.AMBER: "bg-amber-500 animate-pulse",
            PatientStatusColor.EMERALD: "bg-emerald-500",
            PatientStatusColor.PURPLE: "bg-purple-500",
            PatientStatusColor.SLATE: "bg-slate-400",
        }
        return mapping.get(self.color_theme, "bg-slate-400")

    @classmethod
    def ensure_default_statuses(cls) -> Dict[str, "PatientStatusConfig"]:
        """Garantit l'existence des 7 statuts initiaux réglementaires dans la base."""
        result = {}
        for item in DEFAULT_PATIENT_STATUSES:
            obj, _ = cls.objects.get_or_create(
                code=item["code"],
                defaults=item,
            )
            result[item["code"]] = obj
        return result


class Patient(AuditableModel):
    """
    Dossier Patient Unique (DPI) partagé entre l'ensemble des départements et spécialités.
    Identifiant Permanent du Patient (IPP) unique et garanti immuable.
    Intègre le suivi en temps réel du statut actuel du patient après son admission.
    """

    ipp = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        verbose_name="IPP (Identifiant Permanent Patient)",
        help_text="Format normalisé : IPP-YYYY-XXXXXX",
    )
    nir = models.CharField(
        max_length=15,
        unique=True,
        validators=[validate_french_nir],
        verbose_name="Numéro de Sécurité Sociale (NIR)",
        help_text="15 caractères avec clé de contrôle",
    )
    last_name = models.CharField(max_length=100, verbose_name="Nom usuel")
    first_name = models.CharField(max_length=100, verbose_name="Prénom")
    maiden_name = models.CharField(max_length=100, blank=True, verbose_name="Nom de naissance")
    birth_date = models.DateField(verbose_name="Date de naissance")
    gender = models.CharField(
        max_length=1,
        choices=[("M", "Masculin"), ("F", "Féminin"), ("I", "Indéterminé")],
        verbose_name="Sexe biologique",
    )
    blood_group = models.CharField(
        max_length=4,
        choices=BloodGroup.choices,
        default=BloodGroup.INDETERMINE,
        verbose_name="Groupe sanguin & Rhésus",
    )
    current_status = models.ForeignKey(
        PatientStatusConfig,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="patients",
        verbose_name="Statut actuel du patient",
    )
    status_updated_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Dernier changement de statut",
    )
    known_allergies = models.TextField(blank=True, verbose_name="Allergies connues")
    major_medical_history = models.TextField(blank=True, verbose_name="Antécédents médico-chirurgicaux majeurs")
    ongoing_treatments = models.TextField(blank=True, verbose_name="Traitements en cours")
    trusted_person_name = models.CharField(max_length=120, blank=True, verbose_name="Personne de confiance / Représentant légal")
    trusted_person_relation = models.CharField(
        max_length=80,
        blank=True,
        default="Représentant légal / Tuteur",
        verbose_name="Qualité du représentant légal",
    )
    trusted_person_phone = models.CharField(max_length=25, blank=True, verbose_name="Téléphone de la personne de confiance")
    phone = models.CharField(max_length=25, blank=True, verbose_name="Téléphone patient")
    email = models.EmailField(blank=True, verbose_name="Adresse courriel")
    address = models.CharField(max_length=255, blank=True, verbose_name="Adresse postale")
    city = models.CharField(max_length=100, blank=True, verbose_name="Ville / Commune")
    state_province = models.CharField(max_length=100, blank=True, verbose_name="Wilaya / Province / État")
    national_id_number = models.CharField(max_length=50, blank=True, verbose_name="N° PC ou Carte d'Identité (CI)")

    class Meta:
        verbose_name = "Dossier Patient Unique (DPI)"
        verbose_name_plural = "Dossiers Patients Uniques (DPI)"
        ordering = ["last_name", "first_name"]

    def __str__(self) -> str:
        return f"{self.last_name.upper()} {self.first_name} (IPP: {self.ipp})"

    def save(self, *args, **kwargs) -> None:
        """
        Génération automatique de l'IPP hospitalier et affectation du statut initial 'Admission'
        si aucun statut actuel n'est encore défini.
        """
        if not self.ipp:
            current_year = date.today().year
            last_patient = (
                Patient.objects.filter(ipp__startswith=f"IPP-{current_year}-")
                .order_by("-ipp")
                .first()
            )
            if last_patient and last_patient.ipp:
                try:
                    seq_num = int(last_patient.ipp.split("-")[-1]) + 1
                except (ValueError, IndexError):
                    seq_num = 1
            else:
                seq_num = 1
            self.ipp = f"IPP-{current_year}-{seq_num:06d}"

        if not self.current_status_id:
            admission_status = PatientStatusConfig.objects.filter(code="ADMISSION", is_active=True).first()
            if admission_status:
                self.current_status = admission_status
                if not self.status_updated_at:
                    self.status_updated_at = timezone.now()

        super().save(*args, **kwargs)

    @transaction.atomic
    def change_status(
        self,
        new_status: PatientStatusConfig,
        changed_by: CustomUser,
        comment: str = "",
    ) -> "PatientStatusHistory":
        """
        Met à jour en temps réel le statut actuel du patient et enregistre l'historique
        complet (Date/Heure, Ancien statut, Nouveau statut, Utilisateur) de manière atomique.
        """
        if not new_status.is_active:
            raise ValidationError("Impossible d'affecter un statut désactivé.")

        old_status = self.current_status
        now = timezone.now()
        self.current_status = new_status
        self.status_updated_at = now
        self.save(update_fields=["current_status", "status_updated_at", "updated_at"])

        return PatientStatusHistory.objects.create(
            patient=self,
            old_status=old_status,
            new_status=new_status,
            changed_by=changed_by,
            comment=comment,
        )


class PatientStatusHistory(models.Model):
    """
    Journal d'audit immuable (HDS / RGPD) conservant l'historique complet
    de tous les changements de statut d'un patient après son admission.
    """

    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name="status_history",
        verbose_name="Patient (DPI)",
    )
    old_status = models.ForeignKey(
        PatientStatusConfig,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="transitions_from",
        verbose_name="Ancien statut",
    )
    new_status = models.ForeignKey(
        PatientStatusConfig,
        on_delete=models.PROTECT,
        related_name="transitions_to",
        verbose_name="Nouveau statut",
    )
    changed_by = models.ForeignKey(
        CustomUser,
        on_delete=models.PROTECT,
        related_name="patient_status_changes",
        verbose_name="Modifié par (Utilisateur)",
    )
    comment = models.TextField(blank=True, verbose_name="Observation / Motif")
    changed_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        verbose_name="Date et heure du changement",
    )

    class Meta:
        verbose_name = "Historique de Statut Patient"
        verbose_name_plural = "Historiques des Statuts Patients"
        ordering = ["-changed_at", "-id"]

    def __str__(self) -> str:
        old_label = self.old_status.label if self.old_status else "Initial"
        return (
            f"{self.patient.last_name} : {old_label} -> {self.new_status.label} "
            f"({self.changed_at.strftime('%d/%m/%Y %H:%M')} par {self.changed_by.username})"
        )


# -----------------------------------------------------------------------------
# 3. Gestion des Rendez-vous avec Validateur Anti-Collision
# -----------------------------------------------------------------------------
class AppointmentStatus(models.TextChoices):
    PLANIFIE = "PLANIFIE", "Planifié"
    CONFIRME = "CONFIRME", "Confirmé"
    EN_COURS = "EN_COURS", "En cours"
    HONORE = "HONORE", "Honoré"
    ANNULE = "ANNULE", "Annulé"
    ABSENT = "ABSENT", "Patient absent non excusé"


class Appointment(AuditableModel):
    """
    Rendez-vous médical avec contrôle strict d'absence de chevauchement d'agenda
    pour le médecin concerné.
    """

    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name="appointments",
        verbose_name="Patient",
    )
    practitioner = models.ForeignKey(
        CustomUser,
        on_delete=models.PROTECT,
        related_name="practitioner_appointments",
        verbose_name="Médecin / Praticien",
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="department_appointments",
        verbose_name="Département",
    )
    start_datetime = models.DateTimeField(verbose_name="Date et heure de début")
    end_datetime = models.DateTimeField(verbose_name="Date et heure de fin")
    reason = models.CharField(max_length=200, verbose_name="Motif du rendez-vous")
    status = models.CharField(
        max_length=20,
        choices=AppointmentStatus.choices,
        default=AppointmentStatus.PLANIFIE,
        verbose_name="Statut du rendez-vous",
    )
    clinical_notes = models.TextField(blank=True, verbose_name="Notes cliniques post-consultation")

    class Meta:
        verbose_name = "Rendez-vous Médical"
        verbose_name_plural = "Rendez-vous Médicaux"
        ordering = ["start_datetime"]

    def __str__(self) -> str:
        return f"RDV {self.patient.last_name} avec Dr {self.practitioner.last_name} le {self.start_datetime.strftime('%d/%m/%Y %H:%M')}"

    def clean(self) -> None:
        """
        Validateur strict empêchant les doubles réservations pour un même médecin
        sur des créneaux horaires qui se chevauchent.
        """
        super().clean()
        if not self.start_datetime or not self.end_datetime:
            return

        if self.end_datetime <= self.start_datetime:
            raise ValidationError(
                {"end_datetime": "La date et l'heure de fin doivent être strictement postérieures au début."}
            )

        # Vérification des chevauchements d'agenda pour ce praticien
        if self.practitioner_id and self.status != AppointmentStatus.ANNULE:
            overlapping_query = (
                Appointment.objects.filter(practitioner=self.practitioner)
                .exclude(id=self.id)
                .exclude(status=AppointmentStatus.ANNULE)
                .filter(
                    start_datetime__lt=self.end_datetime,
                    end_datetime__gt=self.start_datetime,
                )
            )

            if overlapping_query.exists():
                conflict = overlapping_query.first()
                raise ValidationError(
                    {
                        "start_datetime": (
                            f"Conflit d'agenda détecté : Le Dr {self.practitioner.get_full_name() or self.practitioner.username} "
                            f"a déjà un rendez-vous planifié ({conflict.reason}) de "
                            f"{conflict.start_datetime.strftime('%H:%M')} à {conflict.end_datetime.strftime('%H:%M')} le même jour."
                        )
                    }
                )


# -----------------------------------------------------------------------------
# 4. Gestion des Lits et Hospitalisations Automatisées
# -----------------------------------------------------------------------------
class BedStatus(models.TextChoices):
    DISPONIBLE = "DISPONIBLE", "Disponible"
    OCCUPE = "OCCUPE", "Occupé"
    NETTOYAGE = "NETTOYAGE", "En cours de désinfection / Nettoyage"
    MAINTENANCE = "MAINTENANCE", "Hors service / Maintenance"


class Bed(AuditableModel):
    """Lit hospitalier rattaché à une chambre et un département."""

    service = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="beds",
        verbose_name="Service / Département",
    )
    room_number = models.CharField(max_length=20, verbose_name="Numéro de chambre")
    bed_number = models.CharField(max_length=10, verbose_name="Numéro de lit", default="1")
    status = models.CharField(
        max_length=20,
        choices=BedStatus.choices,
        default=BedStatus.DISPONIBLE,
        verbose_name="Statut du lit",
    )

    class Meta:
        verbose_name = "Lit Hospitalier"
        verbose_name_plural = "Lits Hospitaliers"
        unique_together = ("service", "room_number", "bed_number")
        ordering = ["service", "room_number", "bed_number"]

    def __str__(self) -> str:
        return f"{self.service.code} - Ch. {self.room_number} (Lit {self.bed_number}) [{self.get_status_display()}]"


class HospitalizationStatus(models.TextChoices):
    EN_COURS = "EN_COURS", "Hospitalisation en cours"
    CLOTUREE = "CLOTUREE", "Sortie effectuée"
    TRANSFEREE = "TRANSFEREE", "Transféré vers autre établissement"


class Hospitalization(AuditableModel):
    """
    Séjour hospitalier.
    Automatisation du statut des lits :
    - À l'admission active : le lit passe automatiquement à 'OCCUPÉ'.
    - À la saisie de la date de sortie réelle : le lit passe automatiquement à 'NETTOYAGE'.
    """

    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name="hospitalizations",
        verbose_name="Patient hospitalisé",
    )
    bed = models.ForeignKey(
        Bed,
        on_delete=models.PROTECT,
        related_name="hospitalizations",
        verbose_name="Lit affecté",
    )
    practitioner = models.ForeignKey(
        CustomUser,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="referring_hospitalizations",
        verbose_name="Médecin référent",
    )
    admission_date = models.DateTimeField(default=timezone.now, verbose_name="Date et heure d'admission")
    expected_discharge_date = models.DateTimeField(verbose_name="Date prévisionnelle de sortie")
    actual_discharge_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Date et heure de sortie réelle",
        help_text="Dès renseignement, le lit bascule automatiquement au statut 'NETTOYAGE'.",
    )
    admission_reason = models.TextField(verbose_name="Motif d'hospitalisation")
    entry_diagnosis = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Diagnostic principal d'entrée",
    )
    status = models.CharField(
        max_length=20,
        choices=HospitalizationStatus.choices,
        default=HospitalizationStatus.EN_COURS,
        verbose_name="Statut du séjour",
    )

    class Meta:
        verbose_name = "Séjour Hospitalier / Hospitalisation"
        verbose_name_plural = "Séjours Hospitaliers / Hospitalisations"
        ordering = ["-admission_date"]

    def __str__(self) -> str:
        return f"Hospitalisation {self.patient.last_name} ({self.bed}) - {self.get_status_display()}"

    def clean(self) -> None:
        """Contrôles d'intégrité métier lors de l'admission et de la sortie."""
        super().clean()
        if self.actual_discharge_date and self.actual_discharge_date < self.admission_date:
            raise ValidationError(
                {"actual_discharge_date": "La date de sortie réelle ne peut pas précéder la date d'admission."}
            )

        if not self.actual_discharge_date:
            # Séjour en cours : vérifier si le lit est disponible ou s'il s'agit déjà de l'hospitalisation courante
            active_hosp = Hospitalization.objects.filter(
                bed=self.bed,
                actual_discharge_date__isnull=True,
            ).exclude(id=self.id)

            if active_hosp.exists():
                raise ValidationError(
                    {"bed": f"Le lit {self.bed} est actuellement déjà occupé par un autre patient hospitalisé."}
                )

            if not self.pk and self.bed.status in (BedStatus.OCCUPE, BedStatus.MAINTENANCE):
                raise ValidationError(
                    {"bed": f"Le lit sélectionné n'est pas disponible pour une nouvelle admission (Statut: {self.bed.get_status_display()})."}
                )

    def save(self, *args, **kwargs) -> None:
        """
        Application automatique de la logique d'état des lits avec transaction atomique
        (admission, transfert inter-lits/services et sortie réelle).
        """
        with transaction.atomic():
            previous_bed = None
            if self.pk:
                prev_hosp = Hospitalization.objects.select_related("bed").filter(pk=self.pk).first()
                if prev_hosp and prev_hosp.bed_id != self.bed_id:
                    previous_bed = prev_hosp.bed

            if self.actual_discharge_date:
                # Sortie effective : clôture du séjour et passage immédiat du lit au statut NETTOYAGE
                self.status = HospitalizationStatus.CLOTUREE
                super().save(*args, **kwargs)
                if previous_bed and previous_bed.status == BedStatus.OCCUPE:
                    previous_bed.status = BedStatus.NETTOYAGE
                    previous_bed.save(update_fields=["status", "updated_at"])
                if self.bed.status != BedStatus.NETTOYAGE:
                    self.bed.status = BedStatus.NETTOYAGE
                    self.bed.save(update_fields=["status", "updated_at"])
            else:
                # Admission active ou transfert de lit : l'ancien lit passe en NETTOYAGE et le nouveau à OCCUPÉ
                self.status = HospitalizationStatus.EN_COURS
                super().save(*args, **kwargs)
                if previous_bed and previous_bed.status == BedStatus.OCCUPE:
                    previous_bed.status = BedStatus.NETTOYAGE
                    previous_bed.save(update_fields=["status", "updated_at"])
                if self.bed.status != BedStatus.OCCUPE:
                    self.bed.status = BedStatus.OCCUPE
                    self.bed.save(update_fields=["status", "updated_at"])


# -----------------------------------------------------------------------------
# 5. Gestion des Gardes, Plannings et Remplacements Verrouillés
# -----------------------------------------------------------------------------
class ShiftType(models.TextChoices):
    JOUR = "JOUR", "Shift de Jour (08h00 - 18h00)"
    NUIT = "NUIT", "Garde de Nuit (18h00 - 08h00)"
    ASTREINTE = "ASTREINTE", "Astreinte Opérationnelle"
    GARDE_24H = "GARDE_24H", "Garde de 24 Heures (08h00 - 08h00)"


class DutyShift(AuditableModel):
    """
    Planification d'un shift ou d'une garde par département hospitalier.
    Détection et blocage automatique des chevauchements d'horaires pour un même soignant.
    """

    staff_member = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="duty_shifts",
        verbose_name="Personnel soignant planifié",
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="duty_shifts",
        verbose_name="Département hospitalier",
    )
    shift_date = models.DateField(verbose_name="Date de début du shift")
    shift_type = models.CharField(
        max_length=20,
        choices=ShiftType.choices,
        default=ShiftType.JOUR,
        verbose_name="Type de shift",
    )
    start_time = models.TimeField(verbose_name="Heure de début")
    end_time = models.TimeField(verbose_name="Heure de fin")
    is_cancelled = models.BooleanField(default=False, verbose_name="Shift annulé")

    class Meta:
        verbose_name = "Garde / Shift Médical"
        verbose_name_plural = "Gardes & Plannings Médicaux"
        ordering = ["shift_date", "start_time"]

    def __str__(self) -> str:
        return f"{self.shift_date.strftime('%d/%m/%Y')} | {self.get_shift_type_display()} - {self.staff_member.get_full_name() or self.staff_member.username} ({self.department.code})"

    def get_absolute_start_end_datetimes(self) -> tuple[datetime, datetime]:
        """Convertit le shift en timestamps absolus avec gestion des shifts de nuit franchissant minuit."""
        start_dt = datetime.combine(self.shift_date, self.start_time)
        if self.end_time <= self.start_time:
            # Le shift se termine le lendemain matin
            end_dt = datetime.combine(self.shift_date + timedelta(days=1), self.end_time)
        else:
            end_dt = datetime.combine(self.shift_date, self.end_time)
        return start_dt, end_dt

    def clean(self) -> None:
        """
        Détection et blocage rigoureux des chevauchements d'horaires pour le même soignant.
        """
        super().clean()
        if not self.shift_date or not self.start_time or not self.end_time or not self.staff_member_id:
            return

        if self.is_cancelled:
            return

        my_start, my_end = self.get_absolute_start_end_datetimes()

        # Recherche des autres shifts du soignant sur une fenêtre de +/- 1 jour
        potential_overlaps = (
            DutyShift.objects.filter(staff_member=self.staff_member, is_cancelled=False)
            .filter(shift_date__range=[self.shift_date - timedelta(days=1), self.shift_date + timedelta(days=1)])
            .exclude(id=self.id)
        )

        for other_shift in potential_overlaps:
            other_start, other_end = other_shift.get_absolute_start_end_datetimes()
            # Test de chevauchement strict des intervalles semi-ouverts
            if my_start < other_end and my_end > other_start:
                raise ValidationError(
                    {
                        "shift_date": (
                            f"Chevauchement d'horaires interdit pour {self.staff_member.get_full_name() or self.staff_member.username} : "
                            f"Un shift existe déjà le {other_shift.shift_date.strftime('%d/%m/%Y')} de "
                            f"{other_shift.start_time.strftime('%H:%M')} à {other_shift.end_time.strftime('%H:%M')} "
                            f"({other_shift.get_shift_type_display()} - {other_shift.department.name})."
                        )
                    }
                )


class ShiftReplacementStatus(models.TextChoices):
    DEMANDE = "DEMANDE", "Demande en attente"
    VALIDE = "VALIDE", "Validé par le chef de service"
    REFUSE = "REFUSE", "Refusé"
    ANNULE = "ANNULE", "Annulé"


class ShiftReplacement(AuditableModel):
    """
    Gestion des remplacements et permutations de gardes.
    Verrouillage strict : le remplaçant doit OBLIGATOIREMENT appartenir
    au même département hospitalier que le shift de soins d'origine.
    """

    duty_shift = models.ForeignKey(
        DutyShift,
        on_delete=models.CASCADE,
        related_name="replacement_requests",
        verbose_name="Garde / Shift à remplacer",
    )
    original_caregiver = models.ForeignKey(
        CustomUser,
        on_delete=models.PROTECT,
        related_name="original_shifts_replaced",
        verbose_name="Soignant titulaire",
    )
    substitute_caregiver = models.ForeignKey(
        CustomUser,
        on_delete=models.PROTECT,
        related_name="accepted_shift_replacements",
        verbose_name="Soignant remplaçant",
    )
    status = models.CharField(
        max_length=20,
        choices=ShiftReplacementStatus.choices,
        default=ShiftReplacementStatus.DEMANDE,
        verbose_name="Statut du remplacement",
    )
    validation_date = models.DateTimeField(null=True, blank=True, verbose_name="Date de validation administrative")
    reason = models.TextField(verbose_name="Motif de la demande de remplacement")

    class Meta:
        verbose_name = "Remplacement de Garde"
        verbose_name_plural = "Remplacements de Gardes"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return (
            f"Remplacement {self.duty_shift.shift_date.strftime('%d/%m/%Y')} : "
            f"{self.original_caregiver.last_name} -> {self.substitute_caregiver.last_name} "
            f"({self.duty_shift.department.code}) [{self.get_status_display()}]"
        )

    def clean(self) -> None:
        """
        Verrouillage sécuritaire :
        1. Le remplaçant doit appartenir au même département que le shift.
        2. Le titulaire et le remplaçant ne peuvent pas être la même personne.
        3. Le remplaçant ne doit pas être déjà de garde sur le même créneau.
        """
        super().clean()
        if not self.duty_shift_id or not self.substitute_caregiver_id or not self.original_caregiver_id:
            return

        if self.substitute_caregiver == self.original_caregiver:
            raise ValidationError(
                {"substitute_caregiver": "Le soignant remplaçant ne peut pas être identique au soignant d'origine."}
            )

        # Règle stricte d'affectation départementale :
        # Le remplaçant doit impérativement appartenir au même département de soin que le shift
        required_department = self.duty_shift.department
        if self.substitute_caregiver.department_id != required_department.id:
            raise ValidationError(
                {
                    "substitute_caregiver": (
                        f"Verrouillage de sécurité départementale : Le remplaçant doit obligatoirement "
                        f"appartenir au département de soin de la garde ({required_department.name}). "
                        f"Le soignant sélectionné appartient actuellement à "
                        f"'{self.substitute_caregiver.department.name if self.substitute_caregiver.department else 'Aucun'}."
                    )
                }
            )

        # Vérifier que le remplaçant n'a pas lui-même un chevauchement horaire
        my_start, my_end = self.duty_shift.get_absolute_start_end_datetimes()
        overlapping_substitute_shifts = (
            DutyShift.objects.filter(staff_member=self.substitute_caregiver, is_cancelled=False)
            .filter(
                shift_date__range=[
                    self.duty_shift.shift_date - timedelta(days=1),
                    self.duty_shift.shift_date + timedelta(days=1),
                ]
            )
            .exclude(id=self.duty_shift.id)
        )

        for other_shift in overlapping_substitute_shifts:
            o_start, o_end = other_shift.get_absolute_start_end_datetimes()
            if my_start < o_end and my_end > o_start:
                raise ValidationError(
                    {
                        "substitute_caregiver": (
                            f"Le remplaçant {self.substitute_caregiver.get_full_name()} a déjà un shift programmé "
                            f"en conflit horaire le {other_shift.shift_date.strftime('%d/%m/%Y')} ({other_shift.start_time.strftime('%H:%M')} - {other_shift.end_time.strftime('%H:%M')})."
                        )
                    }
                )

    def save(self, *args, **kwargs) -> None:
        """Si le remplacement est validé, met à jour la date de validation."""
        if self.status == ShiftReplacementStatus.VALIDE and not self.validation_date:
            self.validation_date = timezone.now()
        super().save(*args, **kwargs)


# -----------------------------------------------------------------------------
# 6. Journal d'Audit de Sécurité Immuable (RGPD / HDS / HIPAA)
# -----------------------------------------------------------------------------
class AuditActionType(models.TextChoices):
    """Types d'actions journalisées dans le registre d'audit de sécurité."""

    CREATE = "CREATE", "Création de dossier / mouvement"
    READ = "READ", "Consultation de dossier"
    UPDATE = "UPDATE", "Mise à jour administrative / mouvement"
    DELETE_ATTEMPT = "DELETE_ATTEMPT", "Tentative de suppression bloquée"
    ACCESS_DENIED = "ACCESS_DENIED", "Accès refusé (Secret Médical)"
    SESSION_TIMEOUT = "SESSION_TIMEOUT", "Expiration de session pour inactivité (5 min)"


class ImmutableAuditQuerySet(models.QuerySet):
    """Empêche toute modification ou suppression en masse sur la table d'audit."""

    def update(self, **kwargs):
        raise ValidationError("Sécurité HDS : La modification en masse des journaux d'audit est strictement interdite.")

    def delete(self):
        raise ValidationError("Sécurité HDS : La suppression en masse des journaux d'audit est strictement interdite.")


class SecurityAuditLog(models.Model):
    """
    Journal d'audit de sécurité immuable (WORM : Write-Once-Read-Many) conforme HDS / RGPD / HIPAA.
    Enregistre obligatoirement pour chaque action :
    - user (ID_Utilisateur)
    - timestamp (Horodatage)
    - patient (ID_Patient)
    - action_type (Type_Action)
    """

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.PROTECT,
        related_name="security_audit_logs",
        verbose_name="Utilisateur (ID_Utilisateur)",
    )
    timestamp = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        editable=False,
        verbose_name="Horodatage",
    )
    patient = models.ForeignKey(
        Patient,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="security_audit_logs",
        verbose_name="Patient (ID_Patient)",
    )
    patient_ipp = models.CharField(max_length=20, blank=True, verbose_name="IPP Patient")
    action_type = models.CharField(
        max_length=30,
        choices=AuditActionType.choices,
        db_index=True,
        verbose_name="Type d'action",
    )
    resource_name = models.CharField(max_length=80, default="Patient", verbose_name="Ressource concernée")
    details = models.TextField(blank=True, verbose_name="Détails de l'opération")
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="Adresse IP")

    objects = ImmutableAuditQuerySet.as_manager()

    class Meta:
        verbose_name = "Journal d'Audit de Sécurité (HDS)"
        verbose_name_plural = "Journaux d'Audit de Sécurité (HDS)"
        ordering = ["-timestamp", "-id"]
        indexes = [
            models.Index(fields=["user", "-timestamp"], name="idx_sec_audit_user_ts"),
            models.Index(fields=["patient", "-timestamp"], name="idx_sec_audit_patient_ts"),
            models.Index(fields=["action_type", "-timestamp"], name="idx_sec_audit_action_ts"),
        ]

    def __str__(self) -> str:
        pat_str = self.patient_ipp or (f"Patient #{self.patient_id}" if self.patient_id else "Système")
        return (
            f"[{self.timestamp.strftime('%d/%m/%Y %H:%M:%S')}] "
            f"User={self.user_id} ({self.user.username}) | {self.action_type} | {pat_str}"
        )

    def save(self, *args, **kwargs) -> None:
        if self.pk is not None:
            raise ValidationError(
                "Sécurité HDS : Les entrées du journal d'audit sont immuables et ne peuvent pas être modifiées."
            )
        if self.patient and not self.patient_ipp:
            self.patient_ipp = self.patient.ipp
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs) -> None:
        raise ValidationError(
            "Sécurité HDS : La suppression d'entrées du journal d'audit est strictement interdite."
        )

    @classmethod
    def log_action(
        cls,
        user: Optional[CustomUser],
        action_type: str,
        patient: Optional[Patient] = None,
        resource_name: str = "Patient",
        details: str = "",
        ip_address: Optional[str] = None,
    ) -> Optional["SecurityAuditLog"]:
        """Enregistre de manière sécurisée une entrée immuable dans le journal d'audit."""
        if not user or not getattr(user, "is_authenticated", False):
            return None
        return cls.objects.create(
            user=user,
            patient=patient,
            patient_ipp=patient.ipp if patient else "",
            action_type=action_type,
            resource_name=resource_name,
            details=details,
            ip_address=ip_address,
        )


