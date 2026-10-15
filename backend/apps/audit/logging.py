"""Logging handler that stores ERROR records in ErrorLog (SA-17) and a JSON formatter for container logs (ENGR-05)."""

import json
import logging
import traceback

from apps.core.india import mask_pii


class DatabaseErrorHandler(logging.Handler):
    def emit(self, record):
        try:
            from apps.core.request import current_request

            from .models import ErrorLog

            request = getattr(record, "request", None) or current_request()
            ErrorLog.objects.create(
                level=record.levelname,
                logger=record.name[:200],
                message=mask_pii(record.getMessage())[:10000],
                traceback="".join(traceback.format_exception(*record.exc_info)) if record.exc_info else "",
                path=(request.path[:500] if request else ""),
                request_id=getattr(request, "request_id", "") if request else "",
            )
        except Exception:  # logging must never break the request
            self.handleError(record)


class JsonFormatter(logging.Formatter):
    def format(self, record):
        from apps.core.request import current_request

        request = current_request()
        data = {
            "time": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": mask_pii(record.getMessage()),  # ENG-10: no phone numbers / e-mails in logs
            "request_id": getattr(request, "request_id", None),
        }
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str)
