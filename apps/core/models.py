"""
Modèles du Socle Transversal (Core) - Système d'Information Hospitalier (SIH).
Conformité HDS / RGPD : Gestion du personnel (RBAC), DPI unifié,
gestion des rendez-vous avec anti-collision, cycle de vie automatisé des lits,
et gestion des gardes médicales avec verrouillage strict des permutations.
"""

from datetime import date, datetime, timedelta
import re
from typing import Optional

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


class CustomUser(AbstractUser):
    """
    Modèle utilisateur personnalisé pour l'ensemble du personnel hospitalier.
    Intègre les rôles stricts et l'affectation par département.
    """

    role = models.CharField(
        max_length=20,
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
                "view_department", "view_patient", "view_appointment",
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
                "view_appointment", "add_appointment", "change_appointment", "delete_appointment",
                "view_bed", "view_hospitalization", "add_hospitalization", "change_hospitalization",
                "view_dutyshift",
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


class Patient(AuditableModel):
    """
    Dossier Patient Unique (DPI) partagé entre l'ensemble des départements et spécialités.
    Identifiant Permanent du Patient (IPP) unique et garanti immuable.
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
    known_allergies = models.TextField(blank=True, verbose_name="Allergies connues")
    major_medical_history = models.TextField(blank=True, verbose_name="Antécédents médico-chirurgicaux majeurs")
    ongoing_treatments = models.TextField(blank=True, verbose_name="Traitements en cours")
    trusted_person_name = models.CharField(max_length=120, blank=True, verbose_name="Personne de confiance")
    trusted_person_phone = models.CharField(max_length=25, blank=True, verbose_name="Téléphone de la personne de confiance")
    phone = models.CharField(max_length=25, blank=True, verbose_name="Téléphone patient")
    email = models.EmailField(blank=True, verbose_name="Adresse courriel")

    class Meta:
        verbose_name = "Dossier Patient Unique (DPI)"
        verbose_name_plural = "Dossiers Patients Uniques (DPI)"
        ordering = ["last_name", "first_name"]

    def __str__(self) -> str:
        return f"{self.last_name.upper()} {self.first_name} (IPP: {self.ipp})"

    def save(self, *args, **kwargs) -> None:
        """Génération automatique et sécurisée de l'IPP hospitalier s'il n'existe pas encore."""
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
        super().save(*args, **kwargs)


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
    admission_date = models.DateTimeField(default=timezone.now, verbose_name="Date et heure d'admission")
    expected_discharge_date = models.DateTimeField(verbose_name="Date prévisionnelle de sortie")
    actual_discharge_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Date et heure de sortie réelle",
        help_text="Dès renseignement, le lit bascule automatiquement au statut 'NETTOYAGE'.",
    )
    admission_reason = models.TextField(verbose_name="Motif d'hospitalisation")
    entry_diagnosis = models.CharField(max_length=255, verbose_name="Diagnostic principal d'entrée")
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
        Application automatique de la logique d'état des lits avec transaction atomique.
        """
        with transaction.atomic():
            if self.actual_discharge_date:
                # Sortie effective : clôture du séjour et passage immédiat du lit au statut NETTOYAGE
                self.status = HospitalizationStatus.CLOTUREE
                super().save(*args, **kwargs)
                if self.bed.status != BedStatus.NETTOYAGE:
                    self.bed.status = BedStatus.NETTOYAGE
                    self.bed.save(update_fields=["status", "updated_at"])
            else:
                # Admission active : le lit passe automatiquement à OCCUPÉ
                self.status = HospitalizationStatus.EN_COURS
                super().save(*args, **kwargs)
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

