"""mapgen — turn a natural-language prompt into a procedural 3D game world
(low-poly terrain + placeable props) and export it to glTF/GLB, OBJ, STL.

Pipeline stages:
    1. parse   prompt text   -> WorldSpec (validated)
    2. build   WorldSpec      -> trimesh.Scene (procedural terrain + water)
    3. export  scene          -> .glb / .obj+.mtl / .stl
"""

from .spec import WorldSpec
from .pipeline import Pipeline, PipelineResult

__all__ = ["Pipeline", "PipelineResult", "WorldSpec"]

__version__ = "0.1.0"
