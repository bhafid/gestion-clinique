"""ASGI config for hospital_system project."""
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hospital_system.settings")

application = get_asgi_application()

