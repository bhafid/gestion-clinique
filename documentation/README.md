# 📁 Dossier de Documentation, Schémas & Guides d'Utilisation — Clinique Sidi Yahia 2 (SIH)

Ce dossier regroupe l'ensemble des **guides d'utilisation**, **schémas de base de données (SQL & ERD graphique)**, **spécifications fonctionnelles/techniques** et **procédures de déploiement** du Système d'Information Hospitalier (SIH).

---

## 1. 📘 Guides d'Utilisation & Manuels Opérationnels

| Fichier | Description |
| :--- | :--- |
| [**`GUIDE_UTILISATION_SIH.md`**](./GUIDE_UTILISATION_SIH.md) | **Guide complet d'utilisation en français** : Connexion, les 7 rôles RBAC et leurs identifiants de test, Cockpit de Supervision, Suivi & Statuts des Patients, Édition du PDF de Consentement, Gestion des Lits et des Gardes. |
| [**`USER_MANUAL.md`**](./USER_MANUAL.md) | Manuel utilisateur général des modules cliniques (Chirurgie, Gynécologie-Maternité, Pédiatrie, Urologie). |
| [**`EXEMPLE_CONSENTEMENT_ADMISSION.pdf`**](./EXEMPLE_CONSENTEMENT_ADMISSION.pdf) | Exemple réel généré du **Formulaire de Consentement aux Soins et Décharge** (PDF A4 avec logo officiel de la Clinique Sidi Yahia 2). |

---

## 2. 🗄️ Schémas & Architecture de la Base de Données

| Fichier | Description |
| :--- | :--- |
| [**`SCHEMA_BASE_DE_DONNEES.md`**](./SCHEMA_BASE_DE_DONNEES.md) | Structure détaillée de toutes les tables de la base de données (`core`, `chirurgie`, `gynecologie_maternite`, `pediatrie`, `urologie`), clés primaires/étrangères, contraintes d'intégrité et règles métiers. |
| [**`SCHEMA_ERD_BASE_DE_DONNEES.svg`**](./SCHEMA_ERD_BASE_DE_DONNEES.svg) | **Diagramme Entité-Association (ERD) graphique vectoriel** haute résolution illustrant les cardinalités et relations entre l'ensemble des entités du SIH. |

---

## 3. 📋 Spécifications Fonctionnelles, Sécurité (HDS/RGPD) & UX/UI

| Fichier | Description |
| :--- | :--- |
| [**`SPECIFICATION_STATUTS_PATIENTS.md`**](./SPECIFICATION_STATUTS_PATIENTS.md) | Spécification complète de la **Gestion Dynamique des Statuts des Patients** après admission (`Admission`, `Service`, `Bloc`, `Réveil`, `Sortie`, `Reporté`, `Annulé`) et traçabilité de l'historique (`PatientStatusHistory`). |
| [**`SPECIFICATION_ROLE_GESTIONNAIRE_ADMISSIONS.md`**](./SPECIFICATION_ROLE_GESTIONNAIRE_ADMISSIONS.md) | Spécification de sécurité du rôle **« Gestionnaire des Admissions et Hospitalisations »** (`GESTIONNAIRE_ADMISSION`) : matrice CRUD, cloisonnement du secret médical, journal d'audit immuable (`SecurityAuditLog`) et expiration de session après 5 min d'inactivité. |
| [**`SPECIFICATION_UX_UI_SUPERVISION_POLES.md`**](./SPECIFICATION_UX_UI_SUPERVISION_POLES.md) | Spécification UX/UI du **Cockpit de Supervision Hospitalière & Gestion des Pôles Cliniques** (jauges en anneau SVG, barres segmentées par pôle, Kanban parcours patient, tiroir latéral et Mode Garde de Nuit). |

---

## 4. 🚀 Installation, Administration & Déploiement Serveur (Ubuntu / VPS)

| Fichier | Description |
| :--- | :--- |
| [**`DEPLOIEMENT_CODE_SOURCE_UBUNTU.md`**](./DEPLOIEMENT_CODE_SOURCE_UBUNTU.md) | Guide pas-à-pas de déploiement en production sur **Ubuntu Server 24.04 LTS** (PostgreSQL, `venv`, Gunicorn `clinic.service`, Nginx et pare-feu `iptables` / Oracle Cloud). |
| [**`INSTALLATION_AND_ADMINISTRATION.md`**](./INSTALLATION_AND_ADMINISTRATION.md) | Guide d'installation locale, configuration `.env`, migrations et commandes d'administration Django. |
| [**`UBUNTU_DEPLOYMENT.md`**](./UBUNTU_DEPLOYMENT.md) | Notes techniques complémentaires pour l'hébergement Linux. |

