"""Download the default detector once."""
from . import config, models


def main() -> None:
    try:
        models.ensure_weights(config.DEFAULT_DETECTOR)
    except OSError as exc:
        print(f"Couldn't download the detector ({exc}). Analysis will fail until it's available.")


if __name__ == "__main__":
    main()
