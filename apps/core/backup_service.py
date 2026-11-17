"""
Service de Sauvegarde et Restauration Complète de la Base de Données (Full Backup & Restore).
Prend en charge :
- Export SQLite transactionnel à chaud (.sqlite3)
- Export universel Django dumpdata (.json)
- Archive complète Full Backup ZIP (.zip) incluant la BDD, le dossier média et un manifeste
- Restauration vérifiée (avec copie de sécurité automatique pré-restauration dans backups/)
- Gestion des sauvegardes locales serveur
"""

from datetime import datetime
from decimal import Decimal
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any, Dict, List, Optional, Tuple
import zipfile

from django.conf import settings
from django.core.management import call_command
from django.db import connection, connections, transaction
from django.utils import timezone


def get_backup_dir() -> Path:
    """Retourne et crée si besoin le répertoire des sauvegardes locales."""
    backup_dir = Path(settings.BASE_DIR) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def export_sqlite_backup_bytes() -> bytes:
    """Effectue une sauvegarde transactionnelle à chaud de la base SQLite."""
    if connection.vendor != "sqlite":
        raise ValueError("L'export SQLite natif n'est disponible que lorsque le moteur est SQLite.")

    db_name = str(connection.settings_dict.get("NAME", ""))
    with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        if db_name == ":memory:":
            connection.ensure_connection()
            src_conn = connection.connection
            dst_conn = sqlite3.connect(str(tmp_path))
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
        else:
            src_conn = sqlite3.connect(db_name)
            dst_conn = sqlite3.connect(str(tmp_path))
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
                src_conn.close()

        return tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)


def export_json_backup_bytes() -> bytes:
    """Effectue un dumpdata universel au format JSON (compatible SQLite et PostgreSQL)."""
    buf = io.StringIO()
    call_command(
        "dumpdata",
        exclude=["contenttypes", "auth.permission", "sessions.session", "admin.logentry"],
        indent=2,
        stdout=buf,
    )
    return buf.getvalue().encode("utf-8")


def export_full_zip_backup_bytes() -> bytes:
    """
    Crée une archive ZIP complète (Full Backup) contenant :
    - La base de données (.sqlite3 ou .json)
    - Les fichiers médias / pièces jointes (logos, ordonnances, consentements)
    - Un fichier manifest.json détaillé
    """
    stamp = timezone.localtime(timezone.now()).strftime("%Y%m%d_%H%M%S")
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. Base de données
        if connection.vendor == "sqlite":
            db_bytes = export_sqlite_backup_bytes()
            db_filename = f"database_{stamp}.sqlite3"
        else:
            db_bytes = export_json_backup_bytes()
            db_filename = f"database_{stamp}.json"
        zf.writestr(f"database/{db_filename}", db_bytes)

        # 2. Dump JSON systématique pour portabilité multi-moteurs
        json_bytes = export_json_backup_bytes()
        zf.writestr(f"database/dumpdata_{stamp}.json", json_bytes)

        # 3. Fichiers médias si présents
        media_root = getattr(settings, "MEDIA_ROOT", Path(settings.BASE_DIR) / "media")
        if media_root and Path(media_root).is_dir():
            for root, _, files in os.walk(media_root):
                for f in files:
                    file_path = Path(root) / f
                    arcname = f"media/{file_path.relative_to(media_root)}"
                    zf.write(file_path, arcname)

        # 4. Manifeste
        manifest = {
            "app_name": "Clinique Sidi Yahia 2 (SIH & WMS)",
            "created_at": timezone.now().isoformat(),
            "timestamp": stamp,
            "database_engine": connection.vendor,
            "db_filename": db_filename,
            "version": "2.0.0",
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))

    return zip_buffer.getvalue()


def create_safety_backup_snapshot() -> Optional[Path]:
    """Crée une copie de sécurité pré-restauration dans backups/."""
    stamp = timezone.localtime(timezone.now()).strftime("%Y%m%d_%H%M%S")
    backup_dir = get_backup_dir()

    if connection.vendor == "sqlite":
        db_name = str(connection.settings_dict.get("NAME", ""))
        if db_name != ":memory:":
            safety_path = backup_dir / f"safety_pre_restore_{stamp}.sqlite3"
            cur_conn = sqlite3.connect(db_name)
            saf_conn = sqlite3.connect(str(safety_path))
            try:
                cur_conn.backup(saf_conn)
                return safety_path
            finally:
                saf_conn.close()
                cur_conn.close()
    else:
        json_bytes = export_json_backup_bytes()
        safety_path = backup_dir / f"safety_pre_restore_{stamp}.json"
        safety_path.write_bytes(json_bytes)
        return safety_path

    return None


def restore_database_from_bytes(
    raw_bytes: bytes,
    filename: str,
    flush_first: bool = False,
    create_safety: bool = True,
) -> Tuple[bool, str]:
    """
    Restaure la base de données depuis un flux binaire (.sqlite3, .json ou archive .zip) :
    1. Crée un snapshot de sécurité automatique dans backups/
    2. Valide l'intégrité avant d'écraser
    3. Restaure les données et extrait les médias si c'est un ZIP
    """
    filename_lower = filename.lower()
    if create_safety:
        create_safety_backup_snapshot()

    # CAS 1 : Archive ZIP Full Backup
    if filename_lower.endswith(".zip"):
        try:
            zip_buffer = io.BytesIO(raw_bytes)
            with zipfile.ZipFile(zip_buffer, "r") as zf:
                namelist = zf.namelist()

                # Trouver le fichier SQLite ou JSON dans l'archive
                sqlite_names = [n for n in namelist if n.endswith((".sqlite3", ".db", ".sqlite"))]
                json_names = [n for n in namelist if n.endswith(".json") and not n.endswith("manifest.json")]

                # Extraire et restaurer les médias
                media_root = getattr(settings, "MEDIA_ROOT", Path(settings.BASE_DIR) / "media")
                Path(media_root).mkdir(parents=True, exist_ok=True)
                for member in namelist:
                    if member.startswith("media/") and not member.endswith("/"):
                        rel_path = member[len("media/"):]
                        target_file = Path(media_root) / rel_path
                        target_file.parent.mkdir(parents=True, exist_ok=True)
                        target_file.write_bytes(zf.read(member))

                # Restaurer la BDD (SQLite de préférence si moteur SQLite, sinon JSON)
                if connection.vendor == "sqlite" and sqlite_names:
                    db_bytes = zf.read(sqlite_names[0])
                    return _restore_sqlite_bytes(db_bytes, sqlite_names[0])
                elif json_names:
                    json_bytes = zf.read(json_names[0])
                    return _restore_json_bytes(json_bytes, flush_first=flush_first)
                else:
                    return False, "Aucune base de données (.sqlite3 ou .json) trouvée dans l'archive ZIP."
        except Exception as exc:
            return False, f"Erreur de lecture de l'archive ZIP : {exc}"

    # CAS 2 : Fichier SQLite direct
    if filename_lower.endswith((".sqlite3", ".db", ".sqlite")):
        return _restore_sqlite_bytes(raw_bytes, filename)

    # CAS 3 : Fichier JSON Django dumpdata direct
    if filename_lower.endswith(".json"):
        return _restore_json_bytes(raw_bytes, flush_first=flush_first)

    return False, "Format de fichier non reconnu. Utilisez .sqlite3, .json ou une archive .zip."


def _restore_sqlite_bytes(raw_bytes: bytes, filename: str) -> Tuple[bool, str]:
    """Restaure un fichier SQLite après contrôle d'intégrité."""
    if connection.vendor != "sqlite":
        return False, "Le serveur actif utilise PostgreSQL. Restaurez à l'aide d'un fichier .json."

    if len(raw_bytes) < 16 or raw_bytes[:16] != b"SQLite format 3\x00":
        return False, "Le fichier n'est pas une base de données SQLite valide (en-tête invalide)."

    with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as tmp:
        tmp.write(raw_bytes)
        tmp_path = Path(tmp.name)

    try:
        check_conn = sqlite3.connect(str(tmp_path))
        try:
            integrity = check_conn.execute("PRAGMA integrity_check;").fetchone()
            if not integrity or integrity[0] != "ok":
                return False, "Le fichier SQLite est corrompu (échec de PRAGMA integrity_check)."
        finally:
            check_conn.close()

        db_name = str(connection.settings_dict.get("NAME", ""))
        if db_name != ":memory:":
            connections.close_all()
            src_conn = sqlite3.connect(str(tmp_path))
            dst_conn = sqlite3.connect(db_name)
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
                src_conn.close()
        else:
            connection.ensure_connection()
            src_conn = sqlite3.connect(str(tmp_path))
            try:
                src_conn.backup(connection.connection)
            finally:
                src_conn.close()

        return True, f"Base SQLite restaurée avec succès depuis « {filename} »."
    except Exception as exc:
        return False, f"Erreur lors de la restauration SQLite : {exc}"
    finally:
        tmp_path.unlink(missing_ok=True)


def _restore_json_bytes(raw_bytes: bytes, flush_first: bool = False) -> Tuple[bool, str]:
    """Restaure un fichier dumpdata JSON via loaddata."""
    try:
        parsed = json.loads(raw_bytes.decode("utf-8"))
        if not isinstance(parsed, list):
            return False, "Le fichier JSON doit contenir une liste d'enregistrements Django."
    except Exception as exc:
        return False, f"Fichier JSON invalide : {exc}"

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp.write(raw_bytes)
        tmp_path = Path(tmp.name)

    try:
        with transaction.atomic():
            if flush_first:
                call_command("flush", interactive=False, verbosity=0)
            call_command("loaddata", str(tmp_path), verbosity=0)
        return True, "Données JSON restaurées avec succès dans la base."
    except Exception as exc:
        return False, f"Erreur lors du chargement des données JSON : {exc}"
    finally:
        tmp_path.unlink(missing_ok=True)


def list_local_backups() -> List[Dict[str, Any]]:
    """Liste tous les fichiers de sauvegarde stockés dans backups/ sur le serveur."""
    backup_dir = get_backup_dir()
    results = []
    for file_path in sorted(backup_dir.glob("*"), key=os.path.getmtime, reverse=True):
        if file_path.is_file() and file_path.suffix.lower() in [".sqlite3", ".json", ".zip", ".db"]:
            stat = file_path.stat()
            size_bytes = stat.st_size
            if size_bytes >= 1024 * 1024:
                size_str = f"{size_bytes / (1024 * 1024):.2f} Mo"
            elif size_bytes >= 1024:
                size_str = f"{size_bytes / 1024:.1f} Ko"
            else:
                size_str = f"{size_bytes} octets"

            dt = datetime.fromtimestamp(stat.st_mtime)
            results.append({
                "filename": file_path.name,
                "size_str": size_str,
                "modified_at": dt,
                "extension": file_path.suffix.lower().replace(".", ""),
                "is_safety": "safety" in file_path.name.lower() or "pre_restore" in file_path.name.lower(),
            })
    return results

