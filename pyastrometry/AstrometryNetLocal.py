import os
import math
import logging
import subprocess
import numpy as np
from astropy.coordinates import SkyCoord
from astropy import units as u
from astropy.coordinates import Angle

from pyastrometry.PlateSolveSolution import PlateSolveSolution

class AstrometryNetLocal:
    """A wrapper of the astrometry.net local server  which allows
    plate solving of images.

    :param str exec_path: Path to the "solve-field" executable.
    """

    def __init__(self, exec_path):
        """Initialize object so it is ready to handle solve requests

        Parameters
        ----------
        exec_path : str
            Path to the astrometry.net executable
        """
        self.exec_path = exec_path
        self.solve_field_revision = None

    def set_exec_path(self, exec_path):
        """
        Set path to "solve-field" executable.

        :param str exec_path: Path to the astap executable.
        """

        self.exec_path = exec_path

    def probe_solve_field_revision(self):
        """
        Runs "solve-field" executable to determine its version.
        """
        # did we do this already
        if self.solve_field_revision is not None:
            return self.solve_field_revision

        cmd_args = [self.exec_path, '-h']

        logging.debug(f'probe_solve_field_revision cmd_args = {cmd_args}')

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


# output
#This program is part of the Astrometry.net suite.
#For details, visit http://astrometry.net.
#Git URL https://github.com/dstndstn/astrometry.net
#Revision 0.73, date Thu_Nov_16_08:30:44_2017_-0500.

        rev_str = None

        for l in net_proc.stdout.readlines():
            logging.debug(f'{l.strip()}')
            if l.startswith('Revision'):
                fields = l.split()
                rev_str = fields[1]
                logging.debug(f'rev str-> "{rev_str}"')
                break

        if rev_str is None:
            return None

        # clean up rev_str
        rev_str = ''.join(filter(lambda x: x.isalnum() or x == '.', rev_str))
        logging.debug(f'found astrometrynet local rev_str -> "{rev_str}"')

        try:
            rev = float(rev_str)
        except:
            rev = None

        self.solve_field_revision = rev

        return rev


    def solve_file(self, fname, solve_params, downsample=2, search_rad=10):
        """
        Plate solve the specified file using solve-field

        :param str fname: Filename of the file to be solved.
        :param PlateSolveParameters solve_params: Parameters for plate solver.
        :param int downsample: Downsample factor for image.
        :param float search_rad: Number of degrees to search.

        :returns:
          solved_position (SkyCoord)
             The J2000 sky coordinate of the plate solve match, or None if no
             match was found.
          angle (Angle)
             Position angle of Y axis expressed as East of North.
        """

        # determine installed version of solve-field
        rev = self.probe_solve_field_revision()

# example cmdline
# /usr/bin/solve-field -O --no-plots --no-verify --resort --no-fits2fits --do^Csample 2 -3 310.521 -4 45.3511 -5 10 --config /etc/astrometry.cfg -W /tmp/solution.wcs plate_solve_image.fits

        # remove any solved files
        filename, extension = os.path.splitext(fname)
        solved_filename = filename + '.solved'
        logging.debug(f'{filename} {extension} {solved_filename}')
        if os.path.isfile(solved_filename):
            logging.debug(f'Removing existing solved file {solved_filename}')
            os.remove(solved_filename)

        cmd_line = self.exec_path
        cmd_line += ' -O --no-plots --no-verify --resort'
        cmd_line += f' --downsample {downsample}'
        # this is only needed for rev of 0.67 or earlier
        if rev <= 0.67:
            cmd_line += ' --no-fits2fits'
        cmd_line += f' -3 {solve_params.radec.ra.degree}'
        cmd_line += f' -4 {solve_params.radec.dec.degree}'

        # give guess of pixel scale unless given as 0
        if solve_params.pixel_scale is not None and solve_params.pixel_scale > 0:
            scale = solve_params.pixel_scale
            cmd_line += f' -u arcsecperpix'
            cmd_line += f' -L {0.9*scale} -H {1.1*scale}'

        # search radius - default to 10 if not given
        if search_rad is None:
            search_rad = 10

        cmd_line += f' -5 {search_rad}'

        cmd_line += ' --config /etc/astrometry.cfg'
        cmd_line += ' -W /tmp/solution.wcs'
        cmd_line += ' --crpix-center'

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

        logging.debug(f'cmd_line for astrometry.net local = "{cmd_line}"')
        logging.debug(f'cmd_args for astrometry.net local = "{cmd_args}"')

#/usr/bin/solve-field -O --no-plots --no-verify --resort --no-fits2fits --do^Csample 2 -3 310.521 -4 45.3511 -5 10 --config /etc/astrometry.cfg -W /tmp/solution.wcs plate_solve_image.fits

        with subprocess.Popen(cmd_args,
                                    stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    universal_newlines=True) as net_proc:
#        poll_value = None
#        while True:
#            poll_value = net_proc.poll()
#            if poll_value is not None:
#                break

            for l in net_proc.stdout:
                logging.debug(f'astromentrynetlocal: {l.strip()}')

        # see if solve succeeded
        if os.path.isfile(solved_filename):
            logging.info('Solved file found!')
        else:
            logging.error('No solved file - solve failed!')
            return None

# output
#Field center: (RA,Dec) = (2.101258, 29.091103) deg.
#Field center: (RA H:M:S, Dec D:M:S) = (00:08:24.302, +29:05:27.971).
#Field size: 76.07 x 57.4871 arcminutes
#Field rotation angle: up is 1.12149 degrees E of N

#        for l in net_proc.stdout.readlines():
#            ll = ''.join(filter(lambda x: x.isalnum() or x.isspace() or x == '.', l))
#            print(ll)

        # parse solution.wcs
        from astropy import wcs
        import astropy.io.fits as pyfits

        wcs_hdulist = pyfits.open('/tmp/solution.wcs')
        #print('wcs_hdulist: ', wcs_hdulist[0], vars(wcs_hdulist[0]))
        w = wcs.WCS(wcs_hdulist[0].header)

        #print('wcs.wcs=', wcs)
        #print('vars(wcs.wcs): ',vars(wcs.wcs))
        #wcs.wcs.print_contents()
#        print('CRPIX = ', w.wcs.crpix)
#        print('CD = ', w.wcs.cd)
#        print('pixel scales = ', wcs.utils.proj_plane_pixel_scales(w))

        solved_ra, solved_dec = w.wcs.crval
        logging.info(f'solved_ra solved_dec = {solved_ra} {solved_dec}')
#        solved_scale_x, solved_scale_y = wcs.utils.proj_plane_pixel_scales(w)

        #FIXME just take X scale
#        solved_scale = solved_scale_x

        # convert CD matrix
        cd_1_1 = w.wcs.cd[0][0]
        cd_1_2 = w.wcs.cd[0][1]
        cd_2_1 = w.wcs.cd[1][0]
        cd_2_2 = w.wcs.cd[1][1]

        cdelt1 = math.sqrt(cd_1_1**2+cd_2_1**2)
        cdelt2 = math.sqrt(cd_1_2**2+cd_2_2**2)

        # convention is to set cdelt1 negative if det of CD is negative
#        if cd_1_1*cd_2_2-cd_1_2*cd_2_2 < 0:
#            cdelt1 = -cdelt1
#
#        logging.info(f'cdelt = {cdelt1*3600:5.2f} {cdelt2*3600:5.2f} arcsec/pixel')
#
#        cdel = cdelt1 - cdelt2
#
#        logging.debug(f'cd_1_1 cd_2_1 cd_1_2 cd_2_2 = {cd_1_1} {cd_2_1} {cd_1_2} {cd_2_2})')
#        logging.debug(f'cdelt1 cdelt2 cdel = {cdelt1} {cdelt2} {cdel}')

        # compute angle between North and the positive Y axis of sensor
        # positive is CCW
        crota = math.atan2(cd_2_1, cd_1_1)
        crota_deg = np.rad2deg(crota)
        logging.debug(f'cdelt = {cdelt1*3600:5.2f} {cdelt2*3600:5.2f} arcsec/pixel')
        logging.debug(f'crota/crota_deg = {crota} {crota_deg}')

        #  get roll angle
        roll_angle_deg =  -crota_deg
        logging.info(f'roll_angle_deg = {roll_angle_deg:5.2f}')
        solved_scale = cdelt1*3600
        solved_angle = roll_angle_deg

#        ra_str = None
#        dec_str = None
#        ang_str = None
#        fov_x_str = None
#        for l in net_proc.stdout.readlines():
#            ll = ''.join(filter(lambda x: x.isalnum() or x.isspace() or x == '.', l))
#            print(ll)
#            fields = ll.split()
#            # look for ra/dec in deg first
#            if 'center' in ll and 'deg' in ll:
#                # should look like:
#                # Field center RADec  2.101258 29.091103 deg
#                print(fields)
#                ra_str = fields[3]
#                dec_str = fields[4]
#            elif 'angle' in ll:
#                # should look like:
#                # Field rotation angle up is 1.12149 degrees E of N.
#                ang_str = fields[5]
#            elif 'Field size' in ll:
#                fov_x_str = fields[2]
#
#        logging.info(f'{ra_str} {dec_str} {ang_str}')
#
#        try:
#            solved_ra = float(ra_str)
#            solved_dec = float(dec_str)
#            solved_angle = float(ang_str)
#
#            # fov is given in arcmin so convert to arcsec
#            fov_x = float(fov_x_str)*60.0
#
#            logging.info(f'solved fov = {fov_x} arcsec')
#            if solve_params.width is not None:
#                solved_scale = fov_x / solve_params.width
#                logging.info(f'using given width of {solve_params.width} pixel scale is {solved_scale} arcsec/pix')
#            else:
#                solved_scale = None
#                logging.warning('No width given so pixel scale not computed!')
#
#        except Exception as e:
#            logging.exception('Failed to parse solution')
#            return None
#
#        logging.info(f'{solved_ra} {solved_dec} {solved_angle} {solved_scale}')

        radec = SkyCoord(ra=solved_ra*u.degree, dec=solved_dec*u.degree, frame='fk5', equinox='J2000')

        logging.info(f"AstrometryNetLocal solved coordinates: {radec.to_string('hmsdms', sep=':')}")
        return PlateSolveSolution(radec, pixel_scale=solved_scale,
                                  angle=Angle(solved_angle*u.degree), binning=solve_params.bin_x)



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
