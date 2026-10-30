# Guide de Déploiement du Code Source vers le Serveur Ubuntu

Ce document explique étape par étape comment transférer et mettre à jour le code source du projet depuis votre **PC Windows (`C:\OLD-PC\AL\Clinic`)** vers votre **serveur Ubuntu (`/var/www/clinic`)**.

---

## Étape 0 : Préparer le dossier sur le serveur Ubuntu

Connectez-vous en SSH à votre serveur Ubuntu et créez le répertoire de destination avec les bons droits :

```bash
ssh utilisateur@IP_DU_SERVEUR

sudo mkdir -p /var/www/clinic
sudo chown -R $USER:www-data /var/www/clinic
```

---

## Méthode 1 : Transfert direct via `scp` (Recommandé sans GitHub)

Cette méthode utilise les outils natifs de Windows 10/11 (**PowerShell**) pour envoyer une archive compressée directement au serveur Ubuntu via SSH.

### 1. Sur votre PC Windows (dans PowerShell)

Placez-vous **directement à l'intérieur** du dossier de votre projet (`C:\OLD-PC\AL\Clinic` ou `C:\Users\hafid\Documents\GitHub\gestion-clinique`) :

#### Option A : Avec `tar.exe` (recommandé)
> **Attention dans PowerShell** : ne mettez pas de guillemets dans `--exclude=...`, placez les `--exclude` avant `-czf`, et utilisez `.` à la fin pour archiver le dossier courant peu importe son nom.

```powershell
# 1. Se placer DANS le dossier du projet
cd C:\Users\hafid\Documents\GitHub\gestion-clinique
# (ou cd C:\OLD-PC\AL\Clinic selon l'emplacement de votre projet)

# 2. Créer l'archive dans le dossier parent (..\clinic.tar.gz) à partir du dossier courant (.)
C:\Windows\System32\tar.exe --exclude=venv --exclude=__pycache__ --exclude=.git -czf ..\clinic.tar.gz .

# 3. Envoyer l'archive sur le serveur Ubuntu
scp ..\clinic.tar.gz utilisateur@IP_DU_SERVEUR:/tmp/
```

#### Option B : Avec `Compress-Archive` (100% PowerShell, format `.zip`)
```powershell
# 1. Se placer DANS le dossier du projet
cd C:\Users\hafid\Documents\GitHub\gestion-clinique

# 2. Créer un fichier clinic.zip dans le dossier parent en excluant venv, .git et __pycache__
Get-ChildItem -Path . -Exclude "venv", ".git", "__pycache__" | Compress-Archive -DestinationPath ..\clinic.zip -Force

# 3. Envoyer le fichier zip sur le serveur Ubuntu
scp ..\clinic.zip utilisateur@IP_DU_SERVEUR:/tmp/
```

#### Option C : Avec `git archive` (si Git est installé)
```powershell
cd C:\Users\hafid\Documents\GitHub\gestion-clinique
git archive --format=tar.gz -o ..\clinic.tar.gz HEAD
scp ..\clinic.tar.gz utilisateur@IP_DU_SERVEUR:/tmp/
```

### 2. Sur le serveur Ubuntu (en SSH)
```bash
# Créer le dossier cible s'il n'existe pas encore
sudo mkdir -p /var/www/html/clinic

# Si vous avez envoyé clinic.tar.gz (Option A ou C) :
sudo tar -xzf /tmp/clinic.tar.gz -C /var/www/html/clinic
rm /tmp/clinic.tar.gz

# OU si vous avez envoyé clinic.zip (Option B) :
sudo apt update && sudo apt install -y unzip
sudo unzip -o /tmp/clinic.zip -d /var/www/html/clinic
rm /tmp/clinic.zip

# Appliquer les permissions pour le serveur web (www-data)
sudo chown -R $USER:www-data /var/www/html/clinic
sudo chmod -R 775 /var/www/html/clinic
```

---

## Méthode 2 : Déploiement via Git (GitHub / GitLab)

Cette méthode est idéale si vous modifiez régulièrement le code et souhaitez mettre à jour le serveur en une seule commande (`git pull`).

### 1. Sur votre PC Windows (dans PowerShell)
Créez d'abord un fichier `.gitignore` à la racine du projet pour ne pas envoyer les fichiers locaux inutiles :
```powershell
cd C:\OLD-PC\AL\Clinic

@"
venv/
__pycache__/
*.pyc
.env
staticfiles/
"@ | Out-File -Encoding utf8 .gitignore

git init
git add .
git commit -m "Version initiale SIH"
git branch -M main
git remote add origin https://github.com/VOTRE_COMPTE/VOTRE_DEPOT.git
git push -u origin main
```

### 2. Sur le serveur Ubuntu (en SSH)
```bash
git clone https://github.com/VOTRE_COMPTE/VOTRE_DEPOT.git /var/www/clinic
sudo chown -R $USER:www-data /var/www/clinic
```

### 3. Pour mettre à jour le serveur plus tard
Chaque fois que vous modifiez le code sur Windows :
1. **Sur Windows** :
   ```powershell
   git add .
   git commit -m "Mise à jour"
   git push
   ```
2. **Sur Ubuntu** :
   ```bash
   cd /var/www/html/clinic
   git fetch origin main
   git reset --hard origin/main
   source venv/bin/activate
   pip install -r requirements.txt
   python manage.py migrate
   python manage.py seed_hospital_data
   python manage.py collectstatic --noinput
   sudo chown -R $USER:www-data /var/www/html/clinic
   sudo chmod -R 775 /var/www/html/clinic
   sudo systemctl restart clinic.service
   sudo systemctl restart nginx
   ```

---

## Méthode 3 : Transfert graphique avec WinSCP ou FileZilla

Si vous préférez une interface visuelle avec glisser-déposer :

1. Téléchargez et ouvrez **WinSCP** (ou **FileZilla**) sur votre PC Windows.
2. Configurez une nouvelle connexion :
   - **Protocole** : `SFTP`
   - **Hôte** : `IP_DU_SERVEUR`
   - **Port** : `22`
   - **Nom d'utilisateur** : votre utilisateur Ubuntu
   - **Mot de passe** : votre mot de passe Ubuntu
3. Dans le panneau de gauche (Windows), ouvrez `C:\OLD-PC\AL\Clinic`.
4. Dans le panneau de droite (Ubuntu), ouvrez `/var/www/clinic`.
5. Sélectionnez tous les fichiers et dossiers (`apps`, `hospital_system`, `static`, `templates`, `manage.py`, `requirements.txt`, etc. — **sauf `venv`**) et faites-les glisser vers `/var/www/clinic`.

---

## Que faire sur Ubuntu juste après le transfert ?

Une fois le code source copié dans `/var/www/clinic`, exécutez ces commandes sur le serveur Ubuntu pour finaliser l'installation :

```bash
cd /var/www/html/clinic

# 1. Créer et activer l'environnement virtuel Python
python3 -m venv venv
source venv/bin/activate

# 2. Installer les dépendances
pip install --upgrade pip
pip install -r requirements.txt

# 3. Appliquer les migrations et collecter les fichiers statiques
python manage.py migrate
python manage.py collectstatic --noinput

# 4. (Optionnel) Charger les données hospitalières de test
python manage.py seed_hospital_data

# 5. Appliquer les permissions au dossier
sudo chown -R $USER:www-data /var/www/html/clinic
sudo chmod -R 775 /var/www/html/clinic
```

---

## Créer et démarrer le service `clinic.service` (Systemd + Gunicorn)

Si vous obtenez l'erreur `Unit clinic.service not found`, c'est que le fichier de service systemd n'a pas encore été créé sur Ubuntu. Exécutez ce bloc en une seule fois pour le créer et le démarrer :

```bash
sudo tee /etc/systemd/system/clinic.service > /dev/null <<EOF
[Unit]
Description=Gunicorn daemon for SIH Gestion Clinique
After=network.target

[Service]
User=$USER
Group=www-data
WorkingDirectory=/var/www/html/clinic
Environment="DJANGO_ALLOWED_HOSTS=*"
ExecStart=/var/www/html/clinic/venv/bin/gunicorn --workers 3 --bind 0.0.0.0:8000 hospital_system.wsgi:application
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Recharger systemd, activer et démarrer le service
sudo systemctl daemon-reload
sudo systemctl enable clinic.service
sudo systemctl restart clinic.service
sudo systemctl status clinic.service
```

---

## Résoudre l'erreur « This site can’t be reached » sur un VPS Oracle Cloud

Sur **Oracle Cloud (OCI)**, même lorsque `clinic.service` est démarré (`active (running)`), la page web affiche **`This site can’t be reached`** car Oracle bloque tous les ports par défaut à deux niveaux (**`iptables` sur Ubuntu** + **Security List dans la console Oracle**) et parce que Gunicorn écoute sur le port `8000` (et non `80` tant que Nginx n'est pas configuré).

### Étape 1 : Vérifier que l'application répond en local sur le VPS
En SSH sur votre serveur Ubuntu, testez si Gunicorn tourne bien :
```bash
curl -I http://127.0.0.1:8000
```
- Si vous voyez `HTTP/1.1 200 OK` ou `HTTP/1.1 302 Found`, le serveur Django fonctionne correctement.
- Si vous voyez `curl: (7) Failed to connect`, consultez les journaux d'erreur avec :
  ```bash
  sudo journalctl -u clinic.service -n 50 --no-pager
  ```

### Étape 2 : Ouvrir les ports dans le pare-feu interne Ubuntu d'Oracle (`iptables`)
Les images Ubuntu d'Oracle Cloud possèdent une règle `iptables` (`REJECT --reject-with icmp-host-prohibited`) qui bloque tout trafic entrant sauf le port 22. Exécutez ces commandes sur votre VPS Ubuntu :

```bash
# Ouvrir les ports 80 (HTTP), 443 (HTTPS) et 8000 (Gunicorn) dans iptables
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT

# Sauvegarder les règles pour qu'elles restent actives au redémarrage
sudo netfilter-persistent save
```

*(Si vous avez activé `ufw`, autorisez aussi les ports avec `sudo ufw allow 80/tcp && sudo ufw allow 8000/tcp`).*

### Étape 3 : Ouvrir les ports dans la console web Oracle Cloud (VCN Ingress Rules)
C'est l'étape la plus souvent oubliée sur Oracle Cloud :
1. Connectez-vous à la console **Oracle Cloud** (https://cloud.oracle.com).
2. Allez dans le menu **Compute** → **Instances** → cliquez sur le nom de votre VPS.
3. Dans la section **Primary VNIC** (à droite), cliquez sur le lien à côté de **Subnet** (ex: `subnet-...`).
4. Sous **Security Lists**, cliquez sur **Default Security List for vcn-...**.
5. Cliquez sur le bouton **Add Ingress Rules** (Ajouter des règles entrantes) et remplissez :
   - **Source Type** : `CIDR`
   - **Source CIDR** : `0.0.0.0/0`
   - **IP Protocol** : `TCP`
   - **Destination Port Range** : `80,443,8000`
6. Validez en cliquant sur **Add Ingress Rules** en bas.

Vous pouvez alors accéder directement à votre site sur :
👉 **`http://IP_DU_SERVEUR:8000`**

### Étape 4 : Configurer Nginx pour accéder au site sans `:8000` (`http://IP_DU_SERVEUR`)
Pour que le site fonctionne directement sur `http://IP_DU_SERVEUR` (port 80 standard) avec les fichiers statiques CSS/JS :

```bash
# 1. Installer Nginx
sudo apt update && sudo apt install -y nginx

# 2. Créer la configuration Nginx (avec prise en charge de /sidiyahia/ et de la Clinique)
sudo tee /etc/nginx/sites-available/clinic > /dev/null <<'EOF'
server {
    listen 80;
    server_name 204.216.108.214 _;

    client_max_body_size 20M;

    location = /favicon.ico { access_log off; log_not_found off; }

    # Site Sidi Yahia dans /var/www/html/sidiyahia
    location /sidiyahia/ {
        root /var/www/html;
        index index.html index.htm;
        try_files $uri $uri/ =404;
    }

    location /static/ {
        alias /var/www/html/clinic/staticfiles/;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

# 3. Activer le site et désactiver la page par défaut de Nginx
sudo ln -sf /etc/nginx/sites-available/clinic /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# 4. Tester et redémarrer Nginx
sudo nginx -t
sudo systemctl restart nginx
sudo systemctl enable nginx
```



