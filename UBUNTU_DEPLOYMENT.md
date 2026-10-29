# Ubuntu Server Deployment

This guide deploys the Django application with PostgreSQL, Gunicorn, systemd, and Nginx. Use a domain name that points to your server before enabling HTTPS.

> The project defaults to development settings and SQLite. Do not expose it publicly until you have configured the production environment variables below. If you handle real patient data, use hosting and operational controls appropriate to your legal and regulatory requirements; this guide alone does not establish HDS or other certification.

## 1. Install system packages

SSH into the Ubuntu server and run:

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip nginx postgresql postgresql-contrib git
```

## 2. Create the PostgreSQL database

Open the PostgreSQL prompt:

```bash
sudo -u postgres psql
```

Create a database user and database, then exit:

```sql
CREATE USER hospital_user WITH PASSWORD 'replace-with-a-long-unique-password';
CREATE DATABASE hospital_db OWNER hospital_user;
\q
```

Keep the database password private.

## 3. Clone the project and install Python dependencies

```bash
sudo mkdir -p /srv/gestion-clinique
sudo chown "$USER":"$USER" /srv/gestion-clinique
git clone https://github.com/bhafid/gestion-clinique.git /srv/gestion-clinique
cd /srv/gestion-clinique

python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
```

If the repository contains a dependency file, use it:

```bash
pip install -r requirements.txt
```

Otherwise install the packages required for this deployment:

```bash
pip install Django gunicorn "psycopg[binary]"
```

## 4. Configure production environment variables

Generate a secret key:

```bash
venv/bin/python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
```

Create an environment file:

```bash
sudo nano /etc/gestion-clinique.env
```

Add the following, replacing the example domain, generated secret, and database password. Do not put spaces between the comma-separated host names.

```ini
DJANGO_SECRET_KEY=paste-the-generated-secret-here
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=example.com,www.example.com
POSTGRES_DB=hospital_db
POSTGRES_USER=hospital_user
POSTGRES_PASSWORD=replace-with-a-long-unique-password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_SSLMODE=prefer
```

Protect the file:

```bash
sudo chmod 600 /etc/gestion-clinique.env
```

The project reads `DJANGO_ALLOWED_HOSTS` as a comma-separated list. `POSTGRES_DB` enables PostgreSQL instead of the default SQLite database.

## 5. Configure Django for Nginx HTTPS proxying

In `hospital_system/settings.py`, add this setting so Django recognizes HTTPS requests forwarded by Nginx:

```python
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
```

Only use this setting when the app is behind a trusted reverse proxy that sets the `X-Forwarded-Proto` header, as the Nginx configuration below does.

## 6. Run migrations and prepare static files

From the project directory:

```bash
source venv/bin/activate
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
python manage.py check --deploy
```

Review and resolve any deployment warnings reported by `check --deploy` before going live. Do not load development/test seed data into a production database.

## 7. Configure Gunicorn with systemd

Create the service file:

```bash
sudo nano /etc/systemd/system/gestion-clinique.service
```

Use this configuration:

```ini
[Unit]
Description=Gestion Clinique Django application
After=network.target postgresql.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/srv/gestion-clinique
EnvironmentFile=/etc/gestion-clinique.env
ExecStart=/srv/gestion-clinique/venv/bin/gunicorn hospital_system.wsgi:application --bind 127.0.0.1:8000 --workers 3
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Give the service user access to the project, then start the service:

```bash
sudo chown -R www-data:www-data /srv/gestion-clinique
sudo systemctl daemon-reload
sudo systemctl enable --now gestion-clinique
sudo systemctl status gestion-clinique
```

If the service fails, inspect its logs:

```bash
sudo journalctl -u gestion-clinique -n 100 --no-pager
```

## 8. Configure Nginx

Create an Nginx site configuration:

```bash
sudo nano /etc/nginx/sites-available/gestion-clinique
```

Add the following, replacing the domain:

```nginx
server {
    listen 80;
    server_name example.com www.example.com;

    location /static/ {
        alias /srv/gestion-clinique/staticfiles/;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable the site and verify the Nginx configuration:

```bash
sudo ln -s /etc/nginx/sites-available/gestion-clinique /etc/nginx/sites-enabled/gestion-clinique
sudo nginx -t
sudo systemctl reload nginx
```

Ensure your domain's DNS records point to the server. If UFW is enabled, allow web traffic:

```bash
sudo ufw allow 'Nginx Full'
```

## 9. Enable HTTPS

Install Certbot and obtain a Let's Encrypt certificate:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d example.com -d www.example.com
```

Follow the prompts and replace the example domains with your own. Verify certificate renewal:

```bash
sudo certbot renew --dry-run
```

## Useful operations

Restart the app after deployment changes:

```bash
sudo systemctl restart gestion-clinique
```

View application service logs:

```bash
sudo journalctl -u gestion-clinique -f
```

After deploying updated code, run migrations and collect static files as needed:

```bash
cd /srv/gestion-clinique
sudo -u www-data /srv/gestion-clinique/venv/bin/python manage.py migrate
sudo -u www-data /srv/gestion-clinique/venv/bin/python manage.py collectstatic --noinput
sudo systemctl restart gestion-clinique
```
