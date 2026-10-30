# 🏥 Guide Complet d'Utilisation du SIH — Clinique Sidi Yahia 2

Ce guide présente le fonctionnement quotidien du **Système d'Information Hospitalier (SIH)** de la **Clinique Sidi Yahia 2**, ses 7 profils utilisateurs sécurisés (RBAC), et ses fonctionnalités clés.

---

## 1. Accès & Authentification Multi-Rôles (Zéro Accès Anonyme)

L'ensemble de l'application est protégé par le middleware `StrictAuthenticationMiddleware` : aucune page n'est accessible sans connexion préalable.

- **URL de connexion locale** : `http://127.0.0.1:8000/login/`
- **Comptes de démonstration pré-configurés** (accessibles en 1 clic sur la page de connexion) :

| Rôle Hospitalier | Identifiant | Mot de passe | Périmètre & Droits d'Accès |
| :--- | :--- | :--- | :--- |
| **Administrateur / Directeur Médical** | `admin` | `AdminPassword123!` | Supervision intégrale du SIH, paramétrage des statuts patients, gestion du personnel, tous les pôles cliniques, validation des remplacements et journaux d'audit HDS. |
| **Gestionnaire des Admissions et Hospitalisations** | `adm_karim` | `HospitalPass123!` | **CRU** Dossier administratif patient & séjours (sans droit de suppression), transferts de lits, lecture seule sur l'occupation des lits et les allergies vitales, **aucun accès au dossier médical**, session expirant après **5 minutes d'inactivité**. |
| **Chirurgien** | `dr_alain_chir` | `HospitalPass123!` | Pôle Chirurgie & Bloc Opératoire, Checklists OMS, Comptes-rendus opératoires (CRO), Urologie, suivi des statuts patients et validation des remplacements. |
| **Médecin Praticien** | `dr_marc_ped` | `HospitalPass123!` | Consultations, DPI complet, Pédiatrie, Maternité, Bilans urodynamiques, séjours hospitaliers et suivi des statuts patients. |
| **Sage-Femme** | `sf_elodie_mat` | `HospitalPass123!` | Suivi des grossesses, Salle de naissance (Registre d'accouchements & score APGAR), biométrie des nouveau-nés et statuts patientes. |
| **Infirmier(e) D.E.** | `inf_paul_chir` | `HospitalPass123!` | Soins infirmiers, mise à jour des statuts (`Service`, `Bloc`, `Réveil`), libération des lits après désinfection (`Nettoyage` → `Disponible`), vaccinations et checklists OMS. |
| **Secrétaire Médicale** | `sec_nadia` | `HospitalPass123!` | Accueil, création des dossiers patients, planification des rendez-vous (avec anti-collision d'agenda) et admissions. |

---

## 2. Cockpit de Supervision Hospitalière & Gestion des Pôles Cliniques (`/`)

Accessible dès la connexion sur `http://127.0.0.1:8000/` :

1. **Barre de Recherche Rapide (`Ctrl + K`)** :
   - Située en haut à droite, elle filtre instantanément les lits, chambres, patients (Nom ou IPP) et pôles cliniques affichés à l'écran.
2. **Mode Jour / Mode « Garde de Nuit » (`🌙 Mode Nuit`)** :
   - Permet de basculer l'interface en thème sombre `Slate-900` pour réduire la fatigue visuelle lors des gardes de nuit.
3. **Bandeau d'Alertes & Cartes KPI (Jauge en Anneau SVG)** :
   - Affiche en temps réel le taux d'occupation global, le nombre de lits disponibles, occupés et en nettoyage, ainsi que les demandes de remplacement de garde à arbitrer.
4. **Supervision par Pôle Clinique & Actions 1-Clic sur les Lits** :
   - Chaque pôle affiche une **barre segmentée tricolore** (`Occupés | Nettoyage | Disponibles`) et l'effectif de garde du jour.
   - Sur un lit **Occupé (`🔴`)** : cliquez sur la tuile pour ouvrir le **Tiroir Latéral de Détail (*Slide-Over Drawer*)** (identité, IPP, allergies vitales, médecin référent, bouton **`📄 Consentement PDF`** et lien de transfert).
   - Sur un lit **En Nettoyage (`🧹`)** : cliquez sur **`✓ Marquer Disponible`** pour valider la désinfection et remettre immédiatement le lit en service.
   - Sur un lit **Disponible (`🟢`)** : cliquez sur **`+ Affecter Patient`** pour créer une hospitalisation sur ce lit.
5. **Vue Kanban du Flux Patients & Arbitrage des Gardes** :
   - Utilisez les onglets du cockpit pour basculer entre la **Supervision des Lits**, le **Kanban Parcours Patients** (`Admission` → `Service` → `Bloc` → `Réveil` → `Sortie`) et le **Planning Hebdomadaire des Gardes** (avec validation en 1 clic des remplacements en attente).

---

## 3. Suivi & Gestion Dynamique des Statuts des Patients (`/core/patients/`)

Accessible via le bouton **`Suivi Patients`** (`http://127.0.0.1:8000/core/patients/`) :

- **Filtrage instantané par Statut** : Cliquez sur les pastilles colorées (`Admission`, `Service`, `Bloc`, `Réveil`, `Reporté`, `Sortie`, `Annulé`) ou utilisez le menu déroulant combiné à la recherche texte (Nom, Prénom, IPP, NIR).
- **Mise à jour en temps réel** : Changez le statut d'un patient directement sur sa ligne avec une note optionnelle ; chaque changement est horodaté et signé dans `PatientStatusHistory`.
- **Historique HDS (`🕒 Historique`)** : Consultez dans une fenêtre modale la chronologie complète de tous les changements de statut du patient.
- **Paramétrage des Statuts (`⚙ Paramétrer Statuts`)** : Les administrateurs peuvent ajouter de nouveaux statuts personnalisés (ex: `Imagerie / Scanner`), choisir leur couleur et les activer/désactiver.

---

## 4. Génération Automatique du PDF « Consentement aux Soins et Décharge »

Pour chaque patient ou admission, un document PDF officiel **A4 (marges 20 mm, en-tête Bleu Marine avec le logo officiel de la Clinique Sidi Yahia 2, identification complète, clauses de consentement et décharge, double bloc de signature côte à côte et numérotation `Page X sur Y`)** peut être généré :

- **Depuis l'interface web** :
  - Bouton **`📄 Consentement PDF`** sur chaque ligne de `/core/patients/`
  - Bouton **`📄 PDF`** sur chaque tuile de lit occupé ou dans le tiroir latéral du Cockpit (`/`)
  - Bouton **`📄 Consentement PDF`** dans le portail métier (`/admin/core/patient/` et `/admin/core/hospitalization/`)
- **Par URL directe** :
  - Par admission : `/core/admissions/<id>/consent-pdf/` (ajouter `?download=1` pour forcer le téléchargement)
  - Par patient : `/core/patients/<id>/consent-pdf/`
- **Depuis le code Python** :
  ```python
  from apps.core.pdf_consent_service import generateAdmissionPDF
  pdf_bytes = generateAdmissionPDF(hospitalization_or_dict, output_path="Consentement.pdf")
  ```

