"""
Modèles de données du module de Facturation Hospitalière Algérienne :
- Conformité fiscale DGI Algérie (NIF, NIS, RC, AI, TVA 0% / 9% / 19%, Droit de Timbre Espèces vs CIB/Edahabia)
- Nomenclature Générale des Actes Professionnels (NGAP Algérie : C, CS, K, KC, Z, B, AMI, SF + Forfaits)
- Rétrocession d'honoraires entre l'établissement (Clinique) et les praticiens exécutants
- Liaison directe avec le stock Pharmacie (FEFO + facturation au PPA - Prix Public Algérien)
- Gestion du Tiers-Payant (CNAS, CASNOS, Caisses Mutuelles, Assurances & Conventions Entreprises) et Bordereaux
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.models import AuditableModel, Hospitalization, Patient
from apps.pharmacie.models import LotStock, MouvementStock, ProduitPharmaceutique


# -----------------------------------------------------------------------------
# Énumérations Réglementaires Algériennes
# -----------------------------------------------------------------------------
class TypeEtablissementSanteChoices(models.TextChoices):
    CLINIQUE_PRIVEE = "CLINIQUE_PRIVEE", "Clinique Médico-Chirurgicale Privée (EHS Privé)"
    ETABLISSEMENT_PUBLIC = "ETABLISSEMENT_PUBLIC", "Établissement Public Hospitalier (EPH / CHU)"


class LettreCleNGAPChoices(models.TextChoices):
    C = "C", "C — Consultation Médecin Généraliste"
    CS = "CS", "CS — Consultation Médecin Spécialiste / Professeur"
    CNPSY = "CNPSY", "CNPSY — Consultation Neuropsychiatrie"
    K = "K", "K — Acte de Chirurgie et de Spécialité"
    KC = "KC", "KC — Acte de Chirurgie Lourde / Complexe"
    Z = "Z", "Z — Acte de Radiologie / Imagerie Médicale"
    B = "B", "B — Acte d'Analyses Biologiques Médicales"
    AMI = "AMI", "AMI — Acte Médico-Infirmier"
    SF = "SF", "SF — Acte de Sage-Femme / Obstétrique"
    FORFAIT = "FORFAIT", "FORFAIT — Forfait Hospitalier / Chirurgie / Maternité"


class TypeActeFacturableChoices(models.TextChoices):
    ACTE_NGAP = "ACTE_NGAP", "Acte Médical / Chirurgical NGAP"
    FORFAIT_CHIRURGIE = "FORFAIT_CHIRURGIE", "Forfait Chirurgical / Bloc Opératoire"
    FORFAIT_MATERNITE = "FORFAIT_MATERNITE", "Forfait Accouchement & Maternité"
    SEJOUR_HOSPITALISATION = "SEJOUR_HOSPITALISATION", "Frais de Séjour & Lit d'Hospitalisation"
    HOTELLERIE_CONFORT = "HOTELLERIE_CONFORT", "Prestation Hôtelière Non Médicale / Chambre VIP (TVA 19%)"


class TauxTVAAlgerieChoices(models.TextChoices):
    EXONERE_0 = "0.00", "0 % — Exonéré (Actes médicaux & soins exonérés Art. 9 CTCA)"
    REDUIT_9 = "9.00", "9 % — Taux réduit (Médicaments & prestations médicales Art. 23 CTCA)"
    NORMAL_19 = "19.00", "19 % — Taux normal (Prestations hôtelières, confort & non médicales)"


class TypeOrganismePayeurChoices(models.TextChoices):
    CNAS = "CNAS", "CNAS (Caisse Nationale des Assurances Sociales des Travailleurs Salariés)"
    CASNOS = "CASNOS", "CASNOS (Caisse Nationale de Sécurité Sociale des Non-Salariés)"
    CAISSE_MILITAIRE = "CAISSE_MILITAIRE", "Caisse Militaire de Sécurité Sociale / MDN"
    MUTUELLE = "MUTUELLE", "Mutuelle SocialeComplémentaire (MGPTT, MGEN, CNMA...)"
    ASSURANCE_PRIVEE = "ASSURANCE_PRIVEE", "Compagnie d'Assurance (SAA, CAAR, Alliance, AXA...)"
    ENTREPRISE_CONVENTIONNEE = "ENTREPRISE_CONVENTIONNEE", "Entreprise Conventionnée (Sonatrach, Sonelgaz, Air Algérie...)"


class BaseCalculRemboursementChoices(models.TextChoices):
    SUR_TARIF_REFERENCE_CNAS = (
        "SUR_TARIF_REFERENCE_CNAS",
        "Sur le Tarif de Référence CNAS / NGAP / PPA (Ticket modérateur + dépassement à charge patient)",
    )
    SUR_FRAIS_REELS_CLINIQUE = (
        "SUR_FRAIS_REELS_CLINIQUE",
        "Sur les Frais Réels facturés par la Clinique (Convention Entreprise / Assurance Privée)",
    )


class TypePriseEnChargeFactureChoices(models.TextChoices):
    HOSPITALISATION_SEJOUR = "HOSPITALISATION_SEJOUR", "Séjour d'Hospitalisation Complète / Jour"
    AMBULATOIRE_CONSULTATION = "AMBULATOIRE_CONSULTATION", "Passage Ambulatoire / Consultation Externe"
    URGENCES = "URGENCES", "Passage aux Urgences Médico-Chirurgicales"


class StatutFactureChoices(models.TextChoices):
    BROUILLON = "BROUILLON", "Brouillon (En cours de saisie au fil de l'eau)"
    VALIDEE_EMISE = "VALIDEE_EMISE", "Validée & Émise (Numéro séquentiel définitif attribué)"
    PARTIELLEMENT_PAYEE = "PARTIELLEMENT_PAYEE", "Partiellement réglée"
    SOLDEE = "SOLDEE", "Soldée / Payée"
    ANNULEE_PAR_AVOIR = "ANNULEE_PAR_AVOIR", "Annulée par Facture d'Avoir"


class ModePaiementAlgerieChoices(models.TextChoices):
    ESPECES = "ESPECES", "Espèces en Dinars Algériens (Soumis au Droit de Timbre légal)"
    CARTE_CIB = "CARTE_CIB", "Carte Interbancaire CIB — SATIM (Exonéré de Droit de Timbre)"
    CARTE_EDAHABIA = "CARTE_EDAHABIA", "Carte Edahabia — Algérie Poste (Exonéré de Droit de Timbre)"
    CHEQUE_BANCAIRE = "CHEQUE_BANCAIRE", "Chèque Bancaire / CCP (Exonéré de Droit de Timbre)"
    VIREMENT_BANCAIRE = "VIREMENT_BANCAIRE", "Virement Bancaire / CCP (Exonéré de Droit de Timbre)"


class StatutBordereauChoices(models.TextChoices):
    EN_PREPARATION = "EN_PREPARATION", "En préparation (Lot ouvert)"
    ENVOYE_CAISSE = "ENVOYE_CAISSE", "Déposé / Télétransmis à la Caisse (CNAS/CASNOS)"
    REMBOURSE_CLOTURE = "REMBOURSE_CLOTURE", "Remboursé par virement & Clôturé"


# -----------------------------------------------------------------------------
# 1. Établissement Fiscal (Mentions Légales Obligatoires Algérie)
# -----------------------------------------------------------------------------
class EtablissementFiscal(AuditableModel):
    """
    Paramètres légaux et fiscaux de l'établissement de santé en Algérie
    (Décret exécutif n° 05-468 : NIF, NIS, RC, AI, adresse, séquence sans rupture).
    """

    raison_sociale = models.CharField(
        max_length=200,
        default="SARL CLINIQUE MÉDICO-CHIRURGICALE SIDI YAHIA 2",
        verbose_name="Raison sociale officielle",
    )
    type_etablissement = models.CharField(
        max_length=30,
        choices=TypeEtablissementSanteChoices.choices,
        default=TypeEtablissementSanteChoices.CLINIQUE_PRIVEE,
        verbose_name="Régime de l'établissement",
    )
    forme_juridique = models.CharField(
        max_length=50,
        default="SARL au capital social de 50 000 000,00 DA",
        verbose_name="Forme juridique & Capital social",
    )
    adresse_complete = models.CharField(
        max_length=255,
        default="Lotissement Sidi Yahia, Hydra / Bir Mourad Raïs, 16035 Alger, Algérie",
        verbose_name="Adresse fiscale complète",
    )
    wilaya = models.CharField(
        max_length=60,
        default="16 - Alger",
        verbose_name="Wilaya",
    )
    telephone = models.CharField(
        max_length=40,
        default="+213 (0) 21 60 88 00",
        verbose_name="Téléphone officiel",
    )
    # Identifiants fiscaux obligatoires en Algérie
    nif = models.CharField(
        max_length=25,
        default="002116099123456",
        verbose_name="N.I.F (Numéro d'Identification Fiscale - 15/20 chiffres)",
    )
    nis = models.CharField(
        max_length=25,
        default="099916100654321",
        verbose_name="N.I.S (Numéro d'Identification Statistique - 15 chiffres)",
    )
    rc = models.CharField(
        max_length=35,
        default="16/00-1048291B21",
        verbose_name="N° R.C (Registre du Commerce CNRC)",
    )
    article_imposition = models.CharField(
        max_length=25,
        default="16125849012",
        verbose_name="A.I (Article d'Imposition - 11 chiffres)",
    )
    rib_bancaire = models.CharField(
        max_length=50,
        default="BEA Alger Hydra : 002 00012 1203456789 44",
        verbose_name="RIB Bancaire / RIP CCP",
    )
    numero_convention_cnas = models.CharField(
        max_length=40,
        default="CONV-CNAS-DZ-16-2026-089",
        verbose_name="N° Agrément / Convention CNAS",
    )
    exercice_fiscal_courant = models.PositiveIntegerField(
        default=2026,
        verbose_name="Exercice fiscal actif",
    )
    dernier_numero_sequentiel = models.PositiveIntegerField(
        default=0,
        verbose_name="Dernier numéro séquentiel de facture validée",
    )

    class Meta:
        verbose_name = "Identité Fiscale de l'Établissement (NIF/NIS/RC/AI)"
        verbose_name_plural = "Identités Fiscales de l'Établissement"

    def __str__(self) -> str:
        return f"{self.raison_sociale} (NIF: {self.nif} | RC: {self.rc})"


# -----------------------------------------------------------------------------
# 2. Nomenclature Générale des Actes Professionnels (NGAP Algérie) & Forfaits
# -----------------------------------------------------------------------------
class ActeMedicalNGAP(AuditableModel):
    """
    Catalogue des actes médicaux et chirurgicaux selon la NGAP algérienne
    (lettres-clés C, CS, K, KC, Z, B, AMI, SF et coefficients) et des forfaits cliniques.
    """

    code_ngap = models.CharField(
        max_length=30,
        unique=True,
        db_index=True,
        verbose_name="Code NGAP / Code Forfait (ex: CS, K50, KC120, Z25, B40, AMI4)",
    )
    libelle = models.CharField(
        max_length=255,
        verbose_name="Désignation officielle de l'acte ou forfait",
    )
    type_acte = models.CharField(
        max_length=30,
        choices=TypeActeFacturableChoices.choices,
        default=TypeActeFacturableChoices.ACTE_NGAP,
        verbose_name="Catégorie d'acte",
    )
    lettre_cle = models.CharField(
        max_length=15,
        choices=LettreCleNGAPChoices.choices,
        default=LettreCleNGAPChoices.K,
        verbose_name="Lettre-clé NGAP",
    )
    coefficient = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("1.00"),
        validators=[MinValueValidator(Decimal("0.01"))],
        verbose_name="Coefficient NGAP",
    )
    valeur_lettre_cle_cnas_da = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("100.00"),
        verbose_name="Valeur unitaire officielle CNAS de la lettre-clé (DA)",
    )
    tarif_reference_cnas_da = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Tarif de référence remboursable CNAS (DA)",
    )
    tarif_clinique_ht_da = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Tarif pratiqué par la Clinique HT (DA)",
    )
    taux_tva = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("9.00"),
        verbose_name="Taux de TVA algérien (0%, 9%, 19%)",
    )
    taux_retrocession_praticien_defaut = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("70.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
        verbose_name="Quote-part honoraires Praticien (%) — Rétrocession",
    )
    est_remboursable_cnas = models.BooleanField(
        default=True,
        verbose_name="Acte remboursable par la CNAS / CASNOS",
    )

    class Meta:
        verbose_name = "Acte Médical NGAP / Forfait (Algérie)"
        verbose_name_plural = "Catalogue des Actes NGAP & Forfaits (Algérie)"
        ordering = ["code_ngap"]

    def __str__(self) -> str:
        return f"[{self.code_ngap}] {self.libelle} ({self.tarif_clinique_ht_da} DA HT)"

    def save(self, *args, **kwargs):
        if self.tarif_reference_cnas_da <= Decimal("0.00"):
            self.tarif_reference_cnas_da = (
                self.coefficient * self.valeur_lettre_cle_cnas_da
            ).quantize(Decimal("0.01"))
        super().save(*args, **kwargs)


# -----------------------------------------------------------------------------
# 3. Organismes de Tiers-Payant (CNAS, CASNOS, Mutuelles, Assurances, Entreprises)
# -----------------------------------------------------------------------------
class OrganismeTiersPayant(AuditableModel):
    """Caisse de sécurité sociale (CNAS, CASNOS), mutuelle, assurance ou entreprise conventionnée."""

    code_organisme = models.CharField(
        max_length=30,
        unique=True,
        verbose_name="Code Organisme (ex: CNAS-16, CASNOS-16, SONATRACH)",
    )
    nom = models.CharField(
        max_length=200,
        verbose_name="Nom complet de l'organisme ou caisse",
    )
    type_organisme = models.CharField(
        max_length=30,
        choices=TypeOrganismePayeurChoices.choices,
        default=TypeOrganismePayeurChoices.CNAS,
        verbose_name="Type d'organisme",
    )
    taux_couverture_defaut_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("80.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
        verbose_name="Taux de prise en charge standard (%)",
    )
    base_calcul = models.CharField(
        max_length=35,
        choices=BaseCalculRemboursementChoices.choices,
        default=BaseCalculRemboursementChoices.SUR_TARIF_REFERENCE_CNAS,
        verbose_name="Base de calcul du Tiers-Payant",
    )
    adresse_centre_paiement = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Centre payeur / Adresse d'envoi des bordereaux",
    )
    est_actif = models.BooleanField(default=True, verbose_name="Convention active")

    class Meta:
        verbose_name = "Organisme de Tiers-Payant (CNAS / CASNOS / Mutuelle)"
        verbose_name_plural = "Organismes de Tiers-Payant (CNAS / CASNOS / Mutuelles)"
        ordering = ["nom"]

    def __str__(self) -> str:
        return f"{self.nom} ({self.taux_couverture_defaut_pct}% - {self.get_type_organisme_display()})"


class ConventionPriseEnCharge(AuditableModel):
    """
    Dossier d'ouverture de droits Tiers-Payant d'un patient auprès d'une caisse
    (Carte Chifa CNAS, CASNOS, Mutuelle ou Prise en charge Entreprise).
    """

    patient = models.ForeignKey(
        Patient,
        on_delete=models.CASCADE,
        related_name="conventions_tiers_payant",
        verbose_name="Patient assuré / ayant-droit",
    )
    organisme = models.ForeignKey(
        OrganismeTiersPayant,
        on_delete=models.PROTECT,
        related_name="prises_en_charge",
        verbose_name="Organisme payeur (CNAS / CASNOS / Assurance)",
    )
    numero_immatriculation_assure = models.CharField(
        max_length=30,
        verbose_name="N° d'Immatriculation Sécurité Sociale / Carte Chifa (12 chiffres)",
    )
    numero_accord_pec = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="N° d'Accord de Prise en Charge (PEC)",
    )
    taux_prise_en_charge_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("80.00"),
        validators=[MinValueValidator(Decimal("0.00")), MaxValueValidator(Decimal("100.00"))],
        verbose_name="Taux de prise en charge accordé (%) — ex: 80% ou 100%",
    )
    plafond_couverture_da = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Plafond annuel/séjour de prise en charge (DA)",
    )
    est_active = models.BooleanField(default=True, verbose_name="Prise en charge valide")

    class Meta:
        verbose_name = "Convention / Prise en Charge Patient (Carte Chifa / PEC)"
        verbose_name_plural = "Conventions & Prises en Charge Patients"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return (
            f"{self.patient.full_name} — {self.organisme.nom} "
            f"(N° Assuré: {self.numero_immatriculation_assure} | {self.taux_prise_en_charge_pct}%)"
        )


# -----------------------------------------------------------------------------
# 4. Bordereau d'Envoi Tiers-Payant (Remboursement Caisses CNAS / CASNOS)
# -----------------------------------------------------------------------------
class BordereauTiersPayant(AuditableModel):
    """
    Bordereau récapitulatif d'envoi des factures Tiers-Payant aux caisses (CNAS, CASNOS,
    Mutuelles, Assurances) pour recouvrement de la part organisme.
    """

    numero_bordereau = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        verbose_name="N° de Bordereau d'Envoi",
    )
    organisme = models.ForeignKey(
        OrganismeTiersPayant,
        on_delete=models.PROTECT,
        related_name="bordereaux",
        verbose_name="Organisme destinataire",
    )
    periode_debut = models.DateField(verbose_name="Début de période")
    periode_fin = models.DateField(verbose_name="Fin de période")
    nombre_factures = models.PositiveIntegerField(
        default=0,
        verbose_name="Nombre de dossiers / factures joints",
    )
    montant_total_tiers_payant_da = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Montant total réclamé à la Caisse (DA)",
    )
    statut = models.CharField(
        max_length=25,
        choices=StatutBordereauChoices.choices,
        default=StatutBordereauChoices.EN_PREPARATION,
        verbose_name="Statut du bordereau",
    )
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="Généré par",
    )

    class Meta:
        verbose_name = "Bordereau d'Envoi Tiers-Payant (CNAS/CASNOS)"
        verbose_name_plural = "Bordereaux d'Envoi Tiers-Payant (CNAS/CASNOS)"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return (
            f"{self.numero_bordereau} — {self.organisme.nom} "
            f"({self.nombre_factures} factures | {self.montant_total_tiers_payant_da} DA)"
        )


# -----------------------------------------------------------------------------
# 5. Facture Patient (Facture Réglementaire Algérienne)
# -----------------------------------------------------------------------------
class FacturePatient(AuditableModel):
    """
    Facture hospitalière réglementaire algérienne regroupant :
    - Les actes médicaux/chirurgicaux NGAP et forfaits de séjour
    - La consommation pharmaceutique au PPA (liée au déstockage FEFO)
    - La ventilation TVA algérienne (0%, 9%, 19%)
    - La séparation Part Organisme (Tiers-Payant) vs Ticket Modérateur Patient
    - Le calcul automatique du Droit de Timbre selon le mode de règlement.
    """

    numero_facture = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        verbose_name="N° de Facture séquentiel",
    )
    exercice_fiscal = models.PositiveIntegerField(
        default=2026,
        verbose_name="Exercice fiscal",
    )
    numero_sequentiel = models.PositiveIntegerField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Numéro séquentiel chronologique sans rupture",
    )
    patient = models.ForeignKey(
        Patient,
        on_delete=models.PROTECT,
        related_name="factures",
        verbose_name="Patient",
    )
    hospitalisation = models.ForeignKey(
        Hospitalization,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="factures",
        verbose_name="Séjour d'hospitalisation associé",
    )
    type_prise_en_charge = models.CharField(
        max_length=35,
        choices=TypePriseEnChargeFactureChoices.choices,
        default=TypePriseEnChargeFactureChoices.HOSPITALISATION_SEJOUR,
        verbose_name="Type de passage / séjour",
    )
    convention = models.ForeignKey(
        ConventionPriseEnCharge,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="factures_prises_en_charge",
        verbose_name="Convention Tiers-Payant appliquée (CNAS/CASNOS/Mutuelle)",
    )
    bordereau = models.ForeignKey(
        BordereauTiersPayant,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="factures",
        verbose_name="Bordereau d'envoi Tiers-Payant",
    )
    statut = models.CharField(
        max_length=25,
        choices=StatutFactureChoices.choices,
        default=StatutFactureChoices.BROUILLON,
        db_index=True,
        verbose_name="Statut de la facture",
    )
    date_emission = models.DateTimeField(
        default=timezone.now,
        verbose_name="Date d'émission",
    )

    # Totaux financiers en Dinars Algériens (DA)
    total_actes_ht_da = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Total Actes Médicaux & Séjour HT (DA)",
    )
    total_pharmacie_ppa_ht_da = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Total Pharmacie & Consommables au PPA HT (DA)",
    )
    montant_total_ht_da = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Total Général HT (DA)",
    )
    montant_tva_9_da = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Cumul TVA Taux Réduit 9 % (DA)",
    )
    montant_tva_19_da = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Cumul TVA Taux Normal 19 % (DA)",
    )
    montant_total_tva_da = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Total TVA (DA)",
    )
    montant_total_ttc_da = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Montant Total TTC hors timbre (DA)",
    )

    # Répartition Tiers-Payant (Caisse) vs Ticket Modérateur (Patient)
    part_organisme_tiers_payant_da = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Part Organisme Tiers-Payant (CNAS/CASNOS/Assurance) (DA)",
    )
    part_patient_ticket_moderateur_da = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Part Patient (Ticket Modérateur + Dépassements) (DA)",
    )

    # Droit de Timbre & Net à Payer Patient
    droit_timbre_da = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Droit de Timbre Fiscal Algérien (Espèces uniquement) (DA)",
    )
    net_a_payer_patient_da = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Net à payer par le Patient TTC (Timbre inclus) (DA)",
    )
    montant_deja_regle_patient_da = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Montant déjà réglé par le patient (DA)",
    )

    # Répartition interne Clinique vs Rétrocession Praticiens
    total_retrocession_praticiens_da = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Total Honoraires à rétrocéder aux Praticiens (DA)",
    )
    total_quote_part_clinique_da = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Quote-part nette Clinique (Plateau technique) (DA)",
    )

    montant_en_toutes_lettres = models.CharField(
        max_length=500,
        blank=True,
        verbose_name="Arrêté de la facture en toutes lettres (Obligation légale DZ)",
    )
    cree_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="factures_emises",
        verbose_name="Agent de facturation",
    )

    class Meta:
        verbose_name = "Facture Patient (Réglementation Algérienne)"
        verbose_name_plural = "Factures Patients (Réglementation Algérienne)"
        ordering = ["-date_emission", "-id"]

    def __str__(self) -> str:
        return f"{self.numero_facture} — {self.patient.full_name} ({self.montant_total_ttc_da} DA TTC)"

    @property
    def reste_a_payer_patient_da(self) -> Decimal:
        return max(Decimal("0.00"), self.net_a_payer_patient_da - self.montant_deja_regle_patient_da)

    def delete(self, *args, **kwargs):
        if self.statut != StatutFactureChoices.BROUILLON or self.numero_sequentiel is not None:
            raise PermissionDenied(
                "CONFORMITÉ FISCALE ALGÉRIENNE (Décret exécutif n° 05-468) : "
                "Une facture validée et numérotée ne peut jamais être supprimée afin de garantir "
                "la continuité chronologique sans rupture de la séquence."
            )
        return super().delete(*args, **kwargs)


# -----------------------------------------------------------------------------
# 6. Ligne de Facture — Acte Médical NGAP / Forfait & Rétrocession Praticien
# -----------------------------------------------------------------------------
class LigneFactureActe(AuditableModel):
    """
    Ligne d'acte médical ou chirurgical sur une facture, intégrant la codification NGAP,
    le dépassement d'honoraires, la TVA algérienne, la ventilation Tiers-Payant et la
    rétrocession d'honoraires au praticien exécutant.
    """

    facture = models.ForeignKey(
        FacturePatient,
        on_delete=models.CASCADE,
        related_name="lignes_actes",
        verbose_name="Facture",
    )
    acte = models.ForeignKey(
        ActeMedicalNGAP,
        on_delete=models.PROTECT,
        related_name="lignes_facturees",
        verbose_name="Acte NGAP / Forfait",
    )
    praticien_executant = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="actes_factures_realises",
        verbose_name="Médecin / Chirurgien exécutant (Bénéficiaire rétrocession)",
    )
    quantite = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        verbose_name="Quantité / Nombre de jours",
    )
    lettre_cle = models.CharField(max_length=15, verbose_name="Lettre-clé NGAP")
    coefficient = models.DecimalField(max_digits=8, decimal_places=2, verbose_name="Coefficient")
    tarif_reference_cnas_unitaire_da = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="Base de remboursement CNAS unitaire (DA)",
    )
    prix_unitaire_clinique_ht_da = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="Prix unitaire Clinique HT (DA)",
    )
    depassement_honoraire_ht_da = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Dépassement d'honoraires HT (DA)",
    )
    taux_tva = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("9.00"),
        verbose_name="Taux TVA (%)",
    )
    montant_ht_da = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    montant_tva_da = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    montant_ttc_da = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    # Ventilation Tiers-Payant vs Patient
    part_organisme_da = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Part Organisme Tiers-Payant (DA)",
    )
    part_patient_da = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Part Patient (Ticket Modérateur + Dépassement) (DA)",
    )

    # Rétrocession Praticien vs Clinique
    taux_retrocession_praticien_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("70.00"),
        verbose_name="% Rétrocession Médecin",
    )
    montant_retrocession_praticien_da = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Honoraires Praticien HT (DA)",
    )
    montant_quote_part_clinique_da = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Quote-part Clinique HT (DA)",
    )

    class Meta:
        verbose_name = "Ligne Facture — Acte NGAP / Séjour"
        verbose_name_plural = "Lignes Facture — Actes NGAP & Séjours"

    def __str__(self) -> str:
        return f"[{self.acte.code_ngap}] {self.acte.libelle} x{self.quantite} ({self.montant_ttc_da} DA TTC)"


# -----------------------------------------------------------------------------
# 7. Ligne de Facture — Consommation Pharmacie au PPA (Liaison FEFO)
# -----------------------------------------------------------------------------
class LigneFacturePharmacie(AuditableModel):
    """
    Ligne de médicament ou consommable facturé au patient sur la base du PPA
    (Prix Public Algérien), avec liaison directe au lot déstocké en FEFO.
    """

    facture = models.ForeignKey(
        FacturePatient,
        on_delete=models.CASCADE,
        related_name="lignes_pharmacie",
        verbose_name="Facture",
    )
    produit = models.ForeignKey(
        ProduitPharmaceutique,
        on_delete=models.PROTECT,
        related_name="lignes_facturees_patients",
        verbose_name="Médicament / Consommable",
    )
    lot_sorti = models.ForeignKey(
        LotStock,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lignes_factures_associees",
        verbose_name="Lot déstocké automatiquement (FEFO)",
    )
    mouvement_stock = models.ForeignKey(
        MouvementStock,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ligne_facture_associee",
        verbose_name="Référence d'audit du déstockage",
    )
    quantite = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        verbose_name="Quantité consommée",
    )
    tarif_ppa_unitaire_ht_da = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="Tarif PPA (Prix Public Algérien) unitaire HT (DA)",
    )
    est_remboursable_cnas = models.BooleanField(
        default=True,
        verbose_name="Produit remboursable CNAS / Tarif de référence",
    )
    taux_tva = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("9.00"),
        verbose_name="Taux TVA (%)",
    )
    montant_ht_da = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    montant_tva_da = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    montant_ttc_da = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    part_organisme_da = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Part Organisme Tiers-Payant (DA)",
    )
    part_patient_da = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Part Patient (DA)",
    )
    destockage_fefo_effectue = models.BooleanField(
        default=True,
        verbose_name="Déstockage automatique FEFO effectué",
    )

    class Meta:
        verbose_name = "Ligne Facture — Médicament PPA / Consommable"
        verbose_name_plural = "Lignes Facture — Médicaments PPA & Consommables"

    def __str__(self) -> str:
        lot_num = self.lot_sorti.numero_lot if self.lot_sorti else "N/A"
        return f"{self.produit.nom_commercial} x{self.quantite} (Lot FEFO: {lot_num}) — {self.montant_ttc_da} DA"


# -----------------------------------------------------------------------------
# 8. Paiement Facture & Calcul du Droit de Timbre Algérien
# -----------------------------------------------------------------------------
class PaiementFacture(AuditableModel):
    """
    Règlement effectué par le patient.
    Déclenche le calcul légal du Droit de Timbre algérien uniquement si mode_paiement == ESPECES,
    et exonère totalement les paiements par Carte CIB, Edahabia, Chèque ou Virement.
    """

    facture = models.ForeignKey(
        FacturePatient,
        on_delete=models.PROTECT,
        related_name="paiements",
        verbose_name="Facture réglée",
    )
    mode_paiement = models.CharField(
        max_length=25,
        choices=ModePaiementAlgerieChoices.choices,
        default=ModePaiementAlgerieChoices.CARTE_CIB,
        verbose_name="Mode de règlement",
    )
    montant_hors_timbre_da = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        verbose_name="Montant réglé hors timbre (DA)",
    )
    droit_timbre_da = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Droit de Timbre fiscal appliqué (DA)",
    )
    montant_total_percu_da = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Montant total encaissé (Timbre inclus) (DA)",
    )
    reference_transaction = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="N° Quittance / N° Transaction TPE CIB-Edahabia / Chèque",
    )
    encaisse_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name="Caissier / Agent d'admission",
    )
    date_paiement = models.DateTimeField(
        default=timezone.now,
        verbose_name="Date et heure d'encaissement",
    )

    class Meta:
        verbose_name = "Encaissement / Paiement Patient"
        verbose_name_plural = "Encaissements & Paiements Patients"
        ordering = ["-date_paiement"]

    def __str__(self) -> str:
        return (
            f"{self.facture.numero_facture} — {self.get_mode_paiement_display()} : "
            f"{self.montant_total_percu_da} DA (dont Timbre: {self.droit_timbre_da} DA)"
        )

