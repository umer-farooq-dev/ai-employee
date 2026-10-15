"""SEED data for Phase 3 (written once by data migrations, edited in Super Admin afterwards).

IND-06 MVP templates (Real Estate, Travel & Tours, Education), CRM-02 statuses, CRM-03 sources, ROLE-01 roles.
Catalogue fields for travel packages and courses are the PRD proposals, to be finalised with the client.
"""


def f(key, label, type="text", **extra):
    return {"key": key, "label": label, "type": type, **extra}


def q(field, en, hi, bn):
    return {"field": field, "question": {"en": en, "hi": hi, "bn": bn}}


STATUSES = [
    # key, label, colour, category
    ("new", "New", "#6c757d", "open"),
    ("calling", "Calling", "#0d6efd", "open"),
    ("connected", "Connected", "#0dcaf0", "open"),
    ("qualified", "Qualified", "#6f42c1", "open"),
    ("hot", "Hot", "#dc3545", "open"),
    ("warm", "Warm", "#fd7e14", "open"),
    ("cold", "Cold", "#5c7cfa", "open"),
    ("follow_up", "Follow-up", "#ffc107", "open"),
    ("appointment", "Appointment", "#20c997", "open"),
    ("converted", "Converted", "#198754", "won"),
    ("not_interested", "Not Interested", "#343a40", "lost"),
]

SOURCES = [
    ("inbound_call", "Inbound Call"),
    ("outbound_campaign", "Outbound Campaign"),
    ("whatsapp", "WhatsApp"),
    ("website_chat", "Website Chat"),
    ("manual", "Manual"),
    ("import", "Import"),
]

ALL_CHANNELS = ["inbound_voice", "outbound_voice", "whatsapp", "web_chat"]
ROLES = [
    (
        "sales_executive",
        "Sales Executive",
        "Calls and messages new leads, qualifies them and books visits or demos.",
        "Qualify the lead with the industry questions, recommend matching options and book an appointment.",
        ALL_CHANNELS,
    ),
    (
        "receptionist",
        "Receptionist",
        "Answers every incoming call and chat and routes it to the right person.",
        "Greet, understand the need, capture contact details and route or book as needed.",
        ["inbound_voice", "whatsapp", "web_chat"],
    ),
    (
        "customer_support",
        "Customer Support",
        "Answers common questions from approved company information.",
        "Answer only from approved knowledge. When unsure, promise a callback and create a follow-up task.",
        ["inbound_voice", "whatsapp", "web_chat"],
    ),
    (
        "appointment_setter",
        "Appointment Setter",
        "Books, confirms and reschedules appointments.",
        "Find a suitable slot in the calendar, confirm it and record it on the lead.",
        ALL_CHANNELS,
    ),
]

TIMELINE = ["Within 30 days", "1-3 months", "3-6 months", "Just exploring"]
TRANSITIONS = {
    "call_started": "calling",
    "call_connected": "connected",
    "qualified": "qualified",
    "appointment_booked": "appointment",
    "not_interested": "not_interested",
    "converted": "converted",
}
COMMON_HANDOFF = [
    {"trigger": "Customer asks for a human", "action": "Transfer to an available agent, else create a callback task"},
    {"trigger": "Complaint or angry customer", "action": "Apologise and transfer to a human"},
    {"trigger": "Price negotiation or discount request", "action": "Do not promise; hand over to the sales team"},
]
DISCLOSURE = {
    "en": "I am {{ employee_name }}, an AI assistant for {{ company_name }}. This call may be recorded.",
    "hi": "मैं {{ employee_name }}, {{ company_name }} की AI सहायक हूँ। यह कॉल रिकॉर्ड हो सकती है।",
    "bn": "আমি {{ employee_name }}, {{ company_name }}-এর একজন AI সহকারী। এই কলটি রেকর্ড করা হতে পারে।",
}


def greetings(topic_en, topic_hi, topic_bn):
    return {
        "en": f"Hello! Thank you for contacting {{{{ company_name }}}}. How can I help you with {topic_en} today?",
        "hi": f"नमस्ते! {{{{ company_name }}}} से संपर्क करने के लिए धन्यवाद। {topic_hi} में मैं आपकी क्या मदद कर सकती हूँ?",
        "bn": f"নমস্কার! {{{{ company_name }}}}-এর সঙ্গে যোগাযোগ করার জন্য ধন্যবাদ। {topic_bn} নিয়ে আমি কীভাবে সাহায্য করতে পারি?",
    }


def scoring(extra):
    return [
        {
            "key": "appointment_booked",
            "name": "Appointment booked",
            "condition": {"event": "appointment_booked"},
            "points": 40,
        },
        {
            "key": "budget_given",
            "name": "Budget given",
            "condition": {"field": "budget", "op": "present"},
            "points": 10,
        },
        {
            "key": "timeline_30_days",
            "name": "Timeline under 30 days",
            "condition": {"field": "timeline", "op": "eq", "value": "Within 30 days"},
            "points": 20,
        },
        {
            "key": "not_interested",
            "name": "Not interested → Cold",
            "condition": {"status": "not_interested"},
            "points": 0,
            "force_label": "cold",
        },
    ] + extra


def wa(name, body):
    return {"name": name, "category": "utility", "language": "en", "body": body}


TEMPLATES = [
    {
        "industry": "real-estate",
        "languages": ["en", "hi", "bn"],
        "instructions": (
            "You are a polite, professional property consultant for {{ company_name }}. Understand what the buyer "
            "needs (budget, location, BHK, property type, purpose, timeline), suggest only properties from the "
            "company's catalogue, never invent prices, offers or availability, and book a site visit when the buyer "
            "is interested."
        ),
        "lead_fields": [
            f(
                "budget",
                "Budget",
                "currency",
                ai_extractable=True,
                filterable=True,
                show_in_list=True,
                extraction_hint="Total budget in rupees, e.g. 70 lakh",
            ),
            f("location", "Location", "location", ai_extractable=True, filterable=True, show_in_list=True),
            f(
                "bhk",
                "BHK",
                "single_select",
                options=["1 RK", "1 BHK", "2 BHK", "3 BHK", "4 BHK", "5+ BHK"],
                ai_extractable=True,
                filterable=True,
                show_in_list=True,
            ),
            f(
                "property_type",
                "Property Type",
                "single_select",
                options=["Apartment", "Villa", "Independent House", "Plot", "Commercial"],
                ai_extractable=True,
                filterable=True,
            ),
            f(
                "purpose",
                "Purpose",
                "single_select",
                options=["Self use", "Investment"],
                ai_extractable=True,
                filterable=True,
            ),
            f("timeline", "Buying Timeline", "single_select", options=TIMELINE, ai_extractable=True, filterable=True),
            f("site_visit", "Site Visit Wanted", "yes_no", ai_extractable=True, filterable=True),
        ],
        "qualification": [
            q(
                "budget",
                "What is your budget for the property?",
                "आपका प्रॉपर्टी का बजट कितना है?",
                "সম্পত্তির জন্য আপনার বাজেট কত?",
            ),
            q(
                "location",
                "Which area or location are you looking in?",
                "आप किस एरिया या लोकेशन में देख रहे हैं?",
                "আপনি কোন এলাকায় খুঁজছেন?",
            ),
            q("bhk", "How many bedrooms do you need?", "आपको कितने BHK चाहिए?", "আপনার কয়টি বেডরুম দরকার?"),
            q(
                "property_type",
                "Apartment, villa, plot or commercial?",
                "फ्लैट, विला, प्लॉट या कमर्शियल?",
                "ফ্ল্যাট, ভিলা, প্লট না কমার্শিয়াল?",
            ),
            q(
                "purpose",
                "Is it for self use or investment?",
                "खुद रहने के लिए या इन्वेस्टमेंट के लिए?",
                "নিজে থাকার জন্য না বিনিয়োগের জন্য?",
            ),
            q("timeline", "When are you planning to buy?", "आप कब तक खरीदना चाहते हैं?", "আপনি কবে কিনতে চান?"),
        ],
        "catalog": {
            "key": "property",
            "name": "Properties",
            "item_label": "Property",
            "display": {"title_field": "project_name", "price_field": "price"},
            "match_rules": {"budget_tolerance_percent": 10},
            "fields": [
                f("project_name", "Project Name", required=True, show_in_list=True),
                f("builder", "Builder", show_in_list=True, filterable=True),
                f("location", "Location", "location", required=True, show_in_list=True, filterable=True),
                f("address", "Address", "textarea"),
                f(
                    "property_type",
                    "Property Type",
                    "single_select",
                    options=["Apartment", "Villa", "Independent House", "Plot", "Commercial"],
                    filterable=True,
                ),
                f(
                    "bhk",
                    "BHK",
                    "single_select",
                    options=["1 RK", "1 BHK", "2 BHK", "3 BHK", "4 BHK", "5+ BHK"],
                    filterable=True,
                    show_in_list=True,
                ),
                f("price", "Price", "currency", required=True, show_in_list=True, filterable=True),
                f("area", "Area (sq ft)", "number"),
                f("floor", "Floor"),
                f(
                    "possession",
                    "Possession",
                    "single_select",
                    options=["Ready to move", "Within 6 months", "6-12 months", "1-2 years", "2+ years"],
                    filterable=True,
                ),
                f(
                    "amenities",
                    "Amenities",
                    "multi_select",
                    options=[
                        "Parking",
                        "Lift",
                        "Gym",
                        "Swimming Pool",
                        "Club House",
                        "Garden",
                        "Security",
                        "Power Backup",
                    ],
                ),
                f("description", "Description", "textarea"),
                f(
                    "availability",
                    "Availability",
                    "single_select",
                    options=["Available", "Few units left", "Sold out"],
                    filterable=True,
                    show_in_list=True,
                ),
                f(
                    "booking_status",
                    "Booking Status",
                    "single_select",
                    options=["Open", "On hold", "Booked"],
                    filterable=True,
                ),
            ],
        },
        "appointment": ("site_visit", "Site Visit", 60, 15, "in_person"),
        "scoring": scoring(
            [
                {
                    "key": "location_given",
                    "name": "Location given",
                    "condition": {"field": "location", "op": "present"},
                    "points": 10,
                },
                {"key": "bhk_given", "name": "BHK given", "condition": {"field": "bhk", "op": "present"}, "points": 10},
            ]
        ),
        "greeting": greetings("your property search", "प्रॉपर्टी ढूँढने", "সম্পত্তি খোঁজা"),
        "faqs": [
            {
                "question": "Do you help with home loans?",
                "answer": "Answer from the company's approved information.",
                "language": "en",
            },
            {"question": "Can I visit the site?", "answer": "Yes, I can book a site visit for you.", "language": "en"},
        ],
        "whatsapp": [
            wa("site_visit_confirmation", "Hi {{1}}, your site visit for {{2}} is confirmed on {{3}}."),
            wa("property_details", "Hi {{1}}, here are the details of {{2}} you asked about: {{3}}"),
        ],
    },
    {
        "industry": "travel",
        "languages": ["en", "hi", "bn"],
        "instructions": (
            "You are a friendly travel consultant for {{ company_name }}. Find out the destination, travel dates, "
            "number of travellers and budget, suggest only packages from the company's catalogue with their real "
            "prices, and book a consultation when the traveller is ready."
        ),
        "lead_fields": [
            f("destination", "Destination", "location", ai_extractable=True, filterable=True, show_in_list=True),
            f("travel_date", "Travel Date", "date", ai_extractable=True, filterable=True, show_in_list=True),
            f("passengers", "Passengers", "number", ai_extractable=True, validation={"min": 1}),
            f("budget", "Budget", "currency", ai_extractable=True, filterable=True, show_in_list=True),
            f("package", "Package", ai_extractable=True),
            f("timeline", "Booking Timeline", "single_select", options=TIMELINE, ai_extractable=True, filterable=True),
        ],
        "qualification": [
            q(
                "destination",
                "Where would you like to travel?",
                "आप कहाँ घूमने जाना चाहते हैं?",
                "আপনি কোথায় বেড়াতে যেতে চান?",
            ),
            q("travel_date", "When do you plan to travel?", "आप कब यात्रा करना चाहते हैं?", "আপনি কবে যেতে চান?"),
            q("passengers", "How many people are travelling?", "कितने लोग यात्रा करेंगे?", "কতজন যাবেন?"),
            q("budget", "What is your budget?", "आपका बजट कितना है?", "আপনার বাজেট কত?"),
        ],
        "catalog": {
            "key": "travel_package",
            "name": "Travel Packages",
            "item_label": "Package",
            "display": {"title_field": "package_name", "price_field": "price_per_person"},
            "fields": [
                f("package_name", "Package Name", required=True, show_in_list=True),
                f("destinations", "Destination(s)", "location", required=True, show_in_list=True, filterable=True),
                f("duration_days", "Duration (days)", "number", show_in_list=True),
                f("duration_nights", "Duration (nights)", "number"),
                f(
                    "price_per_person",
                    "Price per person",
                    "currency",
                    required=True,
                    show_in_list=True,
                    filterable=True,
                ),
                f("inclusions", "Inclusions", "textarea"),
                f("exclusions", "Exclusions", "textarea"),
                f("itinerary", "Itinerary", "textarea"),
                f("available_dates", "Available Dates", "textarea"),
            ],
        },
        "appointment": ("travel_consultation", "Travel Consultation", 30, 10, "phone"),
        "scoring": scoring(
            [
                {
                    "key": "destination_given",
                    "name": "Destination given",
                    "condition": {"field": "destination", "op": "present"},
                    "points": 10,
                },
                {
                    "key": "date_given",
                    "name": "Travel date given",
                    "condition": {"field": "travel_date", "op": "present"},
                    "points": 10,
                },
            ]
        ),
        "greeting": greetings("your trip", "आपकी यात्रा", "আপনার ভ্রমণ"),
        "faqs": [
            {"question": "Are flights included?", "answer": "See the package inclusions.", "language": "en"},
        ],
        "whatsapp": [
            wa("package_details", "Hi {{1}}, here is the {{2}} package you asked about: {{3}}"),
            wa("consultation_confirmation", "Hi {{1}}, your travel consultation is confirmed on {{2}}."),
        ],
    },
    {
        "industry": "education",
        "languages": ["en", "hi", "bn"],
        "instructions": (
            "You are a helpful admissions counsellor for {{ company_name }}. Understand the student's course "
            "interest, qualification and preferred college, quote fees and eligibility only from the approved course "
            "catalogue, and book a counselling session."
        ),
        "lead_fields": [
            f("course", "Course", ai_extractable=True, filterable=True, show_in_list=True),
            f("qualification", "Qualification", ai_extractable=True, filterable=True, show_in_list=True),
            f("preferred_college", "Preferred College", ai_extractable=True, filterable=True),
            f("admission_requirement", "Admission Requirement", "textarea", ai_extractable=True),
            f(
                "timeline",
                "Admission Timeline",
                "single_select",
                options=TIMELINE,
                ai_extractable=True,
                filterable=True,
            ),
        ],
        "qualification": [
            q(
                "course",
                "Which course are you interested in?",
                "आप कौन सा कोर्स करना चाहते हैं?",
                "আপনি কোন কোর্সে আগ্রহী?",
            ),
            q(
                "qualification",
                "What is your current qualification?",
                "आपकी वर्तमान योग्यता क्या है?",
                "আপনার বর্তমান যোগ্যতা কী?",
            ),
            q(
                "preferred_college",
                "Do you have a preferred college?",
                "क्या आपका कोई पसंदीदा कॉलेज है?",
                "আপনার কোনো পছন্দের কলেজ আছে?",
            ),
        ],
        "catalog": {
            "key": "course",
            "name": "Courses",
            "item_label": "Course",
            "display": {"title_field": "course_name", "price_field": "fees"},
            "fields": [
                f("course_name", "Course Name", required=True, show_in_list=True),
                f("institution", "College / Institution", required=True, show_in_list=True, filterable=True),
                f("eligibility", "Eligibility", "textarea"),
                f("fees", "Fees", "currency", required=True, show_in_list=True, filterable=True),
                f("duration", "Duration", show_in_list=True),
                f("intake_dates", "Intake / Admission Dates", "textarea"),
                f("seats", "Seats", "number"),
                f(
                    "mode",
                    "Mode",
                    "single_select",
                    options=["Full time", "Part time", "Online", "Distance"],
                    filterable=True,
                ),
                f("description", "Description", "textarea"),
            ],
        },
        "appointment": ("counselling_session", "Counselling Session", 45, 15, "video"),
        "scoring": scoring(
            [
                {
                    "key": "course_given",
                    "name": "Course given",
                    "condition": {"field": "course", "op": "present"},
                    "points": 15,
                },
            ]
        ),
        "greeting": greetings("your admission", "आपके एडमिशन", "আপনার ভর্তি"),
        "faqs": [
            {
                "question": "What are the fees?",
                "answer": "Fees are quoted only from the course catalogue.",
                "language": "en",
            },
        ],
        "whatsapp": [
            wa("counselling_confirmation", "Hi {{1}}, your counselling session is confirmed on {{2}}."),
            wa("course_details", "Hi {{1}}, here are the details of {{2}}: {{3}}"),
        ],
    },
]
