# Spécification Fonctionnelle, Technique & Sécurité (HDS / RGPD / HIPAA)
## Nouveau Rôle : « Gestionnaire des Admissions et Hospitalisations » (`GESTIONNAIRE_ADMISSION`)

- **Système** : SIH — Clinique Sidi Yahia 2
- **Principe directeur** : Moindre privilège (*Least Privilege*), Cloisonnement strict entre données administratives/hôtelières et données couvertes par le Secret Médical (Article L.1110-4 du CSP / RGPD Art. 9 / HIPAA Privacy Rule).

---

## 1. Matrice de Cloisonnement des Données & Droits CRUD

| Domaine / Ressource | Créer (`C`) | Lire (`R`) | Modifier (`U`) | Supprimer (`D`) | Cloisonnement & Filtrage des Champs (Field-Level Security) |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Dossier Patient (`Patient`) — Volet Administratif** | ✅ Oui | ✅ Oui | ✅ Oui | ❌ **Interdit** | Accès autorisé : `ipp`, `nir`, `last_name`, `first_name`, `maiden_name`, `birth_date`, `gender`, `blood_group`, `phone`, `email`, `trusted_person_*`, `current_status`. |
| **Dossier Patient (`Patient`) — Alertes Sécurité Placement** | ❌ Non | ✅ **Lecture seule** | ❌ Non | ❌ Interdit | Lecture seule de `known_allergies` uniquement (sécurité hôtelière/alimentaire/latex lors du placement). |
| **Dossier Patient (`Patient`) — Volet Médical Confidentiel** | ❌ Non | ❌ **Masqué** | ❌ Non | ❌ Interdit | Champs **strictement exclus/masqués** : `major_medical_history` (Antécédents), `ongoing_treatments` (Prescriptions/Traitements). |
| **Séjours & Mouvements (`Hospitalization`)** | ✅ Oui | ✅ Oui | ✅ Oui | ❌ **Interdit** | Accès CRU à `patient`, `bed`, `admission_date`, `expected_discharge_date`, `actual_discharge_date`, `status`. Lecture seule sur `admission_reason` (motif générique). **Masquage strict** de `entry_diagnosis` (Diagnostic médical CIM-10). |
| **Parc des Lits & Chambres (`Bed`, `Department`)** | ❌ Non | ✅ **Lecture seule** | ❌ Non* | ❌ Interdit | Consultation temps réel du statut d'occupation par service (`DISPONIBLE`, `OCCUPE`, `NETTOYAGE`, `MAINTENANCE`). *(La bascule du lit `OCCUPE`/`NETTOYAGE` s'opère automatiquement via l'admission/sortie).* |
| **Rendez-vous & Médecin Référent (`Appointment`)** | ✅ Oui | ✅ Oui | ✅ Oui | ❌ Interdit | Lecture du médecin référent (`practitioner`) et du motif générique (`reason`). **Aucun accès** à `clinical_notes`. |
| **Pôles Cliniques & Comptes-Rendus (`Chirurgie`, `Maternité`, `Pédiatrie`, `Urologie`)** | ❌ Non | ❌ **Aucun accès** | ❌ Non | ❌ Interdit | **Blocage HTTP 403 total** sur les CRO (`OperativeReport`), bilans (`UrodynamicAssessment`), dossiers obstétricaux, courbes et vaccinations. |

---

## 2. Livrable A — Structure de Base de Données (SQL PostgreSQL / SQLite)

### 2.1 Ajout du Rôle et Table d'Audit Immuable (`core_securityauditlog`)

Conformément aux exigences de traçabilité HDS/RGPD, chaque action (`CREATE`, `READ`, `UPDATE`, `ACCESS_DENIED`) portant sur un dossier patient ou un mouvement hospitalier génère un enregistrement dans une table **Append-Only** protégée contre toute modification ou suppression (`REVOKE UPDATE, DELETE`).

```sql
-- 1. Ajout de la valeur 'GESTIONNAIRE_ADMISSION' dans la contrainte de rôle utilisateur
ALTER TABLE core_customuser
DROP CONSTRAINT IF EXISTS chk_customuser_role;

ALTER TABLE core_customuser
ADD CONSTRAINT chk_customuser_role CHECK (
    role IN (
        'ADMIN',
        'MEDECIN',
        'CHIRURGIEN',
        'INFIRMIER',
        'SAGE_FEMME',
        'SECRETAIRE',
        'GESTIONNAIRE_ADMISSION'
    )
);

-- 2. Table de Journalisation d'Audit Immuable (HDS / RGPD / HIPAA)
CREATE TABLE core_securityauditlog (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL
        REFERENCES core_customuser(id) ON DELETE PROTECT,
    user_role VARCHAR(30) NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    patient_id BIGINT NULL
        REFERENCES core_patient(id) ON DELETE SET NULL,
    patient_ipp VARCHAR(20) NOT NULL DEFAULT '',
    action_type VARCHAR(20) NOT NULL CHECK (
        action_type IN ('CREATE', 'READ', 'UPDATE', 'DELETE_ATTEMPT', 'ACCESS_DENIED')
    ),
    target_model VARCHAR(60) NOT NULL,          -- Ex: 'Patient', 'Hospitalization', 'Bed'
    target_object_id VARCHAR(40) NOT NULL,      -- PK de l'objet manipulé
    changed_fields JSONB DEFAULT '{}'::jsonb,   -- Détail des champs administratifs modifiés (sans données médicales)
    ip_address INET NULL,
    user_agent VARCHAR(255) DEFAULT ''
);

-- Index haute performance pour les contrôles CNIL / HDS
CREATE INDEX idx_audit_patient_time ON core_securityauditlog (patient_id, timestamp DESC);
CREATE INDEX idx_audit_user_time ON core_securityauditlog (user_id, timestamp DESC);
CREATE INDEX idx_audit_action_type ON core_securityauditlog (action_type, timestamp DESC);

-- 3. Trigger PostgreSQL garantissant l'immuabilité stricte (Interdiction d'UPDATE et DELETE sur les logs)
CREATE OR REPLACE FUNCTION prevent_audit_log_tampering()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Sécurité HDS : Le journal d''audit (core_securityauditlog) est strictement immuable (Modification/Suppression interdite).';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_immutable_security_audit_log
BEFORE UPDATE OR DELETE ON core_securityauditlog
FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_tampering();
```

---

## 3. Livrable B — Configuration de Rôle JSON (Politique RBAC & ABAC)

Ce fichier de politique normalisé définit le périmètre exact du rôle `GESTIONNAIRE_ADMISSION`, le filtrage au niveau des champs (*Field-Level Security*), la politique de session (expiration à **5 minutes / 300 secondes**) et la journalisation obligatoire :

```json
{
  "role_definition": {
    "code": "GESTIONNAIRE_ADMISSION",
    "label": "Gestionnaire des Admissions et Hospitalisations",
    "category": "ADMINISTRATIF_FLUX_PATIENTS",
    "security_clearance": "ADMINISTRATIVE_HDS_LEVEL_1",
    "session_policy": {
      "inactivity_timeout_seconds": 300,
      "inactivity_timeout_minutes": 5,
      "absolute_session_timeout_seconds": 28800,
      "require_reauthentication_on_timeout": true,
      "concurrent_sessions_allowed": false
    },
    "audit_policy": {
      "enabled": true,
      "immutable": true,
      "logged_events": ["CREATE", "READ", "UPDATE", "DELETE_ATTEMPT", "ACCESS_DENIED"],
      "required_fields": ["user_id", "timestamp", "patient_id", "action_type"]
    },
    "permissions_matrix": {
      "core.Patient": {
        "operations": ["CREATE", "READ", "UPDATE"],
        "forbidden_operations": ["DELETE"],
        "readable_fields": [
          "id", "ipp", "nir", "last_name", "first_name", "maiden_name",
          "birth_date", "gender", "blood_group", "phone", "email",
          "trusted_person_name", "trusted_person_phone",
          "current_status", "status_updated_at", "known_allergies"
        ],
        "writable_fields": [
          "nir", "last_name", "first_name", "maiden_name",
          "birth_date", "gender", "blood_group", "phone", "email",
          "trusted_person_name", "trusted_person_phone", "current_status"
        ],
        "read_only_fields": ["id", "ipp", "known_allergies", "status_updated_at"],
        "hidden_medical_fields": [
          "major_medical_history",
          "ongoing_treatments"
        ]
      },
      "core.Hospitalization": {
        "operations": ["CREATE", "READ", "UPDATE"],
        "forbidden_operations": ["DELETE"],
        "readable_fields": [
          "id", "patient", "bed", "admission_date",
          "expected_discharge_date", "actual_discharge_date",
          "admission_reason", "status"
        ],
        "writable_fields": [
          "patient", "bed", "admission_date",
          "expected_discharge_date", "actual_discharge_date",
          "admission_reason", "status"
        ],
        "hidden_medical_fields": [
          "entry_diagnosis"
        ]
      },
      "core.Bed": {
        "operations": ["READ"],
        "forbidden_operations": ["CREATE", "UPDATE", "DELETE"],
        "readable_fields": ["id", "service", "room_number", "bed_number", "status"]
      },
      "core.Department": {
        "operations": ["READ"],
        "forbidden_operations": ["CREATE", "UPDATE", "DELETE"]
      },
      "core.Appointment": {
        "operations": ["CREATE", "READ", "UPDATE"],
        "forbidden_operations": ["DELETE"],
        "readable_fields": [
          "id", "patient", "practitioner", "department",
          "start_datetime", "end_datetime", "reason", "status"
        ],
        "hidden_medical_fields": ["clinical_notes"]
      },
      "clinical_modules": {
        "chirurgie.*": "DENY_ALL",
        "gynecologie_maternite.*": "DENY_ALL",
        "pediatrie.*": "DENY_ALL",
        "urologie.*": "DENY_ALL"
      }
    }
  }
}
```

---

## 4. Livrable C — Liste des User Stories Jira (avec Critères d'Acceptation Gherkin)

### US-ADM-01 : Gestion identito-vigilante du dossier administratif sans accès au dossier médical
- **En tant que** Gestionnaire des Admissions et Hospitalisations,
- **Je veux** créer, consulter et mettre à jour le dossier administratif d'un patient tout en voyant uniquement ses allergies vitales en lecture seule,
- **Afin d'** assurer son identitovigilance et sa sécurité lors du placement sans violer le secret médical ni risquer de supprimer un dossier.
- **Critères d'acceptation (Gherkin)** :
  - **Scénario 1 (Création & Modification CRU)** : *Étant donné* un utilisateur connecté avec le rôle `GESTIONNAIRE_ADMISSION`, *quand* il ouvre le formulaire Patient, *alors* il peut modifier l'état civil, le NIR, les coordonnées et la personne de confiance, voit le champ `known_allergies` en lecture seule, et les champs `major_medical_history` et `ongoing_treatments` sont totalement absents du DOM et de l'API.
  - **Scénario 2 (Interdiction de suppression)** : *Quand* il tente d'envoyer une requête de suppression (`DELETE /admin/core/patient/{id}/delete/`), *alors* le système rejette l'action avec un code `403 Forbidden` et génère un log d'audit `DELETE_ATTEMPT`.

### US-ADM-02 : Gestion des admissions, transferts de lits et planification des sorties
- **En tant que** Gestionnaire des Admissions et Hospitalisations,
- **Je veux** consulter en temps réel l'occupation des lits par service et créer/modifier une hospitalisation (attribution de lit, transfert de chambre/service, sortie),
- **Afin d'** optimiser le taux d'occupation des lits de la clinique en coordination avec les unités de soins.
- **Critères d'acceptation (Gherkin)** :
  - **Scénario 1 (Lecture seule du parc de lits)** : *Quand* l'utilisateur consulte la carte des lits, *alors* il visualise en temps réel les lits `DISPONIBLE`, `OCCUPE`, `NETTOYAGE` et `MAINTENANCE` de chaque service, mais ne peut ni supprimer ni modifier manuellement la structure d'un lit.
  - **Scénario 2 (Admission, Transfert et Sortie)** : *Quand* il affecte un patient à un lit disponible ou saisit sa date de sortie, *alors* le séjour est enregistré, le statut du lit bascule automatiquement (`OCCUPE` ou `NETTOYAGE`), et le champ médical `entry_diagnosis` (Diagnostic médical d'entrée) demeure masqué.

### US-ADM-03 : Verrouillage strict des comptes-rendus médicaux et pôles cliniques
- **En tant que** Responsable de la Sécurité du SIH (RSSI),
- **Je veux** bloquer tout accès du rôle `GESTIONNAIRE_ADMISSION` aux modules médicaux spécialisés (`Chirurgie`, `Maternité`, `Pédiatrie`, `Urologie`),
- **Afin de** garantir la conformité RGPD (Article 9) et le respect absolu du secret médical.
- **Critères d'acceptation (Gherkin)** :
  - **Scénario 1 (Rejet d'accès direct par URL)** : *Quand* un utilisateur `GESTIONNAIRE_ADMISSION` tente d'accéder à `/chirurgie/intervention/`, `/pediatrie/anthropometry/` ou `/urologie/assessment/`, *alors* le système renvoie `403 Forbidden` et inscrit un événement `ACCESS_DENIED` dans `SecurityAuditLog`.

### US-ADM-04 : Traçabilité HDS immuable et déconnexion automatique après 5 minutes d'inactivité
- **En tant que** Délégué à la Protection des Données (DPO),
- **Je veux** que chaque consultation, création ou modification d'un dossier patient par le Gestionnaire des Admissions soit journalisée et que sa session expire après 5 minutes d'inactivité,
- **Afin d'** empêcher tout accès non autorisé sur un poste d'accueil laissé sans surveillance et disposer d'une piste d'audit opposable.
- **Critères d'acceptation (Gherkin)** :
  - **Scénario 1 (Audit automatique)** : *Quand* le gestionnaire consulte ou modifie le patient `IPP-2026-000001`, *alors* une ligne immuable contenant `(ID_Utilisateur, Horodatage, ID_Patient, Type_Action)` est créée dans `SecurityAuditLog`.
  - **Scénario 2 (Expiration à 5 minutes)** : *Étant donné* que la dernière requête du gestionnaire remonte à plus de `300 secondes` (5 minutes), *quand* il effectue une nouvelle action, *alors* sa session est immédiatement invalidée et il est redirigé vers `/login/?timeout=1`.

---

## 5. Livrable D — Code d'Implémentation du Contrôle d'Accès (Python / Django)

### 5.1 Modèle `SecurityAuditLog` & Rôle `GESTIONNAIRE_ADMISSION` (`apps/core/models.py`)

```python
class UserRole(models.TextChoices):
    ADMIN = "ADMIN", "Administrateur Système / Directeur Médical"
    MEDECIN = "MEDECIN", "Médecin Praticien"
    CHIRURGIEN = "CHIRURGIEN", "Chirurgien"
    INFIRMIER = "INFIRMIER", "Infirmier(e) D.E."
    SAGE_FEMME = "SAGE_FEMME", "Sage-Femme"
    SECRETAIRE = "SECRETAIRE", "Secrétaire Médicale"
    GESTIONNAIRE_ADMISSION = "GESTIONNAIRE_ADMISSION", "Gestionnaire des Admissions et Hospitalisations"


class AuditActionType(models.TextChoices):
    CREATE = "CREATE", "Création de dossier / mouvement"
    READ = "READ", "Consultation de dossier"
    UPDATE = "UPDATE", "Mise à jour administrative / mouvement"
    DELETE_ATTEMPT = "DELETE_ATTEMPT", "Tentative de suppression bloquée"
    ACCESS_DENIED = "ACCESS_DENIED", "Accès refusé (Secret Médical)"


class SecurityAuditLog(models.Model):
    """
    Journal d'audit de sécurité immuable (HDS / RGPD / HIPAA).
    Trace obligatoirement : ID_Utilisateur, Horodatage, ID_Patient, Type_Action.
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
        max_length=20,
        choices=AuditActionType.choices,
        db_index=True,
        verbose_name="Type d'action",
    )
    resource_name = models.CharField(max_length=80, verbose_name="Ressource concernée")
    details = models.TextField(blank=True, verbose_name="Détails de l'opération")
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="Adresse IP")

    class Meta:
        verbose_name = "Journal d'Audit de Sécurité (HDS)"
        verbose_name_plural = "Journaux d'Audit de Sécurité (HDS)"
        ordering = ["-timestamp", "-id"]

    def save(self, *args, **kwargs) -> None:
        if self.pk:
            raise ValidationError("Sécurité HDS : Les entrées du journal d'audit sont immuables et ne peuvent pas être modifiées.")
        if self.patient and not self.patient_ipp:
            self.patient_ipp = self.patient.ipp
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Sécurité HDS : La suppression d'entrées du journal d'audit est strictement interdite.")
```

---

### 5.2 Middleware d'Expiration de Session à 5 Minutes d'Inactivité (`apps/core/middleware.py`)

```python
import time
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from apps.core.models import UserRole


class RoleInactivityTimeoutMiddleware:
    """
    Implémente l'expiration automatique de session après 5 minutes (300 secondes)
    d'inactivité pour le rôle GESTIONNAIRE_ADMISSION (poste d'accueil/admission exposé).
    """

    ROLE_TIMEOUTS_SECONDS = {
        UserRole.GESTIONNAIRE_ADMISSION: 300,  # 5 minutes strictes
    }
    DEFAULT_TIMEOUT_SECONDS = 28800  # 8 heures pour les sessions médicales standards

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            now_ts = int(time.time())
            user_role = getattr(request.user, "role", None)
            max_idle = self.ROLE_TIMEOUTS_SECONDS.get(user_role, self.DEFAULT_TIMEOUT_SECONDS)

            last_activity = request.session.get("last_activity_ts")
            if last_activity and (now_ts - int(last_activity)) > max_idle:
                logout(request)
                messages.warning(
                    request,
                    "Votre session a expiré par mesure de sécurité après 5 minutes d'inactivité.",
                )
                login_url = getattr(settings, "LOGIN_URL", "/login/")
                return redirect(f"{login_url}?timeout=1")

            request.session["last_activity_ts"] = now_ts

        return self.get_response(request)
```

---

### 5.3 Cloisonnement du Secret Médical & Audit Automatique dans Django Admin (`apps/core/admin.py`)

```python
# Dans PatientAdmin :
def get_readonly_fields(self, request, obj=None):
    ro = list(super().get_readonly_fields(request, obj))
    if getattr(request.user, "role", None) == UserRole.GESTIONNAIRE_ADMISSION:
        # Allergies vitales en lecture seule uniquement
        ro.append("known_allergies")
    return ro

def get_exclude(self, request, obj=None):
    excluded = list(super().get_exclude(request, obj) or [])
    if getattr(request.user, "role", None) == UserRole.GESTIONNAIRE_ADMISSION:
        # Masquage strict du dossier médical partagé et des prescriptions
        excluded.extend(["major_medical_history", "ongoing_treatments"])
    return excluded

def has_delete_permission(self, request, obj=None) -> bool:
    if getattr(request.user, "role", None) == UserRole.GESTIONNAIRE_ADMISSION:
        return False  # Interdiction stricte de supprimer un dossier patient
    return super().has_delete_permission(request, obj)

def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
    # Journalisation automatique de chaque consultation (READ) d'un dossier patient
    if object_id and request.method == "GET" and request.user.is_authenticated:
        patient = Patient.objects.filter(pk=object_id).first()
        if patient:
            SecurityAuditLog.objects.create(
                user=request.user,
                patient=patient,
                action_type=AuditActionType.READ,
                resource_name="Patient (DPI Administratif)",
                details=f"Consultation du dossier patient {patient.ipp}",
                ip_address=request.META.get("REMOTE_ADDR"),
            )
    return super().changeform_view(request, object_id, form_url, extra_context)
```

