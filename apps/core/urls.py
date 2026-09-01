"""Auth routes. There is no signup path here, and that is deliberate: every account
in this system is created by an admin who hands over a one-time set-password link."""

from django.contrib.auth import views as auth_views
from django.urls import path

from apps.core import views

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    # Django 5's LogoutView is POST-only — a GET logout is a CSRF liability, and a
    # prefetching browser extension can hit it. The layouts post a form.
    path("logout/", auth_views.LogoutView.as_view(next_page="login"), name="logout"),
    path("welcome/", views.after_login, name="after_login"),
    path("set-password/<uid>/<token>/", views.set_password, name="set_password"),
]
