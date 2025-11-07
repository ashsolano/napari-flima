"""napari-flima: A Napari plugin for interactive image analysis and segmentation of FLIM data."""

__version__ = "0.1.0"

import importlib.resources as pkg_resources
import os

# def get_logo_path():
#     """
#     Get the absolute path to the logo file packaged with this plugin.
#     Assumes the logo is located in the 'resources' folder within the package.
#     """
#     with pkg_resources.path("napari_flima.resources", "logo.png") as logo_path:
#         return str(logo_path)

def get_logo_path():
    """
    Get the absolute path to the logo file packaged with this plugin.
    This works both for local development (not installed) and as an installed package.
    """
    # First, try local path (when running from source)
    local_path = os.path.join(os.path.dirname(__file__), "resources", "flima-logo.png")
    if os.path.exists(local_path):
        return local_path
    # Fallback: use importlib.resources for installed packages
    try:
        with pkg_resources.path("napari_flima.resources", "flima-logo.png") as logo_path:
            return str(logo_path)
    except Exception as e:
        print("Could not find flima-logo.png:", e)
        return None