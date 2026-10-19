"""Website chat widget phrases for the seeded languages (CHAT-02). Only fills texts that are still empty, so values
edited in Super Admin → Languages & Voices are kept."""

from django.db import migrations

TEXTS = {
    "en": {
        "chat_launcher": "Chat with our AI Employee",
        "chat_placeholder": "Type your message…",
        "chat_send": "Send",
        "chat_human": "Talk to a person",
        "chat_callback": "Request a callback",
        "chat_enquiry": "Send an enquiry",
        "chat_book": "Book an appointment",
        "chat_waiting": "Connecting you to a member of our team…",
        "chat_joined": "{name} from our team has joined the chat.",
        "chat_ai_back": "You are chatting with our AI assistant again.",
        "chat_ended": "This chat has ended.",
        "chat_restart": "Start a new chat",
        "chat_name": "Your name",
        "chat_phone": "Mobile number",
        "chat_email": "E-mail (optional)",
        "chat_message": "How can we help?",
        "chat_submit": "Submit",
        "chat_thanks": "Thank you! Our team will contact you soon.",
        "chat_error": "Something went wrong. Please try again.",
    },
    "hi": {
        "chat_launcher": "हमारे AI कर्मचारी से चैट करें",
        "chat_placeholder": "अपना संदेश लिखें…",
        "chat_send": "भेजें",
        "chat_human": "किसी व्यक्ति से बात करें",
        "chat_callback": "कॉल बैक का अनुरोध",
        "chat_enquiry": "पूछताछ भेजें",
        "chat_book": "अपॉइंटमेंट बुक करें",
        "chat_waiting": "आपको हमारी टीम के सदस्य से जोड़ा जा रहा है…",
        "chat_joined": "हमारी टीम से {name} चैट में जुड़ गए हैं।",
        "chat_ai_back": "अब आप फिर से हमारे AI सहायक से बात कर रहे हैं।",
        "chat_ended": "यह चैट समाप्त हो गई है।",
        "chat_restart": "नई चैट शुरू करें",
        "chat_name": "आपका नाम",
        "chat_phone": "मोबाइल नंबर",
        "chat_email": "ई-मेल (वैकल्पिक)",
        "chat_message": "हम आपकी क्या मदद कर सकते हैं?",
        "chat_submit": "भेजें",
        "chat_thanks": "धन्यवाद! हमारी टीम जल्द ही आपसे संपर्क करेगी।",
        "chat_error": "कुछ गलत हो गया। कृपया फिर से कोशिश करें।",
    },
    "bn": {
        "chat_launcher": "আমাদের AI কর্মীর সাথে চ্যাট করুন",
        "chat_placeholder": "আপনার বার্তা লিখুন…",
        "chat_send": "পাঠান",
        "chat_human": "একজন মানুষের সাথে কথা বলুন",
        "chat_callback": "কলব্যাকের অনুরোধ",
        "chat_enquiry": "জিজ্ঞাসা পাঠান",
        "chat_book": "অ্যাপয়েন্টমেন্ট বুক করুন",
        "chat_waiting": "আপনাকে আমাদের টিমের একজনের সাথে যুক্ত করা হচ্ছে…",
        "chat_joined": "আমাদের টিম থেকে {name} চ্যাটে যোগ দিয়েছেন।",
        "chat_ai_back": "আপনি আবার আমাদের AI সহকারীর সাথে কথা বলছেন।",
        "chat_ended": "এই চ্যাটটি শেষ হয়েছে।",
        "chat_restart": "নতুন চ্যাট শুরু করুন",
        "chat_name": "আপনার নাম",
        "chat_phone": "মোবাইল নম্বর",
        "chat_email": "ই-মেল (ঐচ্ছিক)",
        "chat_message": "আমরা কীভাবে সাহায্য করতে পারি?",
        "chat_submit": "পাঠান",
        "chat_thanks": "ধন্যবাদ! আমাদের টিম শীঘ্রই আপনার সাথে যোগাযোগ করবে।",
        "chat_error": "কিছু ভুল হয়েছে। আবার চেষ্টা করুন।",
    },
}


def seed(apps, schema_editor):
    Language = apps.get_model("providers", "Language")
    for code, texts in TEXTS.items():
        lang = Language.objects.filter(code=code).first()
        if lang:
            lang.texts = {**texts, **{k: v for k, v in (lang.texts or {}).items() if v}}
            lang.save(update_fields=["texts"])


class Migration(migrations.Migration):
    dependencies = [("providers", "0005_model_kinds")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
