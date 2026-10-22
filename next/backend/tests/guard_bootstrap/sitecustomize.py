"""Child-process isolation, loaded by Python before the backend/test worker."""

from tests.guards import install_socket_guard

install_socket_guard()
