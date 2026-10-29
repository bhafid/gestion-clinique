# Manuel d’utilisation – Système de Gestion Hospitalière

## Table des matières
1. [Vue d’ensemble](#vue-densemble)
2. [Connexion & Sécurité](#connexion--sécurité)
3. [Navigation principale](#navigation-principale)
4. [Gestion des patients](#gestion-des-patients)
5. [Modules spécialisés](#modules-spécialisés)
   - 5.1 [Chirurgie](#chirurgie)
   - 5.2 [Pédiatrie](#pédiatrie)
   - 5.3 [Urologie & Néphrologie](#urologie--néphrologie)
   - 5.4 [Gynécologie & Maternité](#gynécologie--maternité)
6. [Recherche & filtres](#recherche--filtres)
7. [Création / Modification / Suppression d’enregistrements (CRUD)](#crud)
8. [Gestion des rôles (RBAC)](#gestion-des-rôles-rbac)
9. [Déconnexion et session](#déconnexion-et-session)
10. [FAQ & résolution de problèmes](#faq--résolution-de-problèmes)

---

## Vue d’ensemble
Le **Système de Gestion Hospitalière** regroupe plusieurs pôles de soin :
- **Chirurgie**
- **Pédiatrie**
- **Urologie & Néphrologie**
- **Gynécologie & Maternité**

Chaque pôle possède ses propres écrans : listes d’entrées, formulaires de saisie, vues détaillées et actions de suppression. L’interface est entièrement responsive grâce à **Bootstrap 5**.

## Connexion & Sécurité
1. Accédez à `http://<host>/login/` (ou `http://127.0.0.1:8000/login/` en dev).  
2. Saisissez votre **e‑mail** et **mot de passe**.  
3. Après authentification, le système applique le **contrôle d’accès basé sur les rôles (RBAC)** : chaque vue vérifie que votre rôle (`ADMIN`, `MEDECIN`, `CHIRURGIEN`, `INFIRMIER`, `SAGE_FEMME`, `SECRETAIRE`) autorise l’opération.

> **Note :** Si votre compte n’a pas les droits nécessaires, vous recevrez une page *403 Forbidden*.

## Navigation principale
Le menu supérieur (ou latéral selon votre thème) propose :
- **Dashboard** – synthèse du nombre d’enregistrements par module.  
- **Patients** – recherche globale, création, édition.  
- **Chirurgie**, **Pédiatrie**, **Urologie**, **Gynécologie & Maternité** – accès aux écrans listés ci‑dessous.  
- **Administration** – uniquement visible pour les administrateurs (`ADMIN`) : gestion des utilisateurs, des rôles, des paramètres du site.

## Gestion des patients
1. **Liste** – `/patients/` : tableau avec recherche par nom/IPP, pagination (20 éléments/page).  
2. **Création** – bouton **« Créer »** → formulaire avec champs : nom, prénom, date de naissance, sexe, adresse, numéro de sécurité sociale, etc.  
3. **Détail** – cliquez sur le numéro d’IPP pour afficher toutes les informations et les raccourcis vers les modules (ex. : historique chirurgical).  
4. **Modification / Suppression** – accessible depuis la vue détail (icônes crayon / corbeille) si votre rôle le permet.

## Modules spécialisés

### Chirurgie
- **Interventions** – `/chirurgie/intervention/` (liste), création via **« Créer »**.  
- **Check‑list OMS** – lien depuis chaque intervention, permet de cocher les points de sécurité.  
- **Compte‑rendu opératoire** – détaillé, champs texte libre, pièces jointes éventuelles.

### Pédiatrie
- **Anthropométrie** – `/pediatrie/anthropometry/` : saisie du poids, taille, périmètre crânien, calcul automatique de l’IMC.  
- **Vaccinations** – `/pediatrie/vaccination/` : création/modification des vaccins, statut affiché avec badge coloré (à faire, effectué, en retard, contre‑indiqué).  
- **Filtres** – barre de recherche (`q`) sur le nom du patient.

### Urologie & Néphrologie
- **Historique urologique** – `/urologie/history/` : antécédents, lithiases, HBP, hématurie, etc.  
- **Bilan urodynamique** – `/urologie/assessment/` : saisie Qmax, volume résiduel, validation Qmax < 15 mL/s affichée en rouge.  
- **Interventions spécialisées** – `/urologie/intervention/` : rapports d’actes (cystoscopie, lithotripsie, résection).  
- **Badges** – Qmax, statut du bilan affichés avec couleur.

### Gynécologie & Maternité
- **Historique gynéco‑obstétrique** – `/gynecologie_maternite/history/`.  
- **Consultations de routine** – `/gynecologie_maternite/consultation/`.  
- **Suivi de grossesse** – `/gynecologie_maternite/pregnancy/` : calcul automatique de la date prévue d’accouchement, affichage du statut (en cours, accouchée, interrompue) avec badge.  
- **Registre d’accouchement** – `/gynecologie_maternite/delivery/` : détails du mode d’accouchement, scores APGAR, complications.

## Recherche & filtres
Toutes les pages listées comprennent :
- **Barre de recherche** (`?q=texte`) qui parcourt les champs les plus pertinents (nom du patient, type d’intervention, vaccin, etc.).  
- **Filtres** dans la barre latérale (date, statut, praticien).  
- **Pagination** (20 lignes / page) avec navigation en bas du tableau.

## Création / Modification / Suppression d’enregistrements (CRUD)
1. **Créer** – bouton **« Créer »** → formulaire pré‑rempli avec les listes déroulantes (`patient`, `praticien`).  
2. **Modifier** – depuis la vue détail ou la liste (icône crayon). Le formulaire charge les données existantes.  
3. **Supprimer** – icône corbeille → page de confirmation avant suppression définitive.  
4. **Validation serveur** – les modèles appliquent des règles métier (ex. : Qmax ≥ 15 mL/s, contrôle de la cohérence des dates). Les messages d’erreur s’affichent sous chaque champ.

## Gestion des rôles (RBAC)
| Rôle          | Accès autorisé                                                            |
|---------------|---------------------------------------------------------------------------|
| **ADMIN**     | Tout le système : création d’utilisateurs, modification des paramètres. |
| **MEDECIN**   | Lecture/écriture dans tous les modules (sauf configuration).            |
| **CHIRURGIEN**| Chirurgie, Urologie, Gynécologie (actes).                                 |
| **INFIRMIER**| Pédiatrie (anthropométrie, vaccinations), Urologie (lecture).           |
| **SAGE_FEMME**| Gynécologie & Maternité (consultations, suivi grossesse).                |
| **SECRETAIRE**| Accès lecture aux dossiers patients, création de rendez‑vous.             |

Le système utilise le **mix‑in `RoleRequiredMixin`** dans chaque vue pour appliquer ces règles.

## Déconnexion et session
- Cliquez sur **« Déconnexion »** dans le menu utilisateur.  
- La session est invalidée et vous êtes redirigé vers la page de login.  
- En mode production, la session expire automatiquement après **30 minutes d’inactivité** (configurable dans `settings.py`).

## FAQ & résolution de problèmes
**Q : Je ne vois pas le bouton « Créer » dans un module.**
> R : Vérifiez que votre rôle possède les permissions d’écriture pour ce module. Un administrateur peut ajuster le champ `role` de votre compte.

**Q : Les dates affichées sont incorrectes.**
> R : Assurez‑vous que le serveur possède le bon fuseau horaire (`TIME_ZONE` dans `settings.py`). Vous pouvez également définir la variable d’environnement `TZ`.

**Q : Une erreur 500 apparaît lors de la sauvegarde d’un bilan urodynamique.**
> R : Consultez les logs dans le répertoire `logs/` ou la console du serveur. Le problème le plus fréquent est une valeur `Qmax` inférieure à 15 mL/s sans justification ; corrigez la donnée ou laissez le champ vide.

**Q : Le badge de statut vaccination ne change pas.**
> R : Le statut est calculé dans le modèle `VaccinationRecord.clean()`. Après modification d’une date ou d’un lot, sauvegardez le formulaire ; le badge se rafraîchit automatiquement.

---

### Besoin d’ajustements supplémentaires ?
N’hésitez pas à demander : génération d’une API REST, ajout de champs spécifiques, ou adaptation à un autre thème visuel.

---

*Fin du manuel d’utilisation.*

