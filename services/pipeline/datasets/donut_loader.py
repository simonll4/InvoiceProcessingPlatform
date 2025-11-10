import os
import json
from typing import List

from datasets import load_dataset
from PIL import Image


def download_donut_samples(out_dir: str = "datasets/donut_samples",
                           split: str = "train",
                           limit: int = 10) -> List[str]:
    """Download a small subset of katanaml-org/invoices-donut-data-v1.

    Saves images to PNG files and a sidecar JSON with the remaining fields.
    Returns list of saved image paths.
    """
    ds = load_dataset("katanaml-org/invoices-donut-data-v1", split=split)
    os.makedirs(out_dir, exist_ok=True)

    saved_paths: List[str] = []

    for i, ex in enumerate(ds):
        if i >= limit:
            break

        # Save image (expects a Pillow image in ex["image"])
        img = ex.get("image")
        if img is None:
            # Skip entries without image
            continue
        img_path = os.path.join(out_dir, f"donut_{split}_{i:04d}.png")
        try:
            if isinstance(img, Image.Image):
                img.save(img_path)
            else:
                # Convert arrays to image if necessary
                Image.fromarray(img).save(img_path)
        except Exception:
            # In case some entry has invalid image data
            continue

        # Save metadata (excluding image payload)
        meta = {k: v for k, v in ex.items() if k != "image"}
        meta_path = os.path.join(out_dir, f"donut_{split}_{i:04d}.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2, default=str)

        saved_paths.append(img_path)

    return saved_paths
