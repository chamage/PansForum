from django.core.management.base import BaseCommand
from django.utils.text import slugify

from forum.models import Community

DEFAULTS = [
    ("General", "Introductions, announcements and anything about student life at PANS."),
    ("Study Help", "Stuck on homework or a concept? Ask here — explain what you've tried."),
    ("Computer Science", "Programming, algorithms, projects and tech talk."),
    ("Mathematics", "Calculus, algebra, statistics and friends."),
    ("Engineering", "Mechanical, electrical, civil — all engineering disciplines welcome."),
    ("Languages", "Language exchange, practice partners and tips."),
    ("Campus Life", "Events, clubs, dorms, food and everything around campus."),
    ("Jobs and Internships", "Internship offers, CV reviews and career advice."),
    ("Off-topic", "Memes, hobbies and everything else."),
]


class Command(BaseCommand):
    help = "Create the default set of communities (safe to run repeatedly)."

    def handle(self, *args, **options):
        created = 0
        for name, description in DEFAULTS:
            _, was_created = Community.objects.get_or_create(
                slug=slugify(name), defaults={"name": name, "description": description}
            )
            created += was_created
        self.stdout.write(self.style.SUCCESS(f"{created} new communities created."))
