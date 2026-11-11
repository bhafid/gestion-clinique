"""
Tests unitaires et réglementaires du module de Facturation Hospitalière Algérienne :
- Barème légal du Droit de Timbre algérien (Espèces vs exonération CIB / Edahabia / Chèque / Virement)
- Tarification NGAP (lettres-clés C, K, Z, B, AMI, SF), TVA 0% / 9% / 19% et Rétrocession Praticien
- Consommation Pharmacie au PPA avec déstockage automatique FEFO
- Ventilation Tiers-Payant CNAS (80%) vs Ticket Modérateur Patient + Dépassement
- Numérotation séquentielle sans rupture (Décret exécutif n° 05-468) et Bordereaux CNAS
"""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Patient, UserRole
from apps.facturation.models import (
    ActeMedicalNGAP,
    BaseCalculRemboursementChoices,
    ConventionPriseEnCharge,
    EtablissementFiscal,
    FacturePatient,
    LettreCleNGAPChoices,
    ModePaiementAlgerieChoices,
    OrganismeTiersPayant,
    StatutFactureChoices,
    TypeActeFacturableChoices,
    TypeOrganismePayeurChoices,
)
from apps.facturation.services import (
    ajouter_acte_ngap_a_facture,
    ajouter_medicament_ppa_a_facture,
    calculer_droit_timbre_algerie,
    enregistrer_paiement_patient,
    generer_bordereau_tiers_payant,
    valider_et_numeroter_facture,
)
from apps.pharmacie.models import (
    CategorieProduitChoices,
    LotStock,
    ProduitPharmaceutique,
    StatutLotChoices,
)

User = get_user_model()


class FacturationAlgerienneTests(TestCase):
    def setUp(self) -> None:
        self.chirurgien = User.objects.create_user(
            username="dr_chirurgien_dz",
            password="StrongPassword123!",
            first_name="Karim",
            last_name="Belkacem",
            role=UserRole.CHIRURGIEN,
        )
        self.etab = EtablissementFiscal.objects.create(
            raison_sociale="EURL CLINIQUE SIDI YAHIA 2",
            nif="002116099123456",
            nis="099916100654321",
            rc="16/00-1048291B21",
            article_imposition="16125849012",
            exercice_fiscal_courant=2026,
            dernier_numero_sequentiel=0,
        )
        self.patient = Patient.objects.create(
            nir="285037511604243",
            first_name="Meriem",
            last_name="Ziani",
            birth_date=date(1985, 3, 21),
            gender="F",
            phone="+213 551 00 11 22",
        )
        self.cnas = OrganismeTiersPayant.objects.create(
            code_organisme="CNAS-16",
            nom="CNAS Wilaya d'Alger",
            type_organisme=TypeOrganismePayeurChoices.CNAS,
            taux_couverture_defaut_pct=Decimal("80.00"),
            base_calcul=BaseCalculRemboursementChoices.SUR_TARIF_REFERENCE_CNAS,
        )
        self.convention = ConventionPriseEnCharge.objects.create(
            patient=self.patient,
            organisme=self.cnas,
            numero_immatriculation_assure="198516088312",
            numero_accord_pec="PEC-CNAS-2026-001",
            taux_prise_en_charge_pct=Decimal("80.00"),
        )

    def test_droit_timbre_algerien_especes_vs_cib_edahabia(self) -> None:
        """
        Vérifie le calcul légal du Droit de Timbre algérien :
        - 0 DA pour CIB, Edahabia, Chèque, Virement
        - 0 DA en Espèces si <= 300 DA
        - Barème progressif par tranches en Espèces (> 300 DA).
        """
        montant = Decimal("45000.00")
        self.assertEqual(
            calculer_droit_timbre_algerie(montant, ModePaiementAlgerieChoices.CARTE_CIB),
            Decimal("0.00"),
        )
        self.assertEqual(
            calculer_droit_timbre_algerie(montant, ModePaiementAlgerieChoices.CARTE_EDAHABIA),
            Decimal("0.00"),
        )
        self.assertEqual(
            calculer_droit_timbre_algerie(montant, ModePaiementAlgerieChoices.CHEQUE_BANCAIRE),
            Decimal("0.00"),
        )
        self.assertEqual(
            calculer_droit_timbre_algerie(Decimal("250.00"), ModePaiementAlgerieChoices.ESPECES),
            Decimal("0.00"),
        )
        # Pour 20 000 DA en espèces : 1% = 200 DA
        self.assertEqual(
            calculer_droit_timbre_algerie(Decimal("20000.00"), ModePaiementAlgerieChoices.ESPECES),
            Decimal("200.00"),
        )
        # Pour 45 000 DA en espèces : 300 DA (sur les premiers 30 000 DA) + 1.5% sur 15 000 DA (225 DA) = 525 DA
        self.assertEqual(
            calculer_droit_timbre_algerie(montant, ModePaiementAlgerieChoices.ESPECES),
            Decimal("525.00"),
        )

    def test_ngap_retrocession_ppa_fefo_and_tiers_payant_cnas(self) -> None:
        """
        Vérifie un cycle complet de facturation algérienne :
        - Acte NGAP K50 (TVA 9%, Rétrocession praticien 70%, Couverture CNAS 80% sur base CNAS)
        - Médicament au PPA avec déstockage FEFO automatique dans apps.pharmacie
        - Validation séquentielle sans rupture (FAC-2026-000001) et génération de bordereau CNAS.
        """
        acte_k50 = ActeMedicalNGAP.objects.create(
            code_ngap="K50-TEST",
            libelle="Appendicectomie Coelioscopique (K50)",
            type_acte=TypeActeFacturableChoices.FORFAIT_CHIRURGIE,
            lettre_cle=LettreCleNGAPChoices.K,
            coefficient=Decimal("50.00"),
            valeur_lettre_cle_cnas_da=Decimal("600.00"),
            tarif_reference_cnas_da=Decimal("30000.00"),
            tarif_clinique_ht_da=Decimal("50000.00"),
            taux_tva=Decimal("9.00"),
            taux_retrocession_praticien_defaut=Decimal("70.00"),
            est_remboursable_cnas=True,
        )

        produit = ProduitPharmaceutique.objects.create(
            code_cip_ean13="3400937777771",
            dci="Énoxaparine",
            nom_commercial="Lovenox Injectable",
            dosage="4000 UI",
            forme_galenique="Seringue",
            categorie=CategorieProduitChoices.MEDICAMENT_REMBOURSABLE,
            prix_achat_ht=Decimal("500.00"),
            prix_vente_ttc=Decimal("650.00"),
        )
        lot_fefo = LotStock.objects.create(
            produit=produit,
            numero_lot="LOT-FEFO-DZ1",
            date_peremption=timezone.localdate() + timedelta(days=120),
            quantite_disponible=10,
            statut=StatutLotChoices.ACTIF,
        )

        facture = FacturePatient.objects.create(
            numero_facture="BROUILLON-TEST-1",
            patient=self.patient,
            convention=self.convention,
            cree_par=self.chirurgien,
        )

        # 1. Ajout de l'acte K50 (HT: 50 000 DA, TVA 9%: 4 500 DA, TTC: 54 500 DA)
        # Base CNAS: 30 000 DA -> Part CNAS (80%): 24 000 DA | Part Patient: 30 500 DA
        # Rétrocession praticien (70% de 50 000 HT): 35 000 DA | Part Clinique: 15 000 DA
        l_acte = ajouter_acte_ngap_a_facture(
            facture_id=facture.id,
            acte_id=acte_k50.id,
            quantite=1,
            praticien_id=self.chirurgien.id,
        )
        self.assertEqual(l_acte.montant_ttc_da, Decimal("54500.00"))
        self.assertEqual(l_acte.part_organisme_da, Decimal("24000.00"))
        self.assertEqual(l_acte.part_patient_da, Decimal("30500.00"))
        self.assertEqual(l_acte.montant_retrocession_praticien_da, Decimal("35000.00"))
        self.assertEqual(l_acte.montant_quote_part_clinique_da, Decimal("15000.00"))

        # 2. Ajout de 2 seringues de Lovenox au PPA de 1 000 DA HT (TVA 9%) -> Déstockage FEFO
        l_pharma = ajouter_medicament_ppa_a_facture(
            facture_id=facture.id,
            produit_id=produit.id,
            quantite=2,
            utilisateur=self.chirurgien,
            tarif_ppa_unitaire_ht_da=Decimal("1000.00"),
        )
        lot_fefo.refresh_from_db()
        self.assertEqual(lot_fefo.quantite_disponible, 8)
        self.assertEqual(l_pharma.lot_sorti, lot_fefo)
        self.assertEqual(l_pharma.montant_ttc_da, Decimal("2180.00"))

        # 3. Validation séquentielle sans rupture -> FAC-2026-000001
        facture = valider_et_numeroter_facture(facture.id)
        self.assertEqual(facture.numero_facture, "FAC-2026-000001")
        self.assertEqual(facture.numero_sequentiel, 1)
        self.assertEqual(facture.statut, StatutFactureChoices.VALIDEE_EMISE)

        # Interdiction de supprimer une facture validée
        with self.assertRaises(PermissionDenied):
            facture.delete()

        # 4. Paiement en espèces du reste à charge patient -> Droit de Timbre calculé
        reste_patient = facture.part_patient_ticket_moderateur_da
        paiement = enregistrer_paiement_patient(
            facture_id=facture.id,
            mode_paiement=ModePaiementAlgerieChoices.ESPECES,
            montant_hors_timbre_da=reste_patient,
            utilisateur=self.chirurgien,
        )
        self.assertGreater(paiement.droit_timbre_da, Decimal("0.00"))
        facture.refresh_from_db()
        self.assertEqual(facture.statut, StatutFactureChoices.SOLDEE)

        # 5. Génération du Bordereau CNAS
        bordereau = generer_bordereau_tiers_payant(
            organisme_id=self.cnas.id,
            utilisateur=self.chirurgien,
        )
        self.assertEqual(bordereau.nombre_factures, 1)
        self.assertEqual(bordereau.montant_total_tiers_payant_da, facture.part_organisme_tiers_payant_da)

    def test_print_invoice_view_displays_nif_nis_rc_ai(self) -> None:
        """Vérifie que la facture imprimable affiche bien NIF, NIS, RC, AI et le numéro séquentiel."""
        facture = FacturePatient.objects.create(
            numero_facture="BROUILLON-PRINT",
            patient=self.patient,
            convention=self.convention,
        )
        valider_et_numeroter_facture(facture.id)
        self.client.force_login(self.chirurgien)
        resp = self.client.get(reverse("facturation:facture_print", kwargs={"pk": facture.id}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "002116099123456")  # NIF
        self.assertContains(resp, "099916100654321")  # NIS
        self.assertContains(resp, "16/00-1048291B21")  # RC
        self.assertContains(resp, "16125849012")      # AI
        self.assertContains(resp, "FAC-2026-000001")
