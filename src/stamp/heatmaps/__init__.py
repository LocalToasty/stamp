import logging
from collections.abc import Collection, Iterable
from pathlib import Path
from typing import cast

import h5py
import matplotlib.pyplot as plt
import numpy as np
import openslide
import torch
from fastai.vision.learner import Learner, load_learner
from matplotlib.axes import Axes
from matplotlib.patches import Patch
from PIL import Image
from torch import Tensor
from torch.func import jacrev  # pyright: ignore[reportPrivateImportUsage]

from stamp.preprocessing.extract import supported_extensions
from stamp.preprocessing.tiling import SlidePixels, get_slide_mpp

logger = logging.getLogger("stamp")


def get_stride(coords: Tensor) -> float:
    xs = coords[:, 0].unique(sorted=True)
    stride = (xs[1:] - xs[:-1]).min()
    return stride


def gradcam_per_category(learn: Learner, feats: Tensor) -> Tensor:
    tile, feat = -2, -1  # feats dimensions

    return (
        (
            feats
            * jacrev(
                lambda x: torch.softmax(
                    learn.model(x.unsqueeze(0), torch.tensor([x.shape[tile]])),
                    dim=1,
                ).squeeze(0)
            )(feats)
        )
        .mean(feat)
        .abs()
    )


def vals_to_im(
    scores: Tensor,  # [n_tiles *d_feats]
    coords_norm: Tensor,  # "n_tiles *d_feats",
) -> Tensor:
    """Arranges scores in a 2d grid according to coordinates"""
    size = coords_norm.max(0).values.flip(0) + 1
    im = torch.zeros((*size.tolist(), *scores.shape[1:]))

    flattened_im = im.flatten(end_dim=1)
    flattened_coords = coords_norm[:, 1] * im.shape[1] + coords_norm[:, 0]
    flattened_im[flattened_coords] = scores

    im = flattened_im.reshape_as(im)

    return im


def show_thumb(slide, thumb_ax: Axes, attention: Tensor) -> np.ndarray:
    mpp = get_slide_mpp(slide)
    dims_um = np.array(slide.dimensions) * mpp
    thumb = slide.get_thumbnail(np.round(dims_um * 8 / 256).astype(int))
    thumb_ax.imshow(np.array(thumb)[: attention.shape[0] * 8, : attention.shape[1] * 8])
    return np.array(thumb)[: attention.shape[0] * 8, : attention.shape[1] * 8]


def show_class_map(
    class_ax: Axes, top_score_indices: Tensor, gradcam_2d, categories: Collection[str]
) -> None:
    cmap = plt.get_cmap("Pastel1")
    classes = cast(np.ndarray, cmap(top_score_indices))
    classes[..., -1] = (gradcam_2d.sum(-1) > 0).detach().cpu() * 1.0
    class_ax.imshow(classes)
    class_ax.legend(
        handles=[
            Patch(facecolor=cmap(i), label=cat) for i, cat in enumerate(categories)
        ]
    )


def heatmaps_(
    *,
    feature_dir: Path,
    wsi_dir: Path,
    checkpoint_path: Path,
    output_dir: Path,
    slide_paths: Iterable[Path] | None = None,
    # top tiles
    topk: int,
    bottomk: int,
) -> None:
    learn = load_learner(checkpoint_path)
    learn.model.eval()
    categories: Collection[str] = learn.dls.train.dataset._datasets[
        -1
    ].encode.categories_[0]

    if slide_paths is not None:
        wsis_to_process = (wsi_dir / slide for slide in slide_paths)
    else:
        wsis_to_process = (
            p for ext in supported_extensions for p in wsi_dir.glob(f"**/*{ext}")
        )

    for wsi_path in wsis_to_process:
        h5_path = feature_dir / wsi_path.with_suffix(".h5").name

        if not h5_path.exists():
            logger.info(f"could not find matching h5 file at {h5_path}. Skipping...")
            continue

        slide_output_dir = output_dir / h5_path.stem
        slide_output_dir.mkdir(exist_ok=True, parents=True)
        logger.info(f"creating heatmaps for {wsi_path.name}")

        slide = openslide.open_slide(wsi_path)
        slide_mpp = get_slide_mpp(slide)
        assert slide_mpp is not None, "could not determine slide MPP"

        with h5py.File(h5_path) as h5:
            feats = torch.tensor(
                h5["feats"][:]  # pyright: ignore[reportIndexIssue]
            ).float()
            coords = torch.tensor(h5["coords"][:])  # pyright: ignore[reportIndexIssue]

            stride = cast(float, h5.attrs.get("tile_size", get_stride(coords)))
            if h5.attrs.get("unit") == "um":
                coords_tile_slide_px = torch.round(coords / slide_mpp).long()
                tile_size_slide_px = SlidePixels(
                    int(cast(np.float64, h5.attrs["tile_size"]) / slide_mpp)
                )
            else:
                xs = np.unique(coords[:, 0])
                stride = round(np.min(xs[1:] - xs[:-1]))
                if round(stride) == 224:
                    slide_path = getattr(slide, "_filename", "unknown slide")
                    print(
                        f"{slide_path}: tile stride is roughly 224, assuming coordinates have unit 256um/224px (historic STAMP format)"
                    )
                    coords_tile_slide_px = coords / 224 * 256 / slide_mpp
                    tile_size_slide_px = SlidePixels(int(256 / slide_mpp))
                else:
                    raise RuntimeError(
                        "unable to infer coordinates from feature file. Please reextract them using `stamp preprocess`."
                    )

        coords_norm = (coords // stride).long()

        preds = torch.softmax(
            learn.model(feats.unsqueeze(0), torch.tensor([feats.shape[-2]])),
            dim=1,
        ).squeeze(0)

        gradcam = gradcam_per_category(
            learn=learn,
            feats=feats,
        ).permute(-1, -2)  # shape: [tile, category]
        gradcam_2d = vals_to_im(
            gradcam,
            coords_norm,
        ).detach()  # shape: [width, height, category]

        scores = torch.softmax(
            learn.model(feats.unsqueeze(-2), torch.ones((len(feats)))), dim=1
        )  # shape: [tile, category]
        scores_2d = vals_to_im(
            scores, coords_norm
        ).detach()  # shape: [width, height, category]

        fig, axs = plt.subplots(nrows=2, ncols=max(2, len(categories)), figsize=(12, 8))

        show_class_map(
            class_ax=axs[0, 1],
            top_score_indices=scores_2d.topk(2).indices[:, :, 0],
            gradcam_2d=gradcam_2d,
            categories=categories,
        )

        for ax, (pos_idx, category) in zip(axs[1, :], enumerate(categories)):
            ax: Axes
            top2 = scores.topk(2)
            # Calculate the distance of the "hot" class
            # to the class with the highest score apart from the hot class
            category_support = torch.where(
                top2.indices[..., 0] == pos_idx,
                scores[..., pos_idx] - top2.values[..., 1],
                scores[..., pos_idx] - top2.values[..., 0],
            )  # shape: [tile]

            # So, if we have a pixel with scores (.4, .4, .2) and would want to get the heat value for the first class,
            # we would get a neutral color, because it is matched with the second class
            # But if our scores were (.4, .3, .3), it would be red,
            # because now our class is .1 above its nearest competitor

            attention = torch.where(
                top2.indices[..., 0] == pos_idx,
                gradcam[..., pos_idx] / gradcam.max(),
                (
                    others := gradcam[
                        ..., list(set(range(len(categories))) - {pos_idx})
                    ]
                    .max(-1)
                    .values
                )
                / others.max(),
            )  # shape: [tile]

            category_score = (
                category_support * attention / attention.max()
            )  # shape: [tile]

            score_im = cast(
                np.ndarray,
                plt.get_cmap("RdBu_r")(
                    vals_to_im(category_score / 2 + 0.5, coords_norm).detach()
                ),
            )

            score_im[..., -1] = vals_to_im(attention, coords_norm) > 0

            ax.imshow(score_im)
            ax.set_title(f"{category} {preds[pos_idx]:1.2f}")
            target_size = np.array(score_im.shape[:2][::-1]) * 8

            Image.fromarray(np.uint8(score_im * 255)).resize(
                tuple(target_size), resample=Image.Resampling.NEAREST
            ).save(
                slide_output_dir
                / f"scores-{h5_path.stem}-score_{category}={preds[pos_idx]:0.2f}.png"
            )

            # Top tiles
            for score, index in zip(*category_score.topk(topk)):
                (
                    slide.read_region(
                        tuple(coords_tile_slide_px[index]),  # pyright: ignore[reportArgumentType]
                        0,
                        (tile_size_slide_px, tile_size_slide_px),
                    )
                    .convert("RGB")
                    .save(
                        slide_output_dir
                        / f"top-{h5_path.stem}-score_{category}={score:0.2f}.jpg"
                    )
                )
            for score, index in zip(*(-category_score).topk(bottomk)):
                (
                    slide.read_region(
                        tuple(coords_tile_slide_px[index]),  # pyright: ignore[reportArgumentType]
                        0,
                        (tile_size_slide_px, tile_size_slide_px),
                    )
                    .convert("RGB")
                    .save(
                        slide_output_dir
                        / f"bottom-{h5_path.stem}-score_{category}={-score:0.2f}.jpg"
                    )
                )

        # Generate overview
        thumb = show_thumb(
            slide=slide,
            thumb_ax=axs[0, 0],
            attention=vals_to_im(
                attention,
                coords_norm,  # pyright: ignore[reportPossiblyUnboundVariable]
            ),
        )
        Image.fromarray(thumb).save(slide_output_dir / f"thumbnail-{h5_path.stem}.png")

        for ax in axs.ravel():
            ax.axis("off")

        fig.savefig(slide_output_dir / f"overview-{h5_path.stem}.png")
        plt.close(fig)
