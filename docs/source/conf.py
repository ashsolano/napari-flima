# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'napari-flima'
copyright = '2025, Ash Solano, Callum Sargeant'
author = 'Ash Solano, Callum Sargeant'
release = '0.1'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    'sphinx.ext.duration',
    'sphinx.ext.doctest',
    'sphinx.ext.autodoc',
]

templates_path = ['_templates']
exclude_patterns = []



# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'pydata_sphinx_theme'
html_static_path = ['_static']
html_logo = "flima-logo.png"

html_theme_options = {
  # ...
  "secondary_sidebar_items": ["page-toc"],
   "use_edit_page_button": False,
   "show_toc_level": 3,
  # ...
}

autodoc_typehints = "both"

html_sidebars = {
    "**": []
}