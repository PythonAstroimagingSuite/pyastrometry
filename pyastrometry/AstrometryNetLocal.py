import os
import math
import logging
import subprocess
from astropy.coordinates import SkyCoord
from astropy.wcs import WCS
from astropy import units as u
from astropy.coordinates import FK5
from astropy.coordinates import Angle
from astropy.coordinates import SkyCoord

from pyastrometry.PlateSolveSolution import PlateSolveSolution

class AstrometryNetLocal:
    """A wrapper of the astrometry.net local server  which allows
    plate solving of images.
    """

    def __init__(self, exec_path):
        """Initialize object so it is ready to handle solve requests

        Parameters
        ----------
        exec_path : str
            Path to the astrometry.net executable
        """
        self.exec_path = exec_path

    #def solve_file(self, fname, radec, fov_x, fov_y, nfields=99, wait=1):

    def set_exec_path(self, exec_path):
        self.exec_path = exec_path

    def solve_file(self, fname, solve_params, wait=1):
        """ Plate solve the specified file using PlateSolve2

        Parameters
        ----------
        fname : str
            Filename of the file to be solved.
        radec : SkyCoord
            RA/DEC of the estimated center of the image `fname`.
        fov_x : Angle
            Angular width (field of view) of the image `fname`.
        fov_y : Angle
            Angular height (field of view) of the image `fname`.
        nfields : int
            Number of fields to search (defaults to 99).
        wait : int
            Number of seconds to wait when solve is complete before
            PlateSolve2 closes its window (defaults to 1 second).

        Returns
        -------
        solved_position : SkyCoord:
            The J2000 sky coordinate of the plate solve match, or None if no
            match was found.
        angle : Angle
            Position angle of Y axis expressed as East of North.
        """

# example cmdline 
# /usr/bin/solve-field -O --no-plots --no-verify --resort --no-fits2fits --do^Csample 2 -3 310.521 -4 45.3511 -5 10 --config /etc/astrometry.cfg -W /tmp/solution.wcs plate_solve_image.fits        

        # remove any solved files
        filename, extension = os.path.splitext(fname)
        solved_filename = filename + '.solved'
        logging.info(f'{filename} {extension} {solved_filename}')
        if os.path.isfile(solved_filename):
            logging.info(f'Removing existing solved file {solved_filename}')
            os.remove(solved_filename)

        cmd_line = self.exec_path
        cmd_line += ' -O --no-plots --no-verify --resort --no-fits2fits --downsample 2'
        cmd_line += f' -3 {solve_params.radec.ra.degree}'
        cmd_line += f' -4 {solve_params.radec.dec.degree}'
        # 10 degree search radius        
        cmd_line += f' -5 10'
        cmd_line += ' --config /etc/astrometry.cfg'
        cmd_line += ' -W /tmp/solution.wcs'
        
        # disable most output files
        #cmd_line += '-N none '
#        cmd_line += '-W none '         
#        cmd_line += '-U none '         
#        cmd_line += '--axy none '         
#        cmd_line += '-I none '         
#        cmd_line += '-M none '         
#        cmd_line += '-R none '         
#        cmd_line += '-B none '     
        cmd_line += ' ' + fname
        
        import shlex
        cmd_args = shlex.split(cmd_line)
       
#        cmd_line += f'{solve_params.fov_x.radian},'
#        cmd_line += f'{solve_params.fov_y.radian},'
#        cmd_line += fname + ','
#        cmd_line += f'{wait}'

        logging.info(f'cmd_line for astrometry.net local = "{cmd_line}"')
        logging.info(f'cmd_args for astrometry.net local = "{cmd_args}"')

#/usr/bin/solve-field -O --no-plots --no-verify --resort --no-fits2fits --do^Csample 2 -3 310.521 -4 45.3511 -5 10 --config /etc/astrometry.cfg -W /tmp/solution.wcs plate_solve_image.fits

        net_proc = subprocess.Popen(cmd_args,
                                    stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    universal_newlines=True)
        poll_value = None
        while True:
            poll_value = net_proc.poll()
            if poll_value is not None:
                break

        # see if solve succeeded
        if os.path.isfile(solved_filename):
            logging.info('Solved file found!')
        else:
            logging.info('No solved file - solve failed!')
            return None

# output
#Field center: (RA,Dec) = (2.101258, 29.091103) deg.
#Field center: (RA H:M:S, Dec D:M:S) = (00:08:24.302, +29:05:27.971).
#Field size: 76.07 x 57.4871 arcminutes
#Field rotation angle: up is 1.12149 degrees E of N

        ra_str = None
        dec_str = None
        ang_str = None
        for l in net_proc.stdout.readlines():
            ll = ''.join(filter(lambda x: x.isalnum() or x.isspace() or x == '.', l))
            print(ll)
            fields = ll.split()
            # look for ra/dec in deg first
            if 'center' in ll and 'deg' in ll:
                # should look like:
                # Field center RADec  2.101258 29.091103 deg
                print(fields)
                ra_str = fields[3]
                dec_str = fields[4]
            elif 'angle' in ll:
                # should look like:
                # Field rotation angle up is 1.12149 degrees E of N.
                ang_str = fields[5]

        logging.info(f'{ra_str} {dec_str} {ang_str}')

        try:
            solved_ra = float(ra_str)
            solved_dec = float(dec_str)
            solved_angle = float(ang_str)
        except:
            logging.error('Failed to parse solution')
            return None

        logging.info(f'{solved_ra} {solved_dec} {solved_angle}')
        
        solved_scale = 1.0
        logging.warning('FORCING SCALE TO 1.0 FOR NOW SINCE WE DONT READ IT FROM SOLUTION!')

        # load solved FITS and get WCS data
#        new_fits_filename = filename + '.new'
#        
#        w=WCS(new_fits_filename)
#        
#        cd1_1 = w.wcs.cd[0][0]
#        cd1_2 = w.wcs.cd[1][0]
#        cd2_1 = w.wcs.cd[1][0]
#        cd2_2 = w.wcs.cd[1][1]
#        
#        logging.info(f'w.wcs.cd = {w.wcs.cd}')
#        logging.info(f'cd1_1 = {cd1_1} cd1_2 = {cd1_2} cd2_1 = {cd2_1} cd2_2 = {cd2_2}')
#        solved_angle = math.atan2(cd2_1, cd1_1)*180/math.pi
#        solved_scale = math.sqrt(cd1_1**2 + cd2_1**2)
#        solved_ra = w.wcs.crval[0]
#        solved_dec = w.wcs.crval[1]
#        logging.info(f'solved_ra = {solved_ra} solved_dec={solved_dec} solved_angle={solved_angle} solved_scale = {solved_scale}')

        radec = SkyCoord(ra=solved_ra*u.degree, dec=solved_dec*u.degree, frame='fk5', equinox='J2000')
        return PlateSolveSolution(radec, pixel_scale=solved_scale, angle=Angle(solved_angle*u.deg))
        
        
        
# from https://groups.google.com/forum/#!topic/adass.iraf.applications/1J3W3RDacjM
        
#The transformation from CDELT/CROTA2 to CD is the following.
#
#CD1_1 =  CDELT1 * cos (CROTA2)
#CD1_2 = -CDELT2 * sin (CROTA2)
#CD2_1 =  CDELT1 * sin (CROTA2)
#CD2_2 =  CDELT2 * cos (CROTA2)
#
#Unfortunately there is no general transformation in the other direction
#as the the CDELT/CROTA2 notation does not support skew and no generally
#accepted way of representing skew was ever adopted in that notation.
#
#On the assumption that that there is in fact no skew the reverse
#transformation is the following
#
#abs (CDELT1) = sqrt (CD1_1 ** 2 + CD2_1 ** 2)
#abs (CDELT2) = sqrt (CD1_2 ** 2 + CD2_2 ** 2)
#sign (CDELT1 * CDELT2) = sign (CD1_1 * CD2_2 - CD1_2 * CD2_1)
#
#As a matter of convention for astronomical images CDELT1 should be assigned
#to be negative if the above expression, actually the determinant of the CD
#matrix, is negative.
#
#The rotation angle is given as
#
#CROTA2 = arctan (-CD1_2 / CD2_2)
#
#or
#
#CROTA2 = arctan ( CD2_1 / CD1_1)
#
#If there is no skew the two expressions for rotation should be the same.
#If they aren't and the skew is small you can take an average.        
        