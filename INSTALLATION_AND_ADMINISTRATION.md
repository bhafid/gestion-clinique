# Installation & Administration Manual

## Prerequisites
- **Operating System**: Windows 10/11 (64‑bit)
- **Python** ≥ 3.10
- **PostgreSQL** 13+ (or SQLite for development)
- **Git** (optional, for source control)
- **Node.js** & **npm** (only if you want to compile custom frontend assets).

## Clone the repository
```powershell
git clone https://github.com/bhafid/hospital-management-system.git
cd hospital-management-system
```

## Create a virtual environment & install dependencies
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Configure environment variables
Create a `.env` file at the project root:
```
DJANGO_SECRET_KEY=changeme-very-secret
DJANGO_DEBUG=True   # set to False in production
DJANGO_ALLOWED_HOSTS=localhost 127.0.0.1
DATABASE_URL=postgres://USER:PASSWORD@localhost:5432/hospital_db
```
> For SQLite development you can omit `DATABASE_URL` and Django will fall back to the default `db.sqlite3`.

## Database setup
```powershell
# Create the PostgreSQL database (skip if using SQLite)
createdb hospital_db

# Apply migrations
python manage.py migrate

# Load initial data (core users, groups, permissions)
python manage.py loaddata fixtures/initial_data.json
```

## Create an admin (super‑user)
```powershell
python manage.py createsuperuser
# Follow the prompts (email, password). This user will have full access to the Django admin.
```

## Populate default roles (RBAC)
The project defines a `UserRole` enum in `apps.core.models`. After creating the super‑user, log into the admin site (`/admin/`) and:
1. Navigate to **Custom Users** → edit the super‑user.
2. Set the **role** field to `ADMIN`.
3. Create additional users with roles `MEDECIN`, `CHIRURGIEN`, `INFIRMIER`, `SAGE_FEMME`, `SECRETAIRE` as required.

## Static files
```powershell
python manage.py collectstatic --noinput
```
This gathers CSS/JS (Bootstrap) into the `staticfiles/` directory for production.

## Run the development server
```powershell
python manage.py runserver
```
Visit `http://127.0.0.1:8000/` to see the application.

## Production deployment (recommended)
- Use **Gunicorn** or **Uvicorn** behind **Nginx**.
- Set `DJANGO_DEBUG=False` and configure `DJANGO_ALLOWED_HOSTS`.
- Secure the PostgreSQL connection with SSL.
- Use a process manager (e.g., **systemd**, **Supervisor**) to keep the app alive.
- Enable HTTPS via Let’s Encrypt or a corporate certificate.

### Starting the production server

The recommended way to run the application in production is with **Gunicorn** (or **Uvicorn** for ASGI) behind **Nginx**.

1. **Install Gunicorn** (if not already installed):
   ```powershell
   pip install gunicorn
   ```
2. **Collect static files** (already done, but ensure up‑to‑date):
   ```powershell
   python manage.py collectstatic --noinput
   ```
3. **Run Gunicorn**:
   ```powershell
   gunicorn hospital_system.wsgi:application \
       --bind 0.0.0.0:8000 \
       --workers 3 \
       --log-file -
   ```
   Adjust the number of workers based on your CPU count.

4. **Optional – Systemd service** (create `c:\Program Files\hospital\hospital.service`):
   ```ini
   [Unit]
   Description=Hospital Management System
   After=network.target

   [Service]
   User=your_user
   Group=your_user_group
   WorkingDirectory=C:\Users\hafid\Documents\AL\Clinic
   ExecStart=C:\Users\hafid\Documents\AL\Clinic\venv\Scripts\gunicorn.exe hospital_system.wsgi:application --bind 0.0.0.0:8000 --workers 3
   Restart=on-failure

   [Install]
   WantedBy=multi-user.target
   ```
   Then enable and start:
   ```powershell
   sc.exe create HospitalService binPath= "C:\\Users\\hafid\\Documents\\AL\\Clinic\\venv\\Scripts\\gunicorn.exe hospital_system.wsgi:application --bind 0.0.0.0:8000 --workers 3"
   sc.exe start HospitalService
   ```

5. **Configure Nginx** (or IIS) to proxy requests to `127.0.0.1:8000` and handle HTTPS termination.

These steps will have the server running continuously in production.


## Administration tasks
| Task | Command / Action |
|------|------------------|
| Apply new migrations | `python manage.py migrate` |
| Create a new user | `python manage.py createsuperuser` (or via admin UI) |
| Change a user’s role | Edit the user in `/admin/` → set **role** field |
| Reset password (user) | `python manage.py changepassword <username>` |
| View logs | Check the `logs/` folder or Django’s console output |
| Run test suite | `python manage.py test` |
| Back‑up database | `pg_dump hospital_db > backup.sql` |

---
**End of manual**

