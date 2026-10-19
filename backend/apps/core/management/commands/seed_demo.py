"""Demo data for testing and client demos: leads, tasks, a calendar with appointments, catalogue items, approved FAQs,
website enquiries and a company waiting for approval. Everything goes through the normal services (scoring, audit,
numbering), and every row is marked "demo" so it is easy to find. Refuses to run in production; runs once per company.

    python manage.py seed_demo --company "Ib Home"
"""

import datetime
import random

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.providers.services import production

rng = random.Random()  # nosec B311 — demo data only, not security related

FIRST = [
    "Rohit",
    "Priya",
    "Amit",
    "Sneha",
    "Vikram",
    "Anjali",
    "Rahul",
    "Pooja",
    "Arjun",
    "Kavita",
    "Sanjay",
    "Neha",
    "Manish",
    "Ritu",
    "Deepak",
    "Swati",
    "Karan",
    "Meera",
    "Ajay",
    "Divya",
    "Suresh",
    "Nisha",
    "Rakesh",
    "Shreya",
]
LAST = ["Sharma", "Verma", "Gupta", "Singh", "Mehta", "Iyer", "Banerjee", "Das", "Reddy", "Kapoor", "Joshi", "Nair"]
CITIES = ["Noida", "Gurgaon", "Greater Noida", "Dwarka", "Ghaziabad", "Faridabad", "Noida Extension", "Sector 150"]
NOTES = [
    "Wants a park-facing flat",
    "Looking for ready to move",
    "Prefers east facing",
    "Needs home loan help",
    "Visiting with family on Sunday",
    "Comparing two projects",
]
PROPERTIES = [
    ("Skyline Residency", "Gaurs Group", "Noida Extension", "Apartment", "2 BHK", "58 lakh", 1050, "Ready to move"),
    ("Green Valley Homes", "Mahagun", "Sector 150", "Apartment", "3 BHK", "1.2 crore", 1650, "Within 6 months"),
    ("Royal Palms", "ATS", "Greater Noida", "Villa", "4 BHK", "2.4 crore", 3200, "6-12 months"),
    ("Urban Nest", "Supertech", "Noida", "Apartment", "1 BHK", "35 lakh", 620, "Ready to move"),
    ("Lake View Towers", "Godrej", "Gurgaon", "Apartment", "3 BHK", "1.6 crore", 1820, "1-2 years"),
    ("Sunrise Plots", "DLF", "Faridabad", "Plot", "", "75 lakh", 2000, "Ready to move"),
    ("Metro Heights", "M3M", "Dwarka", "Apartment", "2 BHK", "92 lakh", 1180, "Within 6 months"),
    ("Silver Oak Villas", "Ace", "Greater Noida", "Villa", "5+ BHK", "3.1 crore", 4100, "2+ years"),
]
FAQS = [
    ("Do you help with home loans?", "Yes. We work with SBI, HDFC and ICICI and our team helps with the paperwork."),
    ("What are your office hours?", "Monday to Saturday, 10 am to 7 pm. Site visits are also possible on Sundays."),
    ("Is there a brokerage fee?", "No brokerage for projects we market directly. Resale properties have a 1% fee."),
    ("Can I visit a site on the weekend?", "Yes, weekend site visits can be booked; we arrange a pick-up on request."),
    (
        "Are the projects RERA registered?",
        "Yes, every project we list is RERA registered; ask us for the number.",
    ),
]


class Command(BaseCommand):
    help = "Create demo data (leads, tasks, calendar, catalogue, FAQs, enquiries, a pending company) for testing."

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True, help="Company name or slug")

    def handle(self, *args, **options):
        if production():
            raise CommandError("Demo data is never created in production.")
        from apps.tenancy.context import company_context, platform_context
        from apps.tenancy.models import Company

        with platform_context():
            company = (
                Company.objects.filter(name=options["company"]).first()
                or Company.objects.filter(slug=options["company"]).first()
            )
        if not company:
            raise CommandError(f"No company {options['company']!r}.")
        rng.seed(7)
        with company_context(company.id):
            from apps.crm.models import Lead

            if Lead.objects.filter(company=company, tags__contains=["demo"]).exists():
                self.stdout.write("Demo data already exists for this company — nothing to do.")
                return
            leads = self._leads(company)
            self._tasks(company, leads)
            self._calendar(company, leads)
            self._catalogue(company)
            self._faqs(company)
        self._platform()
        self.stdout.write(self.style.SUCCESS(f"Demo data created for {company.name}."))

    # ------------------------------------------------------------------ company data
    def _leads(self, company):
        from apps.crm import services as crm
        from apps.crm.models import Lead
        from apps.industries import services as templates

        statuses = {s.key: s for s in templates.statuses(company)}
        plan = ["new"] * 6 + [
            "calling",
            "connected",
            "qualified",
            "qualified",
            "hot",
            "hot",
            "warm",
            "warm",
            "warm",
            "cold",
            "follow_up",
            "follow_up",
            "appointment",
            "appointment",
            "converted",
            "not_interested",
            "new",
            "connected",
        ]
        leads, now = [], timezone.now()
        for i, key in enumerate(plan):
            name = f"{FIRST[i % len(FIRST)]} {LAST[i % len(LAST)]}"
            data = {
                "name": name,
                "phone": f"+9198{rng.randint(10000000, 99999999)}",
                "email": f"{name.split()[0].lower()}.{name.split()[1].lower()}{i}@example.com",
                "source": rng.choice(["inbound_call", "website_chat", "whatsapp", "manual", "import"]),
                "tags": ["demo"],
                "custom": {
                    "budget": rng.choice(["45 lakh", "65 lakh", "85 lakh", "1.2 crore", "2 crore"]),
                    "location": rng.choice(CITIES),
                    "bhk": rng.choice(["1 BHK", "2 BHK", "3 BHK", "4 BHK"]),
                    "property_type": rng.choice(["Apartment", "Apartment", "Villa", "Plot"]),
                    "purpose": rng.choice(["Self use", "Investment"]),
                    "timeline": rng.choice(["Within 30 days", "1-3 months", "3-6 months", "Just exploring"]),
                },
            }
            if key in statuses:
                data["status"] = statuses[key]
            try:
                lead = crm.create_lead(company, data, created_via="import")
            except (ValidationError, crm.DuplicateLead) as exc:
                self.stderr.write(f"lead skipped: {exc}")
                continue
            if i % 3 == 0:
                crm.add_note(lead, rng.choice(NOTES))
            Lead.objects.filter(pk=lead.pk).update(created_at=now - datetime.timedelta(days=i % 19, hours=i))
            leads.append(lead)
        self.stdout.write(f"  {len(leads)} leads")
        return leads

    def _tasks(self, company, leads):
        from apps.crm import services as crm

        now = timezone.now()
        for i, lead in enumerate(leads[:8]):
            due = now + datetime.timedelta(hours=-20 + i * 9)  # a couple overdue, the rest coming up
            crm.create_task(
                company, {"title": f"Call back {lead.name}", "due_at": due, "lead": lead, "type": "callback"}
            )
        self.stdout.write("  8 follow-up tasks")

    def _calendar(self, company, leads):
        from apps.industries import services as templates
        from apps.scheduling import services as calendar

        types = templates.appointment_types(company)
        if not types:
            return
        hours = {d: [["10:00", "19:00"]] for d in ("mon", "tue", "wed", "thu", "fri", "sat")}
        resource = calendar.save_resource(
            company,
            {
                "name": "Site visits — Noida office",
                "kind": "location",
                "working_hours": hours,
                "appointment_types": [t.key for t in types],
            },
        )
        from apps.agents.tools import company_tz

        tz = company_tz(company)
        booked, day = 0, timezone.localtime(timezone.now(), tz).date()
        for lead in leads[-10:]:
            day += datetime.timedelta(days=1)
            start = datetime.datetime.combine(day, datetime.time(11 + booked % 5, 0), tzinfo=tz)
            try:
                calendar.book(company, resource, types[0], start, lead=lead, location="Noida office, Sector 62")
                booked += 1
            except ValidationError:
                continue
            if booked == 6:
                break
        self.stdout.write(f"  calendar + {booked} appointments")

    def _catalogue(self, company):
        from apps.catalog import services as catalog
        from apps.industries import services as templates

        ctypes = templates.catalog_types(company)
        if not ctypes or ctypes[0].key != "property":
            return
        for name, builder, loc, ptype, bhk, price, area, possession in PROPERTIES:
            values = {
                "project_name": name,
                "builder": builder,
                "location": loc,
                "property_type": ptype,
                "price": price,
                "area": area,
                "possession": possession,
                "availability": "Available",
                "amenities": ["Parking", "Lift", "Gym"],
                "description": f"{ptype} by {builder} in {loc}.",
            }
            if bhk:
                values["bhk"] = bhk
            try:
                catalog.create_item(company, ctypes[0], values)
            except ValidationError as exc:
                self.stderr.write(f"item skipped: {exc}")
        self.stdout.write(f"  {len(PROPERTIES)} catalogue items")

    def _faqs(self, company):
        from apps.knowledge import services as knowledge
        from apps.knowledge.models import Source

        source = knowledge.create_source(company, {"type": Source.FAQ, "title": "Common questions (demo)"})
        for q, a in FAQS:
            knowledge.save_faq(source, {"question": q, "answer": a, "approved": True})
        self.stdout.write(f"  {len(FAQS)} approved FAQs")

    # ------------------------------------------------------------------ Super Admin data
    def _platform(self):
        from apps.accounts.models import User
        from apps.industries.models import Industry
        from apps.tenancy.context import platform_context
        from apps.tenancy.services import register_company
        from apps.website import services as website

        with platform_context():
            for i, (name, biz) in enumerate(
                [
                    ("Anil Kumar", "Kumar Realty"),
                    ("Farah Khan", "Skyway Tours"),
                    ("Joseph Mathew", "Bright Minds Academy"),
                ]
            ):
                website.create_enquiry(
                    {
                        "name": name,
                        "business_name": biz,
                        "phone": f"+91981234567{i}",
                        "email": f"{name.split()[0].lower()}@example.com",
                        "message": "We would like a demo of the AI Employee for our business.",
                    }
                )
            if not User.objects.filter(email="owner@sunrise-travels.example").exists():
                owner = User.objects.create_user(
                    "owner@sunrise-travels.example", full_name="Meena Pillai", phone="+919812300001"
                )
                register_company(
                    owner,
                    {
                        "business_name": "Sunrise Travels (demo)",
                        "industry": Industry.objects.filter(key="travel").first(),
                        "city": "Kochi",
                        "state": "Kerala",
                        "business_size": "11-50",
                    },
                )
        self.stdout.write("  3 website enquiries + 1 company waiting for approval")
