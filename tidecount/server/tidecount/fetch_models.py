"""Download every model the app can use, so the first analysis doesn't have to wait for them.

Docker Compose runs this before the app starts. Models already downloaded are skipped, so a later
start needs no network and doesn't load the species model only to check it.
"""
import open_clip

from . import config, models, settings


def main() -> None:
    config.ensure_folders()
    for key in config.DETECTORS:
        print(f"Detector: {key}", flush=True)
        models.ensure_weights(key)
    name = settings.current().species.model
    done = config.WEIGHTS / "species-model.txt"
    if done.exists() and done.read_text() == name:
        print(f"Species model: {name} is ready", flush=True)
        return
    print(f"Species model: {name}, about 3.7 GB", flush=True)
    open_clip.create_model_and_transforms(name)
    open_clip.get_tokenizer(name)
    done.write_text(name)
    print("All models are ready", flush=True)


if __name__ == "__main__":
    main()
