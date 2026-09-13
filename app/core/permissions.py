"""System permission catalog and default roles.

Permissions are stored in ``Role.permisos_csv`` as comma-separated text
(see app.database.models). The wildcard ``"*"`` grants all permissions
(used by the "Administrador" role).
"""

PERM_DASHBOARD = "dashboard.ver"
PERM_PERSONAS = "personas.usar"  # Register/edit persons and photos.
PERM_COMPARADOR = "comparador.usar"
PERM_BUSQUEDA = "busqueda.usar"
PERM_WEBCAM = "webcam.usar"
PERM_VIDEO = "video.usar"
PERM_ESTADISTICAS = "estadisticas.usar"  # Includes export.
PERM_ADMIN = "admin.acceso"  # Users, roles, backup, cleanup, secure settings.

ALL_PERMISSIONS = [
    PERM_DASHBOARD, PERM_PERSONAS, PERM_COMPARADOR, PERM_BUSQUEDA,
    PERM_WEBCAM, PERM_VIDEO, PERM_ESTADISTICAS, PERM_ADMIN,
]

PERMISSION_LABELS = {
    PERM_DASHBOARD: "Ver dashboard",
    PERM_PERSONAS: "Registrar y editar personas",
    PERM_COMPARADOR: "Usar comparador biométrico",
    PERM_BUSQUEDA: "Buscar personas",
    PERM_WEBCAM: "Reconocimiento por webcam",
    PERM_VIDEO: "Analizar videos",
    PERM_ESTADISTICAS: "Ver estadísticas y exportar",
    PERM_ADMIN: "Administración del sistema",
}

# Roles seeded automatically on first application launch.
DEFAULT_ROLES: dict[str, list[str]] = {
    "Administrador": ["*"],
    "Operador": [
        PERM_DASHBOARD, PERM_PERSONAS, PERM_COMPARADOR, PERM_BUSQUEDA,
        PERM_WEBCAM, PERM_VIDEO, PERM_ESTADISTICAS,
    ],
    "Visualizador": [PERM_DASHBOARD, PERM_BUSQUEDA, PERM_ESTADISTICAS],
}


def permissions_from_csv(permisos_csv: str | None) -> set[str]:
    """Parse a CSV permission string into a set.

    Args:
        permisos_csv: Comma-separated permission names or None.

    Returns:
        Set of permission strings.
    """
    return {p.strip() for p in (permisos_csv or "").split(",") if p.strip()}


def permissions_to_csv(permisos: list[str]) -> str:
    """Serialize a permission list to CSV.

    Args:
        permisos: List of permission names.

    Returns:
        Comma-separated, sorted, deduplicated permission string.
    """
    return ",".join(sorted(set(permisos)))
