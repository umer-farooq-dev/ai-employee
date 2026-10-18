"""SEED website content (Phase 2). Written once into empty sections by a data migration and published as version 1;
everything is edited in Super Admin → Website Content afterwards. Images point at the template's own files.

Rules for seed text: describe the product only. No customer counts, ratings or testimonials are invented; the
testimonials section starts hidden and empty until real ones are added.
"""

IMG = "/static/website/img/"
BADGE = IMG + "logo/span9.svg"
REGISTER = {"label": "Get Started", "url": "/accounts/signup/"}
DEMO = {"label": "Book a Demo", "url": "/contact/"}


def link(label, url):
    return {"label": label, "url": url}


def heading(badge, text):
    return {"badge_icon": BADGE, "badge_text": badge, "heading": text}


PRICING_LABELS = {
    "per_month_text": "/month",
    "per_year_text": "/year",
    "button_label": "Start free trial",
    "custom_price_text": "Custom",
    "custom_button_label": "Contact us",
}

FAQ_ITEMS = [
    {
        "question": "What is an AI Employee?",
        "answer": "An AI Employee answers calls, WhatsApp messages and website chats for your business 24/7. It "
        "qualifies leads, answers questions from your own information, books appointments and hands over to your "
        "team when needed.",
    },
    {
        "question": "Which languages does it speak?",
        "answer": "Hindi, English and Bengali at launch, including mixed Hinglish. More Indian languages are added "
        "over time.",
    },
    {
        "question": "Does it make up prices or offers?",
        "answer": "No. It answers only from the information you approve. When something is not in your information, "
        "it says it will confirm with your team.",
    },
    {
        "question": "Do I need technical knowledge to set it up?",
        "answer": "No. After registration you get a ready-made AI Employee for your industry. You add your own "
        "information, connect your number and test it before going live.",
    },
]

CONTENT = {
    # ---------------------------------------------------------------- site-wide
    ("site", "header"): {
        "menu": [
            {"label": "How It Works", "url": "/how-it-works/", "new_tab": ""},
            {"label": "Industries", "url": "/industries/", "new_tab": ""},
            {"label": "Features", "url": "/features/", "new_tab": ""},
            {"label": "Pricing", "url": "/pricing/", "new_tab": ""},
            {"label": "Contact", "url": "/contact/", "new_tab": ""},
        ],
        "login_label": "Login",
        "cta": REGISTER,
    },
    ("site", "cta"): {
        "heading": "Hire your first AI Employee today",
        "paragraph": "Answer every call and message, follow up every lead and book more appointments — day and night.",
        "button": REGISTER,
        "image": IMG + "others/cta2-main-img.png",
    },
    ("site", "footer"): {
        "badges": [
            {"icon": IMG + "icons/footer-icon1.png", "text": "Works 24/7 in Indian languages"},
            {"icon": IMG + "icons/footer-icon2.png", "text": "Serious about security & privacy"},
            {"icon": IMG + "icons/footer-icon3.png", "text": "Your data stays separate from every other business"},
        ],
        "links": [
            {"column": "Product", "label": "How It Works", "url": "/how-it-works/"},
            {"column": "Product", "label": "Features", "url": "/features/"},
            {"column": "Product", "label": "Pricing", "url": "/pricing/"},
            {"column": "Product", "label": "AI Employees", "url": "/ai-employees/"},
            {"column": "Company", "label": "About", "url": "/about/"},
            {"column": "Company", "label": "Contact", "url": "/contact/"},
            {"column": "Company", "label": "FAQ", "url": "/faq/"},
            {"column": "Legal", "label": "Terms of Service", "url": "/terms/"},
            {"column": "Legal", "label": "Privacy Policy", "url": "/privacy/"},
            {"column": "Legal", "label": "Refund & Cancellation", "url": "/refund/"},
            {"column": "Legal", "label": "AI Usage Policy", "url": "/ai-usage/"},
        ],
        "bottom_links": [
            {"label": "Privacy", "url": "/privacy/"},
            {"label": "Terms", "url": "/terms/"},
        ],
    },
    # ---------------------------------------------------------------- home
    ("home", "hero"): {
        **heading("Your 24/7 AI workforce", "Hire An AI Employee For Your Business"),
        "paragraph": "It answers calls, WhatsApp and website chats in Hindi, English and Bengali, qualifies your leads "
        "and books appointments — while your team focuses on closing.",
        "button": REGISTER,
        "main_image": IMG + "hero/hero9-main.png",
        "floating_images": [{"image": IMG + f"hero/hero9-img{i}.png"} for i in range(1, 6)],
    },
    ("home", "work"): {
        **heading("One AI Employee, every channel", "Never Miss A Customer Again"),
        "cards": [
            {"tab": "Calls", "title": "Answers every call", "image": IMG + "work/work2-img1.png"},
            {"tab": "Calls", "title": "Calls new leads back", "image": IMG + "work/work2-img2.png"},
            {"tab": "Calls", "title": "Transfers to your team", "image": IMG + "work/work2-img3.png"},
            {"tab": "WhatsApp", "title": "Replies in seconds", "image": IMG + "work/work2-img1.png"},
            {"tab": "WhatsApp", "title": "Shares details and brochures", "image": IMG + "work/work2-img2.png"},
            {"tab": "WhatsApp", "title": "Follows up automatically", "image": IMG + "work/work2-img3.png"},
            {"tab": "Website", "title": "Chats with visitors", "image": IMG + "work/work2-img1.png"},
            {"tab": "Website", "title": "Captures enquiries", "image": IMG + "work/work2-img2.png"},
            {"tab": "Website", "title": "Books appointments", "image": IMG + "work/work2-img3.png"},
        ],
    },
    ("home", "counters"): {
        "items": [
            {"number": 24, "suffix": "/7", "label": "Always available"},
            {"number": 3, "suffix": "", "label": "Channels: calls, WhatsApp, chat"},
            {"number": 3, "suffix": "", "label": "Languages at launch"},
            {"number": 3, "suffix": "", "label": "Industries ready to go"},
        ],
    },
    ("home", "features"): {
        **heading("What it does", "Work Your AI Employee Does For You"),
        "cards": [
            {
                "title": "Qualifies every lead",
                "text": "Asks your questions — budget, location, timeline — and scores each lead.",
                "image": IMG + "work/work-prosses7-img1.png",
                "url": "/features/",
            },
            {
                "title": "Books appointments",
                "text": "Finds a free slot in your built-in calendar and confirms it with the customer.",
                "image": IMG + "work/work-prosses7-img2.png",
                "url": "/features/",
            },
            {
                "title": "Built-in CRM",
                "text": "Every call and chat lands in your CRM with a summary.",
                "image": IMG + "work/work-prosses7-img3.png",
                "url": "/features/",
            },
            {
                "title": "Follows up",
                "text": "Reminds and re-engages leads so none go cold.",
                "image": IMG + "work/work-prosses7-img4.png",
                "url": "/features/",
            },
            {
                "title": "Hands over to humans",
                "text": "Transfers hot leads and tricky questions to your team.",
                "image": IMG + "work/work-prosses7-img5.png",
                "url": "/features/",
            },
        ],
    },
    ("home", "benefits"): {
        **heading("Why businesses choose it", "Benefits For Your Business"),
        "boxes": [
            {
                "icon": IMG + "icons/system-icon1.svg",
                "title": "Speaks your customers' language",
                "text": "Hindi, English, Bengali and mixed Hinglish.",
                "url": "",
            },
            {
                "icon": IMG + "icons/system-icon2.svg",
                "title": "Answers only from your facts",
                "text": "No invented prices or offers.",
                "url": "",
            },
            {
                "icon": IMG + "icons/system-icon3.svg",
                "title": "Safe and secure",
                "text": "Your data is kept separate and encrypted.",
                "url": "",
            },
            {
                "icon": IMG + "icons/system-icon4.svg",
                "title": "Ready for your industry",
                "text": "Real estate, travel, education and more.",
                "url": "/industries/",
            },
        ],
        "centre_image": IMG + "others/system9-img1.png",
        "secondary_image": IMG + "others/system9-img2.png",
    },
    ("home", "solution"): {
        "image": IMG + "others/hr-solution-img.png",
        "badge_text": "Ready in minutes",
        "heading": "A Ready-Made AI Employee For Your Industry",
        "paragraph": "Register your business and get an AI Employee already trained for your industry. Add your own "
        "information, connect your phone or WhatsApp number, test it and go live.",
        "button": link("See how it works", "/how-it-works/"),
    },
    ("home", "testimonials"): {**heading("Testimonials", "What Our Customers Say"), "items": []},
    ("home", "pricing"): {
        **heading("Pricing", "Simple Plans For Every Business"),
        "subtext": "Start with a free trial. Prices exclude GST.",
        "monthly_label": "Monthly",
        "yearly_label": "Yearly",
        "yearly_saving_text": "",
        **PRICING_LABELS,
    },
    ("home", "industries"): {
        **heading("Industries", "Built For Your Industry"),
        "intro": "Each industry gets an AI Employee that already knows the right questions to ask.",
        "link_label": "Learn more",
    },
    ("home", "faq"): {**heading("FAQ", "Frequently Asked Questions"), "items": FAQ_ITEMS},
    # ---------------------------------------------------------------- legal (text written by the client's legal team)
    **{
        (key, "rich_text"): {
            "heading": title,
            "body": "<p>This page will be published by the platform team. "
            "Edit it in Super Admin → Website Content.</p>",
        }
        for key, title in (
            ("terms", "Terms of Service"),
            ("privacy", "Privacy Policy"),
            ("refund", "Refund & Cancellation Policy"),
            ("ai-usage", "Acceptable Use / AI Usage Policy"),
        )
    },
    # ---------------------------------------------------------------- inner pages
    ("not-found", "page_hero"): {
        "heading": "Page not found",
        "paragraph": "The page you are looking for has moved or does not exist.",
        "button": {"label": "Back to home", "url": "/"},
        "button2": DEMO,
        "image": "",
    },
    ("how-it-works", "page_hero"): {
        "heading": "How It Works",
        "paragraph": "From registration to a working AI Employee in a few simple steps.",
        "button": REGISTER,
        "button2": DEMO,
        "image": IMG + "about/about-main-img.png",
    },
    ("how-it-works", "steps"): {
        **heading("Step by step", "Your AI Employee In Five Steps"),
        "items": [
            {
                "badge": "Step 1",
                "title": "Register your business",
                "text": "Enter your business details and choose your industry. Our team reviews and approves your "
                "account.",
                "image": IMG + "features/features-page-stapes1.png",
                "button": REGISTER,
            },
            {
                "badge": "Step 2",
                "title": "Get a ready-made AI Employee",
                "text": "An AI Employee for your industry is created for you, with the right questions and greetings.",
                "image": IMG + "features/features-page-stapes2.png",
                "button": {"label": "", "url": ""},
            },
            {
                "badge": "Step 3",
                "title": "Add your knowledge",
                "text": "Upload your brochures, price lists and FAQs, or add your properties, packages or courses.",
                "image": IMG + "features/features-page-stapes1.png",
                "button": {"label": "", "url": ""},
            },
            {
                "badge": "Step 4",
                "title": "Connect and test",
                "text": "Connect your phone number, WhatsApp and website chat, then test it yourself.",
                "image": IMG + "features/features-page-stapes2.png",
                "button": {"label": "", "url": ""},
            },
            {
                "badge": "Step 5",
                "title": "Go live",
                "text": "Activate it. Your AI Employee works 24/7 and every lead lands in your CRM.",
                "image": IMG + "features/features-page-stapes1.png",
                "button": DEMO,
            },
        ],
    },
    ("ai-employees", "page_hero"): {
        "heading": "AI Employee Types",
        "paragraph": "Pick the role you need. Each one comes trained for your industry.",
        "button": REGISTER,
        "button2": DEMO,
        "image": IMG + "about/about-main-img.png",
    },
    ("ai-employees", "card_grid"): {
        **heading("Roles", "Choose Your AI Employee"),
        "intro": "",
        "cards": [
            {
                "icon": IMG + "icons/features-icon1.png",
                "title": "Sales Executive",
                "text": "Calls and messages new leads, qualifies them and books visits or demos.",
                "url": "",
            },
            {
                "icon": IMG + "icons/features-icon2.png",
                "title": "Receptionist",
                "text": "Answers every incoming call and chat and routes it to the right person.",
                "url": "",
            },
            {
                "icon": IMG + "icons/features-icon3.png",
                "title": "Customer Support",
                "text": "Answers common questions from your information, day and night.",
                "url": "",
            },
            {
                "icon": IMG + "icons/features-icon4.png",
                "title": "Appointment Setter",
                "text": "Books, confirms and reminds appointments in your calendar.",
                "url": "",
            },
        ],
    },
    ("ai-employees", "faq"): {**heading("FAQ", "Questions About AI Employees"), "items": FAQ_ITEMS[:2]},
    ("industries", "page_hero"): {
        "heading": "Industries",
        "paragraph": "AI Employees trained for the way your industry sells.",
        "button": REGISTER,
        "button2": DEMO,
        "image": IMG + "about/about-main-img.png",
    },
    ("industries", "industries"): {
        **heading("Industries", "Choose Your Industry"),
        "intro": "",
        "link_label": "Learn more",
    },
    ("features", "page_hero"): {
        "heading": "Features",
        "paragraph": "Everything your AI Employee needs to win more customers.",
        "button": REGISTER,
        "button2": DEMO,
        "image": IMG + "about/about-main-img.png",
    },
    ("features", "steps"): {
        **heading("Features", "One Platform, Every Channel"),
        "items": [
            {
                "badge": "Voice",
                "title": "Human-like phone calls",
                "text": "Answers and makes calls in Indian languages, transfers to your team when needed.",
                "image": IMG + "features/features-page-stapes1.png",
                "button": {"label": "", "url": ""},
            },
            {
                "badge": "WhatsApp",
                "title": "Instant WhatsApp replies",
                "text": "Replies in seconds, shares details and follows up automatically.",
                "image": IMG + "features/features-page-stapes2.png",
                "button": {"label": "", "url": ""},
            },
            {
                "badge": "Website chat",
                "title": "Chat on your website",
                "text": "Talks to visitors, captures enquiries and books appointments.",
                "image": IMG + "features/features-page-stapes1.png",
                "button": {"label": "", "url": ""},
            },
            {
                "badge": "CRM & Calendar",
                "title": "Built-in CRM and calendar",
                "text": "Every lead, conversation and appointment in one place.",
                "image": IMG + "features/features-page-stapes2.png",
                "button": {"label": "", "url": ""},
            },
            {
                "badge": "Campaigns & Analytics",
                "title": "Campaigns and reports",
                "text": "Reach your leads at the right time and see what works.",
                "image": IMG + "features/features-page-stapes1.png",
                "button": REGISTER,
            },
        ],
    },
    ("pricing", "page_hero"): {
        "heading": "Pricing",
        "paragraph": "Simple plans. Start with a free trial.",
        "button": REGISTER,
        "button2": DEMO,
        "image": IMG + "about/about-main-img.png",
    },
    ("pricing", "pricing"): {
        **heading("Plans", "Choose Your Plan"),
        "subtext": "Prices exclude GST.",
        "monthly_label": "Monthly",
        "yearly_label": "Yearly",
        "yearly_saving_text": "",
        **PRICING_LABELS,
    },
    ("pricing", "faq"): {**heading("FAQ", "Pricing Questions"), "items": []},
    ("about", "page_hero"): {
        "heading": "About Us",
        "paragraph": "We help Indian businesses answer every customer, every time.",
        "button": DEMO,
        "button2": {"label": "", "url": ""},
        "image": IMG + "about/about-main-img.png",
    },
    ("about", "solution"): {
        "image": IMG + "about/about-page-img1.png",
        "badge_text": "Our mission",
        "heading": "A 24/7 AI Workforce For Every Business",
        "paragraph": "Small and growing businesses lose customers when calls and messages go unanswered. Our AI "
        "Employees make sure every customer gets a fast, helpful answer in their own language.",
        "button": REGISTER,
    },
    ("about", "counters"): {
        "items": [
            {"number": 24, "suffix": "/7", "label": "Always available"},
            {"number": 3, "suffix": "", "label": "Channels"},
            {"number": 3, "suffix": "", "label": "Languages at launch"},
        ]
    },
    ("about", "card_grid"): {
        **heading("Our values", "What We Stand For"),
        "intro": "",
        "cards": [
            {
                "icon": IMG + "icons/about-page-sec-icon1.png",
                "title": "Honest answers",
                "text": "AI Employees answer only from facts you approve.",
                "url": "",
            },
            {
                "icon": IMG + "icons/about-page-sec-icon2.png",
                "title": "Privacy first",
                "text": "Every business's data is kept separate and secure.",
                "url": "",
            },
            {
                "icon": IMG + "icons/about-page-sec-icon3.png",
                "title": "Built for India",
                "text": "Indian languages, Indian numbers, Indian businesses.",
                "url": "",
            },
        ],
    },
    ("contact", "contact"): {
        "heading": "Contact Us / Book a Demo",
        "paragraph": "Tell us about your business and we will show you how an AI Employee can help.",
        "form_heading": "Send us a message",
        "form_text": "We usually reply within one working day.",
        "button_label": "Send",
        "success_message": "Thank you! We have received your message and will contact you soon.",
        "hours_text": "Mon – Sat: 10am to 7pm",
    },
    ("faq", "page_hero"): {
        "heading": "Frequently Asked Questions",
        "paragraph": "Answers to common questions about AI Employees.",
        "button": DEMO,
        "button2": {"label": "", "url": ""},
        "image": IMG + "about/about-main-img.png",
    },
    ("faq", "faq"): {**heading("FAQ", "Everything You Need To Know"), "items": FAQ_ITEMS},
}

# Sections that start hidden until the platform team adds real content.
HIDDEN = {("home", "testimonials")}

# SEED industries (MVP: real estate, travel, education). More are added in Super Admin.
INDUSTRIES = [
    (
        "real-estate",
        "Real Estate",
        "Qualify property enquiries and book site visits.",
        "<p>Your AI Employee answers property enquiries, asks about budget, location and BHK, shares matching "
        "properties and books site visits.</p>",
        IMG + "icons/service3-icon1.png",
    ),
    (
        "travel",
        "Travel",
        "Answer package enquiries and capture bookings.",
        "<p>Your AI Employee answers questions about packages, dates and prices, collects traveller details and passes "
        "ready-to-book leads to your team.</p>",
        IMG + "icons/service3-icon2.png",
    ),
    (
        "education",
        "Education",
        "Guide students and book counselling sessions.",
        "<p>Your AI Employee explains courses, fees and admissions, qualifies students and books counselling "
        "sessions.</p>",
        IMG + "icons/features-icon3.png",
    ),
]
