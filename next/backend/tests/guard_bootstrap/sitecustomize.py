"""Child-process isolation, loaded by Python before the backend/test worker."""

from tests.guards import install_ai_cli_guard, install_socket_guard

install_socket_guard()
install_ai_cli_guard()
