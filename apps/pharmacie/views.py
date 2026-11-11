"""
Vues et Routes API Transactionnelles du module Gestion de Stock Pharmaceutique & Achats.
Sécurisées par authentification obligatoire HDS/RGPD et transactions atomiques (select_for_update).
"""

from decimal import Decimal
from typing import Any, Dict, List

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from apps.core.excel_utils import (
    build_csv_bytes,
    build_xlsx_bytes,
    first_non_empty,
    parse_excel_or_csv_bytes,
    parse_flexible_date,
)
from apps.core.models import Patient
from apps.facturation.services import imputer_consommation_medicament_malade
from apps.pharmacie.models import (
    CategorieProduitChoices,
    CommandeAchat,
    Fournisseur,
    LigneCommandeAchat,
    LotStock,
    MouvementStock,
    ProduitPharmaceutique,
    StatutCommandeChoices,
    StatutLotChoices,
    TypeMouvementStockChoices,
)

PHARMACIE_ROLE_CONFIG = {
    "ADMIN": {"badge_class": "bg-purple-100 text-purple-800 border-purple-300"},
    "MEDECIN": {"badge_class": "bg-sky-100 text-sky-800 border-sky-300"},
    "CHIRURGIEN": {"badge_class": "bg-indigo-100 text-indigo-800 border-indigo-300"},
    "INFIRMIER": {"badge_class": "bg-emerald-100 text-emerald-800 border-emerald-300"},
    "SAGE_FEMME": {"badge_class": "bg-pink-100 text-pink-800 border-pink-300"},
    "SECRETAIRE": {"badge_class": "bg-amber-100 text-amber-800 border-amber-300"},
    "GESTIONNAIRE_ADMISSION": {"badge_class": "bg-teal-100 text-teal-800 border-teal-300"},
    "GESTIONNAIRE_PHARMACIE": {"badge_class": "bg-teal-100 text-teal-800 border-teal-300"},
    "GESTIONNAIRE_FACTURATION": {"badge_class": "bg-emerald-100 text-emerald-800 border-emerald-300"},
}
from apps.pharmacie.services import (
    ajuster_inventaire_tournant,
    creer_commande_achat_depuis_lignes,
    dispensation_sortie_fefo,
    generer_suggestions_reapprovisionnement,
    initialiser_donnees_demo_pharmacie,
    mettre_lot_en_quarantaine_ou_rappel,
    receptionner_livraison_commande,
)


class PharmacieDashboardView(LoginRequiredMixin, TemplateView):
    """
    Cockpit Principal de Gestion de Stock Pharmaceutique et d'Achats :
    1. KPIs temps réel (Valeur du stock PMP, Alertes rupture, Péremptions < 3 mois, Commandes en attente)
    2. Catalogue & État des stocks filtrable avec vue dépliable par lot (FEFO) et badges Rouge/Orange/Vert
    3. Cycle des Achats : Suggestions automatiques (Stock Max - Stock Actuel), Bons de Commande & Réception Douchette
    4. Inventaire Tournant avec justification obligatoire & Journal d'Audit immuable (Stupéfiants/HDS)
    """

    template_name = "pharmacie/dashboard_pharmacie.html"

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)
        initialiser_donnees_demo_pharmacie(utilisateur=self.request.user)

        # Filtres de recherche du catalogue
        q_search = self.request.GET.get("q", "").strip()
        f_categorie = self.request.GET.get("categorie", "").strip()
        f_urgence = self.request.GET.get("urgence", "").strip()
        active_tab = self.request.GET.get("tab", "catalogue").strip()

        tous_produits = list(
            ProduitPharmaceutique.objects.select_related("fournisseur_prefere")
            .prefetch_related("lots")
            .all()
        )

        # Calcul des KPIs sur l'ensemble du stock
        valeur_totale_stock_ht = sum(
            (p.valeur_stock_ht for p in tous_produits), Decimal("0.00")
        ).quantize(Decimal("0.01"))
        nb_produits_alerte_rupture = sum(1 for p in tous_produits if p.est_en_alerte_rupture)
        nb_produits_critiques_rouge = sum(1 for p in tous_produits if p.statut_urgence_ui == "ROUGE")

        tous_lots = list(LotStock.objects.select_related("produit").all())
        nb_lots_proche_peremption = sum(
            1
            for l in tous_lots
            if l.statut == StatutLotChoices.PROCHE_PEREMPTION and l.quantite_disponible > 0
        )
        nb_lots_perimes_quarantaine = sum(
            1
            for l in tous_lots
            if l.statut in (StatutLotChoices.PERIME, StatutLotChoices.QUARANTAINE, StatutLotChoices.RAPPELE)
        )

        commandes = list(
            CommandeAchat.objects.select_related("fournisseur", "cree_par")
            .prefetch_related("lignes__produit")
            .all()
        )
        commandes_en_attente = [
            c
            for c in commandes
            if c.statut in (StatutCommandeChoices.ENVOYEE, StatutCommandeChoices.PARTIELLEMENT_RECUE)
        ]

        # Filtrage du catalogue affiché
        produits_filtres: List[ProduitPharmaceutique] = []
        for prod in tous_produits:
            if q_search:
                q_low = q_search.lower()
                match_lots = any(q_low in l.numero_lot.lower() for l in prod.lots.all())
                if not (
                    q_low in prod.nom_commercial.lower()
                    or q_low in prod.dci.lower()
                    or q_low in prod.code_cip_ean13.lower()
                    or match_lots
                ):
                    continue
            if f_categorie and prod.categorie != f_categorie:
                continue
            if f_urgence and prod.statut_urgence_ui != f_urgence:
                continue
            produits_filtres.append(prod)

        # Suggestions automatiques de réapprovisionnement : (Stock Max - Stock Actuel)
        suggestions_reappro = generer_suggestions_reapprovisionnement()
        total_suggestions_ht = sum(
            (s["cout_estime_ht"] for s in suggestions_reappro), Decimal("0.00")
        ).quantize(Decimal("0.01"))

        # Journal d'audit des mouvements de stock
        mouvements_audit = (
            MouvementStock.objects.select_related("produit", "lot", "utilisateur")
            .order_by("-date_mouvement", "-id")[:60]
        )

        user_role = getattr(self.request.user, "role", "MEDECIN")
        role_config = PHARMACIE_ROLE_CONFIG.get(
            user_role,
            {
                "badge_class": "bg-slate-100 text-slate-800 border-slate-300",
                "title": "Espace Pharmacie Hospitalière",
            },
        )

        context.update(
            {
                "role_config": role_config,
                "active_tab": active_tab,
                "q_search": q_search,
                "f_categorie": f_categorie,
                "f_urgence": f_urgence,
                "categories_choices": CategorieProduitChoices.choices,
                # KPIs
                "valeur_totale_stock_ht": valeur_totale_stock_ht,
                "nb_produits_total": len(tous_produits),
                "nb_produits_alerte_rupture": nb_produits_alerte_rupture,
                "nb_produits_critiques_rouge": nb_produits_critiques_rouge,
                "nb_lots_proche_peremption": nb_lots_proche_peremption,
                "nb_lots_perimes_quarantaine": nb_lots_perimes_quarantaine,
                "nb_commandes_en_attente": len(commandes_en_attente),
                # Données métiers
                "produits": produits_filtres,
                "tous_produits": tous_produits,
                "tous_lots": tous_lots,
                "patients": Patient.objects.order_by("last_name", "first_name"),
                "fournisseurs": Fournisseur.objects.filter(est_actif=True),
                "suggestions_reappro": suggestions_reappro,
                "total_suggestions_ht": total_suggestions_ht,
                "commandes": commandes,
                "commandes_en_attente": commandes_en_attente,
                "mouvements_audit": mouvements_audit,
                "default_expiry_date": (timezone.localdate() + timezone.timedelta(days=365)).isoformat(),
            }
        )
        return context


class DispensationFEFOView(LoginRequiredMixin, View):
    """
    POST /pharmacie/fefo-dispense/
    Exécute une sortie de stock en appliquant strictement l'algorithme FEFO
    (First Expired, First Out) de manière transactionnelle.
    Si un malade (`patient_id`) est sélectionné, reporte automatiquement la consommation
    sur la facture du malade au tarif PPA réglementé algérien !
    """

    def post(self, request: HttpRequest) -> HttpResponse:
        try:
            produit_id = int(request.POST.get("produit_id", 0))
            quantite = int(request.POST.get("quantite", 0))
            patient_id = int(request.POST.get("patient_id", "0") or 0)
            motif = request.POST.get("motif_reference", "").strip()

            if patient_id > 0:
                facture, ligne_pharma, facture_creee = imputer_consommation_medicament_malade(
                    patient_id=patient_id,
                    produit_id=produit_id,
                    quantite=quantite,
                    utilisateur=request.user,
                )
                lot_code = ligne_pharma.lot_sorti.numero_lot if ligne_pharma.lot_sorti else "FEFO"
                statut_info = "nouvelle facture ouverte" if facture_creee else "facture mise à jour"
                messages.success(
                    request,
                    f"Consommation médicament imputée au malade {facture.patient.full_name} : "
                    f"{ligne_pharma.quantite} x {ligne_pharma.produit.nom_commercial} (Lot FEFO {lot_code}) "
                    f"reportée sur la facture {facture.numero_facture} ({statut_info}) — "
                    f"Ligne TTC : {ligne_pharma.montant_ttc_da} DA (Part Caisse : {ligne_pharma.part_organisme_da} DA | "
                    f"Part Patient : {ligne_pharma.part_patient_da} DA).",
                )
            else:
                if not motif:
                    motif = "Dotation service interne / Sortie FEFO"
                mouvements = dispensation_sortie_fefo(
                    produit_id=produit_id,
                    quantite_demandee=quantite,
                    utilisateur=request.user,
                    motif_reference=motif,
                )
                lots_touches = ", ".join(
                    f"Lot {m.lot.numero_lot} ({abs(m.quantite)} u., exp. {m.lot.date_peremption.strftime('%d/%m/%Y')})"
                    for m in mouvements
                )
                messages.success(
                    request,
                    f"Sortie FEFO validée avec succès : {lots_touches}.",
                )
        except (ValidationError, ValueError, ProduitPharmaceutique.DoesNotExist, Patient.DoesNotExist) as exc:
            msg = exc.message if isinstance(exc, ValidationError) and hasattr(exc, "message") else str(exc)
            messages.error(request, f"Erreur lors de la sortie FEFO : {msg}")
        return redirect("/pharmacie/?tab=catalogue")


class QuarantaineRappelLotView(LoginRequiredMixin, View):
    """
    POST /pharmacie/lot/<int:lot_id>/quarantine/
    Place un lot en quarantaine sanitaire, en rappel de lot (ANSM) ou en retrait péremption.
    """

    def post(self, request: HttpRequest, lot_id: int) -> HttpResponse:
        try:
            nouveau_statut = request.POST.get("nouveau_statut", StatutLotChoices.QUARANTAINE).strip()
            motif = request.POST.get(
                "motif",
                "Isolement sanitaire / Retrait préventif lot périmé ou rappelé",
            ).strip()
            retirer = request.POST.get("retirer_du_stock", "1") == "1"
            lot = mettre_lot_en_quarantaine_ou_rappel(
                lot_id=lot_id,
                nouveau_statut=nouveau_statut,
                motif=motif,
                utilisateur=request.user,
                retirer_du_stock=retirer,
            )
            messages.success(
                request,
                f"Lot {lot.numero_lot} ({lot.produit.nom_commercial}) placé en statut « {lot.get_statut_display()} » et journalisé.",
            )
        except (ValidationError, LotStock.DoesNotExist) as exc:
            messages.error(request, f"Erreur de mise en quarantaine : {exc}")
        return redirect("/pharmacie/?tab=catalogue")


class CreerCommandeDepuisSuggestionsView(LoginRequiredMixin, View):
    """
    POST /pharmacie/orders/create/
    Crée un Bon de Commande (CommandeAchat) à partir des suggestions de réapprovisionnement
    (Stock Max - Stock Actuel) ou d'une sélection manuelle.
    """

    def post(self, request: HttpRequest) -> HttpResponse:
        try:
            fournisseur_id = int(request.POST.get("fournisseur_id", 0))
            notes = request.POST.get("notes", "").strip()
            produit_ids = request.POST.getlist("produit_ids")

            lignes_data: List[Dict[str, Any]] = []
            for pid in produit_ids:
                qte_str = request.POST.get(f"quantite_{pid}", "0").strip()
                prix_str = request.POST.get(f"prix_{pid}", "").strip()
                qte = int(qte_str or 0)
                if qte > 0:
                    item: Dict[str, Any] = {"produit_id": int(pid), "quantite": qte}
                    if prix_str:
                        item["prix_unitaire_ht"] = Decimal(prix_str.replace(",", "."))
                    lignes_data.append(item)

            commande = creer_commande_achat_depuis_lignes(
                fournisseur_id=fournisseur_id,
                lignes_data=lignes_data,
                utilisateur=request.user,
                notes=notes,
                envoyer_directement=True,
            )
            messages.success(
                request,
                f"Bon de Commande {commande.numero_commande} créé et envoyé à {commande.fournisseur.nom} "
                f"(Total TTC : {commande.montant_total_ttc} €).",
            )
        except (ValidationError, ValueError, Fournisseur.DoesNotExist) as exc:
            messages.error(request, f"Impossible de générer le bon de commande : {exc}")
        return redirect("/pharmacie/?tab=achats")


class ReceptionLivraisonCommandeView(LoginRequiredMixin, View):
    """
    POST /pharmacie/orders/<int:commande_id>/receive/
    Réceptionne une livraison fournisseur avec saisie obligatoire du N° de lot
    et de la date de péremption, gestion des reliquats et recalcul automatique du PMP.
    """

    def post(self, request: HttpRequest, commande_id: int) -> HttpResponse:
        try:
            commande = get_object_or_404(CommandeAchat, pk=commande_id)
            receptions: List[Dict[str, Any]] = []
            for ligne in commande.lignes.all():
                qte_recue = int(request.POST.get(f"qte_recue_{ligne.id}", "0") or 0)
                if qte_recue <= 0:
                    continue
                numero_lot = request.POST.get(f"lot_{ligne.id}", "").strip()
                date_peremption = request.POST.get(f"peremption_{ligne.id}", "").strip()
                emplacement = request.POST.get(f"emplacement_{ligne.id}", "").strip()
                receptions.append(
                    {
                        "ligne_id": ligne.id,
                        "quantite_recue": qte_recue,
                        "numero_lot": numero_lot,
                        "date_peremption": date_peremption,
                        "emplacement_physique": emplacement,
                    }
                )

            commande_maj = receptionner_livraison_commande(
                commande_id=commande_id,
                receptions=receptions,
                utilisateur=request.user,
            )
            messages.success(
                request,
                f"Livraison enregistrée sur {commande_maj.numero_commande} "
                f"(Statut : {commande_maj.get_statut_display()}). Stock, lots FEFO et PMP mis à jour.",
            )
        except (ValidationError, ValueError) as exc:
            messages.error(request, f"Erreur lors de la réception de livraison : {exc}")
        return redirect("/pharmacie/?tab=reception")


class AjustementInventaireTournantView(LoginRequiredMixin, View):
    """
    POST /pharmacie/inventory/adjust/
    Corrige l'écart entre le stock théorique et le stock réel compté lors d'un inventaire tournant,
    avec justification obligatoire.
    """

    def post(self, request: HttpRequest) -> HttpResponse:
        try:
            lot_id = int(request.POST.get("lot_id", 0))
            quantite_reelle = int(request.POST.get("quantite_reelle", 0))
            motif = request.POST.get("motif_justification", "").strip()

            mvt = ajuster_inventaire_tournant(
                lot_id=lot_id,
                quantite_reelle_comptee=quantite_reelle,
                motif_justification=motif,
                utilisateur=request.user,
            )
            messages.success(
                request,
                f"Inventaire tournant validé pour {mvt.produit.nom_commercial} (Lot {mvt.lot.numero_lot}) : "
                f"Stock théorique {mvt.stock_lot_avant} -> Stock réel {mvt.stock_lot_apres} (Écart {mvt.quantite:+d}).",
            )
        except (ValidationError, ValueError, LotStock.DoesNotExist) as exc:
            messages.error(request, f"Erreur d'inventaire tournant : {exc}")
        return redirect("/pharmacie/?tab=inventaire")


@login_required
def api_scan_code_barres(request: HttpRequest, code_barres: str) -> JsonResponse:
    """
    GET /pharmacie/api/barcode/<code_barres>/
    Endpoint JSON temps réel optimisé pour les douchettes codes-barres CIP13 / EAN13.
    """
    code_clean = code_barres.strip()
    produit = (
        ProduitPharmaceutique.objects.select_related("fournisseur_prefere")
        .prefetch_related("lots")
        .filter(
            Q(code_cip_ean13__iexact=code_clean)
            | Q(nom_commercial__icontains=code_clean)
            | Q(dci__icontains=code_clean)
        )
        .first()
    )
    if not produit:
        return JsonResponse(
            {"found": False, "error": f"Aucun produit trouvé pour le code « {code_clean} »."},
            status=404,
        )

    today = timezone.localdate()
    lots_fefo = [
        {
            "id": l.id,
            "numero_lot": l.numero_lot,
            "date_peremption": l.date_peremption.strftime("%d/%m/%Y"),
            "quantite_disponible": l.quantite_disponible,
            "emplacement": l.emplacement_physique,
            "statut": l.statut,
            "statut_label": l.get_statut_display(),
        }
        for l in produit.lots.all()
        if l.quantite_disponible > 0 and l.date_peremption >= today
    ]

    lignes_en_attente = list(
        LigneCommandeAchat.objects.select_related("commande", "commande__fournisseur")
        .filter(
            produit=produit,
            commande__statut__in=[
                StatutCommandeChoices.ENVOYEE,
                StatutCommandeChoices.PARTIELLEMENT_RECUE,
            ],
        )
    )

    return JsonResponse(
        {
            "found": True,
            "id": produit.id,
            "code_cip_ean13": produit.code_cip_ean13,
            "nom_commercial": produit.nom_commercial,
            "dci": produit.dci,
            "dosage": produit.dosage,
            "forme_galenique": produit.forme_galenique,
            "categorie": produit.get_categorie_display(),
            "stock_actuel": produit.stock_actuel,
            "stock_minimum": produit.stock_minimum,
            "stock_maximum": produit.stock_maximum,
            "pmp_ht": str(produit.prix_moyen_pondere_ht),
            "urgence": produit.statut_urgence_ui,
            "premier_lot_fefo": lots_fefo[0] if lots_fefo else None,
            "lots_fefo": lots_fefo,
            "lignes_commandes_attente": [
                {
                    "ligne_id": lc.id,
                    "commande_id": lc.commande.id,
                    "numero_commande": lc.commande.numero_commande,
                    "fournisseur": lc.commande.fournisseur.nom,
                    "reliquat": lc.reliquat_a_recevoir,
                }
                for lc in lignes_en_attente
                if lc.reliquat_a_recevoir > 0
            ],
        }
    )


class ExportMedicamentsExcelView(LoginRequiredMixin, View):
    """
    GET /pharmacie/export/excel/
    Exporte le catalogue complet des médicaments et de leurs stocks FEFO au format Excel (.xlsx ou .csv).
    Supporte également ?template=1 pour télécharger un modèle Excel vierge prêt à remplir.
    """

    def get(self, request: HttpRequest) -> HttpResponse:
        fmt = request.GET.get("format", "xlsx").lower()
        is_template = request.GET.get("template", "0") == "1"

        headers = [
            "Code_CIP_EAN13",
            "Nom_Commercial",
            "DCI",
            "Dosage",
            "Forme_Galenique",
            "Classe_Therapeutique",
            "Categorie",
            "Prix_Achat_HT",
            "PMP_HT",
            "Prix_Vente_TTC",
            "Taux_TVA",
            "Stock_Minimum",
            "Stock_Securite",
            "Stock_Maximum",
            "Stock_Actuel_FEFO",
            "Numero_Lot_Initial",
            "Date_Peremption_Lot",
            "Rayon_Emplacement",
            "Fournisseur",
        ]

        rows: List[List[Any]] = []
        if is_template:
            rows.append(
                [
                    "3400935955838",
                    "Perfalgan Injectable",
                    "Paracétamol",
                    "10 mg/ml (1g/100ml)",
                    "Flacon perfusion IV",
                    "N02BE01 - Analgésique Antipyrétique",
                    "MEDICAMENT_REMBOURSABLE",
                    "1.85",
                    "1.85",
                    "2.45",
                    "9.00",
                    "30",
                    "15",
                    "150",
                    "50",
                    "LOT-PERF-2027",
                    (timezone.localdate() + timezone.timedelta(days=365)).strftime("%Y-%m-%d"),
                    "Armoire Pharmacie Centrale - A1",
                    "SAIDAL / BIOPHARM",
                ]
            )
        else:
            produits = (
                ProduitPharmaceutique.objects.select_related("fournisseur_prefere")
                .prefetch_related("lots")
                .all()
            )
            for p in produits:
                premier_lot = p.lots.filter(quantite_disponible__gt=0).order_by("date_peremption").first()
                rows.append(
                    [
                        p.code_cip_ean13,
                        p.nom_commercial,
                        p.dci,
                        p.dosage,
                        p.forme_galenique,
                        p.classe_therapeutique,
                        p.categorie,
                        str(p.prix_achat_ht),
                        str(p.prix_moyen_pondere_ht),
                        str(p.prix_vente_ttc),
                        str(p.taux_tva),
                        p.stock_minimum,
                        p.stock_securite,
                        p.stock_maximum,
                        p.stock_actuel,
                        premier_lot.numero_lot if premier_lot else "",
                        premier_lot.date_peremption.strftime("%Y-%m-%d") if premier_lot else "",
                        p.rayon_par_defaut,
                        p.fournisseur_prefere.nom if p.fournisseur_prefere else "",
                    ]
                )

        date_str = timezone.localdate().strftime("%Y%m%d")
        base_name = "Modele_Import_Medicaments" if is_template else f"Catalogue_Medicaments_Pharmacie_{date_str}"

        if fmt == "csv":
            data = build_csv_bytes(headers, rows)
            response = HttpResponse(data, content_type="text/csv; charset=utf-8")
            response["Content-Disposition"] = f'attachment; filename="{base_name}.csv"'
            return response

        data = build_xlsx_bytes("Medicaments_Pharmacie", headers, rows)
        response = HttpResponse(
            data,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{base_name}.xlsx"'
        return response


class ImportMedicamentsExcelView(LoginRequiredMixin, View):
    """
    POST /pharmacie/import/excel/
    Importe une liste de médicaments (et leurs lots initiaux optionnels) depuis un fichier Excel (.xlsx ou .csv).
    """

    def post(self, request: HttpRequest) -> HttpResponse:
        uploaded = request.FILES.get("excel_file")
        if not uploaded:
            messages.error(request, "Veuillez sélectionner un fichier Excel (.xlsx ou .csv) à importer.")
            return redirect("/pharmacie/?tab=catalogue")

        try:
            raw_bytes = uploaded.read()
            records = parse_excel_or_csv_bytes(raw_bytes, filename=uploaded.name)
            if not records:
                messages.error(
                    request,
                    "Aucune ligne valide détectée dans le fichier Excel. Vérifiez la ligne d'en-tête.",
                )
                return redirect("/pharmacie/?tab=catalogue")

            nb_crees = 0
            nb_maj = 0
            nb_lots = 0
            valid_cats = {c[0] for c in CategorieProduitChoices.choices}

            for idx, rec in enumerate(records, start=1):
                nom_comm = first_non_empty(
                    rec,
                    ["nom_commercial", "nom", "designation", "medicament", "produit", "libelle"],
                )
                dci = first_non_empty(rec, ["dci", "substance_active", "molecule"], default=nom_comm)
                if not nom_comm and not dci:
                    continue
                if not nom_comm:
                    nom_comm = dci

                code_cip = first_non_empty(
                    rec,
                    ["code_cip_ean13", "code_cip", "ean13", "code_barres", "cip", "code"],
                )
                if not code_cip:
                    code_cip = f"3400999{idx:06d}"[:20]

                dosage = first_non_empty(rec, ["dosage", "concentration", "force"], default="Standard")
                forme = first_non_empty(
                    rec, ["forme_galenique", "forme", "presentation"], default="Boîte / Unité"
                )
                classe_ther = first_non_empty(rec, ["classe_therapeutique", "classe", "atc"], default="")
                cat_raw = first_non_empty(
                    rec, ["categorie", "type"], default=CategorieProduitChoices.MEDICAMENT_REMBOURSABLE
                ).upper()
                categorie = (
                    cat_raw
                    if cat_raw in valid_cats
                    else CategorieProduitChoices.MEDICAMENT_REMBOURSABLE
                )

                def _to_dec(val_str: str, fallback: str = "0.00") -> Decimal:
                    try:
                        clean = (val_str or "").replace(" ", "").replace(",", ".").replace("€", "").replace("DA", "")
                        return Decimal(clean) if clean else Decimal(fallback)
                    except Exception:
                        return Decimal(fallback)

                def _to_int(val_str: str, fallback: int = 0) -> int:
                    try:
                        clean = (val_str or "").split(".")[0].split(",")[0].strip()
                        return max(0, int(clean)) if clean else fallback
                    except Exception:
                        return fallback

                prix_achat = _to_dec(first_non_empty(rec, ["prix_achat_ht", "prix_achat", "pa_ht"], "10.00"), "10.00")
                pmp_ht = _to_dec(first_non_empty(rec, ["pmp_ht", "pmp"], str(prix_achat)), str(prix_achat))
                prix_vente = _to_dec(first_non_empty(rec, ["prix_vente_ttc", "prix_vente", "ppa"], "0.00"), "0.00")
                taux_tva = _to_dec(first_non_empty(rec, ["taux_tva", "tva"], "9.00"), "9.00")

                stock_min = _to_int(first_non_empty(rec, ["stock_minimum", "seuil_alerte", "stock_min"], "20"), 20)
                stock_sec = _to_int(first_non_empty(rec, ["stock_securite", "stock_sec"], "10"), 10)
                stock_max = _to_int(first_non_empty(rec, ["stock_maximum", "stock_max"], "100"), 100)
                rayon = first_non_empty(
                    rec,
                    ["rayon_emplacement", "rayon_par_defaut", "emplacement", "rayon"],
                    default="Armoire Pharmacie Centrale - A1",
                )
                fournisseur_nom = first_non_empty(rec, ["fournisseur", "laboratoire", "grossiste"], default="")
                fournisseur_obj = None
                if fournisseur_nom:
                    fournisseur_obj, _ = Fournisseur.objects.get_or_create(nom=fournisseur_nom[:150])

                produit, created = ProduitPharmaceutique.objects.update_or_create(
                    code_cip_ean13=code_cip[:20],
                    defaults={
                        "nom_commercial": nom_comm[:200],
                        "dci": dci[:200],
                        "dosage": dosage[:100],
                        "forme_galenique": forme[:100],
                        "classe_therapeutique": classe_ther[:150],
                        "categorie": categorie,
                        "fournisseur_prefere": fournisseur_obj,
                        "prix_achat_ht": prix_achat,
                        "prix_moyen_pondere_ht": pmp_ht,
                        "prix_vente_ttc": prix_vente,
                        "taux_tva": taux_tva,
                        "stock_minimum": stock_min,
                        "stock_securite": stock_sec,
                        "stock_maximum": max(stock_max, stock_min + 10),
                        "rayon_par_defaut": rayon[:100],
                    },
                )
                if created:
                    nb_crees += 1
                else:
                    nb_maj += 1

                # Si le fichier Excel contient aussi un stock/lot initial, on crée/met à jour le LotStock FEFO
                qte_lot = _to_int(
                    first_non_empty(
                        rec,
                        [
                            "stock_actuel_fefo",
                            "quantite_lot_initial",
                            "quantite_lot",
                            "stock_initial",
                            "quantite_disponible",
                            "quantite",
                            "stock",
                        ],
                        "0",
                    ),
                    0,
                )
                num_lot = first_non_empty(
                    rec,
                    ["numero_lot_initial", "numero_lot", "lot"],
                    default=f"LOT-IMP-{timezone.localdate().strftime('%Y')}-{idx:03d}",
                )
                date_peremp = parse_flexible_date(
                    first_non_empty(rec, ["date_peremption_lot", "date_peremption", "peremption", "expiration"]),
                    default_date=timezone.localdate() + timezone.timedelta(days=365),
                )
                if qte_lot > 0 and num_lot:
                    lot_obj, lot_created = LotStock.objects.update_or_create(
                        produit=produit,
                        numero_lot=num_lot[:80],
                        defaults={
                            "date_peremption": date_peremp,
                            "quantite_disponible": qte_lot,
                            "emplacement_physique": rayon[:120],
                            "statut": StatutLotChoices.ACTIF,
                        },
                    )
                    lot_obj.actualiser_statut_peremption(save=True)
                    if lot_created:
                        MouvementStock.objects.create(
                            lot=lot_obj,
                            produit=produit,
                            type_mouvement=TypeMouvementStockChoices.ENTREE_ACHAT,
                            quantite=qte_lot,
                            stock_lot_avant=0,
                            stock_lot_apres=qte_lot,
                            prix_unitaire_ht=prix_achat,
                            utilisateur=request.user if request.user.is_authenticated else None,
                            motif_reference=f"Importation Excel Catalogue ({uploaded.name})",
                        )
                    nb_lots += 1

            messages.success(
                request,
                f"Importation Excel Médicaments réussie ({uploaded.name}) : "
                f"{nb_crees} créé(s), {nb_maj} mis à jour, {nb_lots} lot(s) FEFO initialisé(s).",
            )
        except Exception as exc:
            messages.error(request, f"Erreur lors de l'importation Excel des médicaments : {exc}")
        return redirect("/pharmacie/?tab=catalogue")

