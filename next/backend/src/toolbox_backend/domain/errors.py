class SettingsError(Exception):
    """Only fixed, non-sensitive text is allowed in public messages."""

    def __init__(self, code: str, message: str, status: int = 409, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra

    def detail(self) -> dict:
        return {"code": self.code, "message": self.message, **self.extra}
