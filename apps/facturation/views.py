"""
Vues et Contrôleurs du module de Facturation Hospitalière Algérienne :
- Tableau de bord Facturation, NGAP, Tiers-Payant (CNAS/CASNOS) & Fiscalité DGI (NIF, NIS, RC, AI)
- Ajout d'actes NGAP (avec rétrocession praticien) et de médicaments au PPA (avec déstockage FEFO)
- Validation séquentielle chronologique sans rupture (Décret exécutif n° 05-468)
- Encaissement avec calcul automatique du Droit de Timbre algérien (Espèces vs CIB/Edahabia)
- Génération des Bordereaux d'envoi CNAS/CASNOS et impression de Facture Réglementaire Algérienne
"""

from decimal import Decimal
from typing import Any, Dict

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import DetailView, TemplateView

from apps.core.models import Hospitalization, Patient, UserRole
from apps.facturation.models import (
    ActeMedicalNGAP,
    BordereauTiersPayant,
    ConventionPriseEnCharge,
    EtablissementFiscal,
    FacturePatient,
    LigneFactureActe,
    ModePaiementAlgerieChoices,
    OrganismeTiersPayant,
    StatutFactureChoices,
    TypePriseEnChargeFactureChoices,
)
from apps.facturation.services import (
    ajouter_acte_ngap_a_facture,
    ajouter_medicament_ppa_a_facture,
    calculer_droit_timbre_algerie,
    enregistrer_paiement_patient,
    generer_bordereau_tiers_payant,
    initialiser_donnees_demo_facturation_algerie,
    valider_et_numeroter_facture,
)
from apps.pharmacie.models import ProduitPharmaceutique

FACTURATION_ROLE_BADGES = {
    "ADMIN": {"badge_class": "bg-purple-100 text-purple-800 border-purple-300"},
    "MEDECIN": {"badge_class": "bg-sky-100 text-sky-800 border-sky-300"},
    "CHIRURGIEN": {"badge_class": "bg-indigo-100 text-indigo-800 border-indigo-300"},
    "INFIRMIER": {"badge_class": "bg-emerald-100 text-emerald-800 border-emerald-300"},
    "SAGE_FEMME": {"badge_class": "bg-pink-100 text-pink-800 border-pink-300"},
    "SECRETAIRE": {"badge_class": "bg-amber-100 text-amber-800 border-amber-300"},
    "GESTIONNAIRE_ADMISSION": {"badge_class": "bg-teal-100 text-teal-800 border-teal-300"},
}


class FacturationAlgerieDashboardView(LoginRequiredMixin, TemplateView):
    """
    Cockpit Principal de Facturation Hospitalière Algérienne :
    1. Factures Patients (Actes NGAP + Médicaments au PPA liés au stock FEFO + Validation + Paiement CIB/Edahabia/Espèces)
    2. Nomenclature NGAP Algérienne (C, CS, K, KC, Z, B, AMI, SF) & Rétrocession d'Honoraires aux Praticiens
    3. Tiers-Payant (CNAS, CASNOS, Mutuelles, Assurances) & Bordereaux de Remboursement Caisses
    4. Identité Fiscale DGI (NIF, NIS, RC, AI, TVA 9%/19%, Barème du Droit de Timbre)
    """

    template_name = "facturation/dashboard_facturation.html"

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)
        initialiser_donnees_demo_facturation_algerie(utilisateur=self.request.user)

        active_tab = self.request.GET.get("tab", "factures").strip()
        etablissement = EtablissementFiscal.objects.first()

        factures = list(
            FacturePatient.objects.select_related(
                "patient",
                "hospitalisation",
                "convention__organisme",
                "bordereau",
                "cree_par",
            )
            .prefetch_related(
                "lignes_actes__acte",
                "lignes_actes__praticien_executant",
                "lignes_pharmacie__produit",
                "lignes_pharmacie__lot_sorti",
                "paiements",
            )
            .all()
        )

        # KPIs Financiers & Fiscaux en Dinars Algériens (DA)
        ca_total_ttc_da = sum((f.montant_total_ttc_da for f in factures), Decimal("0.00")).quantize(
            Decimal("0.01")
        )
        total_tva_9_da = sum((f.montant_tva_9_da for f in factures), Decimal("0.00")).quantize(
            Decimal("0.01")
        )
        total_tva_19_da = sum((f.montant_tva_19_da for f in factures), Decimal("0.00")).quantize(
            Decimal("0.01")
        )
        total_part_caisses_da = sum(
            (f.part_organisme_tiers_payant_da for f in factures), Decimal("0.00")
        ).quantize(Decimal("0.01"))
        total_part_patients_da = sum(
            (f.part_patient_ticket_moderateur_da for f in factures), Decimal("0.00")
        ).quantize(Decimal("0.01"))
        total_timbre_da = sum((f.droit_timbre_da for f in factures), Decimal("0.00")).quantize(
            Decimal("0.01")
        )
        total_retrocession_medecins_da = sum(
            (f.total_retrocession_praticiens_da for f in factures), Decimal("0.00")
        ).quantize(Decimal("0.01"))
        total_quote_clinique_da = sum(
            (f.total_quote_part_clinique_da for f in factures), Decimal("0.00")
        ).quantize(Decimal("0.01"))

        User = get_user_model()
        praticiens = User.objects.filter(
            role__in=[UserRole.MEDECIN, UserRole.CHIRURGIEN, UserRole.SAGE_FEMME, UserRole.ADMIN]
        )

        lignes_retrocession = (
            LigneFactureActe.objects.select_related("facture__patient", "acte", "praticien_executant")
            .order_by("-created_at")[:50]
        )

        user_role = getattr(self.request.user, "role", "ADMIN")
        role_config = FACTURATION_ROLE_BADGES.get(
            user_role,
            {"badge_class": "bg-slate-100 text-slate-800 border-slate-300"},
        )

        context.update(
            {
                "role_config": role_config,
                "active_tab": active_tab,
                "etablissement": etablissement,
                # KPIs en Dinars Algériens (DA)
                "ca_total_ttc_da": ca_total_ttc_da,
                "total_tva_9_da": total_tva_9_da,
                "total_tva_19_da": total_tva_19_da,
                "total_part_caisses_da": total_part_caisses_da,
                "total_part_patients_da": total_part_patients_da,
                "total_timbre_da": total_timbre_da,
                "total_retrocession_medecins_da": total_retrocession_medecins_da,
                "total_quote_clinique_da": total_quote_clinique_da,
                # Données métiers
                "factures": factures,
                "actes_ngap": ActeMedicalNGAP.objects.all(),
                "produits_pharmacie": ProduitPharmaceutique.objects.all(),
                "organismes": OrganismeTiersPayant.objects.filter(est_actif=True),
                "conventions": ConventionPriseEnCharge.objects.select_related("patient", "organisme").all(),
                "bordereaux": BordereauTiersPayant.objects.select_related("organisme").prefetch_related("factures").all(),
                "patients": Patient.objects.all(),
                "hospitalisations": Hospitalization.objects.select_related("patient", "bed").all(),
                "praticiens": praticiens,
                "lignes_retrocession": lignes_retrocession,
                "modes_paiement": ModePaiementAlgerieChoices.choices,
                "types_pec": TypePriseEnChargeFactureChoices.choices,
            }
        )
        return context


class CreerFacturePatientView(LoginRequiredMixin, View):
    """POST /facturation/factures/create/ — Crée un nouveau dossier de facturation patient."""

    def post(self, request: HttpRequest) -> HttpResponse:
        try:
            import uuid

            patient_id = int(request.POST.get("patient_id", 0))
            hosp_id = request.POST.get("hospitalisation_id", "").strip()
            conv_id = request.POST.get("convention_id", "").strip()
            type_pec = request.POST.get(
                "type_prise_en_charge",
                TypePriseEnChargeFactureChoices.HOSPITALISATION_SEJOUR,
            )

            patient = get_object_or_404(Patient, pk=patient_id)
            hosp = Hospitalization.objects.filter(pk=int(hosp_id)).first() if hosp_id else None
            conv = ConventionPriseEnCharge.objects.filter(pk=int(conv_id)).first() if conv_id else None

            num_temp = f"BROUILLON-{uuid.uuid4().hex[:6].upper()}"
            facture = FacturePatient.objects.create(
                numero_facture=num_temp,
                patient=patient,
                hospitalisation=hosp,
                convention=conv,
                type_prise_en_charge=type_pec,
                cree_par=request.user,
            )
            messages.success(
                request,
                f"Facture brouillon {facture.numero_facture} ouverte pour {patient.full_name}. "
                f"Ajoutez les actes NGAP et les consommations pharmacie au PPA.",
            )
        except Exception as exc:
            messages.error(request, f"Erreur lors de la création de la facture : {exc}")
        return redirect("/facturation/?tab=factures")


class AjouterActeNGAPFactureView(LoginRequiredMixin, View):
    """POST /facturation/factures/<int:facture_id>/add-acte/ — Ajoute un acte NGAP ou forfait."""

    def post(self, request: HttpRequest, facture_id: int) -> HttpResponse:
        try:
            acte_id = int(request.POST.get("acte_id", 0))
            quantite = int(request.POST.get("quantite", 1) or 1)
            praticien_id_str = request.POST.get("praticien_id", "").strip()
            prix_perso_str = request.POST.get("prix_unitaire_ht", "").strip()

            praticien_id = int(praticien_id_str) if praticien_id_str else None
            prix_perso = (
                Decimal(prix_perso_str.replace(",", "."))
                if prix_perso_str
                else None
            )

            ligne = ajouter_acte_ngap_a_facture(
                facture_id=facture_id,
                acte_id=acte_id,
                quantite=quantite,
                praticien_id=praticien_id,
                prix_unitaire_ht_personnalise=prix_perso,
            )
            messages.success(
                request,
                f"Acte [{ligne.acte.code_ngap}] « {ligne.acte.libelle} » ajouté "
                f"(TTC : {ligne.montant_ttc_da} DA | Part Caisse : {ligne.part_organisme_da} DA | "
                f"Ticket Modérateur : {ligne.part_patient_da} DA | Rétrocession Médecin : {ligne.montant_retrocession_praticien_da} DA).",
            )
        except Exception as exc:
            messages.error(request, f"Impossible d'ajouter l'acte NGAP : {exc}")
        return redirect("/facturation/?tab=factures")


class AjouterMedicamentPPAFactureView(LoginRequiredMixin, View):
    """
    POST /facturation/factures/<int:facture_id>/add-pharma/
    Ajoute un médicament au tarif PPA et déclenche automatiquement le déstockage FEFO dans la Pharmacie.
    """

    def post(self, request: HttpRequest, facture_id: int) -> HttpResponse:
        try:
            produit_id = int(request.POST.get("produit_id", 0))
            quantite = int(request.POST.get("quantite", 1) or 1)
            ppa_str = request.POST.get("tarif_ppa_unitaire_ht_da", "").strip()
            ppa_val = Decimal(ppa_str.replace(",", ".")) if ppa_str else None

            ligne = ajouter_medicament_ppa_a_facture(
                facture_id=facture_id,
                produit_id=produit_id,
                quantite=quantite,
                utilisateur=request.user,
                tarif_ppa_unitaire_ht_da=ppa_val,
            )
            lot_code = ligne.lot_sorti.numero_lot if ligne.lot_sorti else "FEFO"
            messages.success(
                request,
                f"Consommation Pharmacie ajoutée et déstockée en FEFO (Lot {lot_code}) : "
                f"{ligne.produit.nom_commercial} x{ligne.quantite} au PPA ({ligne.montant_ttc_da} DA TTC).",
            )
        except (ValidationError, Exception) as exc:
            messages.error(request, f"Erreur lors du déstockage FEFO / Facturation PPA : {exc}")
        return redirect("/facturation/?tab=factures")


class ValiderFactureSequentielleView(LoginRequiredMixin, View):
    """
    POST /facturation/factures/<int:facture_id>/validate/
    Attribue le numéro séquentiel chronologique sans rupture (FAC-2026-XXXXXX).
    """

    def post(self, request: HttpRequest, facture_id: int) -> HttpResponse:
        try:
            facture = valider_et_numeroter_facture(facture_id)
            messages.success(
                request,
                f"Facture validée et numérotée sans rupture : {facture.numero_facture} "
                f"(Arrêtée à : {facture.montant_en_toutes_lettres}).",
            )
        except Exception as exc:
            messages.error(request, f"Erreur de validation séquentielle : {exc}")
        return redirect("/facturation/?tab=factures")


class EnregistrerPaiementFactureView(LoginRequiredMixin, View):
    """
    POST /facturation/factures/<int:facture_id>/pay/
    Enregistre le règlement patient et calcule automatiquement le Droit de Timbre algérien
    uniquement en cas de paiement en espèces (0 DA si CIB / Edahabia / Chèque / Virement).
    """

    def post(self, request: HttpRequest, facture_id: int) -> HttpResponse:
        try:
            mode_paiement = request.POST.get("mode_paiement", ModePaiementAlgerieChoices.CARTE_CIB)
            montant_str = request.POST.get("montant_hors_timbre_da", "0").strip()
            reference = request.POST.get("reference_transaction", "").strip()
            montant = Decimal(montant_str.replace(",", "."))

            paiement = enregistrer_paiement_patient(
                facture_id=facture_id,
                mode_paiement=mode_paiement,
                montant_hors_timbre_da=montant,
                utilisateur=request.user,
                reference_transaction=reference,
            )
            if paiement.droit_timbre_da > Decimal("0.00"):
                info_timbre = f"Droit de Timbre Espèces appliqué : +{paiement.droit_timbre_da} DA"
            else:
                info_timbre = "Exonéré de Droit de Timbre (0,00 DA — Paiement électronique/scriptural)"

            messages.success(
                request,
                f"Encaissement validé sur {paiement.facture.numero_facture} ({paiement.get_mode_paiement_display()}) : "
                f"Total perçu {paiement.montant_total_percu_da} DA ({info_timbre}).",
            )
        except Exception as exc:
            messages.error(request, f"Erreur lors de l'encaissement : {exc}")
        return redirect("/facturation/?tab=factures")


class CreerConventionPatientView(LoginRequiredMixin, View):
    """POST /facturation/conventions/create/ — Enregistre une prise en charge CNAS/CASNOS/Mutuelle."""

    def post(self, request: HttpRequest) -> HttpResponse:
        try:
            patient_id = int(request.POST.get("patient_id", 0))
            organisme_id = int(request.POST.get("organisme_id", 0))
            num_assure = request.POST.get("numero_immatriculation_assure", "").strip()
            num_pec = request.POST.get("numero_accord_pec", "").strip()
            taux_str = request.POST.get("taux_prise_en_charge_pct", "80").strip()

            conv = ConventionPriseEnCharge.objects.create(
                patient_id=patient_id,
                organisme_id=organisme_id,
                numero_immatriculation_assure=num_assure,
                numero_accord_pec=num_pec,
                taux_prise_en_charge_pct=Decimal(taux_str.replace(",", ".")),
            )
            messages.success(
                request,
                f"Convention Tiers-Payant enregistrée pour {conv.patient.full_name} auprès de {conv.organisme.nom} ({conv.taux_prise_en_charge_pct}%).",
            )
        except Exception as exc:
            messages.error(request, f"Erreur de création de convention : {exc}")
        return redirect("/facturation/?tab=tiers_payant")


class GenererBordereauTiersPayantView(LoginRequiredMixin, View):
    """POST /facturation/bordereaux/generate/ — Génère un Bordereau d'envoi CNAS/CASNOS."""

    def post(self, request: HttpRequest) -> HttpResponse:
        try:
            organisme_id = int(request.POST.get("organisme_id", 0))
            bordereau = generer_bordereau_tiers_payant(
                organisme_id=organisme_id,
                utilisateur=request.user,
            )
            messages.success(
                request,
                f"Bordereau d'envoi {bordereau.numero_bordereau} généré pour {bordereau.organisme.nom} : "
                f"{bordereau.nombre_factures} dossier(s) pour un montant Tiers-Payant de {bordereau.montant_total_tiers_payant_da} DA.",
            )
        except Exception as exc:
            messages.error(request, f"Impossible de générer le bordereau : {exc}")
        return redirect("/facturation/?tab=tiers_payant")


class FactureOfficielleAlgeriePrintView(LoginRequiredMixin, DetailView):
    """
    GET /facturation/factures/<int:pk>/imprimer/
    Affiche la Facture Réglementaire Algérienne prête à imprimer (ou exporter en PDF)
    avec toutes les mentions obligatoires (NIF, NIS, RC, AI, TVA 9%/19%, Timbre, NGAP, PPA,
    Tiers-Payant CNAS/CASNOS vs Ticket Modérateur, Arrêté en toutes lettres et Cachet).
    """

    model = FacturePatient
    template_name = "facturation/facture_print_algerie.html"
    context_object_name = "facture"

    def get_context_data(self, **kwargs: Any) -> Dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["etablissement"] = EtablissementFiscal.objects.first()
        context["timbre_simulation_especes"] = calculer_droit_timbre_algerie(
            self.object.part_patient_ticket_moderateur_da,
            ModePaiementAlgerieChoices.ESPECES,
        )
        return context


@login_required
def api_simuler_droit_timbre(request: HttpRequest) -> JsonResponse:
    """
    GET /facturation/api/simuler-timbre/?montant=45000&mode=ESPECES
    Simule en temps réel le Droit de Timbre algérien et le Net à Payer TTC.
    """
    try:
        montant = Decimal(request.GET.get("montant", "0").replace(",", "."))
    except Exception:
        montant = Decimal("0.00")
    mode = request.GET.get("mode", ModePaiementAlgerieChoices.CARTE_CIB)
    timbre = calculer_droit_timbre_algerie(montant, mode)
    total = (montant + timbre).quantize(Decimal("0.01"))
    return JsonResponse(
        {
            "montant_hors_timbre_da": str(montant.quantize(Decimal("0.01"))),
            "mode_paiement": mode,
            "droit_timbre_da": str(timbre),
            "net_a_payer_da": str(total),
            "exonere": timbre == Decimal("0.00"),
        }
    )
