"""Download every model the app can use, so the first analysis doesn't have to wait for them.

Run through ./fetch-models.sh when the app is in Docker. Models already downloaded are skipped.
"""
import open_clip

from . import config, models, settings


def main() -> None:
    config.ensure_folders()
    for key in config.DETECTORS:
        print(f"Detector: {key}", flush=True)
        models.ensure_weights(key)
    name = settings.current().species.model
    print(f"Species model: {name}, about 3.7 GB", flush=True)
    open_clip.create_model_and_transforms(name)
    open_clip.get_tokenizer(name)
    print("All models are ready. Next: docker compose up -d", flush=True)


if __name__ == "__main__":
    main()
