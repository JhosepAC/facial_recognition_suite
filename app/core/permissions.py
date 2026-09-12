"""
Catálogo de permisos del sistema y roles por defecto.

Los permisos se guardan en Role.permisos_csv como texto separado por comas
(ver app/database/models.py). El comodín "*" concede todos los permisos
(usado por el rol "Administrador").
"""

PERM_DASHBOARD = "dashboard.ver"
PERM_PERSONAS = "personas.usar"          # registrar/editar personas y fotos
PERM_COMPARADOR = "comparador.usar"
PERM_BUSQUEDA = "busqueda.usar"
PERM_WEBCAM = "webcam.usar"
PERM_VIDEO = "video.usar"
PERM_ESTADISTICAS = "estadisticas.usar"  # incluye exportación
PERM_ADMIN = "admin.acceso"              # usuarios, roles, respaldo, limpieza, config. segura

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

# Roles sembrados automáticamente la primera vez que se ejecuta la aplicación.
DEFAULT_ROLES: dict[str, list[str]] = {
    "Administrador": ["*"],
    "Operador": [
        PERM_DASHBOARD, PERM_PERSONAS, PERM_COMPARADOR, PERM_BUSQUEDA,
        PERM_WEBCAM, PERM_VIDEO, PERM_ESTADISTICAS,
    ],
    "Visualizador": [PERM_DASHBOARD, PERM_BUSQUEDA, PERM_ESTADISTICAS],
}


def permissions_from_csv(permisos_csv: str | None) -> set[str]:
    return {p.strip() for p in (permisos_csv or "").split(",") if p.strip()}


def permissions_to_csv(permisos: list[str]) -> str:
    return ",".join(sorted(set(permisos)))
