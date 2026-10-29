# SIH - Système d'Information Hospitalier (Hospital Management System)
### Architecture Modulaire, Sécurisée HDS / RGPD en Python & Django

Application web hospitalière robuste développée selon les standards stricts de l'informatique médicale et de l'hébergement de données de santé (HDS / RGPD).

---

## 1. Structure du Projet & Sous-Applications

Le projet est découpé en applications indépendantes mais étroitement orchestrées :

```text
Clinic/
├── manage.py
├── hospital_system/               # Configuration du projet Django
│   ├── settings.py                # PostgreSQL, Sécurité HDS, Logging, RBAC
│   ├── urls.py                    # Routage centralisé & Admin personnalisé
│   ├── wsgi.py / asgi.py
├── apps/
│   ├── core/                      # Socle transversal hospitalier
│   │   ├── models.py              # Personnel (RBAC), DPI (Patient), RDV, Lits, Gardes
│   │   ├── forms.py               # Formulaires validés
│   │   ├── views.py               # WeeklyDashboardView (Temps réel)
│   │   ├── admin.py               # Administration avec filtres et traçabilité
│   │   └── management/commands/   # seed_hospital_data.py (Peuplement automatique)
│   ├── chirurgie/                 # Pôle Bloc Opératoire
│   │   └── models.py              # Salles, Interventions, Checklist OMS tripartite, CRO
│   ├── gynecologie_maternite/     # Pôle Maternité & Obstétrique
│   │   └── models.py              # Consultations, Suivi Grossesse (DPA), Registre Accouchements
│   ├── pediatrie/                 # Pôle Pédiatrie & Néonatalogie
│   │   └── models.py              # Anthropométrie (IMC), Calendrier Vaccinal (lots obligatoires)
│   └── urologie/                  # Pôle Urologie & Néphrologie
│       └── models.py              # Antécédents, Bilan Urodynamique (BUD), Actes spécialisés (JJ)
└── templates/
    └── dashboard/
        └── weekly_dashboard.html  # Dashboard moderne Tailwind CSS
```

---

## 2. Garanties Métier & Intégrité des Données

1. **RBAC & Personnel Médical** : Modèle `CustomUser` étendant `AbstractUser` avec rôles stricts (`ADMIN`, `MEDECIN`, `CHIRURGIEN`, `INFIRMIER`, `SAGE_FEMME`, `SECRETAIRE`) et affectation départementale obligatoire.
2. **Dossier Patient Unique (DPI)** :
   - Génération automatique d'un Identifiant Permanent du Patient (`IPP-YYYY-XXXXXX`).
   - Validation algorithmique de la clé modulo 97 du numéro de sécurité sociale français (NIR).
3. **Anti-collision d'agenda pour les Rendez-vous** : Le validateur `clean()` de `Appointment` détecte et bloque toute tentative de double réservation pour un praticien sur des créneaux horaires qui se chevauchent.
4. **Cycle de vie automatisé des lits** :
   - À l'admission : Le lit affecté passe automatiquement au statut `OCCUPÉ`.
   - À la date de sortie effective : Le séjour est clôturé et le lit bascule automatiquement au statut `NETTOYAGE` (désinfection requise avant d'être réutilisable).
5. **Gardes et permutations verrouillées** :
   - Interdiction formelle de chevauchement d'horaires pour un même soignant.
   - Verrouillage départemental : le remplaçant doit **obligatoirement** appartenir au même service hospitalier que le soignant titulaire.
6. **Checklist OMS au bloc opératoire** : Validation séquentielle en 3 étapes (*Sign-in*, *Time-out*, *Sign-out*) pour prévenir les erreurs chirurgicales.
7. **Traçabilité & Pharmacovigilance** : Numéro de lot obligatoire pour tout vaccin pédiatrique administré et traçabilité des implants chirurgicaux / sondes JJ.

---

## 3. Configuration de la Base de Données PostgreSQL

En production ou en hébergement certifié HDS, définissez les variables d'environnement suivantes :

```bash
export POSTGRES_DB="hospital_db"
export POSTGRES_USER="hospital_user"
export POSTGRES_PASSWORD="MotDePasseTresSecurise123!"
export POSTGRES_HOST="db-cluster.internal"
export POSTGRES_PORT="5432"
export POSTGRES_SSLMODE="require"
```

> **Note :** En local ou en l'absence de ces variables, Django bascule automatiquement sur SQLite sécurisé pour faciliter le développement et les tests.

---

## 4. Prise en Main & Commandes Utiles

### Exécution des migrations
```bash
python manage.py migrate
```

### Peuplement avec le jeu de données de test complet
```bash
python manage.py seed_hospital_data
```
*Identifiants du compte administrateur généré :*
- **Identifiant :** `admin`
- **Mot de passe :** `AdminPassword123!`

### Lancement de la suite de tests automatisés (15 tests)
```bash
python manage.py test
```

### Lancement du serveur de développement
```bash
python manage.py runserver
```

- **Tableau de Bord Hebdomadaire (Frontend Tailwind CSS) :** `http://127.0.0.1:8000/`
- **Portail d'Administration Hospitalier :** `http://127.0.0.1:8000/admin/`
