"""The structured scene specification — the contract between the AI parser
and the geometry pipeline. Everything downstream depends only on this schema,
so the parser backend (Claude / rules / future) is fully swappable."""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

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
    water = "water"        # generic body of water
    river = "river"
    lake = "lake"
    sea = "sea"
    coast = "coast"
    forest = "forest"
    park = "park"
    desert = "desert"
    plain = "plain"
    building = "building"
    district = "district"  # cluster of buildings
    road = "road"
    landmark = "landmark"


class MapStyle(str, Enum):
    topographic = "topographic"   # contour-driven terrain emphasis
    terrain = "terrain"           # natural relief, muted greens/browns
    satellite = "satellite"       # photoreal-ish flat-ish coloring
    city = "city"                 # buildings dominant, extruded blocks
    schematic = "schematic"       # clean, abstract, flat colors
    fantasy = "fantasy"           # stylized, exaggerated relief
    minimal = "minimal"           # grayscale, geometry only


class Size(str, Enum):
    small = "small"
    medium = "medium"
    large = "large"


class GeoFeature(BaseModel):
    """One described element of the scene (a mountain to the north, a lake, etc.)."""

    type: FeatureType
    name: Optional[str] = Field(
        default=None, description="Proper name if given, e.g. 'Mont Blanc'."
    )
    direction: Optional[Direction] = Field(
        default=None,
        description="Where it sits relative to the scene centre.",
    )
    relative_size: Size = Field(
        default=Size.medium, description="Apparent footprint/prominence."
    )
    description: Optional[str] = Field(
        default=None, description="Any extra qualitative detail from the prompt."
    )


class SceneSpec(BaseModel):
    """Fully validated description of what to generate. Produced by a Parser."""

    location: str = Field(
        description="Raw location phrase from the prompt (place name or description)."
    )
    is_real_location: bool = Field(
        description="True if this names a real, geocodable place on Earth; "
        "False if fictional/abstract and should be generated procedurally."
    )
    map_style: MapStyle = MapStyle.terrain
    extent_km: float = Field(
        default=2.0,
        gt=0.05,
        le=200.0,
        description="Approx. side length of the square area to model, in km.",
    )
    features: List[GeoFeature] = Field(default_factory=list)
    notes: Optional[str] = Field(
        default=None, description="Parser commentary / assumptions made."
    )

    # ------------------------------------------------------------------ #
    def features_of(self, *types: FeatureType) -> List[GeoFeature]:
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
