from datetime import date

from allauth.account.adapter import get_adapter

from . import services


def platform(request):
    """SA-23: General Settings available to every template as {{ platform.* }} (website, panels, auth pages)."""
    values = services.get_all()
    data = {
        key.split(".", 1)[1]: value
        for key, value in values.items()
        if key.startswith(("general.", "contact.", "seo.", "locale."))
    }
    data["copyright"] = (data.get("copyright") or "").replace("{year}", str(date.today().year))
    data["signup_open"] = get_adapter(request).is_open_for_signup(request)
    return {"platform": data}
