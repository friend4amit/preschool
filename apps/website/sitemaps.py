from django.contrib.sitemaps import Sitemap
from django.urls import reverse


class StaticViewSitemap(Sitemap):
    """The public pages. Priorities reflect what an admissions search should land on."""

    protocol = "https"
    changefreq = "monthly"

    PRIORITIES = {"home": 1.0, "programs": 0.9, "contact": 0.9, "about": 0.8}

    def items(self) -> list[str]:
        return ["home", "about", "approach", "programs", "team", "special_education", "contact"]

    def location(self, item: str) -> str:
        return reverse(item)

    def priority(self, item: str) -> float:
        return self.PRIORITIES.get(item, 0.6)
