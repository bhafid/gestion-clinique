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
    BaseCalculRemboursementChoices,
    BordereauTiersPayant,
    ConventionPriseEnCharge,
    EtablissementFiscal,
    FacturePatient,
    LettreCleNGAPChoices,
    LigneFactureActe,
    ModePaiementAlgerieChoices,
    OrganismeTiersPayant,
    StatutFactureChoices,
    TauxTVAAlgerieChoices,
    TypeActeFacturableChoices,
    TypeEtablissementSanteChoices,
    TypeOrganismePayeurChoices,
    TypePriseEnChargeFactureChoices,
)
from apps.facturation.services import (
    ajouter_acte_ngap_a_facture,
    ajouter_medicament_ppa_a_facture,
    calculer_droit_timbre_algerie,
    enregistrer_paiement_patient,
    generer_bordereau_tiers_payant,
    imputer_consommation_medicament_malade,
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
    "GESTIONNAIRE_PHARMACIE": {"badge_class": "bg-teal-100 text-teal-800 border-teal-300"},
    "GESTIONNAIRE_FACTURATION": {"badge_class": "bg-emerald-100 text-emerald-800 border-emerald-300"},
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
                # Choix pour les formulaires de Paramétrage Facturation
                "types_etablissement": TypeEtablissementSanteChoices.choices,
                "lettres_cles_ngap": LettreCleNGAPChoices.choices,
                "types_acte_facturable": TypeActeFacturableChoices.choices,
                "taux_tva_choices": TauxTVAAlgerieChoices.choices,
                "types_organisme": TypeOrganismePayeurChoices.choices,
                "bases_calcul_remboursement": BaseCalculRemboursementChoices.choices,
                "preselected_patient_id": self.request.GET.get("patient_id", ""),
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


class ImputerConsommationMaladeView(LoginRequiredMixin, View):
    """
    POST /facturation/consommation-malade/
    Enregistre une consommation de médicament pour un malade et la reporte automatiquement
    sur sa facture ouverte (ou crée une nouvelle facture brouillon pour ce malade) avec
    déstockage FEFO automatique dans la Pharmacie.
    """

    def post(self, request: HttpRequest) -> HttpResponse:
        try:
            patient_id = int(request.POST.get("patient_id", 0))
            produit_id = int(request.POST.get("produit_id", 0))
            quantite = int(request.POST.get("quantite", 1) or 1)
            facture_id_str = request.POST.get("facture_id", "").strip()
            facture_id = int(facture_id_str) if facture_id_str else None
            ppa_str = request.POST.get("tarif_ppa_unitaire_ht_da", "").strip()
            ppa_val = Decimal(ppa_str.replace(",", ".")) if ppa_str else None

            facture, ligne_pharma, facture_creee = imputer_consommation_medicament_malade(
                patient_id=patient_id,
                produit_id=produit_id,
                quantite=quantite,
                utilisateur=request.user,
                facture_id=facture_id,
                tarif_ppa_unitaire_ht_da=ppa_val,
            )
            lot_code = ligne_pharma.lot_sorti.numero_lot if ligne_pharma.lot_sorti else "FEFO"
            info_fac = "Nouvelle facture ouverte automatiquement" if facture_creee else "Reporté sur facture existante"
            messages.success(
                request,
                f"Consommation médicament reportée sur la facture {facture.numero_facture} ({info_fac}) "
                f"du malade {facture.patient.full_name} : {ligne_pharma.quantite} x {ligne_pharma.produit.nom_commercial} "
                f"(Lot FEFO déstocké : {lot_code}) — Ligne TTC : {ligne_pharma.montant_ttc_da} DA "
                f"(Part Caisse : {ligne_pharma.part_organisme_da} DA | Part Patient : {ligne_pharma.part_patient_da} DA).",
            )
        except Exception as exc:
            messages.error(request, f"Erreur lors de l'imputation du médicament au malade : {exc}")
        return redirect("/facturation/?tab=factures")


class ParametrageFiscalUpdateView(LoginRequiredMixin, View):
    """
    POST /facturation/settings/fiscal/
    Met à jour le paramétrage légal et fiscal de l'établissement (Raison sociale, Régime,
    NIF, NIS, N° RC, Article d'Imposition AI, RIB/RIP, N° Convention CNAS, Exercice fiscal).
    """

    def post(self, request: HttpRequest) -> HttpResponse:
        try:
            etab = EtablissementFiscal.objects.first()
            if not etab:
                etab = EtablissementFiscal()

            if "nom_clinique" in request.POST:
                etab.nom_clinique = request.POST.get("nom_clinique", etab.nom_clinique).strip()
            etab.raison_sociale = request.POST.get("raison_sociale", etab.raison_sociale).strip()
            etab.type_etablissement = request.POST.get("type_etablissement", etab.type_etablissement).strip()
            etab.forme_juridique = request.POST.get("forme_juridique", etab.forme_juridique).strip()
            etab.adresse_complete = request.POST.get("adresse_complete", etab.adresse_complete).strip()
            etab.wilaya = request.POST.get("wilaya", etab.wilaya).strip()
            etab.telephone = request.POST.get("telephone", etab.telephone).strip()
            if "email" in request.POST:
                etab.email = request.POST.get("email", etab.email).strip()
            if "site_web" in request.POST:
                etab.site_web = request.POST.get("site_web", etab.site_web).strip()
            if "directeur_etablissement" in request.POST:
                etab.directeur_etablissement = request.POST.get(
                    "directeur_etablissement", etab.directeur_etablissement
                ).strip()
            etab.nif = request.POST.get("nif", etab.nif).strip()
            etab.nis = request.POST.get("nis", etab.nis).strip()
            etab.rc = request.POST.get("rc", etab.rc).strip()
            etab.article_imposition = request.POST.get("article_imposition", etab.article_imposition).strip()
            etab.rib_bancaire = request.POST.get("rib_bancaire", etab.rib_bancaire).strip()
            etab.numero_convention_cnas = request.POST.get(
                "numero_convention_cnas", etab.numero_convention_cnas
            ).strip()
            exo_str = request.POST.get("exercice_fiscal_courant", "").strip()
            if exo_str.isdigit():
                etab.exercice_fiscal_courant = int(exo_str)

            etab.save()
            messages.success(
                request,
                f"Paramétrage fiscal mis à jour : {etab.raison_sociale} (NIF : {etab.nif} | NIS : {etab.nis} | RC : {etab.rc} | AI : {etab.article_imposition}).",
            )
        except Exception as exc:
            messages.error(request, f"Erreur lors de la sauvegarde du paramétrage fiscal : {exc}")
        return redirect("/facturation/?tab=fiscalite_dz")


class ParametrageActeNGAPSaveView(LoginRequiredMixin, View):
    """
    POST /facturation/settings/ngap-save/
    Crée ou met à jour un acte médical/chirurgical NGAP ou forfait clinique
    (Code NGAP, Libellé, Lettre-clé, Coefficient, Tarif CNAS, Tarif Clinique HT, TVA, % Rétrocession praticien).
    """

    def post(self, request: HttpRequest) -> HttpResponse:
        try:
            code_ngap = request.POST.get("code_ngap", "").strip().upper()
            if not code_ngap:
                raise ValidationError("Le code NGAP est obligatoire.")
            libelle = request.POST.get("libelle", "").strip()
            type_acte = request.POST.get("type_acte", TypeActeFacturableChoices.ACTE_NGAP).strip()
            lettre_cle = request.POST.get("lettre_cle", LettreCleNGAPChoices.K).strip()
            coefficient = Decimal(request.POST.get("coefficient", "1").replace(",", ".") or "1")
            valeur_cle_cnas = Decimal(
                request.POST.get("valeur_lettre_cle_cnas_da", "100").replace(",", ".") or "100"
            )
            tarif_ref_str = request.POST.get("tarif_reference_cnas_da", "").strip()
            tarif_ref_cnas = (
                Decimal(tarif_ref_str.replace(",", "."))
                if tarif_ref_str
                else (coefficient * valeur_cle_cnas).quantize(Decimal("0.01"))
            )
            tarif_clinique_ht = Decimal(
                request.POST.get("tarif_clinique_ht_da", "0").replace(",", ".") or "0"
            )
            taux_tva = Decimal(request.POST.get("taux_tva", "9.00").replace(",", ".") or "9.00")
            taux_retro = Decimal(
                request.POST.get("taux_retrocession_praticien_defaut", "70.00").replace(",", ".") or "70.00"
            )
            est_remboursable = request.POST.get("est_remboursable_cnas", "1") == "1"

            acte, created = ActeMedicalNGAP.objects.update_or_create(
                code_ngap=code_ngap,
                defaults={
                    "libelle": libelle,
                    "type_acte": type_acte,
                    "lettre_cle": lettre_cle,
                    "coefficient": coefficient,
                    "valeur_lettre_cle_cnas_da": valeur_cle_cnas,
                    "tarif_reference_cnas_da": tarif_ref_cnas,
                    "tarif_clinique_ht_da": tarif_clinique_ht,
                    "taux_tva": taux_tva,
                    "taux_retrocession_praticien_defaut": taux_retro,
                    "est_remboursable_cnas": est_remboursable,
                },
            )
            action_lbl = "créé" if created else "mis à jour"
            messages.success(
                request,
                f"Paramétrage NGAP [{acte.code_ngap}] « {acte.libelle} » {action_lbl} : "
                f"{acte.tarif_clinique_ht_da} DA HT (TVA {acte.taux_tva}%, Rétrocession praticien {acte.taux_retrocession_praticien_defaut}%).",
            )
        except Exception as exc:
            messages.error(request, f"Erreur de paramétrage NGAP : {exc}")
        return redirect("/facturation/?tab=ngap_retro")


class ParametrageOrganismeSaveView(LoginRequiredMixin, View):
    """
    POST /facturation/settings/organisme-save/
    Crée ou met à jour un organisme de Tiers-Payant (CNAS, CASNOS, Mutuelle, Assurance, Entreprise).
    """

    def post(self, request: HttpRequest) -> HttpResponse:
        try:
            code_org = request.POST.get("code_organisme", "").strip().upper()
            if not code_org:
                raise ValidationError("Le code organisme est obligatoire.")
            nom = request.POST.get("nom", "").strip()
            type_org = request.POST.get("type_organisme", TypeOrganismePayeurChoices.CNAS).strip()
            taux_defaut = Decimal(
                request.POST.get("taux_couverture_defaut_pct", "80.00").replace(",", ".") or "80.00"
            )
            base_calcul = request.POST.get(
                "base_calcul", BaseCalculRemboursementChoices.SUR_TARIF_REFERENCE_CNAS
            ).strip()
            adresse = request.POST.get("adresse_centre_paiement", "").strip()

            org, created = OrganismeTiersPayant.objects.update_or_create(
                code_organisme=code_org,
                defaults={
                    "nom": nom,
                    "type_organisme": type_org,
                    "taux_couverture_defaut_pct": taux_defaut,
                    "base_calcul": base_calcul,
                    "adresse_centre_paiement": adresse,
                    "est_actif": True,
                },
            )
            action_lbl = "ajouté" if created else "mis à jour"
            messages.success(
                request,
                f"Organisme Tiers-Payant [{org.code_organisme}] {org.nom} {action_lbl} (Couverture défaut : {org.taux_couverture_defaut_pct}%).",
            )
        except Exception as exc:
            messages.error(request, f"Erreur de paramétrage organisme Tiers-Payant : {exc}")
        return redirect("/facturation/?tab=tiers_payant")

