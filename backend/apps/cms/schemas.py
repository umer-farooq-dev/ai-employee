"""Section types for the website CMS, one per section of the eSoft HR template (docs/phase0/website-section-mapping.md).

These are SEED definitions written to the database (SectionType); the content itself is entered in Super Admin.
Field types: text, textarea, rich, image, link ({label, url}), number, list (repeatable rows of sub-fields).
"""


def f(key, label, type="text", **extra):
    return {"key": key, "label": label, "type": type, **extra}


HEADING = [f("badge_icon", "Badge icon", "image"), f("badge_text", "Badge text"), f("heading", "Heading")]

SECTION_TYPES = [
    (
        "header",
        "Header & menu",
        "Logo comes from General Settings.",
        False,
        [
            f(
                "menu",
                "Menu items",
                "list",
                fields=[f("label", "Label"), f("url", "Link"), f("new_tab", "Open in new tab")],
            ),
            f("login_label", "Login link label"),
            f("cta", "Call-to-action button", "link"),
        ],
    ),
    (
        "hero",
        "Hero",
        "",
        False,
        HEADING
        + [
            f("paragraph", "Paragraph", "textarea"),
            f("button", "Button", "link"),
            f("main_image", "Main image", "image"),
            f("floating_images", "Floating images (up to 5)", "list", max=5, fields=[f("image", "Image", "image")]),
        ],
    ),
    (
        "work",
        "Work / highlights",
        "Cards are grouped into tabs by their tab label.",
        False,
        HEADING
        + [
            f(
                "cards",
                "Cards",
                "list",
                fields=[f("tab", "Tab label"), f("title", "Title"), f("image", "Image", "image")],
            ),
        ],
    ),
    (
        "counters",
        "Counters",
        "Numbers count up on scroll.",
        False,
        [
            f(
                "items",
                "Counters",
                "list",
                max=4,
                fields=[f("number", "Number"), f("suffix", "Suffix (e.g. +, K+)"), f("label", "Label")],
            ),
        ],
    ),
    (
        "features",
        "Features / work process",
        "",
        False,
        HEADING
        + [
            f(
                "cards",
                "Cards",
                "list",
                max=5,
                fields=[
                    f("title", "Title"),
                    f("text", "Text", "textarea"),
                    f("image", "Image", "image"),
                    f("url", "Link (optional)"),
                ],
            ),
        ],
    ),
    (
        "benefits",
        "Benefits / system",
        "Two boxes left and two right of the centre image.",
        False,
        HEADING
        + [
            f(
                "boxes",
                "Benefit boxes",
                "list",
                max=4,
                fields=[
                    f("icon", "Icon", "image"),
                    f("title", "Title"),
                    f("text", "Text", "textarea"),
                    f("url", "Link (optional)"),
                ],
            ),
            f("centre_image", "Centre image", "image"),
            f("secondary_image", "Secondary image", "image"),
        ],
    ),
    (
        "solution",
        "Solution",
        "",
        False,
        [f("image", "Image", "image")]
        + HEADING[1:]
        + [
            f("paragraph", "Paragraph", "textarea"),
            f("button", "Button", "link"),
        ],
    ),
    (
        "testimonials",
        "Testimonials",
        "",
        False,
        HEADING
        + [
            f(
                "items",
                "Testimonials",
                "list",
                fields=[
                    f("rating", "Rating (1-5)", "number"),
                    f("quote", "Quote", "textarea"),
                    f("photo", "Photo", "image"),
                    f("name", "Name"),
                    f("designation", "Designation"),
                    f("logo", "Company logo", "image"),
                ],
            ),
        ],
    ),
    (
        "pricing",
        "Pricing",
        "Plans are read live from Plans & Pricing.",
        True,
        HEADING
        + [
            f("subtext", "Sub-text", "textarea"),
            f("monthly_label", "Monthly toggle label"),
            f("yearly_label", "Yearly toggle label"),
            f("yearly_saving_text", "Yearly saving text"),
        ],
    ),
    (
        "industries",
        "Industries",
        "Industry cards are read live from active industry templates.",
        True,
        HEADING
        + [
            f("intro", "Intro", "textarea"),
        ],
    ),
    (
        "faq",
        "FAQ",
        "",
        False,
        HEADING
        + [
            f("items", "Questions", "list", fields=[f("question", "Question"), f("answer", "Answer", "rich")]),
        ],
    ),
    (
        "cta",
        "Call to action",
        "Shown above the footer on every page.",
        False,
        [
            f("heading", "Heading"),
            f("paragraph", "Paragraph", "textarea"),
            f("button", "Button", "link"),
            f("image", "Image", "image"),
        ],
    ),
    (
        "footer",
        "Footer",
        "Social links and copyright come from General Settings.",
        False,
        [
            f("badges", "Trust badges", "list", max=3, fields=[f("icon", "Icon", "image"), f("text", "Text")]),
            f(
                "links",
                "Link columns",
                "list",
                fields=[f("column", "Column title"), f("label", "Label"), f("url", "Link")],
            ),
            f("bottom_links", "Bottom links", "list", fields=[f("label", "Label"), f("url", "Link")]),
        ],
    ),
    (
        "rich_text",
        "Rich text",
        "Free text block, used for legal pages.",
        False,
        [
            f("heading", "Heading"),
            f("body", "Body", "rich"),
        ],
    ),
]

# Seed pages: (key, slug, title, [section type keys in order])
SEED_PAGES = [
    ("site", "_site", "Site-wide (header, call to action, footer)", ["header", "cta", "footer"]),
    (
        "home",
        "",
        "Home",
        [
            "hero",
            "work",
            "counters",
            "features",
            "benefits",
            "solution",
            "testimonials",
            "pricing",
            "industries",
            "faq",
        ],
    ),
    ("terms", "terms", "Terms of Service", ["rich_text"]),
    ("privacy", "privacy", "Privacy Policy", ["rich_text"]),
    ("refund", "refund", "Refund & Cancellation Policy", ["rich_text"]),
    ("ai-usage", "ai-usage", "Acceptable Use / AI Usage Policy", ["rich_text"]),
]
