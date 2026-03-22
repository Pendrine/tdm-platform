from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class AppMeta:
    name: str
    version: str
    build_info: str
    schema_version: int


APP_NAME = "Klinikai TDM Platform"
APP_VERSION = "v0.9.3-beta"
BUILD_INFO = f"build {date.today().isoformat()}"
SCHEMA_VERSION = 1

APP_META = AppMeta(
    name=APP_NAME,
    version=APP_VERSION,
    build_info=BUILD_INFO,
    schema_version=SCHEMA_VERSION,
)


def as_dict() -> dict[str, str | int]:
    return {
        "name": APP_META.name,
        "version": APP_META.version,
        "build_info": APP_META.build_info,
        "schema_version": APP_META.schema_version,
    }
