"""ENG-12: run the golden AI evaluation on the providers configured in Super Admin → AI Settings.

  python backend/manage.py run_ai_eval                      all cases
  python backend/manage.py run_ai_eval --only real-estate   one industry (or case ids)
  python backend/manage.py run_ai_eval --output report.json

Exit code 1 when the phase-gate thresholds are not met. Nothing is stored (the run is rolled back).
"""

import json

from django.core.management.base import BaseCommand, CommandError

from apps.agents import evaluation
from apps.providers.services import NoProviderAvailable


class Command(BaseCommand):
    help = "Run the AI quality evaluation (golden conversations)."

    def add_arguments(self, parser):
        parser.add_argument("--only", nargs="*", default=[], help="Case ids or industry keys")
        parser.add_argument("--output", help="Write the full report (JSON) to this file")

    def handle(self, *args, **opts):
        try:
            results, summary = evaluation.run(opts["only"] or None)
        except NoProviderAvailable as exc:
            raise CommandError(f"No AI provider: {exc}. Set one in Super Admin → AI Settings.") from None
        for r in results:
            mark = "PASS" if r["passed"] else "FAIL"
            fields = ", ".join(f"{k}={'ok' if v else 'MISS'}" for k, v in r["fields"].items()) or "-"
            self.stdout.write(f"{mark}  {r['id']:<28} tools={','.join(r['tools_called']) or '-'}  fields: {fields}")
        self.stdout.write(json.dumps(summary, indent=1))
        if opts.get("output"):
            with open(opts["output"], "w", encoding="utf-8") as fh:
                json.dump({"summary": summary, "results": results}, fh, ensure_ascii=False, indent=1)
        if not summary["gate_passed"]:
            raise CommandError("Evaluation gate NOT met.")
        self.stdout.write(self.style.SUCCESS("Evaluation gate met."))
