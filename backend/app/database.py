"""Open an Oracle Autonomous Database connection in Thin mode."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / "backend" / ".env"


class ConnectionSetupError(RuntimeError):
    """A configuration error whose message is safe to display."""


def get_connection():
    if not ENV_PATH.is_file():
        raise ConnectionSetupError("Missing backend/.env.")

    try:
        import oracledb
        from dotenv import dotenv_values
    except ModuleNotFoundError as error:
        if error.name == "oracledb":
            raise ConnectionSetupError("Python package oracledb is missing.") from None
        if error.name == "dotenv":
            raise ConnectionSetupError("Python package python-dotenv is missing.") from None
        raise

    settings = dotenv_values(ENV_PATH, interpolate=False)
    required = ("DB_USER", "DB_PSW", "DSN_ADB", "WALLET_PSW")
    missing = [name for name in required if not settings.get(name)]
    wallet_location = settings.get("WALLET_LOC") or settings.get("CONFIG_DIR")
    if not wallet_location:
        missing.append("WALLET_LOC (or CONFIG_DIR)")
    if missing:
        raise ConnectionSetupError("Missing settings in backend/.env: " + ", ".join(missing))

    wallet_dir = PROJECT_ROOT / wallet_location
    for filename in ("tnsnames.ora", "ewallet.pem"):
        if not (wallet_dir / filename).is_file():
            raise ConnectionSetupError(f"Wallet directory is missing {filename}.")

    if not oracledb.is_thin_mode():
        raise ConnectionSetupError("Oracle driver must be in Thin mode.")

    return oracledb.connect(
        user=settings["DB_USER"],
        password=settings["DB_PSW"],
        dsn=settings["DSN_ADB"],
        config_dir=str(wallet_dir),
        wallet_location=str(wallet_dir),
        wallet_password=settings["WALLET_PSW"],
    )
