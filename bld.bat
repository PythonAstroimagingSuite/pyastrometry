echo "BUILD SCRIPT RUNNING"

:: add to path to find whatever bash we're going to use!
:: SET PATH=%PATH%;C:\Users\msf\AppData\Local\Programs\Git\bin
:: bash -c "echo 'BASH RUN TEST'"

::mkdir %PREFIX%\Scripts
mkdir %PREFIX%\Lib\site-packages\pyastrometry

:: copy without extension so conda-build will make .bat file for it!
copy Scripts\pyastrometry_main.py %PREFIX%\Scripts\pyastrometry_main

xcopy /s pyastrometry %PREFIX%\Lib\site-packages\pyastrometry

:: put version in sources so we can report it when program is run
echo VERSION='%PKG_VERSION%-py%CONDA_PY%%GIT_DESCRIBE_HASH%_%GIT_DESCRIBE_NUMBER%' >> %PREFIX%\Lib\site-packages\pyastrometry\build_version.py
