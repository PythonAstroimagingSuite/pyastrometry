#!/bin/bash
echo "Making uic python files for pyastrometry"

echo "pyastrometry.ui"
/c/Users/msf/Anaconda3/Library/bin/pyuic5.bat pyastrometry.ui > ../../pyastrometry/uic/pyastrometry_uic.py

echo "pyastrometry_settings.ui"
/c/Users/msf/Anaconda3/Library/bin/pyuic5.bat pyastrometry_settings.ui > ../../pyastrometry/uic/pyastrometry_settings_uic.py
