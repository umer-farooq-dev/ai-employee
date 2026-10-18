from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run the Voice Gateway (telephony media streams and browser test calls)."

    def add_arguments(self, parser):
        parser.add_argument("--bind", default=settings.VOICE_GATEWAY_BIND, help="host:port, default VOICE_GATEWAY_BIND")

    def handle(self, *args, **options):
        import uvicorn

        from apps.voice.gateway.app import app

        host, _, port = options["bind"].rpartition(":")
        self.stdout.write(f"Voice Gateway on {host}:{port}")
        uvicorn.run(app, host=host or "127.0.0.1", port=int(port), log_level="info", ws_max_size=2**20)
