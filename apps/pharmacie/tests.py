"""
Tests unitaires et transactionnels du module Gestion de Stock Pharmaceutique & Achats :
- Sortie de stock stricte FEFO (First Expired, First Out)
- Mise en quarantaine / Rappel de lot
- Suggestion automatique de commande : (Stock Max - Stock Actuel) si Stock Actuel <= Seuil d'alerte
- Réception de livraison avec N° de lot + Date de péremption obligatoires et recalcul du PMP
- Inventaire tournant avec justification obligatoire et journal d'audit immuable
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import UserRole
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
)
from apps.pharmacie.services import (
    ajuster_inventaire_tournant,
    creer_commande_achat_depuis_lignes,
    dispensation_sortie_fefo,
    generer_suggestions_reapprovisionnement,
    mettre_lot_en_quarantaine_ou_rappel,
    receptionner_livraison_commande,
)

User = get_user_model()


class PharmacieStockAchatsTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username="pharmacien_chef",
            password="StrongPassword123!",
            first_name="Amine",
            last_name="Khelifi",
            role=UserRole.ADMIN,
        )
        self.today = timezone.localdate()

        self.fournisseur = Fournisseur.objects.create(
            nom="Grossiste Test Pharma",
            contact="Service Commandes",
            email="contact@testpharma.dz",
            delai_livraison_moyen=2,
        )

        self.produit = ProduitPharmaceutique.objects.create(
            code_cip_ean13="3400939999991",
            dci="Paracétamol",
            nom_commercial="Paracétamol Hospitalier",
            dosage="1000 mg",
            forme_galenique="Comprimé",
            categorie=CategorieProduitChoices.MEDICAMENT_REMBOURSABLE,
            fournisseur_prefere=self.fournisseur,
            prix_achat_ht=Decimal("10.00"),
            prix_moyen_pondere_ht=Decimal("10.00"),
            taux_tva=Decimal("2.10"),
            stock_minimum=30,
            stock_securite=10,
            stock_maximum=100,
        )

    def test_fefo_strict_order_across_multiple_lots(self) -> None:
        """
        Vérifie que la sortie de stock prélève en priorité sur le lot expirant le plus tôt (FEFO),
        puis complète sur le lot suivant.
        """
        lot_lointain = LotStock.objects.create(
            produit=self.produit,
            numero_lot="LOT-2027-LOIN",
            date_peremption=self.today + timedelta(days=300),
            quantite_disponible=20,
            statut=StatutLotChoices.ACTIF,
        )
        lot_proche = LotStock.objects.create(
            produit=self.produit,
            numero_lot="LOT-2026-PROCHE",
            date_peremption=self.today + timedelta(days=40),
            quantite_disponible=10,
            statut=StatutLotChoices.PROCHE_PEREMPTION,
        )

        # Sortie de 15 unités : doit vider les 10 du lot_proche puis prendre 5 sur lot_lointain
        mouvements = dispensation_sortie_fefo(
            produit_id=self.produit.id,
            quantite_demandee=15,
            utilisateur=self.user,
            motif_reference="Dotation Service Urgences",
        )
        self.assertEqual(len(mouvements), 2)
        lot_proche.refresh_from_db()
        lot_lointain.refresh_from_db()

        self.assertEqual(lot_proche.quantite_disponible, 0)
        self.assertEqual(lot_lointain.quantite_disponible, 15)
        self.assertEqual(self.produit.stock_actuel, 15)

    def test_quarantine_and_suggestion_formula(self) -> None:
        """
        Vérifie la mise en quarantaine d'un lot et le calcul de la suggestion de réapprovisionnement
        selon la formule (Stock Max - Stock Actuel) lorsque Stock Actuel <= Seuil d'alerte.
        """
        lot1 = LotStock.objects.create(
            produit=self.produit,
            numero_lot="LOT-ACTIF-1",
            date_peremption=self.today + timedelta(days=180),
            quantite_disponible=22,  # <= stock_minimum (30)
            statut=StatutLotChoices.ACTIF,
        )
        lot_suspect = LotStock.objects.create(
            produit=self.produit,
            numero_lot="LOT-SUSPECT-2",
            date_peremption=self.today + timedelta(days=180),
            quantite_disponible=50,
            statut=StatutLotChoices.ACTIF,
        )

        # Isoler lot_suspect en QUARANTAINE
        mettre_lot_en_quarantaine_ou_rappel(
            lot_id=lot_suspect.id,
            nouveau_statut=StatutLotChoices.QUARANTAINE,
            motif="Alerte sanitaire ANSM - Lot isolé",
            utilisateur=self.user,
        )

        # Le stock disponible ne doit compter que lot1 (22 unités <= seuil 30)
        self.assertEqual(self.produit.stock_actuel, 22)
        self.assertTrue(self.produit.est_en_alerte_rupture)
        # Formule : Stock Max (100) - Stock Actuel (22) = 78
        self.assertEqual(self.produit.quantite_suggeree_commande, 78)

        suggestions = generer_suggestions_reapprovisionnement()
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["quantite_suggeree"], 78)

    def test_purchase_order_reception_and_pmp_calculation(self) -> None:
        """
        Vérifie le cycle d'achat complet : création de commande, réception avec lot/péremption
        obligatoires, et recalcul du Prix Moyen Pondéré (PMP).
        """
        # Stock initial : 20 unités à PMP = 10.00 € (Valeur = 200 €)
        LotStock.objects.create(
            produit=self.produit,
            numero_lot="LOT-INIT",
            date_peremption=self.today + timedelta(days=200),
            quantite_disponible=20,
            statut=StatutLotChoices.ACTIF,
        )

        # Création d'une commande de 30 unités à 15.00 € HT
        commande = creer_commande_achat_depuis_lignes(
            fournisseur_id=self.fournisseur.id,
            lignes_data=[
                {
                    "produit_id": self.produit.id,
                    "quantite": 30,
                    "prix_unitaire_ht": Decimal("15.00"),
                }
            ],
            utilisateur=self.user,
        )
        ligne = commande.lignes.first()
        self.assertIsNotNone(ligne)

        # 1. Test d'échec si numéro de lot manquant
        with self.assertRaises(ValidationError):
            receptionner_livraison_commande(
                commande_id=commande.id,
                receptions=[
                    {
                        "ligne_id": ligne.id,
                        "quantite_recue": 30,
                        "numero_lot": "",
                        "date_peremption": (self.today + timedelta(days=365)).isoformat(),
                    }
                ],
                utilisateur=self.user,
            )

        # 2. Réception valide de 30 unités à 15.00 € HT
        # Nouveau PMP attendu = ((20 * 10.00) + (30 * 15.00)) / (20 + 30) = 650 / 50 = 13.00 €
        commande_recue = receptionner_livraison_commande(
            commande_id=commande.id,
            receptions=[
                {
                    "ligne_id": ligne.id,
                    "quantite_recue": 30,
                    "numero_lot": "LOT-RECU-2027",
                    "date_peremption": (self.today + timedelta(days=365)).isoformat(),
                    "emplacement_physique": "Rayon A1",
                }
            ],
            utilisateur=self.user,
        )
        self.produit.refresh_from_db()
        self.assertEqual(commande_recue.statut, StatutCommandeChoices.RECUE)
        self.assertEqual(self.produit.stock_actuel, 50)
        self.assertEqual(self.produit.prix_moyen_pondere_ht, Decimal("13.00"))

    def test_rolling_inventory_and_immutable_audit_log(self) -> None:
        """
        Vérifie l'inventaire tournant avec justification obligatoire et l'interdiction
        absolue de supprimer un MouvementStock.
        """
        lot = LotStock.objects.create(
            produit=self.produit,
            numero_lot="LOT-INV-01",
            date_peremption=self.today + timedelta(days=150),
            quantite_disponible=40,
            statut=StatutLotChoices.ACTIF,
        )

        # Sans justification -> ValidationError
        with self.assertRaises(ValidationError):
            ajuster_inventaire_tournant(
                lot_id=lot.id,
                quantite_reelle_comptee=38,
                motif_justification="   ",
                utilisateur=self.user,
            )

        # Avec justification -> Succès et écart -2 enregistré
        mvt = ajuster_inventaire_tournant(
            lot_id=lot.id,
            quantite_reelle_comptee=38,
            motif_justification="2 comprimés endommagés constatés lors du comptage",
            utilisateur=self.user,
        )
        lot.refresh_from_db()
        self.assertEqual(lot.quantite_disponible, 38)
        self.assertEqual(mvt.quantite, -2)

        # Tentative de suppression du log d'audit -> PermissionDenied
        with self.assertRaises(PermissionDenied):
            mvt.delete()

    def test_dashboard_and_barcode_api_views(self) -> None:
        """Vérifie le chargement du cockpit Pharmacie et l'API JSON douchette code-barres."""
        self.client.force_login(self.user)
        resp = self.client.get(reverse("pharmacie:dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Pharmacie Hospitalière")

        api_resp = self.client.get(
            reverse("pharmacie:api_barcode", kwargs={"code_barres": "3400939999991"})
        )
        self.assertEqual(api_resp.status_code, 200)
        data = api_resp.json()
        self.assertTrue(data["found"])
        self.assertEqual(data["nom_commercial"], "Paracétamol Hospitalier")

