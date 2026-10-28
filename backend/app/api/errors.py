from typing import Dict, Optional


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: Optional[Dict[str, str]] = None):
        super().__init__(message)
        self.status, self.code, self.message, self.headers = status, code, message, headers or {}


def error_body(code: str, message: str, fields=None) -> dict:
    body = {"success": False, "error": {"code": code, "message": message}}
    if fields:
        body["error"]["fields"] = fields
    return body
