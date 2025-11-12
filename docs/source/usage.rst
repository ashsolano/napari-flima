.. _usage:

Usage
=====
Analysis in FLIMa is split into two parts available from the tabs at the top of the FLIMa widget panel on the right side of the :code:`napari` GUI (:ref:`dialogU-a`.2):

.. _dialogU-A:

.. figure:: napari-main-widget-empty.png

    Fig A

    (napari GUI with FLIMa widget on the right; widget tabs highlighted at (2))

.. _dialogU-B:

.. figure:: napari-main-widget-files-selected.png

    Fig B

    (napari main GUI with FLIMa Phasor FLIM widget including example data)

Navigating the GUI
------------------
The two tabs of the FLIMa widget (:ref:`dialogU-a`.2) separate the stages of analysis into data preparation and FLIM Phasor analysis, and downstream analysis functions and report generation.

Image Management
~~~~~~~~~~~~~~~~
The Phasor FLIM tab is further split into File Selection and Cursor Analysis. When populated with files, File Selection will include a row for each file. Each file can be individually added to the analysis using the checkboxes (:ref:`dialogU-b`.1). Groups can be assigned to files using the dropdown (:ref:`dialogU-b`.2), and new groups can be added if necessary using the :menuselection:`Add` button. 

.. important::
    Make sure you've finished configuring a given file, including setting image thresholds before checking :ref:`dialogU-b`.1

Image Thresholding
~~~~~~~~~~~~~~~~~~
After all files have been loaded and assigned to groups but before they've been added to the analysis you are able to select upper and lower thresholds for the image intensity using the slider beside the given file (:ref:`dialogU-b`.3). Threshold values can be set by dragging the handles of the range slider or by typing them in manually in the boxes to the right of the slider.

Phasor Plot and Cursor Analysis
-------------------------------
The Phasor Plot projects the data into the polar (G,S) Phasor space where we will perform cursor-based analysis.

The Phasor Plot
~~~~~~~~~~~~~~~
To open the phasor plot click the button at the bottom of the widget which will open a new window :ref:`dialogU-c`

Adding and Configuring Cursors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
To create a cursor click the button on the bottom right of the :menuselection:`Cursor Analysis` section. Each cursor can be assigned a colour (different colours should be used for each cursor if multiple are used), and enabled using the checkbox (:ref:`dialogU-b`.4) to the left of the cursor row. Cursor details are given in the table (:ref:`dialogU-b`.5) and can be manually adjusted before or after configuring the cursor in the phasor plot. Cursors can be removed with the [x] button (:ref:`dialogu-b`.6).

Using the Phasor Plot
~~~~~~~~~~~~~~~~~~~~~

Segmentation and Downstream Analysis
------------------------------------

Configuring and Running Segmentation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Exporting Results
~~~~~~~~~~~~~~~~~

The HTML Report
---------------