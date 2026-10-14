# Website Section Mapping (Phase 0 deliverable, WEB-09)

Every section of the website becomes a **section type** in the Super Admin CMS (Phase 1, WEB-04).
The website template only keeps layout and animation; all text, images and links below come from Super Admin.

**Every section also has:** `is_visible` (show / hide), `sort_order`, `anchor_id` (for menu links such as `#pricing`), draft / published content.

Field types: `text` (one line), `textarea`, `rich` (formatted text), `image` (upload, served via CDN), `link` (label + URL), `number`, `list[...]` (repeatable items, add / remove / reorder).

Source: `backend/templates/website/` (eSoft HR layout, index5). Template files are named in each section.

---

## 1. Header — `partials/header.html`
| Field | Type | Notes |
|---|---|---|
| Logo (light / dark), favicon | image | From **General Settings**, not the CMS |
| Menu items | list[label, link, open in new tab] | Same list used for desktop and mobile menus |
| Login link label | text | Points to the login page |
| CTA button | link | e.g. "Get Started" → registration |

## 2. Hero — `pages/home.html` (`hero-area9`)
| Field | Type | Notes |
|---|---|---|
| Badge icon | image | Small icon before the badge text |
| Badge text | text | e.g. "Your 24/7 AI workforce" |
| Heading | text | Animated letter-by-letter (`text-anime-style-3`) |
| Paragraph | textarea | |
| Button | link | |
| Main image | image | `main-img` |
| Floating images 1–5 | image (optional each) | Decorative cards around the main image; empty = hidden |

## 3. Work / Highlights — `work2`
| Field | Type | Notes |
|---|---|---|
| Badge text, Heading | text | |
| Tabs | list[tab label] | Template shows 3 tabs (1, 2, 3) |
| Cards per tab | list[title, image] | Template shows 3 cards per tab |

## 4. Counters — `counters6`
| Field | Type | Notes |
|---|---|---|
| Items (4) | list[number, suffix, label] | e.g. 500 · "+" · "Businesses"; number animates (count-up) |

## 5. Features / Work Process — `work-prosess9`
| Field | Type | Notes |
|---|---|---|
| Badge text, Heading | text | |
| Cards (5) | list[title, text, image, link (optional)] | Layout: 2 large on top, 3 below |

## 6. System / Benefits — `buy-sell-bottom2`
| Field | Type | Notes |
|---|---|---|
| Badge text, Heading | text | |
| Benefit boxes (4) | list[icon, title, text, link (optional)] | 2 left, 2 right of the image |
| Centre image, secondary image | image | Decorative shapes stay in the template |

## 7. Solution — `hr-solutions`
| Field | Type | Notes |
|---|---|---|
| Image | image | Left side |
| Badge text, Heading | text | |
| Paragraph | textarea | |
| Button | link | |

## 8. Testimonials — `tes9`
| Field | Type | Notes |
|---|---|---|
| Badge text, Heading | text | |
| Testimonials | list[rating 1–5, quote, photo, name, designation, company logo] | Slider |

## 9. Pricing — taken from `pages/pricing.html` (restyled to HR colours)
| Field | Type | Notes |
|---|---|---|
| Badge text, Heading, Sub-text | text | |
| Monthly / Yearly toggle labels, yearly saving text | text | |
| Plans | **dynamic** | Read live from Plans & Pricing (SUB-01): name, price, features, limits, CTA |

## 10. Industries — feature-card section from another eSoft demo (restyled)
| Field | Type | Notes |
|---|---|---|
| Badge text, Heading, Intro | text / textarea | |
| Industry cards | **dynamic** | Read live from active industry templates: name, icon, short description |

## 11. FAQ — `faq6` section from eSoft `index.html` (restyled)
| Field | Type | Notes |
|---|---|---|
| Badge text, Heading | text | |
| Questions | list[question, answer (rich)] | Accordion; first item open |

## 12. Call to Action — `partials/cta.html`
| Field | Type | Notes |
|---|---|---|
| Heading | text | |
| Paragraph | textarea | |
| Button | link | |
| Image | image | Decorative shapes stay in the template |

## 13. Footer — `partials/footer.html`
| Field | Type | Notes |
|---|---|---|
| Trust badges (3) | list[icon, text] | e.g. "24/7 support", "Secure", "Uptime" |
| Link columns | list[column title, list[label, link]] | Template has 5 columns |
| Social links | list[platform, URL] | From **General Settings** (SA-24) |
| Copyright text, bottom links (Privacy, Terms, Security) | text, list[label, link] | Copyright from General Settings |

---

## Inner pages (Phase 2)
All use the same header and footer. Each page has page-level **SEO** (meta title, description, OpenGraph image) plus its own sections:

| Page | Template | Sections |
|---|---|---|
| About | `pages/about.html` | Hero + reuse of section types above |
| Features | `pages/features.html` | Hero + feature cards |
| Pricing | `pages/pricing.html` | Pricing (dynamic plans) + FAQ |
| Contact | `pages/contact.html` | Contact details (General Settings) + enquiry form (WEB-06) |
| Testimonials | `pages/testimonial.html` | Testimonials |
| Blog (optional) | `pages/blog.html`, `blog-details.html` | Posts |
| Legal pages | new, simple layout | Rich text per page (Terms, Privacy, Refund, AI usage) |
| Account pages | `login`, `account`, `forgot`, `reset`, `verify`, `form-success` | Wired to django-allauth in Phase 2 |
