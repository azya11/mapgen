"""The structured world specification — the contract between the AI parser and
the procedural geometry pipeline. Everything downstream depends only on this
schema, so the parser backend (Claude / rules / future) is fully swappable.

Kept import-light (no numpy/trimesh) so the serverless web bundle can import it.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class Direction(str, Enum):
    north = "north"
    south = "south"
    east = "east"
    west = "west"
    northeast = "northeast"
    northwest = "northwest"
    southeast = "southeast"
    southwest = "southwest"
    center = "center"


class FeatureType(str, Enum):
    mountain = "mountain"
    hill = "hill"
    valley = "valley"
    water = "water"
    river = "river"
    lake = "lake"
    sea = "sea"
    coast = "coast"
    forest = "forest"
    plain = "plain"
    desert = "desert"


class WorldStyle(str, Enum):
    lowpoly_nature = "lowpoly_nature"   # default natural relief, muted greens
    fantasy = "fantasy"                 # stylized, exaggerated relief
    urban = "urban"                     # flat-ish, built-up
    desert = "desert"                   # sandy palette, dunes
    alpine = "alpine"                   # high relief, rock + snow
    schematic = "schematic"             # clean, abstract, flat colors
    minimal = "minimal"                 # grayscale, geometry only


class Size(str, Enum):
    small = "small"
    medium = "medium"
    large = "large"


class Density(str, Enum):
    """How thickly a prop intent scatters across its region (placement, M2)."""

    sparse = "sparse"
    medium = "medium"
    dense = "dense"


class TerrainFeature(BaseModel):
    """One relief element of the world (a hill to the north, a lake, etc.)."""

    type: FeatureType
    name: Optional[str] = Field(default=None, description="Proper name if given.")
    direction: Optional[Direction] = Field(
        default=None, description="Where it sits relative to the world centre."
    )
    relative_size: Size = Field(default=Size.medium)
    description: Optional[str] = Field(default=None)


class TerrainSpec(BaseModel):
    """The relief layer: a list of terrain features shaping the heightfield."""

    features: List[TerrainFeature] = Field(default_factory=list)

    def features_of(self, *types: FeatureType) -> List[TerrainFeature]:
        wanted = set(types)
        return [f for f in self.features if f.type in wanted]

    @property
    def has_water(self) -> bool:
        return bool(
            self.features_of(
                FeatureType.water,
                FeatureType.lake,
                FeatureType.sea,
                FeatureType.river,
                FeatureType.coast,
            )
        )


class PropIntent(BaseModel):
    """A request to place props of one kind. The AI emits intents, never geometry.

    `generator` is a registry key (e.g. "tree.conifer"); it is validated against
    the live registry at build time, not here, so this module stays import-light.
    """

    generator: str = Field(description="Prop generator registry key, e.g. 'rock'.")
    count: int = Field(default=1, ge=1, le=5000)
    region: str = Field(
        default="scatter",
        description="A compass direction, 'scatter', 'edge', or 'cluster'.",
    )
    density: Density = Field(default=Density.medium)
    params: dict = Field(default_factory=dict)
    on: Literal["ground", "water"] = "ground"


class WorldSpec(BaseModel):
    """Fully validated description of a procedural world. Produced by a Parser."""

    name: str = Field(default="world", description="Output basename / world name.")
    world_style: WorldStyle = WorldStyle.lowpoly_nature
    extent_m: float = Field(
        default=200.0,
        gt=1.0,
        le=20000.0,
        description="Side length of the square world to model, in meters.",
    )
    seed: int = Field(default=1234, description="RNG seed; fixes determinism.")
    terrain: TerrainSpec = Field(default_factory=TerrainSpec)
    props: List[PropIntent] = Field(default_factory=list)
    notes: Optional[str] = Field(default=None)
