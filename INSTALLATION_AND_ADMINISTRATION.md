# Manuel d'Installation et d'Administration (Ubuntu Server)

Ce guide détaille le déploiement et l'administration du **Système d'Information Hospitalier (SIH)** sur un serveur **Ubuntu 22.04 LTS / 24.04 LTS** avec **PostgreSQL**, **Gunicorn**, **Systemd** et **Nginx**.

---

## 1. Prérequis Système

- **Système d'exploitation** : Ubuntu Server 22.04 LTS ou 24.04 LTS (64-bit)
- **Python** : ≥ 3.10 (`python3`, `python3-venv`, `python3-pip`)
- **Base de données** : PostgreSQL 14+ (ou SQLite pour les environnements de test)
- **Serveur Web / Reverse Proxy** : Nginx
- **Accès** : Utilisateur disposant des privilèges `sudo`

### Installation des paquets système sur Ubuntu
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-venv python3-pip python3-dev \
    libpq-dev postgresql postgresql-contrib nginx git curl ufw
```

---

## 2. Configuration de PostgreSQL

Connectez-vous à l'invite PostgreSQL pour créer la base de données et l'utilisateur dédié :

```bash
sudo -u postgres psql
```

Dans la console SQL PostgreSQL, exécutez :
```sql
CREATE DATABASE hospital_db ENCODING 'UTF8' LC_COLLATE 'fr_FR.UTF-8' LC_CTYPE 'fr_FR.UTF-8' TEMPLATE template0;
CREATE USER hospital_user WITH PASSWORD 'MotDePasseTresSecurise123!';
ALTER ROLE hospital_user SET client_encoding TO 'utf8';
ALTER ROLE hospital_user SET default_transaction_isolation TO 'read committed';
ALTER ROLE hospital_user SET timezone TO 'Europe/Paris';
GRANT ALL PRIVILEGES ON DATABASE hospital_db TO hospital_user;
\c hospital_db
GRANT ALL ON SCHEMA public TO hospital_user;
\q
```
*(Si la locale `fr_FR.UTF-8` n'est pas installée sur le serveur, utilisez simplement `CREATE DATABASE hospital_db;`)*

---

## 3. Transfert du Code Source et Environnement Virtuel

Nous recommandons de déployer l'application dans `/var/www/clinic`. Préparez d'abord le dossier sur le serveur Ubuntu :

```bash
sudo mkdir -p /var/www/clinic
sudo chown -R $USER:www-data /var/www/clinic
```

Vous pouvez transférer le code source depuis votre PC Windows vers le serveur Ubuntu selon **3 méthodes au choix** :

### Méthode A : Transfert direct depuis Windows via `scp` (Sans GitHub)
1. Sur votre **PC Windows (PowerShell)**, créez une archive du projet et envoyez-la en SSH :
   ```powershell
   cd C:\OLD-PC\AL
   tar -czf clinic.tar.gz --exclude="Clinic/venv" --exclude="Clinic/__pycache__" Clinic
   scp clinic.tar.gz utilisateur@IP_DU_SERVEUR:/tmp/
   ```
2. Sur le **serveur Ubuntu**, décompressez l'archive dans `/var/www/clinic` :
   ```bash
   tar -xzf /tmp/clinic.tar.gz -C /var/www/clinic --strip-components=1
   rm /tmp/clinic.tar.gz
   ```

### Méthode B : Via Git (Recommandé pour faciliter les mises à jour)
1. Sur votre **PC Windows**, poussez le projet sur un dépôt Git (GitHub / GitLab) :
   ```powershell
   cd C:\OLD-PC\AL\Clinic
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/VOTRE_COMPTE/clinic.git
   git push -u origin main
   ```
2. Sur le **serveur Ubuntu**, clonez le dépôt :
   ```bash
   git clone https://github.com/VOTRE_COMPTE/clinic.git /var/www/clinic
   ```
   *(Pour les prochaines mises à jour sur le serveur, il suffira de faire `git pull` dans `/var/www/clinic`).*

### Méthode C : Via FileZilla ou WinSCP (Interface graphique)
1. Connectez-vous au serveur Ubuntu en **SFTP (Port 22)** avec votre utilisateur SSH.
2. Copiez le contenu de `C:\OLD-PC\AL\Clinic` vers `/var/www/clinic` sur le serveur.

---

### Création de l'environnement virtuel Python (sur Ubuntu)
Une fois les fichiers présents dans `/var/www/clinic` :
```bash
cd /var/www/clinic

# Créer et activer l'environnement virtuel Python
python3 -m venv venv
source venv/bin/activate

# Installer les dépendances Python
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 4. Variables d'Environnement (`.env`)

Créez un fichier `.env` à la racine du projet (`/var/www/clinic/.env`) :

```bash
nano /var/www/clinic/.env
```

Contenu recommandé :
```ini
# Sécurité Django
DJANGO_SECRET_KEY=remplacez-moi-par-une-cle-secrete-longue-et-aleatoire
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,votre-domaine.fr,IP_DU_SERVEUR
DJANGO_CSRF_TRUSTED_ORIGINS=http://votre-domaine.fr,https://votre-domaine.fr

# Passer à True uniquement lorsque le certificat HTTPS (SSL/TLS) est actif sur Nginx
DJANGO_ENABLE_HTTPS=False

# Base de données PostgreSQL
POSTGRES_DB=hospital_db
POSTGRES_USER=hospital_user
POSTGRES_PASSWORD=MotDePasseTresSecurise123!
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_SSLMODE=prefer
```

> **Note :** Pour tester rapidement avec SQLite sans PostgreSQL, omettez `POSTGRES_DB` (ou définissez `DJANGO_USE_SQLITE=1`). Django utilisera alors automatiquement le fichier `db_hospital_dev.sqlite3`.

Sécurisez les permissions du fichier `.env` :
```bash
chmod 640 /var/www/clinic/.env
sudo chown $USER:www-data /var/www/clinic/.env
```

---

## 5. Initialisation de la Base de Données et des Fichiers Statiques

Toujours avec l'environnement virtuel activé (`source /var/www/clinic/venv/bin/activate`) :

```bash
cd /var/www/clinic

# 1. Appliquer les migrations de schéma
python manage.py migrate

# 2. (Optionnel) Peupler la base avec les données hospitalières de démonstration
python manage.py seed_hospital_data

# 3. (Alternative) Créer un super-utilisateur administrateur manuellement
python manage.py createsuperuser

# 4. Collecter les fichiers statiques dans staticfiles/
python manage.py collectstatic --noinput

# 5. Ajuster les permissions pour Gunicorn / www-data
sudo chown -R $USER:www-data /var/www/clinic
sudo chmod -R 775 /var/www/clinic
```

---

## 6. Configuration du Service Systemd (Gunicorn)

Créez le fichier de service `systemd` pour exécuter Gunicorn en tâche de fond et le démarrer automatiquement au démarrage d'Ubuntu :

```bash
sudo nano /etc/systemd/system/clinic.service
```

Ajoutez la configuration suivante :
```ini
[Unit]
Description=Gunicorn daemon for SIH Clinic Hospital System
After=network.target postgresql.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/clinic
EnvironmentFile=/var/www/clinic/.env
ExecStart=/var/www/clinic/venv/bin/gunicorn \
    --access-logfile - \
    --workers 3 \
    --bind unix:/run/clinic.sock \
    hospital_system.wsgi:application
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

Activez et démarrez le service :
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now clinic.service
sudo systemctl status clinic.service
```

---

## 7. Configuration du Serveur Web Nginx

Créez un bloc serveur Nginx pour rediriger le trafic HTTP vers le socket Gunicorn et servir les fichiers statiques :

```bash
sudo nano /etc/nginx/sites-available/clinic
```

Contenu du fichier :
```nginx
server {
    listen 80;
    server_name 204.216.108.214;

    client_max_body_size 20M;

    location = /favicon.ico { access_log off; log_not_found off; }

    location /static/ {
        alias /var/www/html/clinic/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, no-transform";
    }

    location / {
        include proxy_params;
        proxy_pass http://unix:/run/clinic.sock;
    }
}
```

Activez le site et redémarrez Nginx :
```bash
sudo ln -s /etc/nginx/sites-available/clinic /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
```

### Configuration du Pare-feu (UFW)
```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

---

## 8. Passage en HTTPS avec Let's Encrypt (Recommandé en Production / HDS)

Si le serveur possède un nom de domaine public :

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d votre-domaine.fr
```

Une fois le certificat SSL installé, éditez `/var/www/clinic/.env` pour activer les protections HTTPS strictes (HSTS, cookies sécurisés) :
```ini
DJANGO_ENABLE_HTTPS=True
```
Puis redémarrez Gunicorn :
```bash
sudo systemctl restart clinic.service
```

---

## 9. Gestion des Rôles (RBAC)

Le projet définit l'énumération `UserRole` dans `apps.core.models`.
Après connexion au portail d'administration (`http://<serveur>/admin/`) :
1. Accédez à **Personnel Hospitalier (Utilisateurs)**.
2. Attribuez le rôle approprié (`ADMIN`, `MEDECIN`, `CHIRURGIEN`, `INFIRMIER`, `SAGE_FEMME`, `SECRETAIRE`) ainsi que le **Service hospitalier d'affectation**.

*(Si vous avez exécuté `python manage.py seed_hospital_data`, le compte administrateur par défaut est `admin` / `AdminPassword123!`.)*

---

## 10. Commandes d'Administration Courantes sur Ubuntu

| Tâche | Commande |
|------|----------|
| Voir l'état du serveur applicatif | `sudo systemctl status clinic.service` |
| Redémarrer l'application après mise à jour | `sudo systemctl restart clinic.service` |
| Consulter les journaux (logs) en direct | `sudo journalctl -u clinic.service -f` |
| Appliquer de nouvelles migrations | `source /var/www/clinic/venv/bin/activate && python manage.py migrate` |
| Mettre à jour les fichiers statiques | `source /var/www/clinic/venv/bin/activate && python manage.py collectstatic --noinput` |
| Changer le mot de passe d'un utilisateur | `source /var/www/clinic/venv/bin/activate && python manage.py changepassword <username>` |
| Lancer la suite de tests | `source /var/www/clinic/venv/bin/activate && python manage.py test` |
| Sauvegarder la base PostgreSQL | `pg_dump -U hospital_user -h localhost hospital_db > backup_$(date +%F).sql` |
