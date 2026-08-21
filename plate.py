from dataclasses import dataclass, field
from typing import List, Tuple

Point2D = Tuple[float, float]


@dataclass
class Opening:
    """An opening belonging to a plate."""
    id: int
    contour: List[Point2D]


@dataclass
class Plate:
    """Large-element plate represented by an arbitrary closed contour."""
    id: int
    contour: List[Point2D]
    z: float = 0.0
    thickness: float = 0.2
    material: str = "slab"
    holes: List[Opening] = field(default_factory=list)

    def __post_init__(self):
        if len(self.contour) < 3:
            raise ValueError("Plate contour must contain at least 3 points.")
        if self.thickness <= 0:
            raise ValueError("Plate thickness must be greater than zero.")

    @staticmethod
    def _closed(points: List[Point2D]) -> List[Point2D]:
        pts = list(points)
        if pts[0] != pts[-1]:
            pts.append(pts[0])
        return pts

    @property
    def closed_contour(self) -> List[Point2D]:
        return self._closed(self.contour)

    def add_hole(self, opening: Opening) -> None:
        if len(opening.contour) < 3:
            raise ValueError("Opening contour must contain at least 3 points.")
        self.holes.append(opening)
