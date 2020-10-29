#
# Platesolve2 client
#
# Copyright 2019 Michael Fulbright
#
#
#    pyastrometry is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
import os
import logging
import subprocess
from astropy import units as u
from astropy.coordinates import Angle
from astropy.coordinates import SkyCoord
from pyastrometry.PlateSolveSolution import PlateSolveSolution

class PlateSolve2:
    """A wrapper of the PlateSolve2 stand alone executable which allows
    plate solving of images.

    The PlateSolve2 executable is started for every solve request.  The
    method blocks until PlateSolve2 completes.  When PlateSolve2 completes
    it will generate a '.apm' file which contains the result of the
    plate solve operation.  The contains are parsed and the solution is
    returned to the caller.

    It is important that the catalog path(s) are correctly configured in
    PlateSolve2 or the operation will fail.

    :param str exec_path: Path to the astap executable.
   """

    def __init__(self, exec_path):
        """Initialize object so it is ready to handle solve requests

        Parameters
        ----------
        exec_path : str
            Path to the PlateSolve2 executable
        """
        self.exec_path = exec_path

        logging.debug(f'PlateSolve2(): set exec path to {self.exec_path}')

    #def solve_file(self, fname, radec, fov_x, fov_y, nfields=99, wait=1):

    def set_exec_path(self, exec_path):
        """
        Set path to "solve-field" executable.

        :param str exec_path: Path to the astap executable.
        """
        self.exec_path = exec_path

    def solve_file(self, fname, solve_params, nfields=99, wait=1):
        """ Plate solve the specified file using PlateSolve2

        :param str fname: Filename of the file to be solved.
        :param SkyCoord radec: RA/DEC of the estimated center of the image.
        :param Angle fov_x: Angular width (field of view) of the image.
        :param Angle fov_y: Angular height (field of view) of the image.
        :param int nfields: Number of fields to search (defaults to 99).
        :param int wait: Number of seconds to wait when solve is complete before
            PlateSolve2 closes its window (defaults to 1 second).
        :returns:
          solved_position (SkyCoord)
             The J2000 sky coordinate of the plate solve match, or None if no
             match was found.
          angle (Angle)
             Position angle of Y axis expressed as East of North.
        """

        cmd_line = f'{solve_params.radec.ra.radian},'
        cmd_line += f'{solve_params.radec.dec.radian},'
        cmd_line += f'{solve_params.fov_x.radian},'
        cmd_line += f'{solve_params.fov_y.radian},'
        cmd_line += f'{nfields},'
        #cmd_line += os.path.basename(fname)
        # ignore wait time

        cmd_line += fname + ','
        cmd_line += f'{wait}'

        logging.debug(f'platesolve2 command line = |{cmd_line}|')

        # unlink previous solve if any
        (base, ext) = os.path.splitext(fname)

        #print(base, ext)

        apm_fname = base + '.apm'

        if os.path.isfile(apm_fname):
            os.unlink(apm_fname)

        #runargs = [self.exec_path, cmd_line]
        #runargs = ['printargs.bat', cmd_line]
        #runargs = ['PlateSolve2.exe', '5.67,1.00,0.025,0.017,99,'+fname+',1']

        #runargs = 'PlateSolve2.exe ' + cmd_line
        runargs = self.exec_path + ' ' + cmd_line

        logging.debug(f'platesolve2 runargs = |{runargs}|')

        with subprocess.Popen(runargs,
                                    stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    universal_newlines=True) as ps_proc:

            logging.debug('ps2_proc output:')
            for l in ps_proc.stdout:
                logging.debug(f'PS2: {l.strip()}')
            logging.debug('end of output')

#        poll_value = None
#        while True:
#            poll_value = ps2_proc.poll()
#
#            if poll_value is not None:
#                break

        try:
            apm_file = open(apm_fname, 'r')
        except OSError as err:
            print(f"Error opening apm file: {err}")
            return None

        # line 1 contains RA, DEC, XYRatio(?)
        try:
            line = apm_file.readline()
            ra_str, dec_str, _ = line.split(',')

            # line 2 contains the plate scale, angle, ?, ?, ?
            line = apm_file.readline()
            scale_str, angle_str, _, _, _ = line.split(',')

            # line 3 reports if the solve was valid or not
            line = apm_file.readline()
            solve_OK = 'Valid plate solution' in line
        except Exception as err:
            print(f"Error parsing apm file! {err}")
            return None

        print(ra_str, dec_str, scale_str, angle_str, solve_OK)

        try:
            solved_ra = float(ra_str)
            solved_dec = float(dec_str)
            solved_scale = float(scale_str)
            solved_angle = float(angle_str)
        except Exception as err:
            print(f"Error converting apm string values! {err}")
            return None

        if solve_OK:
            radec = SkyCoord(ra=solved_ra*u.radian, dec=solved_dec*u.radian, frame='fk5', equinox='J2000')
            return PlateSolveSolution(radec, pixel_scale=solved_scale,
                                      angle=Angle(solved_angle*u.deg), binning=solve_params.bin_x)
        else:
            return None