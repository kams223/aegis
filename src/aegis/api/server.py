from pathlib import Path

from fastapi.staticfiles import StaticFiles

from aegis.api.app import app
from aegis.api.comparison_routes import router


STATIC_DIRECTORY = Path(__file__).parent / "static"


if not STATIC_DIRECTORY.is_dir():
    raise RuntimeError(
        f"Dashboard directory not found: {STATIC_DIRECTORY}"
    )


app.include_router(router)


app.mount(
    "/dashboard",
    StaticFiles(
        directory=str(STATIC_DIRECTORY),
        html=True,
    ),
    name="dashboard",
)
