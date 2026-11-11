"""
Services métiers et moteurs de calcul réglementaires algériens pour la Facturation Hospitalière :
1. Calcul du Droit de Timbre algérien (Code du Timbre Art. 100 / Lois de Finances : Espèces vs exonération CIB/Edahabia/Chèque/Virement)
2. Conversion des montants en Dinars Algériens en toutes lettres (mention légale obligatoire)
3. Tarification NGAP algérienne (lettres-clés C, CS, K, KC, Z, B, AMI, SF), dépassements et rétrocession praticien
4. Consommation de médicaments au PPA avec déstockage transactionnel automatique FEFO depuis apps.pharmacie
5. Ventilation Tiers-Payant (CNAS, CASNOS, Mutuelles, Assurances) vs Ticket Modérateur Patient
6. Validation avec numérotation séquentielle chronologique sans rupture (Décret exécutif n° 05-468)
7. Génération des Bordereaux d'envoi aux caisses (CNAS / CASNOS)
"""

from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING
from typing import Any, List, Optional, Tuple
import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.models import Hospitalization, Patient, UserRole
from apps.facturation.models import (
    ActeMedicalNGAP,
    BaseCalculRemboursementChoices,
    BordereauTiersPayant,
    ConventionPriseEnCharge,
    EtablissementFiscal,
    FacturePatient,
    LettreCleNGAPChoices,
    LigneFactureActe,
    LigneFacturePharmacie,
    ModePaiementAlgerieChoices,
    OrganismeTiersPayant,
    PaiementFacture,
    StatutBordereauChoices,
    StatutFactureChoices,
    TypeActeFacturableChoices,
    TypeOrganismePayeurChoices,
    TypePriseEnChargeFactureChoices,
)
from apps.pharmacie.models import CategorieProduitChoices, ProduitPharmaceutique
from apps.pharmacie.services import dispensation_sortie_fefo, initialiser_donnees_demo_pharmacie


# -----------------------------------------------------------------------------
# 1. Calcul Officiel du Droit de Timbre Algérien (Code du Timbre / Loi de Finances)
# -----------------------------------------------------------------------------
def calculer_droit_timbre_algerie(
    montant_ttc_da: Decimal,
    mode_paiement: str,
    plafond_max_da: Decimal = Decimal("10000.00"),
) -> Decimal:
    """
    Calcule le Droit de Timbre fiscal algérien (Art. 100 du Code du Timbre / LF) :
    - Exonération totale (0,00 DA) pour les paiements par Carte CIB, Carte Edahabia,
      Chèque bancaire/CCP ou Virement.
    - Pour les paiements en ESPECES :
      * Montant <= 300 DA : 0,00 DA
      * Barème légal par tranche de 100 DA (ou fraction de 100 DA) :
        - De 301 DA à 30 000 DA : 1 % (1 DA par tranche de 100 DA)
        - De 30 001 DA à 100 000 DA : 1,5 % sur la tranche au-delà de 30 000 DA
        - Au-delà de 100 000 DA : 2 % sur la tranche au-delà de 100 000 DA
      * Minimum légal de perception : 5,00 DA.
    """
    if mode_paiement != ModePaiementAlgerieChoices.ESPECES:
        return Decimal("0.00")
    if montant_ttc_da <= Decimal("300.00"):
        return Decimal("0.00")

    tranches_100 = (montant_ttc_da / Decimal("100.00")).to_integral_value(rounding=ROUND_CEILING)
    montant_tranche = tranches_100 * Decimal("100.00")

    if montant_tranche <= Decimal("30000.00"):
        timbre = montant_tranche * Decimal("0.01")
    elif montant_tranche <= Decimal("100000.00"):
        timbre = Decimal("300.00") + ((montant_tranche - Decimal("30000.00")) * Decimal("0.015"))
    else:
        timbre = (
            Decimal("300.00")
            + Decimal("1050.00")
            + ((montant_tranche - Decimal("100000.00")) * Decimal("0.02"))
        )

    timbre = max(Decimal("5.00"), timbre)
    if plafond_max_da and plafond_max_da > Decimal("0.00"):
        timbre = min(timbre, plafond_max_da)

    return timbre.quantize(Decimal("0.01"))


# -----------------------------------------------------------------------------
# 2. Conversion d'un montant en Dinars Algériens en toutes lettres
# -----------------------------------------------------------------------------
_UNITES = [
    "",
    "un",
    "deux",
    "trois",
    "quatre",
    "cinq",
    "six",
    "sept",
    "huit",
    "neuf",
    "dix",
    "onze",
    "douze",
    "treize",
    "quatorze",
    "quinze",
    "seize",
    "dix-sept",
    "dix-huit",
    "dix-neuf",
]
_DIZAINES = [
    "",
    "dix",
    "vingt",
    "trente",
    "quarante",
    "cinquante",
    "soixante",
    "soixante",
    "quatre-vingt",
    "quatre-vingt",
]


def _convertir_bloc_999(n: int) -> str:
    if n == 0:
        return ""
    parts: List[str] = []
    centaines = n // 100
    reste = n % 100
    if centaines == 1:
        parts.append("cent")
    elif centaines > 1:
        parts.append(f"{_UNITES[centaines]} cent" + ("s" if reste == 0 else ""))

    if reste > 0:
        if reste < 20:
            parts.append(_UNITES[reste])
        else:
            d = reste // 10
            u = reste % 10
            if d in (7, 9):
                sub = 10 + u
                sep = " et " if (d == 7 and u == 1) else "-"
                parts.append(f"{_DIZAINES[d]}{sep}{_UNITES[sub]}")
            else:
                if u == 0:
                    suffix = "s" if d == 8 else ""
                    parts.append(f"{_DIZAINES[d]}{suffix}")
                elif u == 1 and d != 8:
                    parts.append(f"{_DIZAINES[d]} et un")
                else:
                    parts.append(f"{_DIZAINES[d]}-{_UNITES[u]}")
    return " ".join(parts)


def nombre_entier_en_francais(n: int) -> str:
    if n <= 0:
        return "zéro"
    millions = n // 1_000_000
    milliers = (n % 1_000_000) // 1_000
    unites = n % 1_000
    blocs: List[str] = []
    if millions == 1:
        blocs.append("un million")
    elif millions > 1:
        blocs.append(f"{_convertir_bloc_999(millions)} millions")

    if milliers == 1:
        blocs.append("mille")
    elif milliers > 1:
        blocs.append(f"{_convertir_bloc_999(milliers)} mille")

    if unites > 0:
        blocs.append(_convertir_bloc_999(unites))

    return " ".join(blocs)


def montant_dinars_en_toutes_lettres(montant_da: Decimal) -> str:
    """
    Formate la mention légale obligatoire en Algérie :
    « Arrêtée la présente facture à la somme de : ... Dinars Algériens ... »
    """
    q = montant_da.quantize(Decimal("0.01"))
    entier = int(q)
    centimes = int((q - Decimal(entier)) * 100)
    texte_dinars = nombre_entier_en_francais(entier).capitalize()
    if centimes > 0:
        return f"{texte_dinars} Dinars Algériens et {centimes:02d} Centimes ({q} DA)"
    return f"{texte_dinars} Dinars Algériens ({q} DA)"


# -----------------------------------------------------------------------------
# 3. Ventilation Tiers-Payant (CNAS / CASNOS / Mutuelle vs Ticket Modérateur)
# -----------------------------------------------------------------------------
def calculer_ventilation_tiers_payant(
    montant_ttc_da: Decimal,
    base_reference_cnas_totale_da: Decimal,
    est_remboursable: bool,
    convention: Optional[ConventionPriseEnCharge],
) -> Tuple[Decimal, Decimal]:
    """
    Retourne le tuple (part_organisme_da, part_patient_da) selon la convention :
    - Sans convention ou produit non remboursable : (0.00, montant_ttc_da)
    - Avec convention SUR_TARIF_REFERENCE_CNAS :
      part_organisme = min(montant_ttc_da, base_reference_cnas_totale_da * taux / 100)
    - Avec convention SUR_FRAIS_REELS_CLINIQUE :
      part_organisme = montant_ttc_da * taux / 100
    """
    if not convention or not convention.est_active or not est_remboursable:
        return Decimal("0.00"), montant_ttc_da

    taux = convention.taux_prise_en_charge_pct / Decimal("100.00")
    if convention.organisme.base_calcul == BaseCalculRemboursementChoices.SUR_FRAIS_REELS_CLINIQUE:
        part_org = (montant_ttc_da * taux).quantize(Decimal("0.01"))
    else:
        base_retenue = min(montant_ttc_da, base_reference_cnas_totale_da)
        part_org = (base_retenue * taux).quantize(Decimal("0.01"))

    if convention.plafond_couverture_da and convention.plafond_couverture_da > Decimal("0.00"):
        part_org = min(part_org, convention.plafond_couverture_da)

    part_org = min(montant_ttc_da, max(Decimal("0.00"), part_org))
    part_pat = (montant_ttc_da - part_org).quantize(Decimal("0.01"))
    return part_org, part_pat


# -----------------------------------------------------------------------------
# 4. Recalcul Complet d'une Facture Patient
# -----------------------------------------------------------------------------
@transaction.atomic
def recalculer_facture_patient(facture: FacturePatient, save: bool = True) -> FacturePatient:
    """
    Recalcule l'ensemble des sous-totaux HT, TVA 9%, TVA 19%, TTC, Part Organisme (Tiers-Payant),
    Part Patient (Ticket Modérateur), Rétrocession Praticiens, Droit de Timbre et Arrêté en lettres.
    """
    total_actes_ht = Decimal("0.00")
    total_pharma_ht = Decimal("0.00")
    tva_9 = Decimal("0.00")
    tva_19 = Decimal("0.00")
    total_tva = Decimal("0.00")
    total_ttc = Decimal("0.00")
    part_org_total = Decimal("0.00")
    part_pat_total = Decimal("0.00")
    total_retro_medecins = Decimal("0.00")
    total_quote_clinique = Decimal("0.00")

    for l_acte in facture.lignes_actes.all():
        total_actes_ht += l_acte.montant_ht_da
        total_tva += l_acte.montant_tva_da
        if l_acte.taux_tva == Decimal("9.00"):
            tva_9 += l_acte.montant_tva_da
        elif l_acte.taux_tva == Decimal("19.00"):
            tva_19 += l_acte.montant_tva_da
        total_ttc += l_acte.montant_ttc_da
        part_org_total += l_acte.part_organisme_da
        part_pat_total += l_acte.part_patient_da
        total_retro_medecins += l_acte.montant_retrocession_praticien_da
        total_quote_clinique += l_acte.montant_quote_part_clinique_da

    for l_pharma in facture.lignes_pharmacie.all():
        total_pharma_ht += l_pharma.montant_ht_da
        total_tva += l_pharma.montant_tva_da
        if l_pharma.taux_tva == Decimal("9.00"):
            tva_9 += l_pharma.montant_tva_da
        elif l_pharma.taux_tva == Decimal("19.00"):
            tva_19 += l_pharma.montant_tva_da
        total_ttc += l_pharma.montant_ttc_da
        part_org_total += l_pharma.part_organisme_da
        part_pat_total += l_pharma.part_patient_da
        # La marge/cession pharmacie revient au plateau clinique
        total_quote_clinique += l_pharma.montant_ht_da

    # Cumul des règlements et droit de timbre effectivement constaté
    paiements = list(facture.paiements.all())
    timbre_cumule = sum((p.droit_timbre_da for p in paiements), Decimal("0.00")).quantize(Decimal("0.01"))
    deja_regle = sum((p.montant_total_percu_da for p in paiements), Decimal("0.00")).quantize(Decimal("0.01"))

    facture.total_actes_ht_da = total_actes_ht.quantize(Decimal("0.01"))
    facture.total_pharmacie_ppa_ht_da = total_pharma_ht.quantize(Decimal("0.01"))
    facture.montant_total_ht_da = (total_actes_ht + total_pharma_ht).quantize(Decimal("0.01"))
    facture.montant_tva_9_da = tva_9.quantize(Decimal("0.01"))
    facture.montant_tva_19_da = tva_19.quantize(Decimal("0.01"))
    facture.montant_total_tva_da = total_tva.quantize(Decimal("0.01"))
    facture.montant_total_ttc_da = total_ttc.quantize(Decimal("0.01"))
    facture.part_organisme_tiers_payant_da = part_org_total.quantize(Decimal("0.01"))
    facture.part_patient_ticket_moderateur_da = part_pat_total.quantize(Decimal("0.01"))
    facture.droit_timbre_da = timbre_cumule
    facture.net_a_payer_patient_da = (part_pat_total + timbre_cumule).quantize(Decimal("0.01"))
    facture.montant_deja_regle_patient_da = deja_regle
    facture.total_retrocession_praticiens_da = total_retro_medecins.quantize(Decimal("0.01"))
    facture.total_quote_part_clinique_da = total_quote_clinique.quantize(Decimal("0.01"))
    facture.montant_en_toutes_lettres = montant_dinars_en_toutes_lettres(
        facture.montant_total_ttc_da + facture.droit_timbre_da
    )

    if save and facture.pk:
        facture.save()
    return facture


# -----------------------------------------------------------------------------
# 5. Ajout d'un Acte NGAP et d'un Médicament au PPA (avec déstockage FEFO)
# -----------------------------------------------------------------------------
@transaction.atomic
def ajouter_acte_ngap_a_facture(
    facture_id: int,
    acte_id: int,
    quantite: int = 1,
    praticien_id: Optional[int] = None,
    prix_unitaire_ht_personnalise: Optional[Decimal] = None,
) -> LigneFactureActe:
    """
    Ajoute un acte médical/chirurgical NGAP ou un forfait à une facture,
    calcule la TVA algérienne (0%, 9%, 19%), la part CNAS/CASNOS et la rétrocession médecin.
    """
    facture = FacturePatient.objects.select_for_update().select_related("convention__organisme").get(pk=facture_id)
    acte = ActeMedicalNGAP.objects.get(pk=acte_id)
    User = get_user_model()
    praticien = User.objects.filter(pk=praticien_id).first() if praticien_id else None

    qte = max(1, int(quantite))
    prix_ht_u = (
        prix_unitaire_ht_personnalise
        if prix_unitaire_ht_personnalise is not None and prix_unitaire_ht_personnalise > Decimal("0.00")
        else acte.tarif_clinique_ht_da
    )
    depassement_u = max(Decimal("0.00"), prix_ht_u - acte.tarif_reference_cnas_da)

    montant_ht = (Decimal(qte) * prix_ht_u).quantize(Decimal("0.01"))
    montant_tva = (montant_ht * (acte.taux_tva / Decimal("100.00"))).quantize(Decimal("0.01"))
    montant_ttc = (montant_ht + montant_tva).quantize(Decimal("0.01"))

    base_ref_totale = (Decimal(qte) * acte.tarif_reference_cnas_da).quantize(Decimal("0.01"))
    part_org, part_pat = calculer_ventilation_tiers_payant(
        montant_ttc_da=montant_ttc,
        base_reference_cnas_totale_da=base_ref_totale,
        est_remboursable=acte.est_remboursable_cnas,
        convention=facture.convention,
    )

    taux_retro = acte.taux_retrocession_praticien_defaut
    montant_retro = (montant_ht * (taux_retro / Decimal("100.00"))).quantize(Decimal("0.01"))
    quote_clinique = (montant_ht - montant_retro).quantize(Decimal("0.01"))

    ligne = LigneFactureActe.objects.create(
        facture=facture,
        acte=acte,
        praticien_executant=praticien,
        quantite=qte,
        lettre_cle=acte.lettre_cle,
        coefficient=acte.coefficient,
        tarif_reference_cnas_unitaire_da=acte.tarif_reference_cnas_da,
        prix_unitaire_clinique_ht_da=prix_ht_u,
        depassement_honoraire_ht_da=depassement_u,
        taux_tva=acte.taux_tva,
        montant_ht_da=montant_ht,
        montant_tva_da=montant_tva,
        montant_ttc_da=montant_ttc,
        part_organisme_da=part_org,
        part_patient_da=part_pat,
        taux_retrocession_praticien_pct=taux_retro,
        montant_retrocession_praticien_da=montant_retro,
        montant_quote_part_clinique_da=quote_clinique,
    )
    recalculer_facture_patient(facture, save=True)
    return ligne


@transaction.atomic
def ajouter_medicament_ppa_a_facture(
    facture_id: int,
    produit_id: int,
    quantite: int,
    utilisateur: Any,
    tarif_ppa_unitaire_ht_da: Optional[Decimal] = None,
) -> LigneFacturePharmacie:
    """
    Ajoute une consommation de médicament ou consommable à la facture du patient :
    1. Déclenche automatiquement le déstockage FEFO dans la Pharmacie Hospitalière
    2. Applique le tarif réglementé PPA (Prix Public Algérien) et la TVA algérienne (9% médicaments / 19% parapharmacie)
    3. Ventile la part Tiers-Payant CNAS/CASNOS selon le caractère remboursable du produit.
    """
    facture = (
        FacturePatient.objects.select_for_update()
        .select_related("patient", "convention__organisme")
        .get(pk=facture_id)
    )
    produit = ProduitPharmaceutique.objects.get(pk=produit_id)
    qte = max(1, int(quantite))

    # 1. Déstockage automatique FEFO dans apps.pharmacie
    mouvements = dispensation_sortie_fefo(
        produit_id=produit.id,
        quantite_demandee=qte,
        utilisateur=utilisateur,
        motif_reference=f"Facturation Patient {facture.patient.full_name} ({facture.numero_facture})",
    )
    premier_mvt = mouvements[0] if mouvements else None
    premier_lot = premier_mvt.lot if premier_mvt else None

    # 2. Détermination du PPA (Prix Public Algérien) et du taux de TVA algérien (9% ou 19%)
    # Conversion/adaptation si le produit a un prix catalogue : en Algérie, PPA HT
    ppa_ht = (
        tarif_ppa_unitaire_ht_da
        if tarif_ppa_unitaire_ht_da is not None and tarif_ppa_unitaire_ht_da > Decimal("0.00")
        else (produit.prix_vente_ttc * Decimal("25.00")).quantize(Decimal("0.01"))
    )
    est_remboursable = produit.categorie in (
        CategorieProduitChoices.MEDICAMENT_REMBOURSABLE,
        CategorieProduitChoices.STUPEFIANT_CONTROLE,
    )
    taux_tva = (
        Decimal("19.00")
        if produit.categorie == CategorieProduitChoices.PARAPHARMACIE
        else Decimal("9.00")
    )

    montant_ht = (Decimal(qte) * ppa_ht).quantize(Decimal("0.01"))
    montant_tva = (montant_ht * (taux_tva / Decimal("100.00"))).quantize(Decimal("0.01"))
    montant_ttc = (montant_ht + montant_tva).quantize(Decimal("0.01"))

    part_org, part_pat = calculer_ventilation_tiers_payant(
        montant_ttc_da=montant_ttc,
        base_reference_cnas_totale_da=montant_ttc,
        est_remboursable=est_remboursable,
        convention=facture.convention,
    )

    ligne = LigneFacturePharmacie.objects.create(
        facture=facture,
        produit=produit,
        lot_sorti=premier_lot,
        mouvement_stock=premier_mvt,
        quantite=qte,
        tarif_ppa_unitaire_ht_da=ppa_ht,
        est_remboursable_cnas=est_remboursable,
        taux_tva=taux_tva,
        montant_ht_da=montant_ht,
        montant_tva_da=montant_tva,
        montant_ttc_da=montant_ttc,
        part_organisme_da=part_org,
        part_patient_da=part_pat,
        destockage_fefo_effectue=True,
    )
    recalculer_facture_patient(facture, save=True)
    return ligne


# -----------------------------------------------------------------------------
# 6. Validation Séquentielle Sans Rupture & Encaissement avec Droit de Timbre
# -----------------------------------------------------------------------------
@transaction.atomic
def valider_et_numeroter_facture(facture_id: int) -> FacturePatient:
    """
    Valide définitivement une facture brouillon et lui attribue un numéro séquentiel
    chronologique sans rupture (ex: FAC-2026-000001) via un verrou atomique sur EtablissementFiscal.
    """
    facture = FacturePatient.objects.select_for_update().get(pk=facture_id)
    if facture.statut != StatutFactureChoices.BROUILLON and facture.numero_sequentiel is not None:
        return facture

    etab = EtablissementFiscal.objects.select_for_update().first()
    if not etab:
        etab = EtablissementFiscal.objects.create()

    etab.dernier_numero_sequentiel += 1
    etab.save(update_fields=["dernier_numero_sequentiel", "updated_at"])

    seq = etab.dernier_numero_sequentiel
    exercice = etab.exercice_fiscal_courant
    facture.exercice_fiscal = exercice
    facture.numero_sequentiel = seq
    facture.numero_facture = f"FAC-{exercice}-{seq:06d}"
    facture.statut = StatutFactureChoices.VALIDEE_EMISE
    facture.date_emission = timezone.now()
    recalculer_facture_patient(facture, save=True)
    return facture


@transaction.atomic
def enregistrer_paiement_patient(
    facture_id: int,
    mode_paiement: str,
    montant_hors_timbre_da: Decimal,
    utilisateur: Any,
    reference_transaction: str = "",
) -> PaiementFacture:
    """
    Enregistre un paiement patient :
    - Si la facture est encore en BROUILLON, la valide et la numérote automatiquement
    - Calcule le Droit de Timbre algérien uniquement si mode_paiement == ESPECES
    - Exonère de Droit de Timbre (0 DA) si CIB, Edahabia, Chèque ou Virement
    - Met à jour le statut de la facture (PARTIELLEMENT_PAYEE ou SOLDEE).
    """
    if montant_hors_timbre_da <= Decimal("0.00"):
        raise ValidationError("Le montant du règlement doit être strictement supérieur à 0 DA.")

    facture = valider_et_numeroter_facture(facture_id)
    facture = FacturePatient.objects.select_for_update().get(pk=facture.pk)

    timbre = calculer_droit_timbre_algerie(
        montant_ttc_da=montant_hors_timbre_da,
        mode_paiement=mode_paiement,
    )
    total_percu = (montant_hors_timbre_da + timbre).quantize(Decimal("0.01"))

    ref = reference_transaction.strip()
    if not ref:
        ref = f"QUIT-{timezone.localdate().strftime('%Y%m%d')}-{uuid.uuid4().hex[:5].upper()}"

    paiement = PaiementFacture.objects.create(
        facture=facture,
        mode_paiement=mode_paiement,
        montant_hors_timbre_da=montant_hors_timbre_da.quantize(Decimal("0.01")),
        droit_timbre_da=timbre,
        montant_total_percu_da=total_percu,
        reference_transaction=ref,
        encaisse_par=utilisateur if (utilisateur and getattr(utilisateur, "is_authenticated", False)) else None,
    )

    recalculer_facture_patient(facture, save=False)
    if facture.reste_a_payer_patient_da <= Decimal("0.00"):
        facture.statut = StatutFactureChoices.SOLDEE
    else:
        facture.statut = StatutFactureChoices.PARTIELLEMENT_PAYEE
    facture.save()
    return paiement


@transaction.atomic
def generer_bordereau_tiers_payant(
    organisme_id: int,
    utilisateur: Any,
) -> BordereauTiersPayant:
    """
    Regroupe toutes les factures validées/soldées ayant une part Tiers-Payant > 0
    pour l'organisme sélectionné (CNAS, CASNOS, Mutuelle, Assurance) et qui ne sont pas
    encore rattachées à un bordereau, et génère le Bordereau d'envoi officiel.
    """
    organisme = OrganismeTiersPayant.objects.get(pk=organisme_id)
    factures_eligibles = list(
        FacturePatient.objects.select_for_update().filter(
            convention__organisme=organisme,
            part_organisme_tiers_payant_da__gt=Decimal("0.00"),
            bordereau__isnull=True,
        ).exclude(statut=StatutFactureChoices.BROUILLON)
    )
    if not factures_eligibles:
        raise ValidationError(
            f"Aucune facture validée en attente de bordereau pour « {organisme.nom} »."
        )

    today = timezone.localdate()
    num_bord = f"BORD-{organisme.code_organisme}-{today.strftime('%Y%m')}-{uuid.uuid4().hex[:4].upper()}"
    total_reclame = sum(
        (f.part_organisme_tiers_payant_da for f in factures_eligibles),
        Decimal("0.00"),
    ).quantize(Decimal("0.01"))

    bordereau = BordereauTiersPayant.objects.create(
        numero_bordereau=num_bord,
        organisme=organisme,
        periode_debut=today - timedelta(days=30),
        periode_fin=today,
        nombre_factures=len(factures_eligibles),
        montant_total_tiers_payant_da=total_reclame,
        statut=StatutBordereauChoices.ENVOYE_CAISSE,
        cree_par=utilisateur if (utilisateur and getattr(utilisateur, "is_authenticated", False)) else None,
    )
    for fac in factures_eligibles:
        fac.bordereau = bordereau
        fac.save(update_fields=["bordereau", "updated_at"])

    return bordereau


# -----------------------------------------------------------------------------
# 7. Jeu de Données de Démonstration Réglementaire Algérie
# -----------------------------------------------------------------------------
@transaction.atomic
def initialiser_donnees_demo_facturation_algerie(utilisateur: Any = None) -> None:
    """
    Initialise le référentiel fiscal algérien de la Clinique Sidi Yahia 2 (NIF, NIS, RC, AI),
    la nomenclature NGAP algérienne (C, CS, K, KC, Z, B, AMI, SF + Forfaits), les caisses
    (CNAS, CASNOS, Sonatrach, Alliance Assurances) et deux factures complètes.
    """
    if EtablissementFiscal.objects.exists() and ActeMedicalNGAP.objects.exists():
        return

    initialiser_donnees_demo_pharmacie(utilisateur=utilisateur)

    # 1. Identité Fiscale Officielle de la Clinique Sidi Yahia 2 (Alger)
    etab, _ = EtablissementFiscal.objects.get_or_create(
        nif="002116099123456",
        defaults={
            "raison_sociale": "EURL CLINIQUE MÉDICO-CHIRURGICALE SIDI YAHIA 2",
            "forme_juridique": "EURL au Capital Social de 50 000 000,00 DA",
            "adresse_complete": "Lotissement Sidi Yahia N° 42, Hydra / Bir Mourad Raïs, 16035 Alger, Algérie",
            "wilaya": "16 - Alger",
            "telephone": "+213 (0) 21 60 88 00",
            "nis": "099916100654321",
            "rc": "16/00-1048291B21",
            "article_imposition": "16125849012",
            "rib_bancaire": "BEA Agence Hydra Alger : 002 00012 1203456789 44",
            "numero_convention_cnas": "CONV-CNAS-DZ-16-2026-089",
            "exercice_fiscal_courant": 2026,
            "dernier_numero_sequentiel": 0,
        },
    )

    # 2. Nomenclature Générale des Actes Professionnels (NGAP Algérie) & Forfaits
    acte_cs, _ = ActeMedicalNGAP.objects.get_or_create(
        code_ngap="CS",
        defaults={
            "libelle": "Consultation Médecin Spécialiste / Chirurgien",
            "type_acte": TypeActeFacturableChoices.ACTE_NGAP,
            "lettre_cle": LettreCleNGAPChoices.CS,
            "coefficient": Decimal("1.00"),
            "valeur_lettre_cle_cnas_da": Decimal("1200.00"),
            "tarif_reference_cnas_da": Decimal("1200.00"),
            "tarif_clinique_ht_da": Decimal("3000.00"),
            "taux_tva": Decimal("0.00"),  # Exonéré Art. 9 CTCA
            "taux_retrocession_praticien_defaut": Decimal("75.00"),
            "est_remboursable_cnas": True,
        },
    )
    acte_k50, _ = ActeMedicalNGAP.objects.get_or_create(
        code_ngap="K50",
        defaults={
            "libelle": "Intervention Chirurgicale Viscérale (Appendicectomie / Hernie — K50)",
            "type_acte": TypeActeFacturableChoices.FORFAIT_CHIRURGIE,
            "lettre_cle": LettreCleNGAPChoices.K,
            "coefficient": Decimal("50.00"),
            "valeur_lettre_cle_cnas_da": Decimal("600.00"),
            "tarif_reference_cnas_da": Decimal("30000.00"),
            "tarif_clinique_ht_da": Decimal("55000.00"),
            "taux_tva": Decimal("9.00"),  # Taux réduit 9%
            "taux_retrocession_praticien_defaut": Decimal("65.00"),
            "est_remboursable_cnas": True,
        },
    )
    acte_kc120, _ = ActeMedicalNGAP.objects.get_or_create(
        code_ngap="KC120",
        defaults={
            "libelle": "Chirurgie Lourde / Coelioscopie Avancée & Bloc Opératoire (KC120)",
            "type_acte": TypeActeFacturableChoices.FORFAIT_CHIRURGIE,
            "lettre_cle": LettreCleNGAPChoices.KC,
            "coefficient": Decimal("120.00"),
            "valeur_lettre_cle_cnas_da": Decimal("600.00"),
            "tarif_reference_cnas_da": Decimal("72000.00"),
            "tarif_clinique_ht_da": Decimal("95000.00"),
            "taux_tva": Decimal("9.00"),
            "taux_retrocession_praticien_defaut": Decimal("60.00"),
            "est_remboursable_cnas": True,
        },
    )
    acte_maternite, _ = ActeMedicalNGAP.objects.get_or_create(
        code_ngap="FORF-MAT-SF",
        defaults={
            "libelle": "Forfait Accouchement Eutocique & Surveillance Néonatale Maternité",
            "type_acte": TypeActeFacturableChoices.FORFAIT_MATERNITE,
            "lettre_cle": LettreCleNGAPChoices.SF,
            "coefficient": Decimal("40.00"),
            "valeur_lettre_cle_cnas_da": Decimal("1000.00"),
            "tarif_reference_cnas_da": Decimal("40000.00"),
            "tarif_clinique_ht_da": Decimal("60000.00"),
            "taux_tva": Decimal("9.00"),
            "taux_retrocession_praticien_defaut": Decimal("55.00"),
            "est_remboursable_cnas": True,
        },
    )
    acte_z25, _ = ActeMedicalNGAP.objects.get_or_create(
        code_ngap="Z25",
        defaults={
            "libelle": "Échographie Abdomino-Pelvienne / Doppler & Imagerie (Z25)",
            "type_acte": TypeActeFacturableChoices.ACTE_NGAP,
            "lettre_cle": LettreCleNGAPChoices.Z,
            "coefficient": Decimal("25.00"),
            "valeur_lettre_cle_cnas_da": Decimal("100.00"),
            "tarif_reference_cnas_da": Decimal("2500.00"),
            "tarif_clinique_ht_da": Decimal("4000.00"),
            "taux_tva": Decimal("9.00"),
            "taux_retrocession_praticien_defaut": Decimal("70.00"),
            "est_remboursable_cnas": True,
        },
    )
    acte_b40, _ = ActeMedicalNGAP.objects.get_or_create(
        code_ngap="B40",
        defaults={
            "libelle": "Bilan Biologique Pré-Opératoire Complet (FNS, Hémostase, Ionogramme — B40)",
            "type_acte": TypeActeFacturableChoices.ACTE_NGAP,
            "lettre_cle": LettreCleNGAPChoices.B,
            "coefficient": Decimal("40.00"),
            "valeur_lettre_cle_cnas_da": Decimal("50.00"),
            "tarif_reference_cnas_da": Decimal("2000.00"),
            "tarif_clinique_ht_da": Decimal("3200.00"),
            "taux_tva": Decimal("9.00"),
            "taux_retrocession_praticien_defaut": Decimal("50.00"),
            "est_remboursable_cnas": True,
        },
    )
    acte_ami4, _ = ActeMedicalNGAP.objects.get_or_create(
        code_ngap="AMI4",
        defaults={
            "libelle": "Soins Infirmiers Post-Opératoires, Perfusion & Pansement Complexe (AMI4)",
            "type_acte": TypeActeFacturableChoices.ACTE_NGAP,
            "lettre_cle": LettreCleNGAPChoices.AMI,
            "coefficient": Decimal("4.00"),
            "valeur_lettre_cle_cnas_da": Decimal("250.00"),
            "tarif_reference_cnas_da": Decimal("1000.00"),
            "tarif_clinique_ht_da": Decimal("1500.00"),
            "taux_tva": Decimal("9.00"),
            "taux_retrocession_praticien_defaut": Decimal("30.00"),
            "est_remboursable_cnas": True,
        },
    )
    acte_chambre_vip, _ = ActeMedicalNGAP.objects.get_or_create(
        code_ngap="HOT-VIP-19",
        defaults={
            "libelle": "Supplément Hôtelier Chambre Individuelle VIP & Repas Accompagnant (TVA 19%)",
            "type_acte": TypeActeFacturableChoices.HOTELLERIE_CONFORT,
            "lettre_cle": LettreCleNGAPChoices.FORFAIT,
            "coefficient": Decimal("1.00"),
            "valeur_lettre_cle_cnas_da": Decimal("0.00"),
            "tarif_reference_cnas_da": Decimal("0.00"),
            "tarif_clinique_ht_da": Decimal("8000.00"),
            "taux_tva": Decimal("19.00"),  # Taux normal 19% (Prestation non médicale)
            "taux_retrocession_praticien_defaut": Decimal("0.00"),
            "est_remboursable_cnas": False,
        },
    )

    # 3. Organismes de Tiers-Payant (CNAS, CASNOS, Sonatrach, Alliance Assurances)
    org_cnas, _ = OrganismeTiersPayant.objects.get_or_create(
        code_organisme="CNAS-ALGER-16",
        defaults={
            "nom": "CNAS — Agence Wilaya d'Alger (Assurés Sociaux Salariés)",
            "type_organisme": TypeOrganismePayeurChoices.CNAS,
            "taux_couverture_defaut_pct": Decimal("80.00"),
            "base_calcul": BaseCalculRemboursementChoices.SUR_TARIF_REFERENCE_CNAS,
            "adresse_centre_paiement": "Centre Payeur CNAS Hydra, Alger",
        },
    )
    org_casnos, _ = OrganismeTiersPayant.objects.get_or_create(
        code_organisme="CASNOS-ALGER-16",
        defaults={
            "nom": "CASNOS — Direction Régionale d'Alger (Non-Salariés)",
            "type_organisme": TypeOrganismePayeurChoices.CASNOS,
            "taux_couverture_defaut_pct": Decimal("80.00"),
            "base_calcul": BaseCalculRemboursementChoices.SUR_TARIF_REFERENCE_CNAS,
            "adresse_centre_paiement": "CASNOS El Biar, Alger",
        },
    )
    org_sonatrach, _ = OrganismeTiersPayant.objects.get_or_create(
        code_organisme="CONV-SONATRACH",
        defaults={
            "nom": "SONATRACH — Direction des Œuvres Sociales & Médicales (Convention 100%)",
            "type_organisme": TypeOrganismePayeurChoices.ENTREPRISE_CONVENTIONNEE,
            "taux_couverture_defaut_pct": Decimal("100.00"),
            "base_calcul": BaseCalculRemboursementChoices.SUR_FRAIS_REELS_CLINIQUE,
            "adresse_centre_paiement": "Djenane El Malik, Hydra, Alger",
        },
    )
    OrganismeTiersPayant.objects.get_or_create(
        code_organisme="ASSUR-ALLIANCE",
        defaults={
            "nom": "Alliance Assurances Algérie — Santé Collective",
            "type_organisme": TypeOrganismePayeurChoices.ASSURANCE_PRIVEE,
            "taux_couverture_defaut_pct": Decimal("85.00"),
            "base_calcul": BaseCalculRemboursementChoices.SUR_FRAIS_REELS_CLINIQUE,
            "adresse_centre_paiement": "Centre d'Affaires El Qods, Chéraga, Alger",
        },
    )

    # 4. Patients & Praticiens de démonstration
    User = get_user_model()
    praticien = User.objects.filter(role__in=[UserRole.CHIRURGIEN, UserRole.MEDECIN]).first()
    if not praticien:
        praticien = User.objects.first()

    patient_1 = Patient.objects.first()
    if not patient_1:
        patient_1 = Patient.objects.create(
            nir="178057511604258",
            first_name="Youcef",
            last_name="Benkhedda",
            birth_date=date(1978, 5, 14),
            gender="M",
            phone="+213 550 12 34 56",
            city="Hydra, Alger",
        )

    conv_cnas, _ = ConventionPriseEnCharge.objects.get_or_create(
        patient=patient_1,
        organisme=org_cnas,
        defaults={
            "numero_immatriculation_assure": "197816049218",
            "numero_accord_pec": "PEC-CNAS-2026-8841",
            "taux_prise_en_charge_pct": Decimal("80.00"),
        },
    )

    # 5. Création d'une Facture Validée avec Actes NGAP + Pharmacie PPA (FEFO) + Tiers-Payant CNAS
    if not FacturePatient.objects.exists():
        fac1 = FacturePatient.objects.create(
            numero_facture="BROUILLON-INIT-01",
            patient=patient_1,
            type_prise_en_charge=TypePriseEnChargeFactureChoices.HOSPITALISATION_SEJOUR,
            convention=conv_cnas,
            cree_par=utilisateur if (utilisateur and getattr(utilisateur, "is_authenticated", False)) else praticien,
        )
        ajouter_acte_ngap_a_facture(
            facture_id=fac1.id,
            acte_id=acte_k50.id,
            quantite=1,
            praticien_id=praticien.id if praticien else None,
        )
        ajouter_acte_ngap_a_facture(
            facture_id=fac1.id,
            acte_id=acte_b40.id,
            quantite=1,
            praticien_id=praticien.id if praticien else None,
        )
        ajouter_acte_ngap_a_facture(
            facture_id=fac1.id,
            acte_id=acte_chambre_vip.id,
            quantite=2,
            praticien_id=None,
        )

        prod_perf = ProduitPharmaceutique.objects.filter(code_cip_ean13="3400935955838").first()
        if prod_perf and prod_perf.stock_actuel >= 2:
            ajouter_medicament_ppa_a_facture(
                facture_id=fac1.id,
                produit_id=prod_perf.id,
                quantite=2,
                utilisateur=utilisateur,
                tarif_ppa_unitaire_ht_da=Decimal("650.00"),
            )

        valider_et_numeroter_facture(fac1.id)
