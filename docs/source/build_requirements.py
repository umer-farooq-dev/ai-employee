"""Document 1: Product Requirements Specification & Phased Delivery Plan."""
import re
import sys

from pdfkit import (AMBER_BG, BLUE, CONTENT_W, GREEN, NAVY, PURPLE,
                    PURPLE_BG, RED, SOFT, ST, TEAL, TEAL_BG, WHITE, Dia, H3, Numbering, P, PageBreak, Paragraph,
                    Table, TableStyle, TocMark, bullets, build, callout, cover_story, fx, kv, mm, sp, table, toc)
from reportlab.lib.styles import ParagraphStyle

OUT = sys.argv[1] if len(sys.argv) > 1 else "../01_AI_Employee_Product_Requirements_and_Phase_Plan.pdf"
DATE = "14 October 2026"

META = {
    "title": "Product Requirements Specification &amp; Phased Delivery Plan",
    "short": "Product Requirements & Phase Plan · v1.0",
    "subtitle": "Complete feature catalogue, field definitions, user roles and phase-gated delivery plan "
                "for the AI Employee SaaS platform",
    "tagline": "Hire an AI Employee for your business: a 24/7 AI workforce for Indian businesses",
    "kicker": "AI EMPLOYEE PLATFORM · DOCUMENT 01",
    "author": "AI Employee Platform Development Team",
    "footer": f"Confidential · Draft v1.0 for client approval · {DATE}",
    "cover_meta": [("Document", "PRD-01 Requirements & Phase Plan"), ("Version", "1.0 (Draft for approval)"),
                   ("Date", DATE), ("Companion document", "SDD-02 System Design & Architecture"),
                   ("Prepared for", "Client: AI Employee Platform"), ("Prepared by", "Development Team")],
    "cover_footer": "CONFIDENTIAL: prepared for client review and approval. Not for redistribution.",
}

# ---------------------------------------------------------------------------
# Feature catalogue. Row = (ID, Feature, Details, Ref, Phase)
# Ref: §n = client requirement section; DEC = confirmed internal decision; REC = recommended for production
# ---------------------------------------------------------------------------
MODULES = [
    ("M01", "Public Website (Marketing Site)",
     "Professional, animated, responsive website where visitors learn about the product and register their company.",
     [
         ("WEB-01", "Animated landing page", "Hero built on the positioning <b>\"Hire an AI Employee for your business\"</b>. "
          "Built on the eSoft HR layout (index5). Scroll-triggered animations (GSAP, ScrollTrigger, AOS), animated product mock-ups (AI Employee card, live call transcript, CRM board), "
          "micro-interactions and smooth transitions. Performance budget: Lighthouse score 90 or above so animation never slows the page.", "DEC, §31", "P2"),
         ("WEB-02", "Website pages", "Home · How It Works (Register → Select Industry → Select Employee Type → Create → Add Knowledge → "
          "Connect → Configure → Activate → AI Employee works) · AI Employee Types · Industries (one page per <i>active</i> "
          "industry, generated from Super Admin templates) · Features (Voice, WhatsApp, Website Chat, CRM, Calendar, Campaigns, "
          "Analytics) · Pricing (plans read live from Super Admin) · About · Contact / Book a Demo · FAQ.", "§1-§3, §23", "P2"),
         ("WEB-03", "Legal pages", "Terms of Service, Privacy Policy, Refund & Cancellation Policy, Acceptable Use / AI Usage Policy, "
          "Contact details. Required for Razorpay merchant activation. Content editable from Super Admin.", "REC", "P2"),
         ("WEB-04", "Website content management (Super Admin)", "<b>Every section of the website template</b> (hero, features, "
          "how it works, AI Employee types, industries, pricing, testimonials, FAQ, call-to-action, header menu, footer and every "
          "other section the template has) gets its own Super Admin editor: headings, sub-headings, paragraphs, images, icons, "
          "buttons (text + link), lists / cards, display order, show / hide. Plus per-page SEO meta and legal pages. Built first in "
          "Super Admin; the website reads everything from it. No hard-coded website content.", "DEC", "P1"),
         ("WEB-09", "Section-by-section mapping of the template", "Each section in the supplied website template is mapped to a "
          "content model in Super Admin before development, so nothing on the website is left as fixed template text.", "DEC", "P0, P1"),
         ("WEB-05", "Company registration entry", "\"Get Started\" / \"Register your business\" calls-to-action open the company "
          "registration flow (AUTH-01).", "§1", "P2"),
         ("WEB-06", "Contact / demo enquiries", "Form fields: Name, Business name, Phone, Email, Industry, Message. Stored in "
          "Super Admin → Platform Enquiries with email notification to the platform team.", "REC", "P2"),
         ("WEB-07", "SEO & performance", "Server-side rendering, meta and OpenGraph tags, sitemap.xml, robots.txt, structured data, "
          "optimised images, CDN delivery.", "REC", "P2"),
         ("WEB-08", "Responsive & accessible", "Desktop, laptop, tablet, Android and iPhone. Keyboard navigation, colour contrast, "
          "and reduced-motion mode for users who disable animations.", "§26", "P2"),
     ]),
    ("M02", "Registration, Authentication & Accounts",
     "How a business creates its account, how users sign in and how teams are managed.",
     [
         ("AUTH-01", "Company registration", "Fields: <b>Business name</b>; <b>Owner full name</b>; <b>Work email</b>; "
          "<b>Mobile number</b> (+91 default); <b>Password</b> (policy from Super Admin); <b>Industry</b> (active templates only); "
          "<b>City</b>; <b>State</b>; Business size (optional); Website (optional); GSTIN (optional, printed on invoices); "
          "<b>Accept Terms & Privacy</b> (stored with timestamp and IP). Creates the Company, the Owner user and a trial or plan "
          "according to Super Admin settings.", "§1, §28", "P2"),
         ("AUTH-02", "Verification", "Email verification (link or OTP). Mobile OTP verification, switchable on/off in Super Admin; "
          "SMS sent through the SMS provider adapter.", "REC", "P2"),
         ("AUTH-03", "Login & sessions", "Email + password login, remember-me, logout, configurable session timeout, list and revoke "
          "active sessions.", "§25", "P1"),
         ("AUTH-04", "Password recovery", "Forgot password (email link / OTP), reset password, change password from profile.", "§25", "P1"),
         ("AUTH-05", "Two-factor authentication", "Authenticator-app (TOTP) 2FA. Mandatory for Super Admin staff; optional or "
          "enforceable per company.", "§25", "P1"),
         ("AUTH-06", "Brute-force protection", "Lockout after N failed attempts plus rate limiting per IP and account. N and lock "
          "duration configurable in Super Admin.", "§25", "P1"),
         ("AUTH-07", "Team management", "Invite users by email, assign role (Owner/Admin, Manager, Human Agent), resend or cancel "
          "invitation, deactivate user, transfer ownership. Seat limit enforced from the plan.", "§8, §16", "P2"),
         ("AUTH-08", "User profile", "Name, email, mobile, photo, timezone (default Asia/Kolkata), notification preferences, "
          "availability status for handoff (Online / Away / Offline), password and 2FA settings.", "REC", "P1"),
         ("AUTH-09", "Company profile", "Display name, legal name, logo, address, GSTIN, contact email and phone, website, timezone, "
          "default language, business hours, holidays.", "§1", "P2"),
         ("AUTH-10", "Onboarding checklist", "Guided checklist after registration: Create AI Employee → Add knowledge → Connect "
          "phone / WhatsApp → Test → Activate. Progress tracked per company.", "§1", "P2"),
         ("AUTH-11", "Role-based access control", "Permission check on every screen and every API call. Roles and permission sets "
          "stored in the database and editable in Super Admin (defaults in Section 5).", "§25", "P1"),
     ]),
    ("M03", "Multi-Tenancy & Data Isolation",
     "Thousands of businesses share one platform; none can ever see another's data.",
     [
         ("TEN-01", "Company-level isolation", "Every business record carries <b>company_id</b>. Enforced in the ORM, the API layer and by "
          "PostgreSQL row-level security. One company can never read or change another company's data.", "§8, §25, §32", "P1"),
         ("TEN-02", "Tenant resolution per channel", "Company identified from the signed-in user (panels), the dialled number (calls), "
          "the WhatsApp number (messages) or the widget key (website chat). Never taken from AI output.", "§25", "P1"),
         ("TEN-03", "Isolated file storage", "Files stored under per-company paths in private storage; accessed only through "
          "short-lived signed URLs.", "§25", "P1"),
         ("TEN-04", "Isolated AI knowledge", "Knowledge search always filtered by company. AI tools receive company_id from the "
          "server-side session only.", "§6, §25", "P4"),
         ("TEN-05", "Automated isolation tests", "Cross-tenant test suite covering every API endpoint runs in CI. Any failure blocks "
          "the phase gate.", "§25", "P1 → all"),
         ("TEN-06", "Company suspension", "Super Admin can suspend or reactivate a company. Suspension pauses all its AI Employees, "
          "campaigns and logins.", "§22", "P1"),
         ("TEN-07", "Data export & deletion", "Owner can request a full data export or account deletion (configurable grace period). "
          "Deletion covers records, files, recordings, knowledge vectors and backups per retention policy.", "§25", "P7"),
     ]),
    ("M04", "Industry Template Engine",
     "Reusable engine so any industry can be added from Super Admin without changing source code.",
     [
         ("IND-01", "Industry management", "Super Admin creates industries: Name, Slug, Icon, Description, Display order, "
          "Status (Active / Inactive), Supported languages.", "§2, §22", "P3"),
         ("IND-02", "Template contents", "Each industry template defines: AI persona guidelines and base instructions; qualification "
          "questions (ordered, mapped to CRM fields); CRM custom fields; catalogue type(s) and fields; appointment types; enabled tools; "
          "lead statuses; lead-scoring rules; handoff rules; greeting and AI-disclosure text per language; default WhatsApp templates; "
          "default FAQs.", "§2", "P3"),
         ("IND-03", "Template versioning", "Draft → Published → Archived. Companies stay on their version until they accept an update. "
          "Rollback to a previous version.", "REC", "P3"),
         ("IND-04", "Activate / deactivate", "Inactive templates are hidden from registration and from the AI Employee wizard; existing "
          "companies keep working.", "§22", "P3"),
         ("IND-05", "Clone template", "Create a new industry by cloning an existing template. No code change.", "§2", "P3"),
         ("IND-06", "MVP templates", "<b>Real Estate</b>, <b>Travel & Tours</b>, <b>Education</b>: fully configured, AI-tuned and "
          "tested.", "§11-§13, §28", "P3, P4"),
         ("IND-07", "Post-MVP templates", "Automobile, Hotels, E-commerce, Logistics, Clinics / Healthcare, B2B Services, "
          "Salons / Beauty, Restaurants.", "§2", "P9"),
         ("IND-08", "Future industries", "Any further industry added from Super Admin with the same engine.", "§2, §32", "P9+"),
     ]),
    ("M05", "AI Employee Roles",
     "Role templates define what kind of work an AI Employee does.",
     [
         ("ROLE-01", "Role template management", "Super Admin defines roles: Name, Description, Icon, Role instructions, Allowed "
          "channels (inbound voice, outbound voice, WhatsApp, website chat), Allowed tools, Default rules, Plan availability, Status.",
          "§3, §22", "P3"),
         ("ROLE-02", "AI Sales Employee", "Call leads · explain products/services · qualify customers · follow up · create CRM leads · "
          "transfer hot leads.", "§3", "P4"),
         ("ROLE-03", "AI Receptionist", "Answer incoming calls · answer approved FAQs · take messages · transfer calls · create "
          "appointments.", "§3", "P4"),
         ("ROLE-04", "AI Appointment Employee", "Check availability · book · reschedule · cancel · send reminders.", "§3", "P4"),
         ("ROLE-05", "AI Follow-up Employee", "Call leads · follow up · update CRM · escalate interested customers.", "§3", "P4"),
         ("ROLE-06", "AI Customer Support Employee", "Answer customer questions · check order/status where integrated · create support "
          "tickets · escalate complex issues.", "§3", "P10"),
         ("ROLE-07", "AI Collection / Reminder Employee", "Payment reminders · due-date notifications · human escalation. Enabled per "
          "company by Super Admin only where legally and contractually appropriate; strict tone guardrails.", "§3", "P10"),
         ("ROLE-08", "Custom role builder", "Companies (if plan allows) or Super Admin create new roles from instructions, tools, "
          "channels and rules.", "§3, §31", "P10"),
         ("ROLE-09", "AI Marketing Employee", "<b>PENDING</b>: the client has not yet defined this role. Not planned or estimated "
          "until defined (see Section 9).", "§31", "Pending"),
     ]),
    ("M06", "AI Employee Management (Company Panel)",
     "Screens a business uses to create, configure, test and run its AI Employees.",
     [
         ("EMP-01", "My AI Employees page", "Card per employee showing <b>Name, Industry, Role, Language(s), Status, Calls, Leads, "
          "Appointments</b>. Buttons: <b>Edit, Settings, Knowledge, Calls, Analytics, Activate / Pause</b>. Search, status filter, "
          "empty-state guidance.", "§20", "P4"),
         ("EMP-02", "Wizard step 1: Select Industry", "Pre-selected from the company's industry; only active templates listed.", "§21", "P4"),
         ("EMP-03", "Wizard step 2: Select Employee Type", "Roles available for the industry and the company's plan.", "§21", "P4"),
         ("EMP-04", "Wizard step 3: Employee Name", "Name (e.g., Sara), avatar, persona description, tone (formal / friendly), "
          "greeting message per language.", "§21", "P4"),
         ("EMP-05", "Wizard step 4: Voice", "Voices per language from Super Admin (gender, style), audio preview, speaking speed.",
          "§21", "P4, P5"),
         ("EMP-06", "Wizard step 5: Languages", "Primary language plus additional languages; automatic detection and switching; "
          "code-mixed speech allowed.", "§21", "P4"),
         ("EMP-07", "Wizard step 6: Business Knowledge", "Select existing knowledge sources or upload new ones; restrict sources to this "
          "employee.", "§21", "P4"),
         ("EMP-08", "Wizard step 7: Connect Tools", "<b>Phone</b> number · <b>WhatsApp</b> number · <b>CRM</b> (built-in: pipeline and "
          "assignment rules) · <b>Calendar</b> (built-in: calendars/resources this employee may book).", "§21",
          "P4 (CRM, Calendar), P5 (Phone), P6 (WhatsApp)"),
         ("EMP-09", "Wizard step 8: Configure Rules", "Working hours and after-hours behaviour · maximum call duration · transfer targets and "
          "escalation triggers · fallback message · AI-disclosure text · recording on/off and consent message · follow-up rules · "
          "qualification questions (edit / reorder) · restricted topics · enabled tools.", "§21", "P4"),
         ("EMP-10", "Wizard step 9: Test AI", "Test console: text chat, browser voice test, test call to own number. Shows extracted "
          "fields, tool calls and knowledge used.", "§21, §29", "P4 (text), P5 (voice)"),
         ("EMP-11", "Wizard step 10: Activate", "Readiness checklist (approved knowledge, connected channel, test completed), plan-limit "
          "check, activation.", "§21", "P4"),
         ("EMP-12", "Edit, settings, pause", "Edit any step later; activate/pause instantly; archive. Every change saved as a "
          "configuration version (who / when / what).", "§20", "P4"),
         ("EMP-13", "Employee analytics", "Calls, connected, leads, qualified, hot, appointments, transfers, usage, per employee with "
          "date filter.", "§20", "P7"),
     ]),
    ("M07", "AI Employee Engine (Core Runtime)",
     "One engine powers every AI Employee, in every industry, on every channel.",
     [
         ("ENG-01", "One engine, all channels", "A single channel-independent engine runs voice, WhatsApp and website chat for every "
          "industry and role.", "§2, §31", "P4"),
         ("ENG-02", "Layered configuration", "Behaviour assembled from: platform guardrails → industry template → role → company "
          "profile → employee settings → approved knowledge → conversation state.", "§2", "P4"),
         ("ENG-03", "Tool calling", "AI decides which configured tool to call; the server validates input, injects company_id, "
          "executes and returns the result.", "§7", "P4"),
         ("ENG-04", "No invented facts", "Prices, availability, discounts, policies and specifications come only from approved knowledge "
          "or tools. If missing, the configured fallback applies (human transfer, callback, or message). Verified by automated tests.",
          "§6", "P4"),
         ("ENG-05", "AI disclosure", "AI identifies itself as an AI assistant at the start of each conversation (text per language, "
          "configurable).", "§4", "P4"),
         ("ENG-06", "Structured extraction", "Free speech converted into CRM fields, e.g. <i>\"Sir mujhe New Town mein 2BHK chahiye, "
          "budget around 70 lakh hai\"</i> → Location = New Town, BHK = 2, Budget = ₹70,00,000. Understands lakh, crore, k and "
          "Indian date expressions.", "§5", "P4"),
         ("ENG-07", "Mixed-language understanding", "Hinglish, Bengali-English and other code-mixed input; replies in the customer's "
          "language.", "§4, §5", "P4 (text), P5 (voice)"),
         ("ENG-08", "Returning-customer memory", "Recognises known numbers and uses earlier summaries and CRM data.", "REC", "P4"),
         ("ENG-09", "LLM provider independence", "LLM provider and model per task chosen in Super Admin, with automatic fallback "
          "provider.", "§27", "P4"),
         ("ENG-10", "Safety guardrails", "Prompt-injection resistance, restricted topics, abuse handling, no promises outside policy, "
          "personal data masked in logs.", "§25", "P4"),
         ("ENG-11", "Usage metering", "Tokens / credits recorded per company, employee and conversation.", "§24", "P4"),
         ("ENG-12", "Quality evaluation suite", "Golden test conversations per industry × role × language run in CI to catch "
          "regressions in grounding, extraction, tool use and handoff.", "§29", "P4 → all"),
     ]),
    ("M08", "Knowledge Base (AI Business Brain)",
     "Each business teaches its AI Employees using only approved business information.",
     [
         ("KB-01", "Website source", "Add URL; crawler with page and depth limits; scheduled re-sync; include/exclude pages.", "§6", "P4"),
         ("KB-02", "Document sources", "PDF and DOC/DOCX upload; size and count limits from plan.", "§6", "P4"),
         ("KB-03", "FAQs", "Question & answer editor, bulk import, per language.", "§6", "P4"),
         ("KB-04", "Approved text", "Rich-text entries for service information, policies and price information.", "§6", "P4"),
         ("KB-05", "Excel / CSV & product catalogue", "Catalogues and price lists imported as structured records for exact lookup, "
          "never guessed from text.", "§6", "P4"),
         ("KB-06", "Approval workflow", "Each source is <b>Draft</b> until a company admin marks it <b>Approved</b>. AI uses approved "
          "content only.", "§6", "P4"),
         ("KB-07", "Processing status", "Queued → Processing → Ready / Failed (with reason). Re-process; delete (removed from AI "
          "immediately).", "REC", "P4"),
         ("KB-08", "Knowledge scope", "Company-wide, or limited to selected AI Employees.", "§6", "P4"),
         ("KB-09", "Knowledge test", "Ask a question; see the answer and the exact sources used.", "§6", "P4"),
         ("KB-10", "Unanswered-questions report", "Questions the AI could not answer, grouped and counted, so the business can add "
          "knowledge.", "REC", "P4"),
         ("KB-11", "Source citations", "Each AI answer records which knowledge items were used (visible in transcript view).", "§6", "P4"),
     ]),
    ("M09", "Tools / Actions Framework",
     "Actions the AI Employee performs in the real system, configured per industry and per employee.",
     [
         ("TOOL-01", "Tool registry", "Super Admin manages tools: Key, Description, Input schema, Category, Allowed industries / roles, "
          "Status. Industry-specific tools are configuration.", "§7", "P4"),
         ("TOOL-02", "create_lead() / update_lead()", "Create or update a lead including custom fields and status.", "§7", "P4"),
         ("TOOL-03", "search_customer()", "Find an existing lead/customer by phone, name or email (own company only).", "§7", "P4"),
         ("TOOL-04", "search_product()", "Search the company catalogue (properties, packages, courses …) with filters.", "§7", "P4"),
         ("TOOL-05", "check_availability() / book_appointment() / reschedule_appointment() / cancel_appointment()",
          "Built-in calendar actions with double-booking protection.", "§7", "P4"),
         ("TOOL-06", "assign_salesperson()", "Assign the lead to a human agent using assignment rules.", "§7", "P4"),
         ("TOOL-07", "send_email()", "Send an approved email template (brochure, confirmation, summary).", "§7", "P4"),
         ("TOOL-08", "transfer_call()", "Warm or cold transfer to a human.", "§7", "P5"),
         ("TOOL-09", "send_whatsapp()", "Send an approved WhatsApp template or session message.", "§7", "P6"),
         ("TOOL-10", "create_ticket()", "Create a support ticket.", "§7", "P10"),
         ("TOOL-11", "get_order_status()", "Order / status lookup through the company's integration (API connector or imported data).",
          "§7", "P10"),
         ("TOOL-12", "External API connector", "Company connects its own system (HTTPS + authentication) as a custom tool.", "§7", "P10"),
         ("TOOL-13", "Per-employee tool control", "Enable / disable tools per AI Employee; Super Admin can disable a tool platform-wide.",
          "§7", "P4"),
         ("TOOL-14", "Tool execution log", "Inputs, outputs, status and duration recorded per conversation; visible to company admin "
          "and Super Admin.", "§25", "P4"),
         ("TOOL-15", "MVP industry tools", "<b>Real Estate:</b> search_property, match_properties, book_site_visit. <b>Travel:</b> "
          "search_packages, create_booking_enquiry. <b>Education:</b> search_courses, check_eligibility, book_counselling.",
          "§11-§13", "P4"),
     ]),
    ("M10", "CRM & Lead Management (built-in, controlled from Super Admin)",
     "Every company gets its own CRM inside the platform. No external CRM is required.",
     [
         ("CRM-01", "Lead record: common fields", "<b>Lead ID</b> (auto, per company, e.g. LD-000123) · <b>Name</b> · <b>Phone</b> · "
          "<b>Email</b> · <b>Source</b> · <b>Lead Status</b> · <b>Lead Score</b> · <b>Assigned Employee</b> (AI) · <b>Assigned Human "
          "Agent</b> · <b>Notes</b> · <b>Call History</b> · <b>Follow-up Date</b> · <b>Last Contact</b> · <b>Next Action</b>. "
          "Also: Preferred language, Tags, Consent / opt-out flag, Created / Updated.", "§8", "P3"),
         ("CRM-02", "Lead statuses", "NEW · CALLING · CONNECTED · QUALIFIED · HOT · WARM · COLD · FOLLOW-UP · APPOINTMENT · "
          "CONVERTED · NOT INTERESTED. Seeded defaults; label, colour and order editable in Super Admin; automatic transitions on AI "
          "events.", "§8", "P3"),
         ("CRM-03", "Lead sources", "Inbound Call, Outbound Campaign, WhatsApp, Website Chat, Manual, Import. List managed in Super "
          "Admin.", "§8", "P3"),
         ("CRM-04", "Dynamic custom fields", "Industry fields without code change. Types: text, number, currency (INR), date, "
          "date-time, single select, multi select, yes/no, phone, email, location, file. Properties: label, key, required, "
          "AI-extractable, filterable, show in list, order, help text, validation. Defaults per industry from Super Admin; companies may "
          "add their own fields (plan-gated).", "§9", "P3"),
         ("CRM-05", "Real Estate fields", "Budget · Location · BHK · Property Type · Purpose · Site Visit.", "§9", "P3"),
         ("CRM-06", "Travel fields", "Destination · Travel Date · Passengers · Budget · Package.", "§9", "P3"),
         ("CRM-07", "Education fields", "Course · Qualification · Preferred College · Admission Requirement.", "§9", "P3"),
         ("CRM-08", "Automobile fields", "Car Model · Budget · Variant · Test Drive.", "§9", "P9"),
         ("CRM-09", "Lead list", "Table view (desktop), card view (mobile); search; filters (status, score, source, assignee, AI "
          "employee, dates, custom fields); sort; saved views; pagination.", "§8, §26", "P3"),
         ("CRM-10", "Pipeline board", "Kanban board by status with drag-and-drop.", "REC", "P3"),
         ("CRM-11", "Lead detail", "Profile and custom fields; timeline of calls, WhatsApp, chats, emails, notes, status and score "
          "changes, appointments, handoffs; AI summaries; transcript and recording access; next action; follow-up scheduler.",
          "§8, §17", "P3 (+P5, P6)"),
         ("CRM-12", "Manual create / edit", "Create, edit, soft-delete, restore.", "§8", "P3"),
         ("CRM-13", "Import / export", "CSV / Excel import with column mapping, phone normalisation, duplicate detection and error "
          "report. Export permission-controlled and audit-logged.", "§8, §18", "P3"),
         ("CRM-14", "Duplicate management", "Detect duplicates by phone / email; merge leads.", "REC", "P3"),
         ("CRM-15", "Assignment", "Manual, round-robin, rule-based (e.g., by location or project), or by AI (assign_salesperson).",
          "§3, §7", "P3"),
         ("CRM-16", "Follow-up tasks", "Tasks for humans with due date and reminders; \"My follow-ups today\" list.", "§8", "P3"),
         ("CRM-17", "Bulk actions", "Assign, change status, add to campaign, add tag, export, delete.", "REC", "P3"),
         ("CRM-18", "Super Admin control", "Statuses, sources, default fields, scoring rules and import limits configured by Super "
          "Admin. The CRM lives entirely inside our platform.", "DEC", "P3"),
     ]),
    ("M11", "Lead Scoring", "Automatic HOT / WARM / COLD classification with admin-configurable rules.",
     [
         ("SCORE-01", "Automatic classification", "After every conversation or event: <b>HOT</b> = strong buying intent / appointment / "
          "immediate requirement; <b>WARM</b> = interested but not ready; <b>COLD</b> = low intent / general enquiry.", "§10", "P4"),
         ("SCORE-02", "Configurable rules", "Rule builder with conditions on fields and events, points and thresholds (e.g., appointment "
          "booked +40, budget given +10, timeline under 30 days +20, \"not interested\" → COLD). Industry defaults in Super Admin; "
          "company admin can adjust.", "§10", "P3"),
         ("SCORE-03", "AI intent signal", "AI-assessed intent combined with rules; numeric score 0-100 plus label.", "§10", "P4"),
         ("SCORE-04", "Score explanation", "Reason stored, e.g. \"Booked site visit, budget confirmed\".", "REC", "P4"),
         ("SCORE-05", "Hot-lead actions", "Configurable: notify human, auto-transfer, assign salesperson.", "§3, §16", "P6"),
         ("SCORE-06", "Score history", "Every change logged on the lead timeline.", "REC", "P4"),
     ]),
    ("M12", "Business Catalogues", "Structured business data the AI searches: properties, packages, courses and future catalogues.",
     [
         ("CAT-01", "Catalogue engine", "Catalogue types and their fields defined in Super Admin per industry (same field engine as CRM). "
          "Companies manage their own items. New catalogue types need no code change.", "§2, §11", "P3"),
         ("CAT-02", "Real Estate property database", "<b>Project Name · Builder · Location · Address · Property Type · BHK · Price · "
          "Area · Floor · Possession · Amenities · Photos · Description · Availability · Booking Status</b>.", "§11", "P3"),
         ("CAT-03", "Property matching", "Budget (± tolerance configurable), location (with nearby-area aliases), BHK, property type, "
          "possession; ranked results.", "§11", "P4"),
         ("CAT-04", "Property collections", "Named sets of properties (manual or by filter) used by campaigns and WhatsApp follow-ups.",
          "§18", "P3"),
         ("CAT-05", "Travel package catalogue", "Proposed fields: Package Name, Destination(s), Duration (days / nights), Price per person, "
          "Inclusions, Exclusions, Itinerary, Available Dates, Photos, Status. Finalised with client during P3.", "§12", "P3"),
         ("CAT-06", "Education course catalogue", "Proposed fields: Course Name, College / Institution, Eligibility, Fees, Duration, "
          "Intake / Admission Dates, Seats, Mode, Description, Status. Fees quoted only from this approved data.", "§13", "P3"),
         ("CAT-07", "Import & media", "Excel / CSV import with mapping; photo and brochure upload; bulk edit.", "§6, §11", "P3"),
         ("CAT-08", "Indian price formatting", "INR with Indian formatting (₹70,00,000 · 70 Lakh · 1.2 Cr).", "REC", "P3"),
     ]),
    ("M13", "Calendar & Appointments (built-in)", "The platform's own calendar. No external calendar dependency.",
     [
         ("CAL-01", "Built-in calendar", "Day, week, month and agenda views; mobile friendly.", "DEC", "P3"),
         ("CAL-02", "Calendar resources", "Human agents, sites / projects, counsellors, rooms: anything bookable.", "DEC", "P3"),
         ("CAL-03", "Availability rules", "Working hours per resource, breaks, slot length, buffer, maximum bookings per slot, minimum "
          "notice, booking window, holidays and leave.", "§3", "P3"),
         ("CAL-04", "Appointment types", "From the industry template: Site Visit (Real Estate), Counselling Session (Education), Travel "
          "Consultation (Travel), Test Drive (Automobile, P9) and so on.", "§11-§13", "P3"),
         ("CAL-05", "Appointment record", "ID, Lead, Type, Resource / assigned human, Date & time, Duration, Location or meeting link, "
          "Status (Scheduled, Confirmed, Rescheduled, Cancelled, Completed, No-show), Notes, Created by (AI Employee / human), Channel.",
          "§17", "P3"),
         ("CAL-06", "AI booking tools", "check_availability, book, reschedule, cancel. Double booking prevented at database level.",
          "§3, §7", "P4"),
         ("CAL-07", "Confirmations & reminders", "WhatsApp and email confirmation; reminders at configurable offsets (e.g., 24 h and 2 h "
          "before).", "§3, §14", "P6"),
         ("CAL-08", "Manual booking", "Humans create, edit and cancel appointments.", "REC", "P3"),
         ("CAL-09", "Holiday calendar", "Platform holidays set by Super Admin; company holidays by company admin.", "DEC", "P3"),
         ("CAL-10", "Notifications to humans", "New or changed bookings notified to the assigned human.", "§16", "P6"),
     ]),
    ("M14", "Voice AI", "Natural, low-latency phone conversations in Indian languages.",
     [
         ("VOICE-01", "Inbound calls", "AI Employee answers calls on its connected number.", "§4", "P5"),
         ("VOICE-02", "Authorized outbound calls", "From campaigns, scheduled follow-ups or \"Call now\". Consent, opt-out and "
          "calling-hour checks before every dial.", "§4", "P5"),
         ("VOICE-03", "Real-time pipeline", "Customer → Telephony → Speech-to-Text → AI Agent → Knowledge + Database → Tools / APIs → "
          "Text-to-Speech → Customer, streamed end-to-end.", "§5", "P5"),
         ("VOICE-04", "Low latency", "Target response time P50 ≤ 1.2 s and P95 ≤ 2.0 s from the end of customer speech (validated in "
          "the Phase 0 proof of concept).", "§5", "P5"),
         ("VOICE-05", "Natural conversation", "Turn detection, short acknowledgements, filler while a tool runs (\"ek second, main "
          "check karti hoon\").", "§4, §5", "P5"),
         ("VOICE-06", "Interruption / barge-in", "Customer can interrupt; AI stops speaking immediately and listens.", "§4", "P5"),
         ("VOICE-07", "MVP languages", "Hindi, English, Bengali, including code-mixed speech.", "§4", "P5"),
         ("VOICE-08", "Professional quality in every language", "STT / TTS provider and voice chosen per language from Super Admin. "
          "Phase 0 bake-off compares providers per language on accuracy, naturalness and latency.", "DEC", "P0, P5"),
         ("VOICE-09", "Voice catalogue", "Voices per language (gender, style, sample) managed in Super Admin.", "§22", "P5"),
         ("VOICE-10", "AI identification", "AI introduces itself as an AI assistant (configurable text per language).", "§4", "P5"),
         ("VOICE-11", "Call transfer", "Warm transfer with spoken / on-screen summary to the human; cold transfer fallback; if no human "
          "is available, take a message and create a callback task.", "§4, §16", "P5"),
         ("VOICE-12", "Call recording", "On/off per company and employee; consent announcement; retention days; listen / download "
          "permissions; every access audited.", "§17", "P5"),
         ("VOICE-13", "Transcript", "Speaker-labelled, time-stamped transcript stored for every call.", "§4, §17", "P5"),
         ("VOICE-14", "Post-call analysis", "Call duration · transcript · summary · customer requirement · lead score · sentiment / "
          "intent (only above confidence threshold) · follow-up requirement · appointment details · transfer status · outcome.",
          "§17", "P5"),
         ("VOICE-15", "Call logs", "List with filters; detail with recording player, transcript, summary, extracted fields and tool calls.",
          "§17", "P5"),
         ("VOICE-16", "Phone-number management", "Connect provider numbers, assign to an AI Employee, inbound routing. Development uses "
          "our test account; launch uses the client's own account.", "DEC", "P5"),
         ("VOICE-17", "Voicemail & no-answer handling", "Detect voicemail / busy / no-answer and apply retry rules.", "§18", "P5"),
         ("VOICE-18", "Call limits", "Maximum concurrent calls per company (plan), maximum duration, daily caps, calling hours.",
          "§18", "P5"),
         ("VOICE-19", "Browser test call", "Test the AI Employee by voice from the browser.", "§21", "P5"),
         ("VOICE-20", "Add languages without code", "New language = Super Admin configuration (code, STT / TTS mapping, voices, "
          "greeting and disclosure texts) + quality test.", "§4", "P5 (mechanism), P11"),
         ("VOICE-21", "Provider failover", "Secondary STT / TTS / LLM used automatically when a provider fails.", "§27", "P5"),
         ("VOICE-22", "Voice quality metrics", "Per call: latency per stage, recognition confidence, interruptions, silences, errors.",
          "REC", "P5"),
     ]),
    ("M15", "WhatsApp", "Official WhatsApp Business integration for follow-ups, reminders and two-way AI conversations.",
     [
         ("WA-01", "Official API only", "WhatsApp Business Platform (Cloud API) or an approved BSP through an adapter. No unofficial "
          "automation that risks bans.", "§14", "P6"),
         ("WA-02", "Connect number", "Company connects its WhatsApp Business number (Meta embedded signup or BSP onboarding).", "§14", "P6"),
         ("WA-03", "Template management", "Create and sync message templates; approval status; variables; language; category.", "§14", "P6"),
         ("WA-04", "Automated approved messages", "Lead follow-up · appointment confirmation · reminder · property / product information "
          "(photos, brochure PDF, location).", "§14", "P6"),
         ("WA-05", "AI replies", "AI Employee answers customer replies with the same engine and knowledge.", "§14", "P6"),
         ("WA-06", "Shared inbox", "Conversation list for humans; take over (AI pauses), reply, hand back to AI, assign.", "§14, §16", "P6"),
         ("WA-07", "Human handover", "Rule-based or customer-requested handover with AI summary.", "§14, §16", "P6"),
         ("WA-08", "Opt-in / opt-out", "Opt-out keywords (e.g., STOP) honoured automatically; consent stored.", "§14", "P6"),
         ("WA-09", "Voice notes", "Incoming voice notes transcribed and answered.", "REC", "P6"),
         ("WA-10", "Delivery tracking & usage", "Sent / delivered / read / failed status; usage metered for billing.", "§24", "P6"),
     ]),
    ("M16", "Website Chat Widget", "Embeddable \"Chat with our AI Employee\" widget for each business website.",
     [
         ("CHAT-01", "Embeddable widget", "Generated per AI Employee; added to any website with a small JavaScript snippet.", "§15", "P6"),
         ("CHAT-02", "Customisation", "Launcher text (\"Chat with our AI Employee\"), name, avatar, colours, position, greeting, language.",
          "§15", "P6"),
         ("CHAT-03", "Customer actions", "Ask questions · submit enquiry · request callback · book appointment · get approved "
          "information · connect with human.", "§15", "P6"),
         ("CHAT-04", "Lead capture", "Creates or updates a CRM lead (source: Website Chat).", "§15", "P6"),
         ("CHAT-05", "Security", "Allowed-domain list, rate limiting, bot / spam protection.", "§25", "P6"),
         ("CHAT-06", "Human takeover", "Live chat takeover from the shared inbox.", "§16", "P6"),
         ("CHAT-07", "Lightweight & mobile", "Small bundle, asynchronous loading, works in mobile browsers.", "§26", "P6"),
     ]),
    ("M17", "Human Handoff", "AI knows when to hand over to a human, and the human receives full context.",
     [
         ("HO-01", "Handoff triggers", "Customer asks for a person · question outside approved knowledge · hot lead · plus configurable "
          "triggers (repeated misunderstanding, negative sentiment, keywords).", "§16", "P5 (voice), P6 (chat)"),
         ("HO-02", "Routing", "Assigned agent → team round-robin → any available agent → fallback. Respects agent availability "
          "status and calendar.", "§16", "P5"),
         ("HO-03", "Agent context", "Human sees lead details, AI conversation summary, requirement, score and transcript at the moment "
          "of transfer (screen pop + mobile notification).", "§16", "P5"),
         ("HO-04", "No agent available", "Customer informed with configured message; callback task created; lead flagged.", "§16", "P5"),
         ("HO-05", "Handoff log", "Reason, time to answer and outcome recorded on conversation and lead.", "§17", "P5"),
     ]),
    ("M18", "Call Transcript, Summary & Conversation Records", "What is stored after every conversation.",
     [
         ("REC-01", "Per-call record", "<b>Call duration · Transcript · Summary · Customer requirement · Lead score · Sentiment / intent "
          "(where reliable) · Follow-up requirement · Appointment details · Transfer status</b>; plus direction, numbers, AI Employee, "
          "start / end time, outcome, recording, detected language, tools used, usage.", "§17", "P5"),
         ("REC-02", "WhatsApp & chat records", "Same summary / requirement / score structure for WhatsApp and website chat.", "§17", "P6"),
         ("REC-03", "Recording compliance controls", "Consent announcement, enable/disable, retention period with auto-delete, role-based "
          "listen / download, access audit.", "§17", "P5"),
     ]),
    ("M19", "Campaign Management", "Planned, compliant outbound calling to lead lists.",
     [
         ("CAMP-01", "Create campaign", "Name (e.g., \"New Town Property Leads\") · description · <b>Lead list</b> (filter, saved view or CSV) · "
          "<b>AI Employee</b> · <b>Calling schedule</b> (dates, days, time windows) · <b>Retry rules</b> (maximum attempts, gap, outcomes to "
          "retry) · <b>Property collection</b> (or catalogue collection) · <b>Follow-up rules</b> (e.g., WhatsApp after call, next call for "
          "WARM) · maximum concurrent calls · daily limit.", "§18", "P6"),
         ("CAMP-02", "Campaign controls", "Start · Pause · Resume · Stop. Statuses: Draft, Scheduled, Running, Paused, Completed, Stopped.",
          "§18", "P6"),
         ("CAMP-03", "Compliance enforcement", "Before every dial the system enforces calling limits, calling hours, opt-out / DND list, "
          "consent flags and plan usage.", "§4, §18", "P6"),
         ("CAMP-04", "Live progress", "Total, pending, dialled, connected, qualified, hot, appointments, failed, skipped.", "§18", "P6"),
         ("CAMP-05", "Report & export", "Per-lead outcome export and campaign summary.", "REC", "P6"),
         ("CAMP-06", "Test mode", "Run a campaign against internal test numbers only.", "REC", "P6"),
     ]),
    ("M20", "Dashboard & Analytics", "Company dashboard with KPIs and charts.",
     [
         ("DASH-01", "KPI cards", "<b>Total AI Employees · Calls Today · Connected Calls · Qualified Leads · Hot Leads · Appointments · "
          "Conversions · Human Transfers · AI Usage</b>.", "§19", "P7"),
         ("DASH-02", "Charts", "<b>Leads · Calls · Connected Calls · Qualified Leads · Appointments · Conversion · Usage</b>, with date "
          "range (today, 7 days, 30 days, custom) and AI Employee filter.", "§19", "P7"),
         ("DASH-03", "Per-employee analytics", "As EMP-13.", "§20", "P7"),
         ("DASH-04", "Campaign analytics", "Funnel per campaign.", "§18", "P7"),
         ("DASH-05", "Live counters", "Dashboard updates in real time.", "REC", "P7"),
         ("DASH-06", "Advanced analytics", "Human-agent performance, conversion funnel, AI quality metrics, scheduled email reports, "
          "PDF / CSV export.", "REC", "P12"),
     ]),
    ("M21", "SaaS Subscription & Plans", "Plans, pricing and limits, all controlled from Super Admin.",
     [
         ("SUB-01", "Plans managed in Super Admin", "Name, monthly price (INR), yearly price (optional), GST rate, trial days, public / "
          "private, included limits (AI employees, users, voice minutes, calls, WhatsApp conversations, AI credits, knowledge storage, "
          "concurrent calls, campaigns, feature access), overage prices. Nothing hard-coded.", "§23", "P1"),
         ("SUB-02", "Seed plans", "STARTER ₹2,999 / month · BUSINESS ₹9,999 / month · PRO ₹24,999 / month · ENTERPRISE custom. "
          "Seed data only; editable any time.", "§23", "P1"),
         ("SUB-03", "Razorpay subscriptions", "Checkout, auto-renewal, upgrade / downgrade with proration, cancellation, failed-payment "
          "retries and grace period.", "DEC", "P7"),
         ("SUB-04", "Enterprise plans", "Custom limits and price assigned to a company by Super Admin; manual invoice option.", "§23", "P7"),
         ("SUB-05", "Feature gating", "Plan limits and features enforced in API and UI.", "§23", "P7"),
         ("SUB-06", "GST invoices", "Auto-generated GST-compliant invoices (company GSTIN, place of supply, CGST / SGST / IGST), "
          "downloadable PDF.", "§24", "P7"),
     ]),
    ("M22", "Usage Tracking & Billing", "Voice, AI and WhatsApp usage measured separately, ready for usage-based billing.",
     [
         ("USE-01", "Usage metering", "Voice minutes (inbound / outbound), calls, AI usage (credits from tokens), WhatsApp "
          "conversations / messages, STT / TTS consumption, storage. Recorded per company, employee and conversation.",
          "§23, §24", "P4-P6 capture, P7 display"),
         ("USE-02", "Billing page", "<b>Voice minutes · Calls · AI usage · WhatsApp usage · Credits · Remaining usage · Billing history · "
          "Subscription · Invoices</b>.", "§24", "P7"),
         ("USE-03", "Limits & alerts", "Alerts at configurable thresholds (e.g., 80 %, 100 %); hard stop or overage behaviour per plan.",
          "§24", "P7"),
         ("USE-04", "Credits", "Credit balance; credits granted by plan; Super Admin adjustments.", "§24", "P7"),
         ("USE-05", "Usage-based billing", "Pay-as-you-go / credit top-ups via Razorpay; overage invoicing.", "§24", "P12"),
         ("USE-06", "Provider cost tracking", "Actual provider cost per call / message stored for Super Admin margin reports.", "§24", "P7"),
     ]),
    ("M23", "Super Admin Panel", "Custom panel on our own template. Django's built-in admin is not used.",
     [
         ("SA-01", "Built on our template", "Fully custom Super Admin panel built on the Rizz admin template (folder AdminTemplate), light theme. "
          "Django's built-in admin (django.contrib.admin) is not installed.", "DEC", "P1 → all"),
         ("SA-02", "Platform dashboard", "Companies, active AI Employees, calls, minutes, MRR / revenue, usage, errors, provider health.",
          "§22", "P7"),
         ("SA-03", "Companies", "List / search, detail, create, edit, suspend / activate, change plan, usage, data export / deletion, "
          "support login (impersonation with audit trail and visible banner).", "§22", "P1"),
         ("SA-04", "Users", "All users, roles, reset password, lock / unlock, reset 2FA, deactivate.", "§22", "P1"),
         ("SA-05", "Industries & industry templates", "Everything in M04, including activate / deactivate.", "§22", "P3"),
         ("SA-06", "Roles & tools", "Everything in M05 and M09.", "§22", "P3, P4"),
         ("SA-07", "CRM configuration", "Statuses, sources, fields, scoring rules, import limits.", "DEC", "P3"),
         ("SA-08", "AI Employees (all companies)", "View, status, pause for abuse, configuration history.", "§22", "P4"),
         ("SA-09", "AI providers", "LLM providers, model per task, fallback order, encrypted keys, cost per unit, enable / disable. "
          "Includes a generic <b>OpenAI-compatible</b> provider type (base URL + key), so any compatible gateway can be added "
          "without code.", "§22, §27", "P4"),
         ("SA-28", "Free LLM gateway for testing", "During development and testing the AI runs on free LLM tiers through a "
          "self-hosted <b>FreeLLMAPI</b> gateway (added as an OpenAI-compatible provider), so testing costs neither us nor the "
          "client. Rules: provider marked <b>Test only</b> and blocked in production; dummy data only, never real customer "
          "data; one account per upstream provider; phase-gate AI evaluation and voice latency tests run on the real "
          "production model.", "DEC", "P1 → all"),
         ("SA-10", "Voice & channel providers", "STT, TTS, telephony, WhatsApp, email, SMS and payment providers: encrypted credentials, "
          "routing per language, number pool, health status.", "§22", "P5-P7"),
         ("SA-11", "Languages & voices", "Add / enable languages; STT / TTS mapping; voice catalogue; default greetings and disclosure "
          "texts.", "§22", "P5"),
         ("SA-12", "Plans & pricing", "Everything in M21.", "§22, §23", "P1"),
         ("SA-13", "Billing", "Subscriptions, payments, invoices, failed payments, GST settings, credit adjustments.", "§22", "P7"),
         ("SA-14", "Usage", "Usage per company and per provider; cost vs revenue.", "§22", "P7"),
         ("SA-15", "Calls", "Global call log across companies with filters and quality metrics.", "§22", "P5"),
         ("SA-16", "System settings", "Platform name and branding, registration on/off, trial settings, password and session policy, 2FA "
          "enforcement, upload limits, retention defaults, recording defaults, calling defaults (hours, attempts, DND check), email and "
          "notification templates, website content, legal pages.", "§22", "P1 (+ each phase)"),
         ("SA-17", "Logs", "Audit log, system / error log, API log, webhook log, call-event log: searchable and filterable.", "§22, §25", "P1"),
         ("SA-18", "Security", "Staff accounts and roles (Super Admin, Support), mandatory 2FA, IP allowlist, sessions, security events.",
          "§22, §25", "P1"),
         ("SA-19", "Support", "Tickets from companies, replies, status; platform enquiries from the website.", "§22", "P7"),
         ("SA-20", "Feature flags", "Enable features per plan or per company.", "REC", "P7"),
         ("SA-21", "General Settings menu", "Dedicated <b>General Settings</b> menu in Super Admin holding all platform-wide "
          "settings of our SaaS. Nothing below is hard-coded anywhere; changes apply everywhere without deployment.", "DEC", "P1"),
         ("SA-22", "Branding", "<b>Platform name</b> · short name · tagline · <b>logo</b> (light and dark versions) · <b>favicon</b> · "
          "app / PWA icon · login-page image · brand colours · \"Powered by\" text on the chat widget.", "DEC", "P1"),
         ("SA-23", "Branding shown everywhere", "Values read live by: public website (header, footer, page titles, favicon), company "
          "panel, Super Admin, login / registration pages, emails, GST invoices, chat widget, PWA and the future Flutter app "
          "(through the API).", "DEC", "P1 → all"),
         ("SA-24", "Contact & company details", "Support email, support phone / WhatsApp, office address, legal company name, "
          "GSTIN / PAN for invoices, social media links, copyright / footer text.", "DEC", "P1"),
         ("SA-25", "Localisation defaults", "Default timezone (Asia/Kolkata), currency (INR), date / number format (lakh / crore), "
          "default language.", "DEC", "P1"),
         ("SA-26", "SEO & email defaults", "Default meta title, description, OpenGraph image, analytics tracking IDs; email sender "
          "name and address, email header / footer.", "DEC", "P1"),
         ("SA-27", "Maintenance mode", "Switch the website and panels to a maintenance page with a custom message (Super Admin "
          "still accessible).", "DEC", "P1"),
     ]),
    ("M24", "Company Panel (General)", "Professional panel for each registered business, built on our template.",
     [
         ("CP-01", "Built on our template", "Professional company admin panel built on the same Rizz template as Super Admin "
          "(own sidebar and accent colour), light theme.", "DEC", "P2"),
         ("CP-02", "Navigation", "Dashboard · AI Employees · Leads · Calendar · Conversations (Calls, WhatsApp, Chat inbox) · Campaigns · "
          "Knowledge Base · Catalogue (Properties / Packages / Courses …) · Analytics · Billing & Usage · Team · Settings · Support. "
          "Menus shown per role and plan.", "§19-§21", "P2 (shell)"),
         ("CP-03", "Notifications", "In-app notification centre plus email / WhatsApp / push to humans: hot lead, transfer request, new "
          "appointment, campaign finished, usage alerts.", "§16", "P6"),
         ("CP-04", "Global search", "Find leads by name, phone or email from anywhere in the panel.", "REC", "P3"),
         ("CP-05", "Support", "Raise tickets to platform support.", "§22", "P7"),
         ("CP-06", "Settings", "Company profile, business hours, holidays, channels (numbers, WhatsApp, widget), compliance (recording, "
          "consent texts, calling hours within platform limits), data export / delete request.", "§25", "P2 → P7"),
         ("CP-07", "Mobile-first agent experience", "Human agents work fully from a phone: leads, follow-ups, transfers, calendar, inbox. "
          "Installable web app with push notifications.", "§26", "P6"),
     ]),
    ("M25", "Security", "Security controls required by the client, with implementation detail.",
     [
         ("SEC-01", "HTTPS", "TLS 1.2+ everywhere, HSTS, secure cookies.", "§25", "P1"),
         ("SEC-02", "Secure authentication", "Argon2 password hashing, 2FA, lockout, session controls (M02).", "§25", "P1"),
         ("SEC-03", "Role-based access", "Panel, API and object-level permission checks.", "§25", "P1"),
         ("SEC-04", "API key protection", "Provider keys entered only in Super Admin and stored encrypted in the database; never in .env, code or browsers; rotation supported.",
          "§25", "P1"),
         ("SEC-05", "Database access control", "Private network, least-privilege database users, row-level security.", "§25", "P1"),
         ("SEC-06", "Company-level data isolation", "See M03.", "§25", "P1"),
         ("SEC-07", "Encryption", "Encryption at rest (database, files, backups) and field-level encryption of credentials and tokens.",
          "§25", "P1"),
         ("SEC-08", "Audit logs", "Who did what, when, from where. Append-only.", "§25", "P1"),
         ("SEC-09", "Rate limiting", "Per IP, user, company, widget and webhook.", "§25", "P1"),
         ("SEC-10", "Backups", "Automated daily backups plus point-in-time recovery; restore drill at P8 and quarterly after launch.",
          "§25", "P1, P8"),
         ("SEC-11", "Secure file storage", "Private buckets, signed URLs, file type / size validation, malware scan.", "§25", "P4"),
         ("SEC-12", "Data deletion controls", "Retention policies, recording auto-delete, account deletion (TEN-07).", "§25", "P7"),
         ("SEC-13", "Webhook verification", "Signature verification for telephony, WhatsApp and Razorpay callbacks.", "§25", "P5-P7"),
         ("SEC-14", "AI security", "Prompt-injection defences, tool permission scoping, output validation.", "§25", "P4"),
         ("SEC-15", "Security testing", "SAST, dependency, secret and container scans on every pull request; DAST on staging; external "
          "penetration test before launch.", "§25", "All, P8"),
     ]),
    ("M26", "Compliance & Trust Controls", "Configurable controls written into the client's requirements.",
     [
         ("COMP-01", "AI disclosure", "AI identifies itself as an AI assistant in every conversation.", "§4", "P4"),
         ("COMP-02", "Consent records", "Consent / opt-out stored per lead and channel with source and timestamp.", "§4", "P5"),
         ("COMP-03", "DND / opt-out check", "Opt-out list and DND check before every outbound call (provider / registry integration point).",
          "§4, §18", "P6"),
         ("COMP-04", "Calling hours & attempt caps", "Platform-level limits from Super Admin; company can tighten but not exceed them.",
          "§18", "P6"),
         ("COMP-05", "No unauthorised robocalling", "Outbound only to leads with a valid source or consent; campaign start requires "
          "company-admin approval.", "§4", "P6"),
         ("COMP-06", "Recording consent & retention", "See REC-03.", "§17", "P5"),
         ("COMP-07", "Official WhatsApp API only", "See WA-01 and WA-08.", "§14", "P6"),
         ("COMP-08", "Collection role restrictions", "Enabled per company by Super Admin; tone and timing guardrails.", "§3", "P10"),
         ("COMP-09", "Data privacy", "Export, deletion, retention; hosting region chosen by client.", "§4, §25", "P7"),
     ]),
    ("M27", "Notifications & Communication", "System messages to platform users.",
     [
         ("NOTI-01", "Transactional emails", "Welcome, verification, password reset, invitation, invoice, payment failed, usage alerts. "
          "Templates managed in Super Admin.", "§22", "P1, P7"),
         ("NOTI-02", "In-app notifications", "Notification centre with read / unread state.", "REC", "P6"),
         ("NOTI-03", "Agent alerts", "WhatsApp / push alerts to human agents for transfers, hot leads and bookings.", "§16", "P6"),
     ]),
    ("M28", "Mobile Responsiveness", "Works properly on every device sales teams use.",
     [
         ("MOB-01", "All surfaces responsive", "Website, company panel, Super Admin and widget on desktop, laptop, tablet, Android and "
          "iPhone. Device testing is part of every phase gate.", "§26", "All"),
         ("MOB-02", "Mobile layouts", "Tables become cards; touch-friendly controls; bottom navigation for agents.", "§26", "All"),
         ("MOB-03", "Installable app", "Progressive Web App with push notifications for human agents.", "REC", "P6"),
     ]),
    ("M29", "Platform Engineering", "Non-functional foundations that make the product reliable and testable.",
     [
         ("ENGR-01", "Source control", "GitHub repository, branch protection, mandatory pull-request reviews.", "§29", "P0"),
         ("ENGR-02", "CI pipeline", "GitHub Actions: lint, type checks, tests, builds, security scans on every pull request.", "§29", "P0"),
         ("ENGR-03", "Environments", "Local, staging and production; staging mirrors production.", "§29", "P0, P8"),
         ("ENGR-04", "Deployment as code", "Docker images and compose files for the hosting the client chooses; no provider-specific code.", "§27", "P8"),
         ("ENGR-05", "Monitoring & alerting", "Logs, metrics, traces, error tracking and alerts.", "REC", "P1 → P8"),
         ("ENGR-06", "API documentation", "OpenAPI specification generated from code.", "REC", "P1"),
         ("ENGR-07", "Load & performance testing", "API load tests and concurrent-call simulations.", "§32", "P5, P8"),
         ("ENGR-08", "Disaster recovery", "Documented DR plan and restore drill.", "§25", "P8"),
     ]),
    ("M30", "API-First & Mobile App Readiness",
     "Every section is built in Django together with its REST APIs, so the future Flutter mobile app (Android + iOS) connects "
     "to the same system: same data, same workflows. Only the mobile UI and app-side code will need to be written.",
     [
         ("API-01", "REST API for every feature", "Every feature in this catalogue is delivered with its Django REST API in the "
          "<b>same phase</b>. The web panels use these same APIs, so no capability is web-only.", "DEC", "P1 → all"),
         ("API-02", "Mobile-ready authentication", "The same login endpoints issue Bearer access and refresh tokens for mobile apps "
          "(stored in iOS Keychain / Android Keystore); web panels use secure cookies. Same 2FA, roles and company isolation.",
          "DEC", "P1"),
         ("API-03", "API documentation", "OpenAPI specification generated from the Django code and published every phase; used to "
          "auto-generate the Flutter (Dart) API client.", "DEC", "P1 → all"),
         ("API-04", "Stable versioning", "All endpoints under /api/v1. Breaking changes only in a new version, so already-released "
          "mobile apps keep working.", "DEC", "P1"),
         ("API-05", "Push notification devices", "Register / remove mobile device tokens (Firebase Cloud Messaging for Android and "
          "iOS) so the app receives hot-lead, transfer and appointment alerts.", "DEC", "P6"),
         ("API-06", "Mobile-friendly responses", "Cursor pagination, filters, compact payloads, file upload / download through signed "
          "URLs, real-time events over the same WebSocket.", "DEC", "P1 → all"),
         ("API-07", "API tests every phase", "Every endpoint covered by automated API tests (including cross-company isolation) as "
          "part of the GitHub CI gate.", "DEC", "P1 → all"),
         ("API-08", "Flutter mobile app (Android + iOS)", "Future project. The app connects to the same APIs, data and workflows; "
          "only mobile design and app-side code are written. Not in the current scope.", "DEC", "Future"),
     ]),
]

# ---------------------------------------------------------------------------
PHASES = [
    {
        "id": "P0", "title": "Discovery, Architecture & Project Setup", "client": "Milestone 1: architecture (separate UI/UX "
                                                                                    "design dropped, agreed with client)", "rel": "MVP",
        "objective": "Freeze scope and architecture, set up the project, map the supplied templates, and prove that voice quality "
                     "and latency meet the target in Hindi, English and Bengali. No separate UI/UX design or prototype is produced: "
                     "as agreed with the client, development starts directly on the website and admin templates supplied by our team.",
        "scope": [
            ("Documents", "This requirements document (PRD-01) and the System Design & Architecture document (SDD-02): technical, "
                          "database, API, AI, voice and industry-template architecture; security, deployment and testing plans."),
            ("Template mapping", "Review the supplied website template and admin templates; map every website section to a Super "
                                 "Admin content model (WEB-09) and every panel page to its feature."),
            ("Voice PoC", "Provider bake-off: Hindi, English and Bengali × 2-3 STT / TTS providers. Scored on recognition accuracy "
                          "(including code-mixed speech), voice naturalness and end-to-end latency. Best provider chosen per language."),
            ("AI PoC", "LLM evaluation on Hinglish / Bengali extraction (budget, location, BHK) and grounded answering."),
            ("Engineering", "GitHub repository, branch protection, CI skeleton, environments, (ENGR-01..03); "
                            "one Django 5.2 project; eSoft and Rizz templates and static files copied in; Rizz SCSS built "
                            "once with gulp."),
            ("Commercial", "Timeline, fixed development cost, third-party API, running, hosting and maintenance costs in a separate "
                           "commercial proposal."),
        ],
        "admin": ["Settings registry designed: complete list of every configurable value and which Super Admin screen owns it.",
                  "Template sections mapped to Super Admin content models (website) and screens (panels)."],
        "tests": ["Voice PoC meets latency target (P50 ≤ 1.2 s) for each MVP language, or a mitigation is agreed.",
                  "Template mapping sheet reviewed: no website section left without a Super Admin editor.",
                  "Repository CI pipeline runs green on the empty skeleton."],
        "deliver": ["Signed-off PRD-01 and SDD-02", "Template mapping sheet", "Voice & AI PoC report with per-language "
                    "provider choice", "Commercial proposal", "Repository with green CI"],
    },
    {
        "id": "P1", "title": "Core Platform & Super Admin First",
        "client": "Milestone 2 (part 1): authentication + Super Admin", "rel": "MVP",
        "objective": "Build the backend core (authentication, roles, multi-tenancy, security baseline) and the Super Admin panel on "
                     "our admin template first, because every other part of the product is configured from it. Super Admin gets "
                     "General Settings, the full website content manager (every section of the website template), plans and "
                     "pricing data, companies, users, settings and logs. All with REST APIs.",
        "scope": [
            ("Auth & security", "AUTH-03 to AUTH-06, AUTH-08, AUTH-11, SEC-01 to SEC-10"),
            ("Multi-tenancy", "TEN-01, TEN-02, TEN-03, TEN-05, TEN-06"),
            ("Super Admin", "SA-01, SA-03, SA-04, SA-16 (base), SA-17, SA-18; General Settings SA-21 to SA-27"),
            ("Website content", "WEB-04, WEB-09: an editor for every section of the website template, legal pages, SEO"),
            ("Plans & pricing data", "SUB-01, SUB-02, SA-12 (plans and limits; payments come in P7)"),
            ("Other", "NOTI-01 (account emails), ENGR-05, ENGR-06, API-01 to API-04, API-06, API-07"),
        ],
        "admin": ["General Settings: platform name, logo, favicon, colours, contact details, footer, localisation, email sender, "
                  "maintenance mode (shown everywhere)", "Website content: every section, heading, text, image, button, order, "
                  "show / hide; legal pages; SEO", "Plans, prices and limits", "Registration on/off, trial settings, password, "
                  "session, lockout and 2FA policy", "Roles and permissions", "Email templates",
                  "Companies, users, audit logs, security events"],
        "tests": ["Super Admin login with mandatory 2FA, lockout and audit trail",
                  "Every website section editable and versioned via API; content API returns what the editor saved",
                  "RBAC matrix tests for staff roles", "Cross-tenant isolation suite (TEN-05) green"],
        "deliver": ["Working Super Admin panel on our admin template", "General Settings and full website content manager",
                    "Plans and pricing data", "Documented REST APIs"],
    },
    {
        "id": "P2", "title": "Website, Company Registration & Company Panel",
        "client": "Milestone 2 (part 2): company registration + company dashboard", "rel": "MVP",
        "objective": "Build the public animated website on the supplied template, reading every section from Super Admin, the "
                     "company registration flow, and the company panel shell on our template, so a business can register, verify, "
                     "log in and invite its team.",
        "scope": [
            ("Website", "WEB-01 to WEB-03, WEB-05 to WEB-08: all content from Super Admin (WEB-04)"),
            ("Registration & team", "AUTH-01, AUTH-02, AUTH-07, AUTH-09, AUTH-10"),
            ("Company panel", "CP-01, CP-02 (shell), CP-06 (profile)"),
        ],
        "admin": ["Platform enquiries inbox", "Registered companies appear in Super Admin with onboarding status"],
        "tests": ["E2E: visitor → register company → verify → login → 2FA → invite team member",
                  "Change any website section in Super Admin → visible on the website without deployment",
                  "No hard-coded text left in the website template (review checklist)",
                  "Website Lighthouse ≥ 90 on mobile and desktop; device testing on all five device classes"],
        "deliver": ["Live staging website driven by Super Admin", "Working registration and login", "Company panel shell on our "
                    "template"],
    },
    {
        "id": "P3", "title": "Configuration Engine, CRM, Catalogues & Calendar",
        "client": "Milestone 5: CRM + leads (scheduled earlier because AI tools write into CRM and calendar)", "rel": "MVP",
        "objective": "Build the industry template engine, the built-in CRM with dynamic fields, business catalogues (property "
                     "database, travel packages, courses) and the built-in calendar. Everything the AI Employee will act on "
                     "exists and is configurable before the AI is connected.",
        "scope": [
            ("Industry templates", "IND-01 to IND-05; IND-06 configuration for Real Estate, Travel, Education"),
            ("Roles", "ROLE-01"), ("CRM", "CRM-01 to CRM-07, CRM-09 to CRM-18"), ("Scoring rules", "SCORE-02"),
            ("Catalogues", "CAT-01, CAT-02, CAT-04 to CAT-08"), ("Calendar", "CAL-01 to CAL-05, CAL-08, CAL-09"),
            ("Panels", "CP-04, SA-05, SA-07"),
        ],
        "admin": ["Industries, templates, versions, activate / deactivate, clone", "Lead fields, statuses, sources, scoring rules",
                  "Catalogue types and fields", "Appointment types, platform holidays", "Role templates"],
        "tests": ["Add a new CRM field and a new catalogue field from Super Admin with no deployment (demonstrated live)",
                  "Import 10,000 leads with duplicates and errors; verify report", "Double-booking prevention under concurrent requests",
                  "Template versioning: publish, upgrade a company, roll back"],
        "deliver": ["Working CRM with Real Estate / Travel / Education fields", "Property, package and course catalogues",
                    "Built-in calendar", "Template engine in Super Admin"],
    },
    {
        "id": "P4", "title": "AI Employee Engine, Knowledge Base & Tools",
        "client": "Milestone 3: AI Employee engine + Milestone 6: Knowledge base + tools", "rel": "MVP",
        "objective": "Deliver the AI Employee creation wizard, the shared AI engine, the knowledge base with approval workflow and the "
                     "tools framework. AI Employees work end-to-end in text (test console) for all three MVP industries.",
        "scope": [
            ("Roles", "ROLE-02 to ROLE-05"), ("AI Employee management", "EMP-01 to EMP-12 (text testing)"),
            ("Engine", "ENG-01 to ENG-12"), ("Knowledge base", "KB-01 to KB-11"),
            ("Tools", "TOOL-01 to TOOL-07, TOOL-13 to TOOL-15"), ("Scoring", "SCORE-01, SCORE-03, SCORE-04, SCORE-06"),
            ("Other", "CAT-03, CAL-06, TEN-04, USE-01 (AI usage), SA-06, SA-08, SA-09, SEC-11, SEC-14, COMP-01"),
        ],
        "admin": ["Tool registry", "LLM providers, model per task and fallback order", "Base instructions, guardrails and greetings per "
                  "template and language", "Knowledge limits per plan"],
        "tests": ["AI evaluation suite for Real Estate, Travel, Education × Hindi, English, Bengali (text)",
                  "Grounding test: zero invented prices, discounts or availability across the test set",
                  "Extraction accuracy ≥ agreed threshold (e.g., budget, location, BHK)", "Correct tool selection and arguments",
                  "Prompt-injection and cross-tenant knowledge tests"],
        "deliver": ["AI Employee wizard (10 steps, text test)", "Knowledge base with approval", "Tools framework + MVP tools",
                    "Automatic lead scoring"],
    },
    {
        "id": "P5", "title": "Voice AI", "client": "Milestone 4: Voice calling", "rel": "MVP",
        "objective": "Connect the AI engine to the telephone: inbound and authorised outbound calls in Hindi, English and Bengali with "
                     "low latency, barge-in, transfers, recordings, transcripts and post-call analysis.",
        "scope": [
            ("Voice", "VOICE-01 to VOICE-22"), ("Tools", "TOOL-08"), ("Handoff", "HO-01 to HO-05 (voice)"),
            ("Records", "REC-01, REC-03"), ("Wizard", "EMP-05 live voices, EMP-08 phone, EMP-10 voice test"),
            ("Super Admin", "SA-10 (telephony, STT, TTS), SA-11, SA-15"), ("Compliance", "COMP-02, COMP-06"),
            ("Usage", "USE-01 voice minutes and calls"),
        ],
        "admin": ["Telephony providers and number pool (test account now, client account at launch)", "STT / TTS provider per language",
                  "Voice catalogue", "Recording defaults and retention", "Latency and quality alert thresholds"],
        "tests": ["Latency P50 / P95 measured per language on real test calls", "50+ scripted test calls per language incl. code-mixed",
                  "Barge-in, transfer (warm / cold / no agent) and voicemail tests", "Provider failover test",
                  "Concurrent-call load test at the target agreed in P0"],
        "deliver": ["Inbound and outbound AI calls", "Transfers to humans", "Recordings, transcripts, summaries", "Call logs"],
    },
    {
        "id": "P6", "title": "WhatsApp, Website Chat, Appointments, Handoff & Campaigns",
        "client": "Milestone 7: WhatsApp + appointment", "rel": "MVP",
        "objective": "Add the remaining channels and automation: official WhatsApp, the website chat widget, appointment confirmations "
                     "and reminders, the shared inbox with human takeover, and compliant outbound campaigns.",
        "scope": [
            ("WhatsApp", "WA-01 to WA-10, TOOL-09, EMP-08 WhatsApp"), ("Website chat", "CHAT-01 to CHAT-07"),
            ("Appointments", "CAL-07, CAL-10"), ("Handoff", "HO-01 (chat / WhatsApp), SCORE-05"), ("Records", "REC-02"),
            ("Campaigns", "CAMP-01 to CAMP-06"), ("Compliance", "COMP-03, COMP-04, COMP-05, COMP-07"),
            ("Panel", "CP-03, CP-07, NOTI-02, NOTI-03, MOB-03"),
        ],
        "admin": ["WhatsApp provider configuration and default templates", "Platform calling limits, hours and attempt caps",
                  "Opt-out keywords", "Notification templates"],
        "tests": ["WhatsApp template approval, 24-hour window and opt-out behaviour on a test number",
                  "Campaign pacing, retry rules and limit enforcement; opt-out / DND numbers skipped",
                  "Reminder timing tests", "Widget embedded on an external test website", "Handoff E2E on all three channels"],
        "deliver": ["WhatsApp integration and shared inbox", "Website widget", "Campaigns", "Confirmations and reminders"],
    },
    {
        "id": "P7", "title": "Dashboards, Subscription, Billing, Usage & Super Admin Completion",
        "client": "Milestone 8: Admin + subscription", "rel": "MVP",
        "objective": "Deliver the company dashboard and analytics, Razorpay subscriptions with GST invoices, usage tracking and limits, "
                     "and the remaining Super Admin modules.",
        "scope": [
            ("Analytics", "DASH-01 to DASH-05, EMP-13"), ("Subscription", "SUB-03 to SUB-06 (plans data from P1)"),
            ("Usage", "USE-02, USE-03, USE-04, USE-06"), ("Super Admin", "SA-02, SA-12, SA-13, SA-14, SA-19, SA-20"),
            ("Data & support", "TEN-07, SEC-12, COMP-09, CP-05, NOTI-01 (billing emails)"),
        ],
        "admin": ["Plans, prices, limits, overage prices, GST, trial days", "Feature flags", "Credit adjustments",
                  "Support tickets"],
        "tests": ["Razorpay test mode: subscribe, renew, payment failure, upgrade, downgrade, cancel",
                  "GST invoice correctness (intra-state and inter-state)", "Limit enforcement and alerts",
                  "Usage reconciliation against provider reports", "Dashboard figures match raw data"],
        "deliver": ["Company dashboard", "Subscription and billing", "Usage page", "Complete Super Admin"],
    },
    {
        "id": "P8", "title": "Hardening, Security, Performance & Production Launch",
        "client": "Milestone 9: Testing + security + deployment", "rel": "MVP",
        "objective": "Prove the platform is secure, fast and recoverable, switch from test to client provider accounts, and launch.",
        "scope": [
            ("Testing", "Full regression of P1-P7; UAT with the client's team"),
            ("Security", "External penetration test; DAST; dependency audit; secrets review (SEC-15)"),
            ("Performance", "Load tests at launch targets (ENGR-07)"),
            ("Reliability", "Backup restore drill and DR plan (SEC-10, ENGR-08); alerting tuned"),
            ("Go-live", "Production setup on the hosting and domain chosen by the client; switch to client's telephony and WhatsApp accounts; runbooks; user, admin and "
                        "API guides; handover"),
        ],
        "admin": ["Production settings review: every configurable value verified in Super Admin, none in code"],
        "tests": ["Zero open critical / high vulnerabilities", "Load targets met", "Restore drill successful within the RTO",
                  "Client UAT sign-off and go-live approval"],
        "deliver": ["Production launch (MVP live)", "Security and load-test reports", "Runbooks and documentation"],
    },
    {
        "id": "P9", "title": "Industry Expansion", "client": "Post-MVP", "rel": "Post-MVP",
        "objective": "Add the remaining eight industry templates through the template engine. Template content (fields, catalogues, "
                     "appointment types, instructions, WhatsApp templates) is finalised with the client at the start of the phase.",
        "scope": [("Templates", "IND-07, IND-08, CRM-08 and the industry proposals in the table below")],
        "admin": ["All eight templates are created and published from Super Admin"],
        "tests": ["AI evaluation suite per new template and language", "New templates added without changing the core engine "
                  "(only new tool handlers where an industry needs a new action)"],
        "deliver": ["Eight additional live industry templates"],
    },
    {
        "id": "P10", "title": "Additional AI Employee Types & Custom Roles", "client": "Post-MVP", "rel": "Post-MVP",
        "objective": "Add the Customer Support and Collection / Reminder employees, the ticketing and receivables modules they need, "
                     "an external API connector, and the custom role builder.",
        "scope": [
            ("Roles", "ROLE-06, ROLE-07, ROLE-08"), ("Tools", "TOOL-10, TOOL-11, TOOL-12"), ("Compliance", "COMP-08"),
            ("Support tickets", "Ticket ID, Customer, Subject, Description, Channel, Priority, Status (Open, In Progress, Waiting on "
                                "Customer, Resolved, Closed), Assignee, Conversation link, Timestamps"),
            ("Receivables (collection)", "Customer, Reference, Amount, Due date, Status, Reminders sent, Promise-to-pay date, Escalation"),
        ],
        "admin": ["Role availability per plan", "Collection enablement per company", "Connector security settings"],
        "tests": ["Ticket lifecycle", "Connector security (outbound request allowlist, timeouts)",
                  "Collection guardrails: tone, timing, opt-out"],
        "deliver": ["Support and Collection AI Employees", "Custom role builder", "External API connector"],
    },
    {
        "id": "P11", "title": "Language Expansion", "client": "Post-MVP", "rel": "Post-MVP",
        "objective": "Add Urdu, Marathi, Gujarati, Tamil, Telugu, Kannada, Malayalam, Punjabi and further Indian languages on request, "
                     "each through Super Admin configuration plus a quality bake-off.",
        "scope": [("Languages", "VOICE-20 applied per language: provider bake-off, voices, greetings and disclosure, AI evaluation set")],
        "admin": ["Language records, STT / TTS mapping, voices and texts"],
        "tests": ["Per-language quality score ≥ the threshold agreed in P0", "Latency target met per language"],
        "deliver": ["Eight or more additional production languages"],
    },
    {
        "id": "P12", "title": "Advanced Billing & Analytics", "client": "Post-MVP", "rel": "Post-MVP",
        "objective": "Complete usage-based billing and advanced reporting.",
        "scope": [("Billing", "USE-05: pay-as-you-go, credit top-ups, overage invoicing"),
                  ("Analytics", "DASH-06: agent performance, funnels, AI quality metrics, scheduled reports, exports")],
        "admin": ["Usage pricing, top-up packs, report schedules"],
        "tests": ["Billing reconciliation", "Report accuracy against raw data"],
        "deliver": ["Usage-based billing", "Advanced analytics"],
    },
]

INDUSTRY_PROPOSALS = [
    ("Automobile", "Car Model, Budget, Variant, Test Drive (client-specified); Fuel type, Finance needed, Exchange vehicle",
     "Models / variants / prices", "Test Drive", "search_vehicle, book_test_drive"),
    ("Hotels", "Check-in, Check-out, Guests, Room type, Budget", "Rooms and rates", "Booking enquiry",
     "check_room_availability, create_booking_enquiry"),
    ("E-commerce", "Order number, Product interest, Issue type", "Products", "—", "search_product, get_order_status, create_ticket"),
    ("Logistics", "Pickup city, Drop city, Shipment type, Weight, Tracking number", "Services and rates", "Pickup slot",
     "get_shipment_status, create_quote_request"),
    ("Clinics / Healthcare", "Patient name, Age, Department / doctor, Preferred date (no diagnosis fields)", "Doctors and services",
     "Doctor appointment", "book_appointment; guardrail: no medical advice"),
    ("B2B Services", "Company, Designation, Requirement, Budget, Timeline", "Services", "Meeting / demo", "book_meeting"),
    ("Salons / Beauty", "Service, Stylist preference, Preferred date and time", "Services and price list", "Salon appointment",
     "book_appointment"),
    ("Restaurants", "Party size, Date and time, Occasion, Dietary preference", "Menu", "Table reservation", "book_table"),
]

TRACE = [
    ("§1", "Core product concept & user journey", "WEB-05, AUTH-01, AUTH-10, EMP-01 to EMP-11", "P1, P4"),
    ("§2", "Multi-industry platform", "IND-01 to IND-08, CAT-01, ENG-01, ENG-02", "P3, P4, P9"),
    ("§3", "AI Employee types", "ROLE-01 to ROLE-09", "P3, P4, P10, Pending"),
    ("§4", "Voice AI", "VOICE-01 to VOICE-22, COMP-01 to COMP-05", "P5, P6"),
    ("§5", "Voice conversation engine", "VOICE-03 to VOICE-06, ENG-06, ENG-07", "P4, P5"),
    ("§6", "Knowledge base", "KB-01 to KB-11, ENG-04, TEN-04", "P4"),
    ("§7", "AI tools / actions", "TOOL-01 to TOOL-15", "P4, P5, P6, P10"),
    ("§8", "CRM", "CRM-01 to CRM-18", "P3"),
    ("§9", "Dynamic custom fields", "CRM-04 to CRM-08", "P3, P9"),
    ("§10", "Lead scoring", "SCORE-01 to SCORE-06", "P3, P4, P6"),
    ("§11", "Real Estate template", "CAT-02 to CAT-04, CRM-05, TOOL-15, CAL-04", "P3, P4"),
    ("§12", "Travel template", "CAT-05, CRM-06, TOOL-15", "P3, P4"),
    ("§13", "Education template", "CAT-06, CRM-07, TOOL-15", "P3, P4"),
    ("§14", "WhatsApp", "WA-01 to WA-10", "P6"),
    ("§15", "Website AI chat", "CHAT-01 to CHAT-07", "P6"),
    ("§16", "Human handoff", "HO-01 to HO-05", "P5, P6"),
    ("§17", "Call transcript & summary", "REC-01 to REC-03, VOICE-12 to VOICE-14", "P5, P6"),
    ("§18", "Campaign management", "CAMP-01 to CAMP-06", "P6"),
    ("§19", "Dashboard", "DASH-01 to DASH-05", "P7"),
    ("§20", "AI Employee management", "EMP-01, EMP-12, EMP-13", "P4, P7"),
    ("§21", "Create AI Employee wizard", "EMP-02 to EMP-11", "P4, P5, P6"),
    ("§22", "Super Admin panel", "SA-01 to SA-27", "P1 to P7"),
    ("§23", "SaaS subscription", "SUB-01 to SUB-06", "P1, P7"),
    ("§24", "Usage billing", "USE-01 to USE-06", "P4 to P7, P12"),
    ("§25", "Security", "SEC-01 to SEC-15, TEN-01 to TEN-07", "P1 to P8"),
    ("§26", "Mobile responsive", "MOB-01 to MOB-03, WEB-08, CP-07", "All phases"),
    ("§27", "Technology", "SDD-02 (architecture), ENG-09, VOICE-21", "P0"),
    ("§28", "MVP scope", "Phases P0 to P8", "P0 to P8"),
    ("§29", "Testable milestones", "Phase gates (Section 4)", "All phases"),
    ("§30", "Pre-development deliverables", "Section 11 of this document", "P0"),
    ("§31", "Business goal & positioning", "WEB-01, ENG-01, ROLE-01 to ROLE-09", "All phases"),
    ("§32", "Multi-tenant, modular, scalable", "TEN-01 to TEN-07, SDD-02", "All phases"),
    ("DEC", "API-first for the future Flutter mobile app", "API-01 to API-08", "All phases, Future"),
]


# ---------------------------------------------------------------------------
def phase_color(ph):
    if "Pending" in ph or "Future" in ph:
        return AMBER_BG
    m = re.search(r"P(\d+)", ph)
    return PURPLE_BG if m and int(m.group(1)) >= 9 else TEAL_BG


def feature_table(rows):
    data_rows, extra = [], []
    for i, (fid, name, details, ref, ph) in enumerate(rows, start=1):
        data_rows.append([f'<font color="#1D4ED8"><b>{fid}</b></font>', f"<b>{name}</b>", details, ref, f"<b>{ph}</b>"])
        extra.append(("BACKGROUND", (4, i), (4, i), phase_color(ph)))
    return table(["ID", "Feature", "Details & fields", "Ref", "Phase"], data_rows, [0.105, 0.19, 0.49, 0.095, 0.12],
                 extra=extra)


def phases_of(ph_text):
    """'P4 (text), P5 (voice)' -> {3, 4}; 'P4-P6 capture' / 'P1 → P7' -> ranges; 'P1 → all' -> {1}."""
    found = set()
    for a, b in re.findall(r"P(\d+)\s*(?:-|→|to)\s*P(\d+)", ph_text):
        found.update(range(int(a), int(b) + 1))
    found.update(int(x) for x in re.findall(r"P(\d+)", ph_text))
    return found


def phase_features(pid):
    num = int(pid[1:])
    return [(fid, name, f"{code_} {mname}") for code_, mname, _, rows in MODULES
            for fid, name, _, _, ph in rows if num in phases_of(ph)]


def phase_banner(ph):
    post = ph["rel"] != "MVP"
    bg = PURPLE if post else NAVY
    left = [Paragraph('<font color="#FFFFFF" size="7.5">PHASE</font>', ST["cellc"]),
            Paragraph(f'<font color="#FFFFFF" size="20"><b>{ph["id"][1:]}</b></font>', ST["cellc"])]
    title_style = ParagraphStyle("pb", parent=ST["cell"], fontName="Body-Bold", fontSize=13, leading=16.5, textColor=NAVY)
    right = [Paragraph(fx(ph["title"]), title_style), sp(3),
             Paragraph(f'<font color="#6B7280">Client mapping: {fx(ph["client"])} · Release: <b>{ph["rel"]}</b></font>', ST["cell"])]
    t = Table([[left, right]], colWidths=[24 * mm, CONTENT_W - 24 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), bg), ("BACKGROUND", (1, 0), (1, 0), SOFT),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 9),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 9), ("LEFTPADDING", (1, 0), (1, 0), 12)]))
    return t


def gate_figure():
    g = Dia(CONTENT_W, 128)
    w, h, gap = 84, 40, (CONTENT_W - 5 * 84) / 4
    xs = [i * (w + gap) for i in range(5)]
    top = ["1  Build complete\nall phase features", "2  Code review\nPR approved", "3  Automated tests\nunit · API · E2E · AI",
           "4  GitHub CI green\nall required checks", "5  Security check\nSAST · deps · secrets"]
    bottom = ["6  No-hard-coding\nreview passed", "7  Staging + UAT\nclient test cases", "8  Client sign-off\nwritten approval",
              "GATE EXIT\nphase closed", "NEXT PHASE\nstarts"]
    for i, t in enumerate(top):
        g.box(xs[i], 80, w, h, t)
        if i < 4:
            g.arrow([(xs[i] + w, 100), (xs[i + 1], 100)], color=BLUE)
    for i, t in enumerate(bottom):
        x = xs[4 - i]
        if i == 3:
            g.box(x, 14, w, h, t, fill=GREEN, stroke=GREEN, color=WHITE)
        elif i == 4:
            g.box(x, 14, w, h, t, fill=NAVY, stroke=NAVY, color=WHITE)
        else:
            g.box(x, 14, w, h, t, fill=TEAL_BG, stroke=TEAL)
        if i < 4:
            g.arrow([(x, 34), (xs[3 - i] + w, 34)], color=BLUE)
    g.arrow([(xs[4] + w / 2, 80), (xs[4] + w / 2, 54)], color=BLUE)
    g.text(CONTENT_W / 2, 3, "Any failure at steps 3-8 → fix → re-run from step 3. A phase cannot exit with a failing check.",
           fs=7, color=RED)
    return g.d


def make_story():
    n = Numbering()
    s = cover_story()

    # Document control
    s += [P("Document Control", "H3"),
          kv([("Document", "PRD-01: Product Requirements Specification & Phased Delivery Plan"),
              ("Product", "AI Employee: 24/7 AI Workforce for Indian Businesses"),
              ("Version / status", "1.0, draft for client approval"), ("Date", DATE),
              ("Companion document", "SDD-02: System Design & Architecture (technical design of everything listed here)"),
              ("Source of requirements", "Client requirements brief (sections §1-§32) plus decisions confirmed by our team")]),
          sp(10), P("Revision History", "H3"),
          table(["Version", "Date", "Change"], [["1.0", DATE, "First complete issue for client review"]], [0.15, 0.2, 0.65]),
          sp(10), P("How to Read This Document", "H3")]
    s += bullets([
        "<b>Section 3</b> lists the rules that apply to every phase (no hard-coding, custom Super Admin, our templates).",
        "<b>Section 4</b> defines the phase gate: a phase exits only after tests, GitHub CI and security checks pass and the client signs off.",
        "<b>Section 6</b> is the complete feature catalogue. Every feature has an ID (e.g., CRM-04), a client reference and a phase.",
        "<b>Section 7</b> is the phase plan. Each phase lists its feature IDs, Super Admin controls, tests and gate criteria.",
        "<b>Section 10</b> traces every client section §1-§32 to features and phases, so nothing is missed.",
    ])
    s += [sp(4), P("Reference codes used in the feature catalogue", "H3"),
          table(["Code", "Meaning"], [["§n", "Client requirement section number from the original brief (e.g., §8 = CRM)"],
                                      ["DEC", "Decision confirmed by our team with the client (e.g., own calendar, Razorpay)"],
                                      ["REC", "Recommended addition needed for a production-grade SaaS (clearly marked so it can be reviewed)"]],
                [0.12, 0.88]),
          sp(6), table(["Phase colour", "Meaning"], [["MVP", "Phases P0-P8: Minimum Viable Product (client §28)"],
                                                    ["Post-MVP", "Phases P9-P12: all remaining features, also to be built"],
                                                    ["Pending", "Waiting for client definition; not planned or estimated"],
                                                    ["Future", "Separate future project (Flutter mobile app); APIs made ready now"]],
                       [0.2, 0.8], zebra=False, extra=[("BACKGROUND", (0, 1), (0, 1), TEAL_BG),
                                                       ("BACKGROUND", (0, 2), (0, 2), PURPLE_BG),
                                                       ("BACKGROUND", (0, 3), (0, 3), AMBER_BG),
                                                       ("BACKGROUND", (0, 4), (0, 4), AMBER_BG)]),
          PageBreak(), P("Contents", "title"), toc()]

    # 1 Executive summary
    s += n.H1("Executive Summary")
    s += [P("We are building <b>AI Employee</b>, a multi-tenant SaaS platform where any Indian business registers, chooses its "
            "industry, creates one or more AI Employees, teaches them its approved business information, connects phone, WhatsApp, "
            "its built-in CRM and calendar, and lets them handle real work over voice, WhatsApp and website chat: answering and "
            "making calls, qualifying leads, matching products, booking appointments, following up and handing hot leads to humans.",
            "lead"),
          P("The product is positioned as <b>\"Hire an AI Employee for your business\"</b>, not as AI calling software. The long-term "
            "vision is <b>One Platform → Multiple AI Employees → Multiple Industries</b>. Real Estate is the first market, with Travel "
            "and Education included in the MVP; the architecture is industry-independent from day one.")]
    s += n.H2("Scope at a Glance")
    s += [table(["Release", "Phases", "What it contains"], [
        ["MVP", "P0-P8", "Website, registration, multi-tenancy, Super Admin, company panel, template engine, CRM, catalogues, calendar, "
                         "AI Employee engine, knowledge base, tools, voice (Hindi, English, Bengali), WhatsApp, website chat, handoff, "
                         "campaigns, dashboards, subscription, usage, security hardening, launch. Templates: Real Estate, Travel, Education."],
        ["Post-MVP", "P9-P12", "Eight more industries, Customer Support and Collection employees, custom roles, eight or more additional "
                               "languages, usage-based billing, advanced analytics."],
        ["Pending", "—", "AI Marketing Employee: awaiting client definition."],
    ], [0.13, 0.12, 0.75], bold_first=True)]
    s += n.H2("Delivery Approach")
    s += bullets([
        "Work is delivered in <b>13 phases</b> (P0-P12). Each phase is built, tested, passed through GitHub CI and security checks, "
        "demonstrated on staging and signed off by the client before the next phase starts.",
        "<b>No hard-coding:</b> every business value (industries, fields, statuses, prices, limits, providers, languages, texts) is "
        "controlled from the Super Admin panel.",
        "<b>Custom panels on our templates:</b> Super Admin and company panels are built on professional templates supplied by our team; "
        "Django's built-in admin is not used.",
        "<b>Provider independence:</b> LLM, speech-to-text, text-to-speech, telephony, WhatsApp, email, SMS and payment providers sit "
        "behind adapters and can be replaced from Super Admin.",
        "<b>API-first:</b> every section is built in Django together with its REST APIs, so a future Flutter mobile app (Android + "
        "iOS) connects to the same system with the same data and workflows.",
    ])
    s += [sp(4), P("Feature count by module", "H3")]
    counts = [[m[0], m[1], str(len(m[3]))] for m in MODULES]
    total = sum(len(m[3]) for m in MODULES)
    counts.append(["", "<b>Total catalogued features</b>", f"<b>{total}</b>"])
    s += [table(["Module", "Name", "Features"], counts, [0.12, 0.73, 0.15])]

    # 2 Decisions
    s += n.H1("Confirmed Decisions & Assumptions")
    s += [P("The following decisions were confirmed with the client and shape the plan."),
          table(["#", "Topic", "Decision"], [
              ["D1", "MVP industries", "Real Estate, Travel & Tours and Education are all included in the MVP."],
              ["D2", "CRM", "Our own CRM built into the platform, configured and controlled from Super Admin. No external CRM."],
              ["D3", "Calendar", "Our own built-in calendar. No dependency on Google / Outlook calendars."],
              ["D4", "Telephony accounts", "Development and testing on our test account; at launch the client's own provider account is used."],
              ["D5", "Payment gateway", "Razorpay (subscriptions, payments, credit top-ups)."],
              ["D6", "Voice quality", "Professional, best-available quality in every language, not only Bengali. Provider chosen per language."],
              ["D7", "Scope", "Everything in the client brief will be built, including features outside the MVP list."],
              ["D8", "AI Marketing Employee", "Kept as a pending feature until the client defines what it does."],
              ["D9", "Admin panels", "Super Admin built fully custom on our admin template; Django built-in admin not used."],
              ["D10", "Company panel", "Professional panel built on the template supplied by our team."],
              ["D11", "Website", "Professional, animated marketing website; company registration starts there."],
              ["D12", "No hard-coding", "All configurable values live in the database and are managed from Super Admin."],
              ["D13", "Quality gates", "Every phase: tests pass → GitHub CI pass → security check pass → gate exit → next phase."],
              ["D14", "Technology", "Python / Django 5.2 LTS backend; website and panels as Django templates on the supplied Bootstrap / jQuery templates (no Next.js); PostgreSQL, Redis (detailed in SDD-02)."],
              ["D15", "API-first / mobile", "REST APIs for every section are built in Django alongside each feature. A future Flutter app "
                                           "(Android + iOS) will use the same APIs: same data, same workflows; only mobile design and "
                                           "app code to write."],
              ["D16", "No separate UI/UX phase", "Agreed with the client: no UI/UX designs or prototype are prepared in advance. "
                                                "Development starts directly on the website and admin templates supplied by our team."],
              ["D17", "Super Admin first", "Super Admin (with General Settings and the website content manager) is built first in P1; "
                                          "the website, registration and company panel follow in P2."],
              ["D18", "Website fully managed", "Every section of the website template (headings, text, images, buttons, order, "
                                              "show / hide) is created and edited in Super Admin. Nothing on the website is fixed text."],
              ["D19", "Theme", "Light theme for the website and both panels."],
              ["D20", "Website template", "eSoft (folder WebsiteTemplate), HR layout (index5) as the base design; missing sections "
                                         "taken from other eSoft pages and restyled to match (Section 8)."],
              ["D21", "Admin template", "Rizz (folder AdminTemplate) for both Super Admin and the company panel; different sidebar "
                                       "menu and accent colour per panel."],
              ["D22", "No Next.js", "Both templates already ship as Django projects, so pages are Django templates with Bootstrap / "
                                   "jQuery. Business logic sits in a service layer used by both page views and REST APIs."],
              ["D24", "Hosting & domain", "Chosen by the client at deployment (Phase 8). The system is hosting-agnostic (Docker); nothing provider-specific is built before that decision."],
              ["D23", "Free LLM for testing", "Development and staging use free LLM tiers via a self-hosted FreeLLMAPI gateway to "
                                             "avoid AI costs for us and the client. Never in production, never with real customer "
                                             "data; final quality and latency tests on the real model (SA-28)."],
          ], [0.07, 0.22, 0.71], bold_first=True)]
    s += [sp(6), callout("Assumptions to confirm", [
        "MVP roles are Sales, Receptionist, Appointment and Follow-up. Customer Support and Collection follow in P10.",
        "Travel package and Education course fields (CAT-05, CAT-06) are proposals and will be finalised with the client in P3.",
        "Field lists for the eight post-MVP industries (Section 7, Phase 9) are proposals, finalised at the start of P9.",
        "Phase durations and costs are given in the separate commercial proposal.",
    ], "warn")]

    # 3 Global rules
    s += n.H1("Global Rules (Apply to Every Phase)")
    s += n.H2("Rule 1: No Hard-coding, Super Admin Controls Everything")
    s += [P("No business value is written into source code. Seed values (e.g., the four plans and their prices) are inserted as "
            "editable data. Code reads values from the settings registry and configuration tables. Every phase gate includes a "
            "<b>no-hard-coding review</b>. The table lists what the Super Admin controls."),
          table(["Area", "Controlled from Super Admin"], [
              ["Industries", "Industries, templates, versions, activation, instructions, greetings, disclosure texts"],
              ["AI Employees", "Role templates, tools, guardrails, model per task, knowledge limits"],
              ["CRM", "Lead fields per industry, statuses, sources, scoring rules, import limits"],
              ["Catalogues", "Catalogue types and fields (property, package, course, …)"],
              ["Calendar", "Appointment types, platform holidays, booking defaults"],
              ["Voice & languages", "Languages, STT / TTS provider per language, voices, telephony providers, number pool"],
              ["Channels", "WhatsApp provider, default templates, opt-out keywords, email and SMS providers"],
              ["Compliance", "Calling hours, attempt caps, DND check, recording defaults, retention periods"],
              ["Commercial", "Plans, prices, limits, overage prices, GST, trial days, credits, feature flags"],
              ["Security", "Password, session, lockout and 2FA policy, IP allowlist, upload limits"],
              ["Website & messages", "Website content, legal pages, email and notification templates"],
              ["General Settings", "Platform name, logo, favicon, colours, contact details, social links, footer, SEO, "
                                   "localisation, email sender, maintenance mode (SA-21 to SA-27)"],
          ], [0.22, 0.78], bold_first=True)]
    s += n.H2("Rule 2: Custom Super Admin, Django Built-in Admin Not Used")
    s += bullets(["The Super Admin panel is a fully custom application built on the <b>admin dashboard template supplied by our team</b>.",
                  "<b>django.contrib.admin is not installed</b> in any environment. All Super Admin screens call the same secured "
                  "Admin API, with 2FA, IP allowlist and audit logging.",
                  "Each phase delivers the Super Admin screens for the features it builds, so configuration is never left in code "
                  "\"for later\"."])
    s += n.H2("Rule 3: Professional Panels and Website on Our Templates")
    s += bullets(["<b>No separate UI/UX design phase</b> (agreed with the client): the website template and admin templates "
                  "supplied by our team are placed in the project folder and development starts directly on them.",
                  "<b>Build order:</b> Super Admin first (P1), then the website, registration and company panel (P2).",
                  "<b>Company panel</b> (the registered business's admin) is built on the professional template supplied by our team.",
                  "<b>Public website</b> is professional and animated; visitors learn about the product and register their company there.",
                  "<b>Every website section is managed from Super Admin:</b> each section of the website template has a Super Admin "
                  "editor for headings, text, images, icons, buttons and links, order and show / hide. Content is uploaded there; the "
                  "website only displays it.",
                  "One design language across website, panels and widget; mobile layouts for every screen."])
    s += n.H2("Rule 4: Company Data Isolation")
    s += [P("Every record belongs to one company. Isolation is enforced in three layers (ORM, API, database row-level security) and "
            "proven by an automated cross-tenant test suite that must pass at every gate.")]
    s += n.H2("Rule 5: Provider Independence")
    s += [P("LLM, STT, TTS, telephony, WhatsApp, email, SMS, embedding and payment providers are accessed only through adapters. "
            "Switching provider is a Super Admin configuration change, with fallback providers for critical paths.")]
    s += n.H2("Rule 6: AI Trust Rules")
    s += bullets(["AI never invents prices, availability, discounts, policies or specifications; it uses approved knowledge and tools only.",
                  "AI identifies itself as an AI assistant.",
                  "When unsure, AI follows the configured fallback: human transfer, callback or message."])
    s += n.H2("Rule 7: Mobile Responsive Everywhere")
    s += [P("Every screen works on desktop, laptop, tablet, Android and iPhone. Device testing is part of every gate.")]
    s += n.H2("Rule 8: API-First, Ready for the Flutter Mobile App")
    s += bullets(["Every section is built in Django <b>together with its REST APIs</b> in the same phase, not added later.",
                  "The website, company panel and Super Admin use only these APIs, so everything the web can do, an app can do.",
                  "A future <b>Flutter mobile app (Android + iOS)</b> will connect to the same APIs: same data, same workflows. Only "
                  "the mobile design and app-side code will need to be written.",
                  "APIs are versioned (/api/v1), documented in OpenAPI (used to generate the Dart client) and covered by automated "
                  "API tests at every gate (module M30)."])

    # 4 Phase gate
    s += n.H1("Phase Gate Process (Definition of Done)")
    s += [P("Each phase ends with a formal gate. Only when every criterion is met does the phase exit and the next phase start. "
            "This mirrors the client's request that each milestone be tested and approved before moving on.")]
    s += n.figure(gate_figure(), "Phase gate flow applied at the end of every phase")
    s += n.H2("Gate Exit Checklist")
    s += [table(["#", "Criterion", "Evidence"], [
        ["1", "All features of the phase built and demonstrable", "Feature checklist with IDs ticked"],
        ["2", "Code reviewed and merged through pull requests", "GitHub PR history, approvals"],
        ["3", "Automated tests pass (unit, integration, API, E2E, AI evaluation where relevant); backend coverage ≥ 80 %",
         "CI test report, coverage report"],
        ["3a", "<b>REST APIs complete</b> for every feature of the phase, documented in OpenAPI and covered by API tests",
         "Published OpenAPI spec, API test report"],
        ["4", "<b>GitHub CI pipeline green</b> on the phase release tag (all required checks)", "GitHub Actions run link"],
        ["5", "<b>Security check passed</b>: no open critical / high findings", "SAST, dependency, secret and container scan reports; "
                                                                            "DAST report from P1 onward"],
        ["6", "Cross-tenant isolation suite passes", "CI test report"],
        ["7", "<b>No-hard-coding review</b>: every value introduced is configurable from Super Admin", "Signed checklist"],
        ["8", "Device testing on desktop, laptop, tablet, Android, iPhone", "Test sheet with screenshots"],
        ["9", "Deployed to staging; client UAT test cases executed", "UAT sheet"],
        ["10", "Client written sign-off", "Approval email / signed gate form"],
    ], [0.06, 0.6, 0.34])]
    s += n.H2("Required GitHub CI Checks")
    s += [table(["Check", "Tools", "Blocks merge / gate"], [
        ["Backend lint & format", "ruff, black --check", "Yes"],
        ["Backend type check", "mypy", "Yes"],
        ["Backend tests + coverage", "pytest with PostgreSQL and Redis services", "Yes"],
        ["Migrations consistency", "manage.py makemigrations --check", "Yes"],
        ["Template & JS lint", "djLint (Django templates), eslint (our JavaScript)", "Yes"],
        ["Static build", "collectstatic, Rizz compiled assets present, widget size budget", "Yes"],
        ["End-to-end tests", "Playwright against staging / preview", "Yes (gate)"],
        ["AI evaluation", "Golden conversations per template × language", "Yes (from P4)"],
        ["Security scans", "Bandit, Semgrep, pip-audit, npm audit, Gitleaks, Trivy", "Yes"],
    ], [0.3, 0.52, 0.18], bold_first=True)]
    s += n.H2("Security Check per Phase")
    s += bullets(["<b>Static analysis</b> (SAST) of Python and JavaScript code.",
                  "<b>Dependency vulnerabilities</b> for Python and npm packages.",
                  "<b>Secret scanning</b>: no keys or passwords in the repository.",
                  "<b>Container image scan</b> for OS and library vulnerabilities.",
                  "<b>Dynamic scan</b> (OWASP ZAP baseline) against staging from P1.",
                  "<b>OWASP Top 10 review</b> of the features added in the phase, including AI-specific risks from P4.",
                  "<b>External penetration test</b> before production launch (P8)."])

    # 5 Roles
    s += n.H1("Users, Roles & Panels")
    s += [P("The platform has two panels plus customer-facing surfaces. Admin levels are roles inside the panels, not separate "
            "applications.")]
    s += [table(["Surface", "Used by", "Purpose"], [
        ["Public website", "Visitors, prospects", "Learn about the product, view pricing, register a company, request a demo"],
        ["Company panel", "Company Owner / Admin, Manager, Human Agent", "Run the business's AI Employees, CRM, calendar, inbox, "
                                                                         "campaigns, billing"],
        ["Super Admin panel", "Platform Super Admin, Support staff", "Control the whole platform: companies, templates, providers, "
                                                                     "plans, settings, logs"],
        ["Website chat widget", "The business's own customers", "Chat with the AI Employee on the business website"],
        ["Phone & WhatsApp", "The business's own customers", "Talk to the AI Employee by call or WhatsApp"],
    ], [0.2, 0.3, 0.5], bold_first=True)]
    s += n.H2("Default Permission Matrix")
    s += [P("Defaults below; permission sets are stored in the database and editable from Super Admin."),
          table(["Capability", "Super Admin", "Support", "Owner / Admin", "Manager", "Human Agent"], [
              ["Platform settings, providers, plans, templates", "Full", "—", "—", "—", "—"],
              ["Companies & users (platform-wide)", "Full", "View", "—", "—", "—"],
              ["Company profile, billing, subscription", "Full", "View", "Full", "—", "—"],
              ["Team & roles", "Full", "View", "Full", "—", "—"],
              ["AI Employees (create, edit, activate)", "View / pause", "View", "Full", "Full", "—"],
              ["Knowledge base", "View", "View", "Full", "Full", "View"],
              ["Leads / CRM", "View (audited)", "View (audited)", "All", "All", "Assigned only"],
              ["Calendar & appointments", "View", "View", "All", "All", "Own"],
              ["Conversations & transcripts", "View (audited)", "View (audited)", "All", "All", "Assigned only"],
              ["Call recordings", "Configurable", "—", "Listen / download", "Configurable", "Listen (assigned)"],
              ["Campaigns", "View", "View", "Full", "Full", "—"],
              ["Inbox takeover & handoff", "—", "—", "Yes", "Yes", "Yes"],
              ["Analytics", "All companies", "View", "All", "All", "Own performance"],
              ["Data export", "Full", "—", "Yes", "Configurable", "—"],
          ], [0.3, 0.13, 0.12, 0.15, 0.14, 0.16], bold_first=True)]

    # 6 Feature catalogue
    s += n.H1("Complete Feature Catalogue")
    s += [P("Every feature requested by the client, plus clearly marked production essentials, with its fields, client reference "
            "and delivery phase. Feature IDs are used in the phase plan, tests and sign-off sheets.")]
    for code_, name, intro, rows in MODULES:
        s += n.H2(f"{code_} · {name}")
        s += [P(intro, "small"), feature_table(rows)]

    # 7 Phase plan
    s += n.H1("Phase Plan")
    s += [P("Phases follow dependencies: CRM, catalogues and calendar (P3) are built before the AI engine (P4) because AI tools write "
            "into them; the AI engine is proven in text before voice (P5). The table maps the client's milestones to our phases.")]
    s += [table(["Client milestone", "Our phase(s)"], [
        ["M1 UI/UX + architecture", "P0 (architecture; UI/UX design dropped, templates supplied)"], ["M2 Authentication + company dashboard", "P1 (Super Admin first) + P2 (website, registration, company panel)"], ["M3 AI Employee engine", "P4"],
        ["M4 Voice calling", "P5"], ["M5 CRM + leads", "P3"], ["M6 Knowledge base + tools", "P4"],
        ["M7 WhatsApp + appointment", "P6 (calendar core in P3)"], ["M8 Admin + subscription", "P7 (Super Admin grows every phase)"],
        ["M9 Testing + security + deployment", "P8 (testing and security also at every gate)"],
        ["Post-MVP (client: everything is to be built)", "P9, P10, P11, P12"],
    ], [0.5, 0.5])]
    s += [sp(4), table(["Phase", "Title", "Release"], [[p["id"], p["title"], p["rel"]] for p in PHASES], [0.1, 0.72, 0.18],
                       bold_first=True)]
    for ph in PHASES:
        s += [PageBreak(), TocMark(f"Phase {ph['id'][1:]}: {ph['title']}", 1), phase_banner(ph), sp(8),
              H3("Objective"), P(ph["objective"]), H3("Scope summary")]
        s += [table(["Area", "Features / content"], [[a, b] for a, b in ph["scope"]], [0.22, 0.78], bold_first=True)]
        feats = phase_features(ph["id"])
        if feats:
            s += [H3(f"Feature checklist for this phase ({len(feats)} items, compiled from Section 6)"),
                  table(["ID", "Feature", "Module"], [[f"<b>{a}</b>", b, c] for a, b, c in feats], [0.13, 0.52, 0.35])]
        if ph["id"] == "P9":
            s += [sp(6), H3("Proposed industry templates (finalised with client at phase start)"),
                  table(["Industry", "Proposed lead fields", "Catalogue", "Appointment", "Key tools"],
                        [list(r) for r in INDUSTRY_PROPOSALS], [0.14, 0.32, 0.17, 0.15, 0.22], bold_first=True)]
        s += [H3("Super Admin controls delivered in this phase")] + bullets(ph["admin"])
        s += [H3("Phase-specific tests and gate criteria")] + bullets(ph["tests"])
        s += [H3("Deliverables")] + bullets(ph["deliver"])
        s += [sp(4), callout("Phase rules (apply to this phase)", [
            "<b>No hard-coding:</b> every value introduced in this phase is configurable from Super Admin.",
            "<b>Super Admin screens</b> for this phase are built on our admin template; Django's built-in admin is not used.",
            "<b>REST APIs:</b> every feature of this phase ships with its Django REST API, OpenAPI documentation and API tests, "
            "ready for the future Flutter mobile app.",
            "<b>Gate exit</b> only after: tests pass → GitHub CI green → security check passed → no-hard-coding review → "
            "staging UAT → client sign-off (Section 4).",
        ], "rule")]

    # 8 Pending
    s += n.H1("Templates & Section Mapping")
    s += [P("Both purchased templates are in the project folder and already come as Django projects. This section records how "
            "they are used, so development starts without a separate UI/UX phase.")]
    s += [table(["Item", "Decision"], [
        ["Theme", "Light, for website and both panels"],
        ["Website", "WebsiteTemplate / eSoft: Bootstrap 5, jQuery, GSAP + ScrollTrigger, AOS. Base design: HR layout (index5)"],
        ["Panels", "AdminTemplate / Rizz: Bootstrap 5.3, light / dark ready. Used for Super Admin and company panel"],
        ["Technology", "Django templates (no Next.js); our own Django 5.2 project, templates copied in under website/ and panel/"],
        ["Not used", "Template Docs folders, demo databases, RTL and extra locales, unused demo home pages, UI-kit showcase pages"],
    ], [0.18, 0.82], bold_first=True)]
    s += n.H2("Website: HR Layout (index5) Sections")
    s += [P("Every section below gets a Super Admin editor (WEB-04): headings, text, images, icons, buttons, items, order and "
            "show / hide. Source column shows where the design comes from.")]
    s += [table(["#", "Website section", "Source in eSoft", "Our content"], [
        ["1", "Header / menu", "index5 header (made a shared partial)", "Logo, menu items, Login / Get Started buttons"],
        ["2", "Hero", "index5 Hero", "\"Hire an AI Employee for your business\", CTA buttons, hero image"],
        ["3", "Work", "index5 Work", "What an AI Employee does (calls, WhatsApp, CRM, appointments)"],
        ["4", "Counters", "index5 Counters", "Key numbers (companies, calls handled, languages …)"],
        ["5", "Work process", "index5 Work Process", "How it works: register → create AI Employee → connect → activate"],
        ["6", "System", "index5 System", "Platform features (voice, WhatsApp, chat, CRM, calendar, campaigns)"],
        ["7", "Solution", "index5 HR Solution", "AI Employee types / industries"],
        ["8", "Testimonials", "index5 Testimonials", "Customer reviews"],
        ["9", "Pricing", "eSoft pricing page section (restyled)", "Plans read live from Super Admin"],
        ["10", "Industries", "Feature-card section from another eSoft demo (restyled)", "Active industry templates, read live"],
        ["11", "FAQ", "FAQ section from another eSoft demo (restyled)", "Questions and answers"],
        ["12", "Call to action", "eSoft CTA partial (restyled)", "Final sign-up call to action"],
        ["13", "Footer", "index5 footer (made a shared partial)", "Columns, links, contact, social, copyright (General Settings)"],
    ], [0.05, 0.17, 0.38, 0.4])]
    s += [P("Inner pages from eSoft, all using the index5 header and footer: About, Features, Pricing, Contact, Testimonials, "
            "Blog (optional), Legal pages, and the account pages Login, Register, Forgot, Reset, Verify Email, Success.", "small")]
    s += n.H2("Panels: Rizz Pages Reused")
    s += [table(["Rizz page", "Used for"], [
        ["Dashboard / analytics", "Company dashboard (DASH), Super Admin platform dashboard (SA-02)"],
        ["Datatables / editable tables", "Leads, calls, campaigns, companies, users, invoices lists"],
        ["Contact list", "Leads list (card view)"],
        ["Kanban board", "Lead pipeline (CRM-10)"],
        ["Calendar", "Built-in calendar and appointments (CAL)"],
        ["Chat", "WhatsApp and website-chat shared inbox (WA-06, CHAT-06)"],
        ["Form wizard", "Create AI Employee wizard (EMP-02 to EMP-11)"],
        ["Forms, uploads, image crop, editors", "Settings, knowledge uploads, logo / favicon, website section editors"],
        ["Pricing, invoice", "Plans, billing page, GST invoices"],
        ["Notifications, profile, timeline", "Notification centre, user profile, lead timeline"],
        ["Auth pages (login, register, recover, lock)", "Panel login, 2FA, password recovery"],
        ["Email templates", "Transactional email designs"],
    ], [0.35, 0.65], bold_first=True)]

    s += n.H1("Pending Features")
    s += [callout("AI Marketing Employee: pending client definition", [
        "Listed by the client in §31 as part of the long-term vision.",
        "Its responsibilities have not been defined in the brief.",
        "It is parked: not designed, not estimated and not scheduled until the client provides a definition.",
        "When defined, it will be added as a role template (M05) on the same engine, with its own phase and gate.",
    ], "pending")]
    s += [callout("Future: Flutter mobile app (Android + iOS)", [
        "Planned as a separate future project; not in the current scope or estimate.",
        "Because every section is built with REST APIs (Rule 8, module M30), the app will connect to the same system with the same "
        "data and workflows.",
        "Only the mobile design and app-side code will need to be written; the backend is already in place.",
    ], "pending")]

    # 9 Traceability
    s += n.H1("Requirement Traceability Matrix")
    s += [P("Every section of the client brief mapped to feature IDs and phases."),
          table(["Client §", "Requirement", "Feature IDs", "Phase(s)"], [list(r) for r in TRACE], [0.09, 0.3, 0.42, 0.19],
                bold_first=True)]

    # 10 Pre-dev deliverables
    s += n.H1("Pre-Development Deliverables (Client §30)")
    s += [P("The client requested 17 items before development starts. Where each is delivered:"),
          table(["#", "Requested item", "Delivered in"], [
              ["1", "Complete UI/UX design", "Not required (agreed with client): development uses the website and admin templates supplied by our team"],
              ["2", "Complete technical architecture", "SDD-02 System Design & Architecture"],
              ["3", "Database architecture", "SDD-02, Data Architecture"],
              ["4", "API architecture", "SDD-02, API Architecture"],
              ["5", "AI architecture", "SDD-02, AI Architecture"],
              ["6", "Voice architecture", "SDD-02, Voice Architecture"],
              ["7", "Industry template architecture", "SDD-02, Industry Template Engine"],
              ["8", "Complete feature list", "This document, Section 6"],
              ["9", "Development timeline", "Commercial proposal"],
              ["10", "Fixed development cost", "Commercial proposal (one-time development cost)"],
              ["11", "Third-party API costs", "Commercial proposal (after Phase 0 provider selection)"],
              ["12", "Estimated monthly running cost", "Commercial proposal (monthly running / API cost)"],
              ["13", "Cloud / hosting cost", "Commercial proposal"],
              ["14", "Maintenance cost", "Commercial proposal"],
              ["15", "Security plan", "SDD-02 Security Architecture + this document M25 and Section 4"],
              ["16", "Deployment plan", "SDD-02 Infrastructure & Deployment"],
              ["17", "Testing plan", "This document Section 4 + SDD-02 Testing Strategy"],
          ], [0.06, 0.38, 0.56])]
    s += [sp(6), callout("Cost presentation (as requested by the client)", [
        "<b>One-time development cost</b>, <b>monthly running / API cost</b> and <b>optional future features</b> are shown "
        "separately in the commercial proposal.",
    ], "info")]
    return s


if __name__ == "__main__":
    # every feature must land in at least one phase (or be explicitly All / Pending), and IDs must be unique
    ids = [r[0] for m in MODULES for r in m[3]]
    assert len(ids) == len(set(ids)), "duplicate feature IDs"
    for m in MODULES:
        for fid, _, _, _, ph in m[3]:
            assert phases_of(ph) <= set(range(13)), (fid, ph)
            assert phases_of(ph) or ph in ("All", "Pending", "Future"), (fid, ph)
    pages = build(OUT, META, make_story)
    print("pages:", pages, "features:", sum(len(m[3]) for m in MODULES))
