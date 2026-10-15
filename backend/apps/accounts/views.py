from allauth.account.views import SignupView as BaseSignupView
from django.shortcuts import render


class SignupView(BaseSignupView):
    """Company registration. A visitor who is already signed in (e.g. as staff in another tab of the same browser)
    is told so and offered to log out, instead of being silently redirected to their own panel."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return render(request, "account/signup_signed_in.html")
        return super().dispatch(request, *args, **kwargs)
