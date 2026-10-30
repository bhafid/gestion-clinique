# Spécification UX/UI & Product Design : Modernisation de la « Supervision Hospitalière & Gestion des Pôles Cliniques »
## Clinique Sidi Yahia 2 — Système d'Information Hospitalier (SIH)

**Cibles principales :** Directeur Médical / d'Hôpital, Chefs de Pôles Cliniques (Chirurgie, Maternité, Pédiatrie, Urologie, Urgences), Cadres de Santé et Gestionnaires des Admissions.  
**Objectif produit :** Passer d'un tableau de bord passif (consultation de tableaux) à un **Cockpit Décisionnel Temps Réel (Command Center)** permettant de détecter une tension hospitalière en **moins de 3 secondes** et d'agir en **2 clics maximum**.

---

## 1. ARCHITECTURE DE L'INFORMATION & NAVIGATION

### 1.1 Structure du Tableau de Bord Principal : La Règle des « 3 Niveaux de Lecture (3-Second Rule) »
Un directeur ou chef de pôle qui ouvre son écran à 07h30 ne doit pas chercher l'information dans de longs tableaux. L'écran est structuré en **3 strates visuelles hiérarchisées** de haut en bas :

```
+---------------------------------------------------------------------------------------------------+
| BARRE SUPÉRIEURE : Logo Clinique | Recherche Globale (Ctrl+K) | Mode Clair/Nuit | Profil & Rôle   |
+---------------------------------------------------------------------------------------------------+
| NIVEAU 1 — BANDEAU D'ALERTES CRITIQUES & TENSION HOSPITALIÈRE (Hauteur fixe : 56px)               |
| [🔴 URGENCES : 92% Saturation (2 patients en attente de lit)] [🟠 CHIR : 3 lits en nettoyage >2h] |
+---------------------------------------------------------------------------------------------------+
| NAVIGATION PAR ONGLETS MÉTIERS (Pills Navigation) :                                               |
| [ 1. Vue Cockpit (Synthèse) ] [ 2. Gestion Visuelle des Lits ] [ 3. Flux & Kanban Patients ]      |
| [ 4. Effectifs & Gardes ]     [ 5. Pôles Cliniques & KPI ]                                        |
+---------------------------------------------------------------------------------------------------+
| NIVEAU 2 — JAUGES D'ÉTAT EN TEMPS RÉEL (4 Cartes KPI Actionnables avec Micro-Graphiques)          |
| +-----------------------+ +-----------------------+ +-----------------------+ +-----------------+ |
| | Taux d'Occupation     | | Flux Patients du Jour | | Couverture Soignante  | | Bloc & Actes    | |
| | 78% (Anneau + Jauge)  | | 14 Admis / 6 Sorties  | | 100% Gardes pourvues  | | 4 en cours      | |
| +-----------------------+ +-----------------------+ +-----------------------+ +-----------------+ |
+---------------------------------------------------------------------------------------------------+
| NIVEAU 3 — ZONE DE TRAVAIL OPÉRATIONNELLE (Grille 2 Colonnes : 8 cols / 4 cols)                   |
| +-----------------------------------------------------------------+ +---------------------------+ |
| | CARTOGRAPHIE DES PÔLES CLINIQUES (Cartes interactives par pôle) | | ACTIONS RAPIDES &         | |
| | - Chirurgie (CHIR) : Plan des chambres cliquable (Vert/Rouge)   | | TRANSFERTS EN ATTENTE     | |
| | - Maternité (MAT)  : Lits + Salles de naissance                 | | - Valider remplacement    | |
| | - Urgences (URG)   : Patients en attente d'attribution de lit   | | - Attribuer lit urgent    | |
| +-----------------------------------------------------------------+ +---------------------------+ |
+---------------------------------------------------------------------------------------------------+
```

### 1.2 Organisation Logique des 5 Sous-Sections (Navigation Unifiée sans Rechargement)
Au lieu de disperser les utilisateurs vers les écrans techniques de Django Admin, la section **Supervision Hospitalière** regroupe **5 vues métiers accessibles par onglets rapides** :

1. **Vue Cockpit (Synthèse Temps Réel)** :
   - Vue globale multi-pôles, alertes de saturation, lits immédiatement disponibles par service et demandes d'arbitrage (remplacements de garde en attente, transferts urgents).
2. **Gestion Visuelle des Lits (Bed Map / Plan d'Étage)** :
   - Représentation sous forme de **grille de chambres et de lits** par bâtiment/étage (`Bâtiment A - Étage 2 : Ch. 101 [Lit 1] [Lit 2]`).
3. **Flux & Parcours Patients (Vue Kanban + Liste)** :
   - Bascule instantanée entre le **Tableau Liste** et un **Kanban par Statut** (`Admission` → `Service` → `Bloc` → `Réveil` → `Sortie`).
4. **Effectifs, Gardes & Rééquilibrage** :
   - Matrice hebdomadaire des gardes (`Jour`, `Nuit`, `Garde 24h`, `Astreinte`) avec indicateur de **ratio Soignants / Patients occupés** par pôle.
5. **Indicateurs de Performance (KPI Direction)** :
   - Durée Moyenne de Séjour (DMS), délai moyen de rotation d'un lit (`Nettoyage` → `Disponible`), taux d'occupation par pôle sur 7/30 jours.

---

## 2. ERGONOMIE & INTUITIVITÉ (UX) : RÉDUIRE LA CHARGE MENTALE

### 2.1 Cinq Fonctionnalités à Fort Impact Opérationnel

1. **Vue Kanban & Glisser-Déposer (Drag & Drop) pour les Mouvements Patients et Lits** :
   - **Parcours Patient** : Faire glisser la carte d'un patient de la colonne `Bloc` vers `Réveil` met à jour son statut en temps réel et crée automatiquement le log d'audit HDS.
   - **Attribution / Transfert de Lit** : Faire glisser un patient depuis la liste « *En attente de lit (Urgences)* » directement sur une tuile de lit verte (`Ch. 102 - Lit 1`) ouvre une mini-fenêtre de confirmation pré-remplie (avec vérification automatique des allergies vitales et du sexe dans les chambres doubles).

2. **Barre de Commande Rapide Omniprésente (`Ctrl + K` / Recherche Intelligente)** :
   - Accessible depuis n'importe quel écran : en tapant `Dubois`, `Chambre 101`, ou `Consentement`, l'utilisateur accède en 1 seconde à la fiche patient, au statut du lit ou au téléchargement du PDF de consentement sans naviguer dans les menus.

3. **Filtres Intelligents « 1-Clic » Orientés Décision (Smart Chips)** :
   - Au lieu de formulaires de recherche complexes, proposer des pastilles d'action immédiate :
     - `🚨 Pôles en tension (>85%)`
     - `🧹 Lits en nettoyage à libérer`
     - `⏳ Sorties prévues aujourd'hui (lits bientôt libres)`
     - `🔄 Remplacements de garde à valider`

4. **Alertes Prédictives & Aide à la Décision (Logique Métier Intelligente)** :
   - **Anticipation des sorties (Sorties J0)** : Le système croise `expected_discharge_date = Aujourd'hui` avec les admissions programmées pour afficher : *« Pôle Chirurgie : 1 lit libre actuellement, mais +3 sorties prévues avant 14h00 (Capacité prévisionnelle : 4 lits) »*.
   - **Alerte de Goulot d'Étranglement (Bottleneck)** : Si un lit reste au statut `NETTOYAGE` depuis plus de 90 minutes alors que des patients attendent en `ADMISSION`, le badge du lit clignote en ambre avec un bouton rapide **`✓ Marquer Disponible (Désinfecté)`**.

5. **Tiroir Latéral de Détail (Slide-Over Drawer) au lieu de Changements de Page** :
   - Cliquer sur un lit occupé, un patient ou une garde ouvre un **panneau latéral à droite (Drawer)** sans quitter le tableau de bord : on y consulte le statut, le médecin référent, les allergies vitales, le bouton **`📄 Consentement PDF`** et le changement de statut en 1 clic.

### 2.2 Simplifier la Communication Inter-Pôles et les Transferts de Patients
- **Protocole de Transfert Visuel en 2 étapes (« Demande → Acceptation »)** :
  1. Le service émetteur (ex: *Urgences* ou *Bloc/Réveil*) clique sur **`⇄ Transférer`** sur la carte du patient et choisit le pôle cible (ex: *Chirurgie - Ch. 103 Lit 1*).
  2. Le cadre du pôle receveur voit apparaître une notification en haut de son cockpit avec les **3 informations critiques de sécurité** : Identité/Âge, Motif générique, et **Allergies vitales en rouge** (`⚠ Allergie : Pénicilline`). Un clic sur **`Accepter & Installer`** libère automatiquement l'ancien lit (qui passe en `NETTOYAGE`) et occupe le nouveau.

---

## 3. DESIGN VISUEL & MODERNISATION (UI)

### 3.1 Palette Chromatique Médicale Anti-Fatigue & Sémantique Stricte
En milieu hospitalier (écrans consultés 24h/24, sous éclairage néon le jour et en poste de garde tamisé la nuit), le design doit bannir les couleurs saturées agressives au profit d'une **hiérarchie sémantique stricte** :

- **Fond d'interface (Mode Clair — Jour)** : Gris ardoise ultra-doux (`#F8FAFC` / `Slate-50`) plutôt que du blanc pur éblouissant, avec des cartes blanches (`#FFFFFF`) bordées de `#E2E8F0`.
- **Mode Sombre « Garde de Nuit » (Dark Mode Automatique ou Manuel)** :
  - Fond `#0F172A` (`Slate-900`) et cartes `#1E293B` (`Slate-800`) pour les équipes de nuit (18h00 – 08h00), réduisant la fatigue oculaire de 60 %.
- **Couleurs Sémantiques Normalisées (Uniquement pour l'état clinique/capacitaire)** :
  - **Émeraude (`#10B981`)** : Lit Disponible / Sortie validée / Effectif complet.
  - **Bleu Médical (`#0284C7`)** : En cours normal / Admission / Consultation.
  - **Ambre (`#F59E0B`)** : Attention requise / Lit en Nettoyage / Patient en Salle de Réveil (SSPI) / Remplacement en attente.
  - **Rouge Corail (`#E11D48`)** : Critique / Saturation (>90%) / Patient au Bloc / Allergie vitale.

### 3.2 Typographie & Lisibilité des Données Chiffrées
- **Police principale** : `Plus Jakarta Sans` ou `Inter` (excellente lisibilité des petits corps de texte à l'écran).
- **Chiffres tabulaires (`font-variant-numeric: tabular-nums`)** : Indispensable pour aligner verticalement les heures de garde (`08:00 - 18:00`), les numéros IPP (`IPP-2026-000001`) et les pourcentages d'occupation.

### 3.3 Composants Visuels Modernes pour l'Occupation des Lits et la Charge d'un Pôle
Au lieu d'un simple chiffre `75%`, combiner **3 représentations complémentaires** :
1. **Jauge en Anneau (Donut Chart) + Barre Segmentée Multi-États** pour chaque pôle clinique :
   - Un seul segment horizontal montre instantanément la proportion :
     `[ ████████ Occupés (60%) | ███ Nettoyage (15%) | █████ Disponibles (25%) ]`
2. **Grille de Micro-Tuiles « Plan des Chambres » (Bed Matrix)** :
   - Chaque chambre est un bloc compact affichant ses lits côte à côte sous forme de pilules interactives :
     - `[🛏️ 101-1 : DUBOIS M. (Réveil)]` (Rouge/Ambre)
     - `[🛏️ 101-2 : 🧹 En nettoyage → Libérer]` (Orange cliquable)
     - `[🛏️ 102-1 : ✓ Disponible → Admettre]` (Vert cliquable)
3. **Indicateur de Pression par Pôle (Ratio Patients / Soignants de garde)** :
   - Badge visuel sur chaque pôle : `⚖ Charge : Normale (2 soignants de garde / 4 lits occupés)` ou `⚠ Sous-effectif détecté`.

---

## 4. CAS D'USAGE CONCRET : PARCOURS DU CHEF DE PÔLE À 08H00 (SURCHARGE AUX URGENCES)

**Contexte :** Il est **08h00**. Le **Dr Alain Rousseau** (Chef de Pôle / Directeur Médical) ouvre son tableau de bord. Une surcharge survient au **Service des Urgences (URG)** tandis que le **Pôle Chirurgie (CHIR)** a des lits bloqués en nettoyage et une demande de remplacement de garde.

### Étape 1 — Détection en 3 secondes (Bandeau d'Alerte & Cartes de Tension)
- Dès la connexion, le **Bandeau de Tension** en haut de l'écran affiche :
  > 🔴 **Alerte Capacitaire — Urgences (URG) : Saturation à 90%** • 2 patients en statut `Admission` attendent un lit d'aval • 1 demande de rééquilibrage d'effectif.
- Sur la carte du pôle **Chirurgie**, la barre segmentée montre : `2 Occupés | 2 En nettoyage | 2 Disponibles`.

### Étape 2 — Libération Rapide des Lits d'Aval (1 clic)
- Le chef de pôle clique sur le filtre rapide **`🧹 Lits en nettoyage (2)`**.
- Il voit que le `Lit 101-2 (Chirurgie)` est nettoyé après la sortie de M. Bernard Christian.
- Il clique directement sur le bouton d'action rapide de la tuile **`✓ Passer en Disponible`** → La capacité disponible du pôle Chirurgie monte instantanément de 2 à 3 lits sans quitter la page.

### Étape 3 — Rééquilibrage des Effectifs sur la Matrice des Gardes (2 clics)
- Dans le panneau **« Effectifs & Gardes du Jour »**, un indicateur orange signale que les Urgences ont un pic d'activité ce matin, alors qu'une permutation/renfort est en attente de validation.
- Le chef de pôle clique sur la carte de garde marquée **`⏳ Remplacement / Renfort à valider`** :
  - Un tiroir latéral s'ouvre, vérifie automatiquement les règles de sécurité (absence de chevauchement d'horaires et appartenance au département autorisé) et affiche un bouton vert **`✓ Valider l'affectation immédiatement`**.
- Dès validation, la matrice hebdomadaire se met à jour en temps réel et notifie l'équipe.

### Étape 4 — Transfert fluide des patients des Urgences vers les lits libérés
- Le Gestionnaire des Admissions (`adm_karim`) ou le chef de pôle clique sur **`+ Affecter un lit`** pour le patient en attente aux Urgences, sélectionne le lit `CHIR - Ch. 101 (Lit 2)` qui vient d'être libéré, vérifie les allergies vitales affichées en lecture seule, et génère en 1 clic le **`📄 Consentement PDF`**.
- **Temps total de résolution : moins de 90 secondes**, avec 100 % des actions tracées dans `SecurityAuditLog`.

