"""Template-based CoinPoker rank and suit recognition."""

from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np


class CardRecognizer:
    TEMPLATE_PATH = Path(__file__).with_name("assets") / "card_templates.npz"
    _templates = None

    @staticmethod
    def foreground_mask(region_rgb: np.ndarray) -> np.ndarray:
        """Extract both red and black card glyphs from a white card face."""
        region_rgb = region_rgb[:, :, :3]
        hsv = cv2.cvtColor(region_rgb, cv2.COLOR_RGB2HSV)
        gray = cv2.cvtColor(region_rgb, cv2.COLOR_RGB2GRAY)
        red = cv2.bitwise_or(
            cv2.inRange(hsv, np.array([0, 65, 35]), np.array([14, 255, 255])),
            cv2.inRange(hsv, np.array([164, 65, 35]), np.array([180, 255, 255])),
        )
        # Four-color CoinPoker deck: green clubs and blue diamonds. The green
        # range deliberately stops below the teal felt hue.
        green = cv2.inRange(hsv, np.array([36, 55, 30]), np.array([68, 255, 245]))
        blue = cv2.inRange(hsv, np.array([96, 55, 30]), np.array([132, 255, 245]))
        black = cv2.inRange(gray, 0, 115)
        mask = cv2.bitwise_or(cv2.bitwise_or(red, green), cv2.bitwise_or(blue, black))
        return cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))

    @classmethod
    def normalize_symbol(cls, region_rgb: np.ndarray, largest_only: bool = False) -> Optional[np.ndarray]:
        mask = cls.foreground_mask(region_rgb)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = [contour for contour in contours if cv2.contourArea(contour) >= max(5, mask.size * 0.002)]
        if not contours:
            return None

        if largest_only:
            contours = [max(contours, key=cv2.contourArea)]
        x1 = min(cv2.boundingRect(contour)[0] for contour in contours)
        y1 = min(cv2.boundingRect(contour)[1] for contour in contours)
        x2 = max(cv2.boundingRect(contour)[0] + cv2.boundingRect(contour)[2] for contour in contours)
        y2 = max(cv2.boundingRect(contour)[1] + cv2.boundingRect(contour)[3] for contour in contours)
        glyph = np.zeros_like(mask)
        cv2.drawContours(glyph, contours, -1, 255, thickness=cv2.FILLED)
        glyph = glyph[y1:y2, x1:x2]
        if glyph.size == 0:
            return None

        canvas = np.zeros((80, 80), dtype=np.uint8)
        scale = min(66 / glyph.shape[1], 66 / glyph.shape[0])
        resized = cv2.resize(
            glyph,
            (max(1, round(glyph.shape[1] * scale)), max(1, round(glyph.shape[0] * scale))),
            interpolation=cv2.INTER_NEAREST,
        )
        x = (80 - resized.shape[1]) // 2
        y = (80 - resized.shape[0]) // 2
        canvas[y:y + resized.shape[0], x:x + resized.shape[1]] = resized
        return canvas

    @classmethod
    def _load(cls):
        if cls._templates is None:
            if not cls.TEMPLATE_PATH.exists():
                return None
            data = np.load(cls.TEMPLATE_PATH, allow_pickle=False)
            cls._templates = {
                "rank_images": data["rank_images"],
                "rank_labels": data["rank_labels"],
                "suit_images": data["suit_images"],
                "suit_labels": data["suit_labels"],
            }
        return cls._templates

    @classmethod
    def _recognize(
        cls,
        region_rgb: np.ndarray,
        kind: str,
        allowed_labels=None,
    ) -> Optional[str]:
        templates = cls._load()
        if not templates:
            return None
        candidate = cls.normalize_symbol(region_rgb, largest_only=(kind == "suit"))
        if candidate is None:
            return None
        images = templates[f"{kind}_images"]
        labels = templates[f"{kind}_labels"]
        choices = [
            (template, label)
            for template, label in zip(images, labels)
            if allowed_labels is None or str(label) in allowed_labels
        ]
        if not choices:
            return None
        scores = [
            cv2.matchTemplate(candidate, template, cv2.TM_CCOEFF_NORMED)[0, 0]
            for template, _ in choices
        ]
        best = int(np.argmax(scores))
        return str(choices[best][1]) if scores[best] >= 0.35 else None

    @classmethod
    def recognize_rank(cls, region_rgb: np.ndarray) -> Optional[str]:
        label, score, _ = cls.recognize_rank_scored(region_rgb)
        return label if score >= 0.35 else None

    @classmethod
    def recognize_rank_scored(
        cls, region_rgb: np.ndarray
    ) -> Tuple[Optional[str], float, float]:
        """Return the best rank template plus confidence and label margin.

        Multiple samples exist for most ranks, so the margin is calculated
        between distinct labels rather than between individual templates.
        """
        templates = cls._load()
        if not templates:
            return None, 0.0, 0.0
        candidate = cls.normalize_symbol(region_rgb)
        if candidate is None:
            return None, 0.0, 0.0

        best_by_label = {}
        for template, label in zip(templates["rank_images"], templates["rank_labels"]):
            score = float(cv2.matchTemplate(
                candidate,
                template,
                cv2.TM_CCOEFF_NORMED,
            )[0, 0])
            label = str(label)
            best_by_label[label] = max(score, best_by_label.get(label, -1.0))

        ranked = sorted(best_by_label.items(), key=lambda item: item[1], reverse=True)
        if not ranked:
            return None, 0.0, 0.0
        label, score = ranked[0]
        runner_up = ranked[1][1] if len(ranked) > 1 else -1.0
        return label, score, score - runner_up

    @classmethod
    def recognize_suit(
        cls, region_rgb: np.ndarray, is_red: Optional[bool] = None
    ) -> Optional[str]:
        allowed = {'♦', '♥'} if is_red is True else {'♠', '♣'} if is_red is False else None
        return cls._recognize(region_rgb, "suit", allowed_labels=allowed)
