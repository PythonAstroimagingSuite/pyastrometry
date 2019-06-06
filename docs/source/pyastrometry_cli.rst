Using pyastrometry_cli_main.py
==============================

Introduction
------------

The script "pyastrometry_cli_main.py" handles taking an image and plate solveing
it to find the current position of the mount.

Invocation
----------

The invocation of autofocus_auto_star.py is:

.. code-block:: bash

    usage: pyastrometry_cli <operation> [<args>]

    The accepted commands are:
       solvepos     Take an image and solve current position
       solveimage <filename>    Solve position of an image file
       sync         Take an image, solve and sync mount
       slewsolve  <ra> <dec>  Slew to position and plate solve and slew until within threshold

    Astromentry CLI

    positional arguments:
      operation   Operation to perform

    optional arguments:
      -h, --help  show this help message and exit

Command Details
---------------
solvepos:
    Takes an image with the camera and solves it.  Drivers can be specified via
    a astroprofile or command line arguments.

    .. code-block:: bash

        usage: pyastrometry_cli solvepos [<args>]

        Solve Parameters

        optional arguments:
          -h, --help            show this help message and exit
          --profile PROFILE     Name of astroprofile
          --mount               Name of mount driver
          --camera              Name of camera driver
          --exposure            Exposure time
          --binning             Camera binning
          --solver SOLVER       Solver to use
          --pixelscale PIXELSCALE
                                Pixel scale (arcsec/pixel)
          --downsample DOWNSAMPLE
                                Downsampling
          --outfile OUTFILE     Output JSON file with solution
          --force               Overwrite output file

        Valid solvers are:
            astrometryonline
            astrometrylocal
            platesolve2

solveimage:
    Solves an existing image.

    .. code-block:: bash

        usage: pyastrometry_cli solveimage <filename> [<args>]

        Solve Parameters

        optional arguments:
          -h, --help            show this help message and exit
          --profile PROFILE     Name of astro profile
          --solver SOLVER       Solver to use
          --pixelscale PIXELSCALE
                                Pixel scale (arcsec/pixel)
          --downsample DOWNSAMPLE
                                Downsampling
          --outfile OUTFILE     Output JSON file with solution
          --force               Overwrite output file

        Valid solvers are:
            astrometryonline
            astrometrylocal
            platesolve2

sync:
    Takes an image with the camera and solves it and syncs mount to solution.

    .. code-block:: bash

        usage: pyastrometry_cli sync [<args>]

        Solve Parameters

        optional arguments:
          -h, --help            show this help message and exit
          --profile PROFILE     Name of astroprofile
          --mount               Name of mount driver
          --camera              Name of camera driver
          --exposure            Exposure time
          --binning             Camera binning
          --solver SOLVER       Solver to use
          --pixelscale PIXELSCALE
                                Pixel scale (arcsec/pixel)
          --downsample DOWNSAMPLE
                                Downsampling
          --outfile OUTFILE     Output JSON file with solution
          --force               Overwrite output file

        Valid solvers are:
            astrometryonline
            astrometrylocal
            platesolve2

slewsolve:
    Given an RA/DEC position slew to that position and refine slew using plate solving.

    .. code-block:: bash

        usage: pyastrometry_cli slewsolve <ra> <dec> [<args>]

        Solve Parameters

        optional arguments:
          -h, --help            show this help message and exit
          --profile PROFILE     Name of astroprofile
          --mount               Name of mount driver
          --camera              Name of camera driver
          --exposure            Exposure time
          --binning             Camera binning
          --solver SOLVER       Solver to use
          --pixelscale PIXELSCALE
                                Pixel scale (arcsec/pixel)
          --downsample DOWNSAMPLE
                                Downsampling
          --outfile OUTFILE     Output JSON file with solution
          --force               Overwrite output file

        Valid solvers are:
            astrometryonline
            astrometrylocal
            platesolve2

Using an astroprofile
----------------------

If specified an astroprofile will be used to get camera and mount driver information
as well as the pixelscale used for platesolving.


