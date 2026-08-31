from django.urls import path

from apps.website import views

urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("our-approach/", views.approach, name="approach"),
    path("programmes/", views.programs, name="programs"),
    path("our-team/", views.team, name="team"),
    path("thoughtful-education/", views.special_education, name="special_education"),
    path("contact/", views.contact, name="contact"),
]
