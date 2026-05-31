"""mapgen — an AI pipeline turning natural-language prompts about a place
into 3D models and files ready for rendering.

Pipeline stages:
    1. parse    prompt text          -> SceneSpec (validated JSON)
    2. resolve  SceneSpec            -> geo data (real OSM/elevation) or procedural plan
    3. build    resolved data        -> trimesh.Scene
    4. export   scene                -> .glb / .obj+.mtl / .stl / .py (Blender)
"""

from .spec import SceneSpec, GeoFeature, MapStyle, Direction, FeatureType
from .pipeline import Pipeline, PipelineResult

__all__ = [
    "SceneSpec",
    "GeoFeature",
    "MapStyle",
    "Direction",
    "FeatureType",
    "Pipeline",
    "PipelineResult",
]

__version__ = "0.1.0"
