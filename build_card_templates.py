"""Build card glyph templates from the user-provided CoinPoker samples."""

from pathlib import Path

import cv2
import numpy as np

from card_recognizer import CardRecognizer


SAMPLES = Path(__file__).with_name("assets") / "card_samples"

# file, card-column x origins, top y, top row, bottom row
GRIDS = (
    ("red_grid.png", (40, 164, 289), 27, ("4♦", "6♥", "7♥"), ("A♥", "A♦", "T♦")),
    ("mixed_grid.png", (24, 148, 273, 397), 23, ("7♣", "6♦", "8♠", "4♠"), ("7♠", "9♦", "2♥", "2♦")),
    ("wide_grid.png", (34, 158, 283, 407, 531), 21, ("A♦", "6♣", "4♦", "3♠", "K♦"), ("3♣", "8♦", "7♠", "T♦", "Q♥")),
    ("small_grid.png", (34, 158, 283), 13, ("2♥", "4♣", "9♥"), ("5♣", "3♠", "7♠")),
)


def extract_card(image_rgb, x, y, label, ranks, rank_labels, suits, suit_labels):
    rank_region = image_rgb[y + 2:y + 55, x + 3:x + 50]
    suit_region = image_rgb[y + 43:y + 108, x + 2:x + 64]
    rank = CardRecognizer.normalize_symbol(rank_region)
    suit = CardRecognizer.normalize_symbol(suit_region, largest_only=True)
    if rank is None or suit is None:
        raise RuntimeError(f"Could not extract {label} at {(x, y)}")
    ranks.append(rank)
    rank_labels.append(label[:-1])
    suits.append(suit)
    suit_labels.append(label[-1])


def main():
    ranks, rank_labels, suits, suit_labels = [], [], [], []
    for filename, columns, top_y, top_labels, bottom_labels in GRIDS:
        image_bgr = cv2.imread(str(SAMPLES / filename))
        if image_bgr is None:
            raise FileNotFoundError(SAMPLES / filename)
        image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        for x, label in zip(columns, top_labels):
            extract_card(image_rgb, x, top_y, label, ranks, rank_labels, suits, suit_labels)
        for x, label in zip(columns, bottom_labels):
            extract_card(image_rgb, x, top_y + 100, label, ranks, rank_labels, suits, suit_labels)

    # The grid samples contain every rank except J. The live J♦7♠ crop adds J.
    image_bgr = cv2.imread(str(SAMPLES / "hero_j7.png"))
    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    j_rank = CardRecognizer.normalize_symbol(image_rgb[8:83, 15:71])
    j_suit = CardRecognizer.normalize_symbol(image_rgb[48:125, 15:82], largest_only=True)
    if j_rank is None or j_suit is None:
        raise RuntimeError("Could not extract J♦ from hero_j7.png")
    ranks.append(j_rank)
    rank_labels.append("J")
    suits.append(j_suit)
    suit_labels.append("♦")

    output = CardRecognizer.TEMPLATE_PATH
    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output,
        rank_images=np.stack(ranks),
        rank_labels=np.asarray(rank_labels),
        suit_images=np.stack(suits),
        suit_labels=np.asarray(suit_labels),
    )
    print(f"Wrote {len(ranks)} rank and {len(suits)} suit templates to {output}")
    CardRecognizer._templates = None
    validate_samples()


def validate_samples():
    from screen_reader import ScreenReader

    expected_ranks = set("23456789TJQKA")
    expected_suits = set("♣♦♥♠")
    seen_ranks, seen_suits = set(), set()
    failures = []

    for filename, columns, top_y, top_labels, bottom_labels in GRIDS:
        image_bgr = cv2.imread(str(SAMPLES / filename))
        image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        for y, labels in ((top_y, top_labels), (top_y + 100, bottom_labels)):
            for x, label in zip(columns, labels):
                rank_region = image_rgb[y + 2:y + 55, x + 3:x + 50]
                suit_region = image_rgb[y + 43:y + 108, x + 2:x + 64]
                actual = (
                    ScreenReader._read_rank(rank_region),
                    ScreenReader._read_suit(suit_region),
                )
                expected = (label[:-1], label[-1])
                seen_ranks.add(expected[0])
                seen_suits.add(expected[1])
                if actual != expected:
                    failures.append((filename, label, actual))

    hero_bgr = cv2.imread(str(SAMPLES / "hero_j7.png"))
    hero_rgb = cv2.cvtColor(hero_bgr, cv2.COLOR_BGR2RGB)
    j_rank = ScreenReader._read_rank(hero_rgb[8:83, 15:71])
    seen_ranks.add("J")
    if j_rank != "J":
        failures.append(("hero_j7.png", "J", j_rank))

    if seen_ranks != expected_ranks or seen_suits != expected_suits or failures:
        raise AssertionError(
            f"Template validation failed; ranks={seen_ranks}, suits={seen_suits}, failures={failures}"
        )
    print("Validated 13 ranks, 4 suits, and 52 rank/suit combinations")


if __name__ == "__main__":
    main()
