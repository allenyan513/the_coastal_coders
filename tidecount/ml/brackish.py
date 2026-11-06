"""Code shared by the Brackish notebooks: settings, data loading, the model, training and scoring."""

import collections
import random
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import torch
from IPython.display import display
from torch import nn
from torch.utils.data import DataLoader, Subset, WeightedRandomSampler
from torchvision import datasets, models, transforms
from tqdm.auto import tqdm

# Settings for both notebooks. Restart the kernel after changing one.
EPOCHS = 6  # full passes over the training data
PER_CLASS = 3000  # cap on training crops per class, to keep runs short
BATCH_SIZE = 48
SEED = 42
PADDING = 0.15  # extra context around each box, as a share of its size
MIN_SIDE = 12  # boxes smaller than this many pixels are skipped
SIZE = 224
MEAN, STD = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]
ROUNDS = 1000  # redrawn test sets per bootstrap

ROOT = Path(__file__).resolve().parents[1]
PARQUET = ROOT / "data" / "datasets" / "brackish-parquet"
# The crops depend on these settings, so each combination gets its own folder.
CROPS = ROOT / "data" / "datasets" / "brackish-crops" / f"padding{PADDING}_min{MIN_SIDE}_seed{SEED}"
CLASSES = ["crab", "fish", "jellyfish", "shrimp", "small_fish", "starfish"]
COLORS = dict(zip(CLASSES, ["#e4572e", "#1f5eff", "#17b890", "#f3a712", "#a855f7", "#111827"]))
DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"

train_transform = transforms.Compose([
    transforms.Resize((SIZE, SIZE)),
    transforms.RandomHorizontalFlip(),
    transforms.ColorJitter(0.2, 0.2, 0.2),
    transforms.ToTensor(),
    transforms.Normalize(MEAN, STD),
])
eval_transform = transforms.Compose([
    transforms.Resize((SIZE, SIZE)),
    transforms.ToTensor(),
    transforms.Normalize(MEAN, STD),
])


def video_of(path):
    """Crops are named {video}-{frame}-{box}.jpg."""
    return Path(path).stem.rsplit("-", 2)[0]


def videos_per_class(layout):
    """Print how many crops and how many different videos each class has in each split."""
    splits = ("train", "val", "test")
    print(f"{'class':12s}" + "".join(f"{split + ' crops':>13s}{split + ' videos':>14s}" for split in splits))
    for name in CLASSES:
        row = f"{name:12s}"
        for split in splits:
            files = list((CROPS / layout / split / name).glob("*.jpg"))
            row += f"{len(files):13d}{len({video_of(file) for file in files}):14d}"
        print(row)


def capped(dataset, limit, seed):
    rng = random.Random(seed)
    by_class = collections.defaultdict(list)
    for index, label in enumerate(dataset.targets):
        by_class[label].append(index)
    keep = []
    for rows in by_class.values():
        rng.shuffle(rows)
        keep.extend(rows[:limit])
    return Subset(dataset, keep), [dataset.targets[i] for i in keep]


def make_loaders(layout, seed=SEED):
    root = CROPS / layout
    train_all = datasets.ImageFolder(root / "train", train_transform)
    val_all = datasets.ImageFolder(root / "val", eval_transform)
    test_all = datasets.ImageFolder(root / "test", eval_transform)
    train_set, targets = capped(train_all, PER_CLASS, seed)
    val_set, _ = capped(val_all, 1000, seed)
    class_counts = np.bincount(targets, minlength=len(CLASSES))
    sampler = WeightedRandomSampler(
        [1 / class_counts[t] for t in targets], len(targets), generator=torch.Generator().manual_seed(seed)
    )
    return {
        "train": DataLoader(train_set, batch_size=BATCH_SIZE, sampler=sampler, num_workers=2),
        "val": DataLoader(val_set, batch_size=96, num_workers=2),
        "test": DataLoader(test_all, batch_size=96, num_workers=2),
        "test_set": test_all,
    }


def make_model():
    model = models.resnet18(weights=models.ResNet18_Weights.IMAGENET1K_V1)
    model.fc = nn.Linear(model.fc.in_features, len(CLASSES))
    for name, parameter in model.named_parameters():
        parameter.requires_grad = name.startswith(("layer3", "layer4", "fc"))
    return model.to(DEVICE)


def metrics(matrix):
    recall = matrix.diagonal() / np.maximum(matrix.sum(1), 1)
    precision = matrix.diagonal() / np.maximum(matrix.sum(0), 1)
    f1 = 2 * precision * recall / np.maximum(precision + recall, 1e-9)
    present = matrix.sum(1) > 0  # a class with no examples says nothing about the model
    return {
        "accuracy": matrix.diagonal().sum() / matrix.sum(),
        "macro_f1": f1[present].mean(),
        "recall": recall,
        "precision": precision,
        "f1": np.where(present, f1, np.nan),
    }


@torch.no_grad()
def predict(model, loader):
    model.eval()
    truth, guesses = [], []
    for images, labels in tqdm(loader, desc="predict", leave=False):
        guesses.append(model(images.to(DEVICE)).argmax(1).cpu().numpy())
        truth.append(labels.numpy())
    return np.concatenate(truth), np.concatenate(guesses)


def confusion(truth, guesses):
    matrix = np.zeros((len(CLASSES), len(CLASSES)), dtype=int)
    np.add.at(matrix, (truth, guesses), 1)
    return matrix


def report(matrix):
    result = metrics(matrix)
    print(f"Accuracy {result['accuracy']:.3f}   Macro F1 {result['macro_f1']:.3f}\n")
    print(f"{'class':12s}{'crops':>7s}{'recall':>9s}{'precision':>11s}{'F1':>7s}")
    for i, name in enumerate(CLASSES):
        print(f"{name:12s}{matrix[i].sum():7d}{result['recall'][i]:9.2f}{result['precision'][i]:11.2f}{result['f1'][i]:7.2f}")
    return result


def test_videos(loaders):
    """The video of each test crop, in the same order as predict() returns them."""
    return np.array([video_of(path) for path, _ in loaders["test_set"].samples])


def bootstrap(truth, guesses, videos, seed=SEED):
    """Score redrawn test sets, each made by picking whole videos at random with replacement.

    The same seed on the same videos redraws the same sets, so two models scored this way can be
    compared round by round.
    """
    names = sorted(set(videos))
    per_video = np.stack([confusion(truth[videos == name], guesses[videos == name]) for name in names])
    picks = np.random.default_rng(seed).integers(len(names), size=(ROUNDS, len(names)))
    scores = [metrics(per_video[pick].sum(0)) for pick in tqdm(picks, desc="bootstrap", leave=False)]
    return {"macro_f1": np.array([s["macro_f1"] for s in scores]), "f1": np.stack([s["f1"] for s in scores])}


def interval(scores):
    """The range that holds the middle 95% of the scores."""
    return np.nanpercentile(scores, [2.5, 97.5], axis=0)


def report_interval(score, drawn):
    low, high = interval(drawn["macro_f1"])
    print(f"Macro F1 {score['macro_f1']:.3f}   95% interval {low:.3f} to {high:.3f}\n")
    lows, highs = interval(drawn["f1"])
    missing = np.isnan(drawn["f1"]).mean(0)
    print(f"{'class':12s}{'F1':>7s}{'interval':>16s}{'rounds without class':>23s}")
    for i, name in enumerate(CLASSES):
        print(f"{name:12s}{score['f1'][i]:7.2f}{lows[i]:9.2f} to{highs[i]:5.2f}{missing[i]:23.0%}")


def plot_progress(history, title):
    fig, axes = plt.subplots(1, 3, figsize=(15, 3.6))
    epochs = [h["epoch"] for h in history]
    axes[0].plot(epochs, [h["loss"] for h in history], marker="o")
    axes[0].set_title("Training loss")
    axes[1].plot(epochs, [h["macro_f1"] for h in history], marker="o", color="#0f7b4f")
    axes[1].set_ylim(0, 1)
    axes[1].set_title("Validation macro F1")
    for i, name in enumerate(CLASSES):
        axes[2].plot(epochs, [h["f1"][i] for h in history], marker="o", label=name, color=COLORS[name])
    axes[2].set_ylim(0, 1)
    axes[2].set_title("Validation F1 per class")
    axes[2].legend(fontsize=8, ncol=2)
    for ax in axes:
        ax.set_xlabel("epoch")
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle(title)
    fig.tight_layout()
    return fig


def train(layout, seed=SEED, live=True):
    """Train one model and return the epoch with the best validation macro F1."""
    torch.manual_seed(seed)
    loaders = make_loaders(layout, seed)
    model = make_model()
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=3e-4, weight_decay=1e-4)
    loss_fn = nn.CrossEntropyLoss()
    history, best_score, best_state = [], -1.0, None
    chart = None
    if live:
        chart = display(plt.figure(), display_id=True)
        plt.close("all")

    for epoch in range(1, EPOCHS + 1):
        model.train()
        running, seen = 0.0, 0
        bar = tqdm(loaders["train"], desc=f"epoch {epoch}/{EPOCHS}", leave=False)
        for images, labels in bar:
            optimizer.zero_grad()
            loss = loss_fn(model(images.to(DEVICE)), labels.to(DEVICE))
            loss.backward()
            optimizer.step()
            running += loss.item() * len(labels)
            seen += len(labels)
            bar.set_postfix(loss=f"{running / seen:.3f}")

        val = metrics(confusion(*predict(model, loaders["val"])))
        history.append({"epoch": epoch, "loss": running / seen, "macro_f1": val["macro_f1"], "f1": val["f1"]})
        if val["macro_f1"] > best_score:
            best_score = val["macro_f1"]
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}
        if live:
            figure = plot_progress(history, f"{layout}: best validation macro F1 {best_score:.3f}")
            chart.update(figure)
            plt.close(figure)

    model.load_state_dict(best_state)
    return model, loaders, history
