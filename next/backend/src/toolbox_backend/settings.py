from dataclasses import dataclass

DEV_ORIGINS = ("http://localhost:1420", "http://127.0.0.1:1420")
TAURI_ORIGINS = ("tauri://localhost", "http://tauri.localhost")


@dataclass(frozen=True)
class Settings:
    """Runtime settings. ``token`` and ``port`` are only known after startup."""

    token: str
    port: int
    dev: bool = False
    heartbeat_interval_s: float = 5.0
    ws_auth_timeout_s: float = 5.0
    ws_queue_size: int = 256

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        return TAURI_ORIGINS + (DEV_ORIGINS if self.dev else ())

    @property
    def expected_host(self) -> str:
        return f"127.0.0.1:{self.port}"
