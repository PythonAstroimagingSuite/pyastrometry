import os
import logging
import subprocess
from astropy.coordinates import SkyCoord
from astropy import units as u
from astropy.coordinates import Angle

from pyastrometry.PlateSolveSolution import PlateSolveSolution

class ASTAP:
    """
    A wrapper of the astap local server  which allows
    plate solving of images.

    :param str exec_path: Path to the astap executable.
    """

    def __init__(self, exec_path):
        """
        Initialize object so it is ready to handle solve requests

        """
        self.exec_path = exec_path
        self.solve_field_revision = None


    def solve_file(self, fname, solve_params, search_rad=10, wait=1):
        """
        Plate solve the specified file using PlateSolve2

        :param str fname: Filename of the file to be solved.
        :param int wait: Number of seconds to wait when solve is complete before
                PlateSolve2 closes its window (defaults to 1 second).
        :returns:
          solved_position (SkyCoord)
             The J2000 sky coordinate of the plate solve match, or None if no
             match was found.
          angle (Angle)
             Position angle of Y axis expressed as East of North.
        """

# example cmdline
# /usr/bin/SDYSP -f <fits-file> -r <search-rad> -fov <fov> -ra <ra_guess> -dec <dec_guess> -z <downsample>

        cmd_line = self.exec_path
        cmd_line += f' -ra {solve_params.radec.ra.hour}'
        cmd_line += f' -sdp {solve_params.radec.dec.degree+90}'

        cmd_line += f' -fov {solve_params.fov_x.degree}'

        # search radius - default to 10 if not given
        if search_rad is None:
            search_rad = 10

        cmd_line += f' -r {search_rad}'

        cmd_line += ' -f ' + fname

        # output file
        (base, ext) = os.path.splitext(fname)
        out_fname = base

        if os.path.isfile(out_fname+'.ini'):
            os.unlink(out_fname+'.ini')

        cmd_line += ' -o ' + out_fname

        import shlex
        cmd_args = shlex.split(cmd_line)

        logging.info(f'cmd_line for astrometry.net local = "{cmd_line}"')
        logging.info(f'cmd_args for astrometry.net local = "{cmd_args}"')

#/usr/bin/solve-field -O --no-plots --no-verify --resort --no-fits2fits --do^Csample 2 -3 310.521 -4 45.3511 -5 10 --config /etc/astrometry.cfg -W /tmp/solution.wcs plate_solve_image.fits

        with subprocess.Popen(cmd_line,
                                    stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    universal_newlines=True) as ps_proc:

            logging.debug('ASTAP_proc output:')
            for l in ps_proc.stdout:
                logging.debug(f'ASTAP: {l.strip()}')
            logging.debug('end of output')


        try:
            out_file = open(out_fname+'.ini', 'r')
        except OSError as err:
            print(f"Error opening output file: {err}")
            return None

        solved_str = None
        ra_str = None
        dec_str = None
        ang_str = None
        pixelscale_str = None
        for l in out_file.readlines():
            print('l', l)
            ll = l.strip()
#            ll = ''.join(filter(lambda x: x.isalnum() or x.isspace() or x == '.', l))
#            print(ll)
            fields = ll.split('=')
            print ('fields', fields)
            # look for ra/dec in deg first
            if len(fields) != 2:
                continue

            if 'CRVAL1' in ll:
                # should look like:
                # Field center RADec  2.101258 29.091103 deg
                print('CRVAL1', fields)
                ra_str = fields[1]
            elif 'CRVAL2' in ll:
                # should look like:
                # Field rotation angle up is 1.12149 degrees E of N.
                print('CRVAL2', fields)
                dec_str = fields[1]
            elif 'CDELT1' in ll:
                print('CDELT1', fields)
                pixelscale_str = fields[1]
            elif 'CROTA1' in ll:
                print('CROTA1', fields)
                ang_str = fields[1]
            elif 'PLTSOLVD' in ll:
                print('PLTSOLVED', fields)
                solved_str = fields[1]


        logging.info(f'{solved_str} {ra_str} {dec_str} {ang_str} {pixelscale_str}')

        if solved_str != 'T':
            logging.exception('Failed to parse solution')
            return None

        try:
            solved_ra = float(ra_str)
            solved_dec = float(dec_str)
            solved_angle = float(ang_str)
            solved_scale = float(pixelscale_str)*3600

        except Exception as e:
            logging.exception('Failed to parse solution')
            return None

        logging.info(f'{solved_ra} {solved_dec} {solved_angle} {solved_scale}')

        radec = SkyCoord(ra=solved_ra*u.degree, dec=solved_dec*u.degree, frame='fk5', equinox='J2000')
        return PlateSolveSolution(radec, pixel_scale=solved_scale,
                           angle=Angle(solved_angle*u.deg), binning=solve_params.bin_x)






# OLD CODE
# =============================================================================
#         net_proc = subprocess.Popen(cmd_args,
#                                     stdin=subprocess.PIPE,
#                                     stdout=subprocess.PIPE,
#                                     stderr=subprocess.PIPE,
#                                     universal_newlines=True)
#         poll_value = None
#         while True:
#             poll_value = net_proc.poll()
#             if poll_value is not None:
#                 break
#
# # output
# #Field center: (RA,Dec) = (2.101258, 29.091103) deg.
# #Field center: (RA H:M:S, Dec D:M:S) = (00:08:24.302, +29:05:27.971).
# #Field size: 76.07 x 57.4871 arcminutes
# #Field rotation angle: up is 1.12149 degrees E of N
#
#         ra_str = None
#         dec_str = None
#         ang_str = None
#         fov_x_str = None
#         for l in net_proc.stdout.readlines():
#             ll = ''.join(filter(lambda x: x.isalnum() or x.isspace() or x == '.', l))
#             print(ll)
#             fields = ll.split()
#             # look for ra/dec in deg first
#             if 'CRVAL1' in ll:
#                 # should look like:
#                 # Field center RADec  2.101258 29.091103 deg
#                 print('CRVAL1', fields)
#             elif 'CRVAL2' in ll:
#                 # should look like:
#                 # Field rotation angle up is 1.12149 degrees E of N.
#                 print('CRVAL2', fields)
#             elif 'CRDELT1' in ll:
#                 print('CDELT1', fields)
#             elif 'CROTA1' in ll:
#                 print('CROTA1', fields)
#
#         logging.info(f'{ra_str} {dec_str} {ang_str}')
#
#         try:
#             solved_ra = float(ra_str)
#             solved_dec = float(dec_str)
#             solved_angle = float(ang_str)
#
#             # fov is given in arcmin so convert to arcsec
#             fov_x = float(fov_x_str)*60.0
#
#             logging.info(f'solved fov = {fov_x} arcsec')
#             if solve_params.width is not None:
#                 solved_scale = fov_x / solve_params.width
#                 logging.info(f'using given width of {solve_params.width} pixel scale is {solved_scale} arcsec/pix')
#             else:
#                 solved_scale = None
#                 logging.warning('No width given so pixel scale not computed!')
#
#         except Exception as e:
#             logging.exception('Failed to parse solution')
#             return None
#
#         logging.info(f'{solved_ra} {solved_dec} {solved_angle} {solved_scale}')
#
#         radec = SkyCoord(ra=solved_ra*u.degree, dec=solved_dec*u.degree, frame='fk5', equinox='J2000')
#         return PlateSolveSolution(radec, pixel_scale=solved_scale,
#                                   angle=Angle(solved_angle*u.deg), binning=solve_params.bin_x)
#
#
# =============================================================================

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
