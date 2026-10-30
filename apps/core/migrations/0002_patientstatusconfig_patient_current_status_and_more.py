# Generated for Dynamic Patient Status Management (SIH HDS)

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def seed_default_statuses(apps, schema_editor):
    PatientStatusConfig = apps.get_model("core", "PatientStatusConfig")
    Patient = apps.get_model("core", "Patient")

    defaults = [
        {
            "code": "ADMISSION",
            "label": "Admission",
            "description": "Patient enregistré à l'accueil / en préparation pré-hospitalière",
            "color_theme": "sky",
            "hex_color": "#0284C7",
            "display_order": 1,
            "is_terminal": False,
            "is_active": True,
            "is_system_default": True,
        },
        {
            "code": "SERVICE",
            "label": "Service",
            "description": "Patient installé en chambre dans son unité d'hospitalisation",
            "color_theme": "indigo",
            "hex_color": "#4F46E5",
            "display_order": 2,
            "is_terminal": False,
            "is_active": True,
            "is_system_default": True,
        },
        {
            "code": "BLOC",
            "label": "Bloc",
            "description": "Patient actuellement en salle d'intervention au bloc opératoire",
            "color_theme": "rose",
            "hex_color": "#E11D48",
            "display_order": 3,
            "is_terminal": False,
            "is_active": True,
            "is_system_default": True,
        },
        {
            "code": "REVEIL",
            "label": "Réveil",
            "description": "Patient en Salle de Surveillance Post-Interventionnelle (SSPI)",
            "color_theme": "amber",
            "hex_color": "#D97706",
            "display_order": 4,
            "is_terminal": False,
            "is_active": True,
            "is_system_default": True,
        },
        {
            "code": "REPORTE",
            "label": "Reporté",
            "description": "Acte ou prise en charge reportée à une date ultérieure",
            "color_theme": "purple",
            "hex_color": "#9333EA",
            "display_order": 5,
            "is_terminal": False,
            "is_active": True,
            "is_system_default": True,
        },
        {
            "code": "SORTIE",
            "label": "Sortie",
            "description": "Patient ayant quitté l'établissement après validation médicale",
            "color_theme": "emerald",
            "hex_color": "#059669",
            "display_order": 6,
            "is_terminal": True,
            "is_active": True,
            "is_system_default": True,
        },
        {
            "code": "ANNULE",
            "label": "Annulé",
            "description": "Admission ou venue annulée avant prise en charge",
            "color_theme": "slate",
            "hex_color": "#64748B",
            "display_order": 7,
            "is_terminal": True,
            "is_active": True,
            "is_system_default": True,
        },
    ]

    status_map = {}
    for item in defaults:
        obj, _ = PatientStatusConfig.objects.get_or_create(code=item["code"], defaults=item)
        status_map[item["code"]] = obj

    admission_status = status_map["ADMISSION"]
    now = django.utils.timezone.now()
    Patient.objects.filter(current_status__isnull=True).update(
        current_status=admission_status,
        status_updated_at=now,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PatientStatusConfig",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        help_text="Horodatage immuable de l'enregistrement",
                        verbose_name="Date de création",
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                        help_text="Horodatage automatique de la dernière modification",
                        verbose_name="Dernière mise à jour",
                    ),
                ),
                (
                    "code",
                    models.CharField(
                        help_text="Identifiant unique en majuscules (ex: ADMISSION, BLOC, REVEIL)",
                        max_length=40,
                        unique=True,
                        verbose_name="Code technique",
                    ),
                ),
                ("label", models.CharField(max_length=80, verbose_name="Libellé du statut")),
                ("description", models.CharField(blank=True, max_length=255, verbose_name="Description fonctionnelle")),
                (
                    "color_theme",
                    models.CharField(
                        choices=[
                            ("sky", "Bleu Ciel (Admission / Accueil)"),
                            ("indigo", "Indigo (Service / Unité de soin)"),
                            ("rose", "Rouge Corail (Bloc Opératoire / Urgence)"),
                            ("amber", "Ambre / Orange (Réveil / Surveillance SSPI)"),
                            ("emerald", "Vert Émeraude (Sortie / Validé)"),
                            ("purple", "Violet (Reporté / En attente)"),
                            ("slate", "Gris Ardoise (Annulé / Clôturé)"),
                        ],
                        default="sky",
                        max_length=20,
                        verbose_name="Thème de couleur (Badge UI)",
                    ),
                ),
                ("hex_color", models.CharField(default="#0284C7", max_length=7, verbose_name="Couleur HEX (#RRGGBB)")),
                ("display_order", models.PositiveIntegerField(default=10, verbose_name="Ordre d'affichage")),
                (
                    "is_terminal",
                    models.BooleanField(
                        default=False,
                        verbose_name="Statut de fin de parcours (Sortie / Annulé)",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(
                        default=True,
                        help_text="Désactivez pour masquer ce statut sans perdre l'historique des patients.",
                        verbose_name="Statut actif",
                    ),
                ),
                (
                    "is_system_default",
                    models.BooleanField(default=False, verbose_name="Statut initial par défaut du système"),
                ),
            ],
            options={
                "verbose_name": "Paramétrage Statut Patient",
                "verbose_name_plural": "Paramétrage des Statuts Patients",
                "ordering": ["display_order", "label"],
            },
        ),
        migrations.AddField(
            model_name="patient",
            name="current_status",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="patients",
                to="core.patientstatusconfig",
                verbose_name="Statut actuel du patient",
            ),
        ),
        migrations.AddField(
            model_name="patient",
            name="status_updated_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Dernier changement de statut"),
        ),
        migrations.CreateModel(
            name="PatientStatusHistory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("comment", models.TextField(blank=True, verbose_name="Observation / Motif")),
                (
                    "changed_at",
                    models.DateTimeField(
                        db_index=True,
                        default=django.utils.timezone.now,
                        verbose_name="Date et heure du changement",
                    ),
                ),
                (
                    "changed_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="patient_status_changes",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Modifié par (Utilisateur)",
                    ),
                ),
                (
                    "new_status",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="transitions_to",
                        to="core.patientstatusconfig",
                        verbose_name="Nouveau statut",
                    ),
                ),
                (
                    "old_status",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="transitions_from",
                        to="core.patientstatusconfig",
                        verbose_name="Ancien statut",
                    ),
                ),
                (
                    "patient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="status_history",
                        to="core.patient",
                        verbose_name="Patient (DPI)",
                    ),
                ),
            ],
            options={
                "verbose_name": "Historique de Statut Patient",
                "verbose_name_plural": "Historiques des Statuts Patients",
                "ordering": ["-changed_at", "-id"],
            },
        ),
        migrations.RunPython(seed_default_statuses, migrations.RunPython.noop),
    ]

