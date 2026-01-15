.. _setup:

Getting Started
===============

Installation
------------

1. Fetch the package from Github:

    :code:`git clone https://github.com/ashsolano/napari-flima.git`

2. Install dependencies:

    .. code-block:: bash

        # navigate to the flima root directory
        cd ./napari-flima 
        # dependency install requires setuptools
        pip install .

3. Running FLIMa:
   
   To run FLIMa ensure that you've navigated to the napari-flima root directory, then run the GUI script: :code:`.\run.py` 

    .. code-block:: bash

        python run.py

4. Report any issues on the Github repository ensuring you cite the package version and including your python environment details

Configuring FLIMa
-----------------

Intro Dialog
~~~~~~~~~~~~

.. _dialogS-A:

.. figure:: flima-intro-dialog.png

    Fig A

    (FLIMa configuration dialog)

1. Acquisition Settings
    Here we find the configuration options for microscopy image acquisition, each section needs to be configured to match the parameters of your microscope:

    a. The type of FLIM data, either Time Domain (TCSPC FLIM) or Frequency Domain (FD FLIM)

2. Channel Settings
    Here we assign the channels of our image to the type of data contained, each channel of the image should be matched in order with a data type from the drop down (b):

    a. Select the number of channels in the image

    b. For each channel a row will be listed and needs to be assigned one of the follwing data types: (Intensity, G-values, S-values, Phase-values, Modulation-values)
    
    c. If your images don't contain G-value or S-value layers leave this option ticked, otherwise you may see some performance improvements if you untick it

    d. Once all the options are configured click :code:`Confirm Settings` to launch the :code:`napari` application with the FLIMa widget

.. tip::
    Channel assignment details should be given by the microscope configuration

Adding Images
~~~~~~~~~~~~~
.. _dialogS-B:

.. figure:: napari-main-widget-empty.png

    Fig B

    (napari GUI with FLIMa widget on the right; widget tabs highlighted at (2))

1. First Select :menuselection:`File --> Open File(s)...` from the tabs in the top left (:ref:`dialogS-C`), or press :kbd:`Ctrl-O`
2. Next Make sure the :menuselection:`Phasor FLIM` tab is focused
3. Add the condition groups if you're working with multiple samples and select which images to add to the new group in :ref:`dialog-D`
4. Files will appear as rows in this box as they're added, individual file configuration is described in :ref:`usage`

.. _dialogS-C:

.. figure:: open-files.png

    Fig C

    (napari File Tab with Open File(s)... subsection highlighted)

