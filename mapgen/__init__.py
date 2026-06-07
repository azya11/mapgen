"""mapgen — an AI pipeline turning natural-language prompts about a place
into 3D models and files ready for rendering.

Pipeline stages:
    1. parse    prompt text          -> SceneSpec (validated JSON)
    2. resolve  SceneSpec            -> geo data (real OSM/elevation) or procedural plan
    3. build    resolved data        -> trimesh.Scene
    4. export   scene                -> .glb / .obj+.mtl / .stl / .py (Blender)
"""

from .spec import WorldSpec, TerrainSpec, TerrainFeature, WorldStyle, PropIntent, Direction, FeatureType

try:
    from .pipeline import Pipeline, PipelineResult
    _pipeline_available = True
except (ImportError, ModuleNotFoundError):
    _pipeline_available = False

__all__ = [
    "WorldSpec",
    "TerrainSpec",
    "TerrainFeature",
    "WorldStyle",
    "PropIntent",
    "Direction",
    "FeatureType",
    "Pipeline",
    "PipelineResult",
]

__version__ = "0.1.0"
