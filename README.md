# FLIMa

<img src="https://github.com/ashsolano/napari-flima/blob/main/docs/source/flima-logo.png?raw=true" alt="napari-flima" width=400>

> :warning: This is an early version of the FLIMa software and may not be indicative of a final release. You may encounter issues when using the softwre.
-----

FLIMa is an open source `napari` widget for performing Fluorescence Lifetime Imaging Microscopy data analysis. FLIMa supports both Time Domain and Frequency Domain FLIM data and provides per-sample and group based statistical analysis of FLIM data using FLIM Phasor analysis techniques.

## Installation

1. Fetch the package from Github:

    `git clone https://github.com/ashsolano/napari-flima.git`

2. Install dependencies:

        # navigate to the flima root directory
        `cd ./napari-flima` 
        # dependency install requires setuptools
        `pip install .`

3. Running FLIMa:
   
   To run FLIMa ensure that you've navigated to the napari-flima root directory, then run the GUI script: `.\run.py`
   
        `python run.py`
