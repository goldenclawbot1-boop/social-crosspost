from fastapi.templating import Jinja2Templates
from pathlib import Path

templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

# Make settings available in all templates
from app.config import settings as app_settings
templates.env.globals["settings"] = app_settings
templates.env.globals["app_name"] = app_settings.APP_NAME
