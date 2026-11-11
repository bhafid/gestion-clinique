"""
Services métiers transactionnels du module Pharmacie & Achats :
- Sortie de stock stricte selon la règle FEFO (First Expired, First Out) avec verrouillage select_for_update()
- Mise en quarantaine / Retrait rappel de lot / Perte péremption
- Calcul des suggestions automatiques de commande : (Stock Max - Stock Actuel) si Stock Actuel <= Seuil d'alerte
- Réception de marchandises avec saisie obligatoire du N° de lot + Date de péremption et recalcul du PMP
- Inventaire tournant avec justification d'écart obligatoire et traçabilité d'audit immuable
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional
import uuid

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.pharmacie.models import (
    CategorieProduitChoices,
    CommandeAchat,
    Fournisseur,
    LigneCommandeAchat,
    LotStock,
    MethodeRotationChoices,
    MouvementStock,
    ProduitPharmaceutique,
    StatutCommandeChoices,
    StatutLotChoices,
    TypeMouvementStockChoices,
)


def synchroniser_statuts_lots(delai_alerte_jours: int = 90) -> int:
    """
    Met à jour automatiquement le statut de tous les lots actifs selon leur date de péremption
    (ACTIF, PROCHE_PEREMPTION si <= 90 jours, PERIME si < aujourd'hui).
    """
    compteur = 0
    lots = LotStock.objects.exclude(
        statut__in=[StatutLotChoices.QUARANTAINE, StatutLotChoices.RAPPELE]
    )
    for lot in lots:
        ancien = lot.statut
        nouveau = lot.actualiser_statut_peremption(delai_alerte_jours=delai_alerte_jours, save=True)
        if ancien != nouveau:
            compteur += 1
    return compteur


@transaction.atomic
def dispensation_sortie_fefo(
    produit_id: int,
    quantite_demandee: int,
    utilisateur: Any,
    motif_reference: str,
    type_mouvement: str = TypeMouvementStockChoices.SORTIE_VENTE,
) -> List[MouvementStock]:
    """
    Exécute une sortie de stock en appliquant strictement la règle FEFO
    (First Expired, First Out / Premier périmé, premier sorti).
    Verrouille les lots en base via select_for_update() pour éviter toute concurrence.
    """
    if quantite_demandee <= 0:
        raise ValidationError("La quantité à sortir doit être strictement supérieure à 0.")
    if not motif_reference or not motif_reference.strip():
        raise ValidationError("Le motif / référence (ordonnance, service, patient) est obligatoire.")

    produit = ProduitPharmaceutique.objects.select_for_update().get(pk=produit_id)
    today = timezone.localdate()

    # Sélection FEFO stricte : lots actifs/proche péremption, non périmés, triés par date_peremption ASC
    lots_eligibles = list(
        LotStock.objects.select_for_update()
        .filter(
            produit=produit,
            statut__in=[StatutLotChoices.ACTIF, StatutLotChoices.PROCHE_PEREMPTION],
            date_peremption__gte=today,
            quantite_disponible__gt=0,
        )
        .order_by("date_peremption", "id")
    )

    stock_total_dispo = sum(l.quantite_disponible for l in lots_eligibles)
    if stock_total_dispo < quantite_demandee:
        raise ValidationError(
            f"Stock disponible non périmé insuffisant pour « {produit.nom_commercial} » : "
            f"{stock_total_dispo} unité(s) disponible(s) pour {quantite_demandee} demandée(s)."
        )

    reste_a_prelever = quantite_demandee
    mouvements_crees: List[MouvementStock] = []

    for lot in lots_eligibles:
        if reste_a_prelever <= 0:
            break
        prelevement = min(lot.quantite_disponible, reste_a_prelever)
        stock_avant = lot.quantite_disponible
        lot.quantite_disponible -= prelevement
        lot.actualiser_statut_peremption(save=False)
        lot.save(update_fields=["quantite_disponible", "statut", "updated_at"])

        mvt = MouvementStock.objects.create(
            lot=lot,
            produit=produit,
            type_mouvement=type_mouvement,
            quantite=-prelevement,
            stock_lot_avant=stock_avant,
            stock_lot_apres=lot.quantite_disponible,
            utilisateur=utilisateur if (utilisateur and getattr(utilisateur, "is_authenticated", False)) else None,
            motif_reference=f"[FEFO] {motif_reference.strip()}",
        )
        mouvements_crees.append(mvt)
        reste_a_prelever -= prelevement

    return mouvements_crees


@transaction.atomic
def mettre_lot_en_quarantaine_ou_rappel(
    lot_id: int,
    nouveau_statut: str,
    motif: str,
    utilisateur: Any,
    retirer_du_stock: bool = True,
) -> LotStock:
    """
    Isole un lot en QUARANTAINE, RAPPELE (rappel ANSM/laboratoire) ou PERIME (destruction),
    et journalise l'opération dans MouvementStock.
    """
    if nouveau_statut not in (
        StatutLotChoices.QUARANTAINE,
        StatutLotChoices.RAPPELE,
        StatutLotChoices.PERIME,
    ):
        raise ValidationError("Statut de retrait ou quarantaine invalide.")
    if not motif or not motif.strip():
        raise ValidationError("Le motif de mise en quarantaine ou de rappel de lot est obligatoire.")

    lot = LotStock.objects.select_for_update().select_related("produit").get(pk=lot_id)
    stock_avant = lot.quantite_disponible

    if nouveau_statut == StatutLotChoices.PERIME:
        type_mvt = TypeMouvementStockChoices.PERTE_PEREMPTION
    elif nouveau_statut == StatutLotChoices.RAPPELE:
        type_mvt = TypeMouvementStockChoices.RETOUR_FOURNISSEUR
    else:
        type_mvt = TypeMouvementStockChoices.MISE_QUARANTAINE

    quantite_mvt = 0
    if retirer_du_stock and stock_avant > 0 and nouveau_statut in (StatutLotChoices.PERIME, StatutLotChoices.RAPPELE):
        quantite_mvt = -stock_avant
        lot.quantite_disponible = 0

    lot.statut = nouveau_statut
    lot.motif_quarantaine_rappel = motif.strip()
    lot.save(update_fields=["statut", "quantite_disponible", "motif_quarantaine_rappel", "updated_at"])

    MouvementStock.objects.create(
        lot=lot,
        produit=lot.produit,
        type_mouvement=type_mvt,
        quantite=quantite_mvt,
        stock_lot_avant=stock_avant,
        stock_lot_apres=lot.quantite_disponible,
        utilisateur=utilisateur if (utilisateur and getattr(utilisateur, "is_authenticated", False)) else None,
        motif_reference=f"[{lot.get_statut_display()}] {motif.strip()}",
    )
    return lot


def generer_suggestions_reapprovisionnement(
    fournisseur_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Calcule la liste des produits à commander selon la formule :
    Quantité à commander = (Stock Max - Stock Actuel)
    pour tout produit dont Stock Actuel <= Seuil d'alerte (stock_minimum).
    """
    qs = ProduitPharmaceutique.objects.select_related("fournisseur_prefere").prefetch_related("lots").all()
    if fournisseur_id:
        qs = qs.filter(fournisseur_prefere_id=fournisseur_id)

    suggestions: List[Dict[str, Any]] = []
    for produit in qs:
        actuel = produit.stock_actuel
        if actuel <= produit.stock_minimum:
            qte_suggeree = max(1, produit.stock_maximum - actuel)
            cout_estime_ht = (Decimal(qte_suggeree) * produit.prix_achat_ht).quantize(Decimal("0.01"))
            suggestions.append(
                {
                    "produit": produit,
                    "stock_actuel": actuel,
                    "stock_minimum": produit.stock_minimum,
                    "stock_securite": produit.stock_securite,
                    "stock_maximum": produit.stock_maximum,
                    "quantite_suggeree": qte_suggeree,
                    "prix_unitaire_ht": produit.prix_achat_ht,
                    "cout_estime_ht": cout_estime_ht,
                    "fournisseur": produit.fournisseur_prefere,
                    "urgence": produit.statut_urgence_ui,
                }
            )
    # Trier par urgence (ROUGE d'abord, puis ORANGE)
    suggestions.sort(key=lambda x: (0 if x["urgence"] == "ROUGE" else 1, x["stock_actuel"]))
    return suggestions


@transaction.atomic
def creer_commande_achat_depuis_lignes(
    fournisseur_id: int,
    lignes_data: List[Dict[str, Any]],
    utilisateur: Any,
    notes: str = "",
    envoyer_directement: bool = True,
) -> CommandeAchat:
    """
    Crée un Bon de Commande (CommandeAchat) et ses lignes (LigneCommandeAchat)
    de manière transactionnelle à partir des suggestions de réapprovisionnement.
    """
    if not lignes_data:
        raise ValidationError("Veuillez sélectionner au moins un produit à commander.")

    fournisseur = Fournisseur.objects.get(pk=fournisseur_id)
    today = timezone.localdate()
    prefix = f"BC-PHARM-{today.strftime('%Y%m%d')}"
    short_uid = uuid.uuid4().hex[:4].upper()
    numero_commande = f"{prefix}-{short_uid}"

    commande = CommandeAchat.objects.create(
        numero_commande=numero_commande,
        fournisseur=fournisseur,
        date_livraison_prevue=today + timedelta(days=fournisseur.delai_livraison_moyen),
        statut=StatutCommandeChoices.ENVOYEE if envoyer_directement else StatutCommandeChoices.BROUILLON,
        cree_par=utilisateur if (utilisateur and getattr(utilisateur, "is_authenticated", False)) else None,
        notes=notes.strip() or "Commande générée depuis les suggestions automatiques (Stock Max - Stock Actuel).",
    )

    for item in lignes_data:
        produit = ProduitPharmaceutique.objects.get(pk=int(item["produit_id"]))
        qte = int(item["quantite"])
        if qte <= 0:
            continue
        prix_ht = Decimal(str(item.get("prix_unitaire_ht", produit.prix_achat_ht)))
        LigneCommandeAchat.objects.create(
            commande=commande,
            produit=produit,
            quantite_commandee=qte,
            quantite_recue=0,
            prix_unitaire_achat_negocie=prix_ht,
        )

    commande.recalculer_totaux(save=True)
    return commande


@transaction.atomic
def receptionner_livraison_commande(
    commande_id: int,
    receptions: List[Dict[str, Any]],
    utilisateur: Any,
) -> CommandeAchat:
    """
    Réceptionne tout ou partie d'un Bon de Commande :
    - Exige obligatoirement le numéro de lot et la date de péremption pour chaque ligne reçue
    - Met à jour le Prix Moyen Pondéré (PMP) du produit
    - Crée ou abonde le LotStock correspondant
    - Met à jour le statut de la commande (PARTIELLEMENT_RECUE ou RECUE)
    - Enregistre chaque entrée dans MouvementStock
    """
    commande = (
        CommandeAchat.objects.select_for_update()
        .select_related("fournisseur")
        .get(pk=commande_id)
    )
    if commande.statut in (StatutCommandeChoices.ANNULEE, StatutCommandeChoices.RECUE):
        raise ValidationError(
            f"La commande {commande.numero_commande} est déjà « {commande.get_statut_display()} »."
        )

    au_moins_une_reception = False
    today = timezone.localdate()

    for rec in receptions:
        qte_recue_maintenant = int(rec.get("quantite_recue", 0))
        if qte_recue_maintenant <= 0:
            continue

        ligne = (
            LigneCommandeAchat.objects.select_for_update()
            .select_related("produit")
            .get(pk=int(rec["ligne_id"]), commande=commande)
        )
        numero_lot = str(rec.get("numero_lot", "")).strip()
        date_peremption_str = str(rec.get("date_peremption", "")).strip()
        emplacement = str(rec.get("emplacement_physique", "")).strip() or ligne.produit.rayon_par_defaut

        if not numero_lot:
            raise ValidationError(
                f"Le numéro de lot est obligatoire pour réceptionner « {ligne.produit.nom_commercial} »."
            )
        if not date_peremption_str:
            raise ValidationError(
                f"La date de péremption est obligatoire pour réceptionner « {ligne.produit.nom_commercial} »."
            )

        try:
            date_peremption = date.fromisoformat(date_peremption_str)
        except ValueError as exc:
            raise ValidationError(
                f"Format de date de péremption invalide ({date_peremption_str}) pour le lot {numero_lot}."
            ) from exc

        if date_peremption <= today:
            raise ValidationError(
                f"Impossible de réceptionner un lot déjà périmé ({numero_lot} expire le {date_peremption.strftime('%d/%m/%Y')})."
            )

        produit = ProduitPharmaceutique.objects.select_for_update().get(pk=ligne.produit.pk)
        stock_actuel_avant = produit.stock_actuel
        pmp_actuel = produit.prix_moyen_pondere_ht if produit.prix_moyen_pondere_ht > 0 else produit.prix_achat_ht
        prix_achat_ligne = ligne.prix_unitaire_achat_negocie

        # Recalcul du Prix Moyen Pondéré (PMP)
        nouveau_total_qte = stock_actuel_avant + qte_recue_maintenant
        if nouveau_total_qte > 0:
            nouvelle_valeur_totale = (Decimal(stock_actuel_avant) * pmp_actuel) + (
                Decimal(qte_recue_maintenant) * prix_achat_ligne
            )
            produit.prix_moyen_pondere_ht = (
                nouvelle_valeur_totale / Decimal(nouveau_total_qte)
            ).quantize(Decimal("0.01"))
        produit.prix_achat_ht = prix_achat_ligne
        produit.save(update_fields=["prix_moyen_pondere_ht", "prix_achat_ht", "updated_at"])

        # Création ou mise à jour du LotStock
        lot, created = LotStock.objects.select_for_update().get_or_create(
            produit=produit,
            numero_lot=numero_lot,
            defaults={
                "date_peremption": date_peremption,
                "quantite_disponible": 0,
                "emplacement_physique": emplacement,
                "statut": StatutLotChoices.ACTIF,
            },
        )
        stock_lot_avant = lot.quantite_disponible
        lot.date_peremption = date_peremption
        lot.emplacement_physique = emplacement
        lot.quantite_disponible += qte_recue_maintenant
        lot.actualiser_statut_peremption(save=False)
        lot.save()

        # Mise à jour de la ligne de commande
        ligne.quantite_recue += qte_recue_maintenant
        ligne.save(update_fields=["quantite_recue", "updated_at"])

        # Journalisation MouvementStock
        MouvementStock.objects.create(
            lot=lot,
            produit=produit,
            type_mouvement=TypeMouvementStockChoices.ENTREE_ACHAT,
            quantite=qte_recue_maintenant,
            stock_lot_avant=stock_lot_avant,
            stock_lot_apres=lot.quantite_disponible,
            utilisateur=utilisateur if (utilisateur and getattr(utilisateur, "is_authenticated", False)) else None,
            motif_reference=f"Réception {commande.numero_commande} ({commande.fournisseur.nom}) - Lot {numero_lot}",
        )
        au_moins_une_reception = True

    if not au_moins_une_reception:
        raise ValidationError("Aucune quantité reçue (> 0) n'a été saisie.")

    # Vérifier si toutes les lignes sont intégralement reçues
    toutes_lignes = list(commande.lignes.all())
    tout_recu = all(l.quantite_recue >= l.quantite_commandee for l in toutes_lignes)
    commande.statut = (
        StatutCommandeChoices.RECUE if tout_recu else StatutCommandeChoices.PARTIELLEMENT_RECUE
    )
    commande.save(update_fields=["statut", "updated_at"])
    return commande


@transaction.atomic
def ajuster_inventaire_tournant(
    lot_id: int,
    quantite_reelle_comptee: int,
    motif_justification: str,
    utilisateur: Any,
) -> MouvementStock:
    """
    Outil d'inventaire tournant : corrige l'écart entre le stock théorique et le stock réel compté
    pour un lot donné, avec justification obligatoire et trace d'audit immuable.
    """
    if quantite_reelle_comptee < 0:
        raise ValidationError("La quantité réelle comptée ne peut pas être négative.")
    if not motif_justification or not motif_justification.strip():
        raise ValidationError(
            "Une justification écrite est strictement obligatoire pour valider un écart d'inventaire."
        )

    lot = LotStock.objects.select_for_update().select_related("produit").get(pk=lot_id)
    stock_theorique_avant = lot.quantite_disponible
    ecart = quantite_reelle_comptee - stock_theorique_avant

    lot.quantite_disponible = quantite_reelle_comptee
    lot.actualiser_statut_peremption(save=False)
    lot.save(update_fields=["quantite_disponible", "statut", "updated_at"])

    mvt = MouvementStock.objects.create(
        lot=lot,
        produit=lot.produit,
        type_mouvement=TypeMouvementStockChoices.AJUSTEMENT_INVENTAIRE,
        quantite=ecart,
        stock_lot_avant=stock_theorique_avant,
        stock_lot_apres=quantite_reelle_comptee,
        utilisateur=utilisateur if (utilisateur and getattr(utilisateur, "is_authenticated", False)) else None,
        motif_reference=(
            f"[INVENTAIRE TOURNANT] Théorique: {stock_theorique_avant} -> Réel: {quantite_reelle_comptee} "
            f"(Écart: {ecart:+d}) | Motif: {motif_justification.strip()}"
        ),
    )
    return mvt


@transaction.atomic
def initialiser_donnees_demo_pharmacie(utilisateur: Any = None) -> None:
    """
    Initialise un jeu de données réaliste pour la Pharmacie Hospitalière de la Clinique Sidi Yahia 2
    si la table ProduitPharmaceutique est vide.
    """
    if ProduitPharmaceutique.objects.exists():
        synchroniser_statuts_lots()
        return

    today = timezone.localdate()

    # 1. Fournisseurs (Grossistes-Répartiteurs & Laboratoires)
    f_cerp = Fournisseur.objects.create(
        nom="CERP Répartition Médicale",
        contact="Dr. Karim Mansouri (Grands Comptes)",
        email="commandes-edi@cerp-med.dz",
        telephone="+213 21 60 44 10",
        delai_livraison_moyen=1,
        conditions_paiement="30 jours fin de mois",
    )
    f_biopharm = Fournisseur.objects.create(
        nom="Biopharm Distribution & Logistique",
        contact="Mme. Nadia Benali",
        email="hopital@biopharm-dz.com",
        telephone="+213 21 98 12 00",
        delai_livraison_moyen=2,
        conditions_paiement="45 jours date de facture",
    )
    f_sanofi = Fournisseur.objects.create(
        nom="Sanofi-Aventis Hospitalier",
        contact="Service Commandes Directes Hôpital",
        email="commandes.hopital@sanofi.com",
        telephone="+213 21 74 88 90",
        delai_livraison_moyen=3,
        conditions_paiement="60 jours net",
    )

    # 2. Produits Pharmaceutiques
    p_perfalgan = ProduitPharmaceutique.objects.create(
        code_cip_ean13="3400935955838",
        dci="Paracétamol",
        nom_commercial="Perfalgan Injectable",
        dosage="10 mg/ml (Flacon 100 ml)",
        forme_galenique="Solution pour perfusion IV",
        classe_therapeutique="N02BE01 - Analgésiques / Antipyrétiques",
        categorie=CategorieProduitChoices.MEDICAMENT_REMBOURSABLE,
        fournisseur_prefere=f_cerp,
        prix_achat_ht=Decimal("18.50"),
        prix_moyen_pondere_ht=Decimal("18.50"),
        taux_tva=Decimal("2.10"),
        prix_vente_ttc=Decimal("23.60"),
        stock_minimum=40,
        stock_securite=15,
        stock_maximum=160,
        rayon_par_defaut="Armoire Urgences & Bloc - B1",
    )

    p_augmentin = ProduitPharmaceutique.objects.create(
        code_cip_ean13="3400936214194",
        dci="Amoxicilline / Acide clavulanique",
        nom_commercial="Augmentin Adulte IV",
        dosage="1 g / 200 mg",
        forme_galenique="Poudre pour solution injectable",
        classe_therapeutique="J01CR02 - Antibactériens Bêta-lactamines",
        categorie=CategorieProduitChoices.MEDICAMENT_REMBOURSABLE,
        fournisseur_prefere=f_cerp,
        prix_achat_ht=Decimal("42.00"),
        prix_moyen_pondere_ht=Decimal("42.00"),
        taux_tva=Decimal("2.10"),
        prix_vente_ttc=Decimal("53.60"),
        stock_minimum=30,
        stock_securite=12,
        stock_maximum=120,
        rayon_par_defaut="Rayon Infectiologie - A2",
    )

    p_lovenox = ProduitPharmaceutique.objects.create(
        code_cip_ean13="3400936441583",
        dci="Énoxaparine sodique",
        nom_commercial="Lovenox Préventif / Curatif",
        dosage="4000 UI anti-Xa / 0,4 ml",
        forme_galenique="Seringue préremplie SC",
        classe_therapeutique="B01AB05 - Antithrombotiques (HBPM)",
        categorie=CategorieProduitChoices.MEDICAMENT_REMBOURSABLE,
        fournisseur_prefere=f_sanofi,
        prix_achat_ht=Decimal("64.00"),
        prix_moyen_pondere_ht=Decimal("64.00"),
        taux_tva=Decimal("2.10"),
        prix_vente_ttc=Decimal("81.70"),
        stock_minimum=25,
        stock_securite=10,
        stock_maximum=100,
        rayon_par_defaut="Armoire Chirurgie & Maternité - C1",
    )

    p_morphine = ProduitPharmaceutique.objects.create(
        code_cip_ean13="3400934189210",
        dci="Chlorhydrate de Morphine",
        nom_commercial="Morphine Aguettant",
        dosage="10 mg / 1 ml",
        forme_galenique="Ampoule injectable (Coffre Stupéfiants)",
        classe_therapeutique="N02AA01 - Analgésiques Opioïdes Majeurs",
        categorie=CategorieProduitChoices.STUPEFIANT_CONTROLE,
        fournisseur_prefere=f_biopharm,
        prix_achat_ht=Decimal("35.00"),
        prix_moyen_pondere_ht=Decimal("35.00"),
        taux_tva=Decimal("2.10"),
        prix_vente_ttc=Decimal("44.70"),
        stock_minimum=20,
        stock_securite=10,
        stock_maximum=80,
        rayon_par_defaut="Coffre-Fort Sécurisé Stupéfiants - S1",
    )

    p_insuline = ProduitPharmaceutique.objects.create(
        code_cip_ean13="3400935481122",
        dci="Insuline Asparte",
        nom_commercial="NovoRapid FlexPen",
        dosage="100 UI / ml (3 ml)",
        forme_galenique="Stylo prérempli injectable",
        classe_therapeutique="A10AB05 - Insulines d'action rapide",
        categorie=CategorieProduitChoices.MEDICAMENT_REMBOURSABLE,
        fournisseur_prefere=f_biopharm,
        prix_achat_ht=Decimal("52.00"),
        prix_moyen_pondere_ht=Decimal("52.00"),
        taux_tva=Decimal("2.10"),
        prix_vente_ttc=Decimal("66.40"),
        stock_minimum=15,
        stock_securite=6,
        stock_maximum=60,
        rayon_par_defaut="Chambre Froide / Frigo +2°C à +8°C - F1",
    )

    p_nacl = ProduitPharmaceutique.objects.create(
        code_cip_ean13="3400931199007",
        dci="Chlorure de Sodium 0,9%",
        nom_commercial="Sérum Physiologique B. Braun",
        dosage="0,9% (Poche 500 ml)",
        forme_galenique="Poche souple pour perfusion",
        classe_therapeutique="B05BB01 - Solutés Massifs IV",
        categorie=CategorieProduitChoices.PARAPHARMACIE,
        fournisseur_prefere=f_cerp,
        prix_achat_ht=Decimal("9.20"),
        prix_moyen_pondere_ht=Decimal("9.20"),
        taux_tva=Decimal("19.00"),
        prix_vente_ttc=Decimal("13.70"),
        stock_minimum=60,
        stock_securite=25,
        stock_maximum=250,
        rayon_par_defaut="Réserve Solutés Massifs - R1",
    )

    # 3. Création des Lots (avec cas FEFO, proche péremption, périmé, et sous seuil)
    # Perfalgan : 2 lots actifs (dont 1 proche péremption qui sortira en 1er grâce à FEFO) -> Total 85 (OK / VERT)
    lot_perf_1 = LotStock.objects.create(
        produit=p_perfalgan,
        numero_lot="PERF-2026-A1",
        date_peremption=today + timedelta(days=42),
        quantite_disponible=25,
        emplacement_physique="Armoire Urgences & Bloc - B1 (Avant)",
        statut=StatutLotChoices.PROCHE_PEREMPTION,
    )
    lot_perf_2 = LotStock.objects.create(
        produit=p_perfalgan,
        numero_lot="PERF-2027-B9",
        date_peremption=today + timedelta(days=340),
        quantite_disponible=60,
        emplacement_physique="Armoire Urgences & Bloc - B1 (Réserve)",
        statut=StatutLotChoices.ACTIF,
    )

    # Augmentin : Stock sous le seuil minimum (18 <= 30) -> ORANGE (Suggestion auto: 120 - 18 = 102)
    lot_aug_1 = LotStock.objects.create(
        produit=p_augmentin,
        numero_lot="AUG-2609-X",
        date_peremption=today + timedelta(days=180),
        quantite_disponible=18,
        emplacement_physique="Rayon Infectiologie - A2",
        statut=StatutLotChoices.ACTIF,
    )
    # + 1 lot d'Augmentin périmé à isoler/mettre en quarantaine
    LotStock.objects.create(
        produit=p_augmentin,
        numero_lot="AUG-2401-EXP",
        date_peremption=today - timedelta(days=15),
        quantite_disponible=6,
        emplacement_physique="Zone Quarantaine - Bac Rouge Q1",
        statut=StatutLotChoices.PERIME,
        motif_quarantaine_rappel="Date de péremption dépassée - En attente de destruction réglementaire",
    )

    # Lovenox : En alerte critique (8 <= stock_securite 10) -> ROUGE (Suggestion auto: 100 - 8 = 92)
    lot_lov_1 = LotStock.objects.create(
        produit=p_lovenox,
        numero_lot="LOV-2026-S4",
        date_peremption=today + timedelta(days=65),
        quantite_disponible=8,
        emplacement_physique="Armoire Chirurgie & Maternité - C1",
        statut=StatutLotChoices.PROCHE_PEREMPTION,
    )

    # Morphine (Stupéfiant contrôlé) : Stock sous seuil minimum (14 <= 20) -> ORANGE
    lot_morph_1 = LotStock.objects.create(
        produit=p_morphine,
        numero_lot="STUP-MOR-991",
        date_peremption=today + timedelta(days=270),
        quantite_disponible=14,
        emplacement_physique="Coffre-Fort Sécurisé Stupéfiants - S1",
        statut=StatutLotChoices.ACTIF,
    )

    # Insuline (Frigo) : Stock OK (36 > 15) -> VERT
    LotStock.objects.create(
        produit=p_insuline,
        numero_lot="INS-COLD-77",
        date_peremption=today + timedelta(days=210),
        quantite_disponible=36,
        emplacement_physique="Chambre Froide / Frigo +2°C à +8°C - F1",
        statut=StatutLotChoices.ACTIF,
    )

    # Sérum Physiologique : Critique (20 <= 25) -> ROUGE
    LotStock.objects.create(
        produit=p_nacl,
        numero_lot="NACL-500-M2",
        date_peremption=today + timedelta(days=420),
        quantite_disponible=20,
        emplacement_physique="Réserve Solutés Massifs - R1",
        statut=StatutLotChoices.ACTIF,
    )

    # 4. Commande d'Achat en attente de réception (pour tester la réception douchette code-barres)
    bc_demo = CommandeAchat.objects.create(
        numero_commande=f"BC-PHARM-{today.strftime('%Y%m%d')}-0101",
        fournisseur=f_cerp,
        date_livraison_prevue=today + timedelta(days=1),
        statut=StatutCommandeChoices.ENVOYEE,
        cree_par=utilisateur if (utilisateur and getattr(utilisateur, "is_authenticated", False)) else None,
        notes="Réapprovisionnement prioritaire Pôle Chirurgie & Urgences (EDI CERP).",
    )
    LigneCommandeAchat.objects.create(
        commande=bc_demo,
        produit=p_augmentin,
        quantite_commandee=100,
        quantite_recue=0,
        prix_unitaire_achat_negocie=Decimal("41.20"),
    )
    LigneCommandeAchat.objects.create(
        commande=bc_demo,
        produit=p_nacl,
        quantite_commandee=200,
        quantite_recue=50,
        prix_unitaire_achat_negocie=Decimal("9.00"),
    )
    bc_demo.recalculer_totaux(save=True)

    # 5. Journal d'Audit Initial (Mouvements de Stock)
    MouvementStock.objects.create(
        lot=lot_perf_1,
        produit=p_perfalgan,
        type_mouvement=TypeMouvementStockChoices.ENTREE_ACHAT,
        quantite=30,
        stock_lot_avant=0,
        stock_lot_apres=30,
        utilisateur=utilisateur if (utilisateur and getattr(utilisateur, "is_authenticated", False)) else None,
        motif_reference="Réception initiale BL-CERP-88412",
    )
    MouvementStock.objects.create(
        lot=lot_perf_1,
        produit=p_perfalgan,
        type_mouvement=TypeMouvementStockChoices.SORTIE_VENTE,
        quantite=-5,
        stock_lot_avant=30,
        stock_lot_apres=25,
        utilisateur=utilisateur if (utilisateur and getattr(utilisateur, "is_authenticated", False)) else None,
        motif_reference="[FEFO] Dotation Bloc Opératoire Salle 1 - Chirurgie Viscérale",
    )
    MouvementStock.objects.create(
        lot=lot_morph_1,
        produit=p_morphine,
        type_mouvement=TypeMouvementStockChoices.SORTIE_VENTE,
        quantite=-2,
        stock_lot_avant=16,
        stock_lot_apres=14,
        utilisateur=utilisateur if (utilisateur and getattr(utilisateur, "is_authenticated", False)) else None,
        motif_reference="[FEFO] [REGISTRE STUPÉFIANTS] Prescription post-opératoire Salle de Réveil (SSPI)",
    )
    MouvementStock.objects.create(
        lot=lot_aug_1,
        produit=p_augmentin,
        type_mouvement=TypeMouvementStockChoices.SORTIE_VENTE,
        quantite=-6,
        stock_lot_avant=24,
        stock_lot_apres=18,
        utilisateur=utilisateur if (utilisateur and getattr(utilisateur, "is_authenticated", False)) else None,
        motif_reference="[FEFO] Dispensation nominative Service Pédiatrie & Maternité",
    )
    MouvementStock.objects.create(
        lot=lot_lov_1,
        produit=p_lovenox,
        type_mouvement=TypeMouvementStockChoices.SORTIE_VENTE,
        quantite=-4,
        stock_lot_avant=12,
        stock_lot_apres=8,
        utilisateur=utilisateur if (utilisateur and getattr(utilisateur, "is_authenticated", False)) else None,
        motif_reference="[FEFO] Prophylaxie thrombo-embolique Pôle Chirurgie",
    )

