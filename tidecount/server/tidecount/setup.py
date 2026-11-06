"""Download the default detector once."""
from . import config, models, settings


def main() -> None:
    config.ensure_folders()
    try:
        models.ensure_weights(settings.current().default_detector)
    except OSError as exc:
        print(f"Couldn't download the detector ({exc}). Analysis will fail until it's available.")


if __name__ == "__main__":
    main()
