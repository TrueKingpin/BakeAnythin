# BakeAnythin

A Blender add-on to merge multiple materials into single PBR maps.

BakeAnythin provides an easy way to bake out multiple materials for game production and other real-time render workflows with a single combined texture set.

## Features

- **Automatic UV Unwrapping** – Generate UV maps using Smart UV Project.
- **UV Island Packing** – Automatically arrange and pack UV islands to make efficient use of texture space.
- You may use your existing UV map without any modifications.
- **PBR Texture Baking** - Base Color, Metallic, Roughness, and Normal maps can be baked.
- **Flexible Output** - Set texture resolution, bake location, UV margin and bake padding.
- Do note that features 1 and 2 just use blender's built-in smart UV project and Pack Islands features.

## Installation

1. Download the latest .py file in the repo and rename it to "bakeanythin.py" (excluding the quotation marks).
2. Open Blender.
3. Go to Edit Preferences Get Extensions Install from Disk (or whatever addon install window your Blender version uses).
4. Select the downloaded Python file.
5. Enable Bake Anythin.

## Usage

1. Choose the mesh for which you want to bake.
2. Open the 3D Viewport sidebar.
3. Navigate to the Bake Anythin panel.
4. Configure your UV and output settings.
5. Choose which texture maps to bake.
6. Start baking.

## Compatibility

- Actively Tested: Blender 5.3
- Planned compatibility testing: Blender 4.2+

Not tested on other versions of Blender.

## Current Limitations

- Still not implemented: high-to-low poly normal projection
- Normal baking currently uses the selected mesh's own geometry.
- Compatibility with other Blender versions has not yet been verified.

## Roadmap

- High-to-low poly normal baking.
- Cage-based projection support.
- Ambient Occlusion baking.
- Additional enhancements to UV packing and baking processes.

## License

Bake Anythin is published under the GNU General Public License v3.0 (GPL-3.0). See LICENSE for more information.

Author

Created and maintained by TrueKingpin.
