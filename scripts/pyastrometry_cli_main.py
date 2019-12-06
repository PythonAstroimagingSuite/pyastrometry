#!/usr/bin/python
# even on windows this 'tricks' conda into wrapping script so it will
# execute like it would have in bash
import os
import sys
import time
import json
import argparse
import logging
import tempfile
#import subprocess
from datetime import datetime
from configobj import ConfigObj

try:
    # py3
    from urllib.parse import urlparse, urlencode, quote
    from urllib.request import urlopen, Request
    from urllib.error import HTTPError
except ImportError:
    # py2
    from urlparse import urlparse
    from urllib import urlencode, quote
    from urllib2 import urlopen, Request, HTTPError

#from exceptions import Exception
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.application  import MIMEApplication

from email.encoders import encode_noop

import astropy.io.fits as pyfits
from astropy.time import Time
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.coordinates import FK5
from astropy.coordinates import Angle

from pyastroprofile.AstroProfile import AstroProfile

from pyastrobackend.BackendConfig import get_backend_for_os, get_backend, get_backend_choices


#from pyastrobackend.BackendConfig import get_backend_for_os
#
#BACKEND = get_backend_for_os()
#
#if BACKEND == 'ASCOM':
#    from pyastrobackend.ASCOMBackend import DeviceBackend as Backend
#elif BACKEND == 'INDI':
#    from pyastrobackend.INDIBackend import DeviceBackend as Backend
#else:
#    raise Exception(f'Unknown backend {BACKEND}')
#
#if BACKEND == 'ASCOM':
#    from pyastrobackend.MaximDL.Camera import Camera as MaximDL_Camera
#    from pyastrobackend.RPC.Camera import Camera as RPC_Camera
#elif BACKEND == 'INDI':
#    from pyastrobackend.INDIBackend import Camera as INDI_Camera
#else:
#    raise Exception(f'Unknown backend {BACKEND}')

from pyastrometry.Telescope import Telescope

from pyastrometry.PlateSolveSolution import PlateSolveSolution

#if BACKEND == 'ASCOM':
#    from pyastrometry.PlateSolve2 import PlateSolve2
#if BACKEND == 'INDI':
#    from pyastrometry.AstrometryNetLocal import AstrometryNetLocal
#    from pyastrometry.ASTAP import ASTAP

def json2python(data):
    try:
        return json.loads(data)
    except:
        pass
    return None
python2json = json.dumps

class MalformedResponse(Exception):
    pass
class RequestError(Exception):
    pass

class Client(object):
    default_url = 'http://nova.astrometry.net/api/'

    def __init__(self, apiurl=default_url):
        self.session = None
        self.apiurl = apiurl

    def get_url(self, service):
        return self.apiurl + service

    def send_request(self, service, args={}, file_args=None):
        '''
        service: string
        args: dict
        '''
        if self.session is not None:
            args.update({'session':self.session})
        #print('Python:', args)
        json = python2json(args)
        #print('Sending json:', json)
        url = self.get_url(service)
        #print('Sending to URL:', url)

        # If we're sending a file, format a multipart/form-data
        if file_args is not None:
            # Make a custom generator to format it the way we need.
            from io import BytesIO
            try:
                # py3
                from email.generator import BytesGenerator as TheGenerator
            except ImportError:
                # py2
                from email.generator import Generator as TheGenerator

            m1 = MIMEBase('text', 'plain')
            m1.add_header('Content-disposition',
                          'form-data; name="request-json"')

            logging.debug(f"send_request: {json}")  # MSF

            m1.set_payload(json)
            m2 = MIMEApplication(file_args[1], 'octet-stream', encode_noop)
            m2.add_header('Content-disposition',
                          'form-data; name="file"; filename="%s"'%file_args[0])
            mp = MIMEMultipart('form-data', None, [m1, m2])

            class MyGenerator(TheGenerator):
                def __init__(self, fp, root=True):
                    # don't try to use super() here; in py2 Generator is not a
                    # new-style class.  Yuck.
                    TheGenerator.__init__(self, fp, mangle_from_=False,
                                          maxheaderlen=0)
                    self.root = root
                def _write_headers(self, msg):
                    # We don't want to write the top-level headers;
                    # they go into Request(headers) instead.
                    if self.root:
                        return
                    # We need to use \r\n line-terminator, but Generator
                    # doesn't provide the flexibility to override, so we
                    # have to copy-n-paste-n-modify.
                    for h, v in msg.items():
                        self._fp.write(('%s: %s\r\n' % (h, v)).encode())
                    # A blank line always separates headers from body
                    self._fp.write('\r\n'.encode())

                # The _write_multipart method calls "clone" for the
                # subparts.  We hijack that, setting root=False
                def clone(self, fp):
                    return MyGenerator(fp, root=False)

            fp = BytesIO()
            g = MyGenerator(fp)
            g.flatten(mp)
            data = fp.getvalue()
            headers = {'Content-type': mp.get('Content-type')}

        else:
            # Else send x-www-form-encoded
            data = {'request-json': json}
            #print('Sending form data:', data)
            data = urlencode(data)
            data = data.encode('utf-8')
            #print('Sending data:', data)
            headers = {}

        request = Request(url=url, headers=headers, data=data)

        try:
            f = urlopen(request)
            txt = f.read()
            #print('Got json:', txt)
            result = json2python(txt)
            #print('Got result:', result)
            stat = result.get('status')
            #print('Got status:', stat)
            if stat == 'error':
                errstr = result.get('errormessage', '(none)')
                raise RequestError('server error message: ' + errstr)
            return result
        except HTTPError as e:
            logging.error(f'HTTPError {e}')
            txt = e.read()
            open('err.html', 'wb').write(txt)
            logging.error('Wrote error text to err.html')

    def login(self, apikey):
        args = {'apikey' : apikey}
        result = self.send_request('login', args)
        sess = result.get('session')
        logging.info(f'Got session: {sess}')
        if not sess:
            raise RequestError('no session in result')
        self.session = sess

    def _get_upload_args(self, **kwargs):
        args = {}
        for key, default, typ in [('allow_commercial_use', 'd', str),
                                  ('allow_modifications', 'd', str),
                                  ('publicly_visible', 'y', str),
                                  ('scale_units', None, str),
                                  ('scale_type', None, str),
                                  ('scale_lower', None, float),
                                  ('scale_upper', None, float),
                                  ('scale_est', None, float),
                                  ('scale_err', None, float),
                                  ('center_ra', None, float),
                                  ('center_dec', None, float),
                                  ('parity', None, int),
                                  ('radius', None, float),
                                  ('downsample_factor', None, int),
                                  ('tweak_order', None, int),
                                  ('crpix_center', None, bool),
                                  ('x', None, list),
                                  ('y', None, list),
                                  # image_width, image_height
                                 ]:
            if key in kwargs:
                val = kwargs.pop(key)
                val = typ(val)
                args.update({key: val})
            elif default is not None:
                args.update({key: default})
        #print('Upload args:', args)
        return args

    def url_upload(self, url, **kwargs):
        args = dict(url=url)
        args.update(self._get_upload_args(**kwargs))
        result = self.send_request('url_upload', args)
        return result

    def upload(self, fn=None, **kwargs):
        args = self._get_upload_args(**kwargs)
        file_args = None
        if fn is not None:
            try:
                f = open(fn, 'rb')
                file_args = (fn, f.read())
            except IOError:
                logging.error('File %s does not exist' % fn)
                raise
        return self.send_request('upload', args, file_args)

    def submission_images(self, subid):
        result = self.send_request('submission_images', {'subid':subid})
        return result.get('image_ids')

    def myjobs(self):
        result = self.send_request('myjobs/')
        return result['jobs']

    def job_status(self, job_id, justdict=False):
        result = self.send_request('jobs/%s' % job_id)
        if justdict:
            return result
        stat = result.get('status')
        # if stat == 'success':
            # result = self.send_request('jobs/%s/calibration' % job_id)
            # print('Calibration:', result)
            #result = self.send_request('jobs/%s/tags' % job_id)
            #print('Tags:', result)
            #result = self.send_request('jobs/%s/machine_tags' % job_id)
            #print('Machine Tags:', result)
            #result = self.send_request('jobs/%s/objects_in_field' % job_id)
            #print('Objects in field:', result)
            #result = self.send_request('jobs/%s/annotations' % job_id)
            #print('Annotations:', result)
            #result = self.send_request('jobs/%s/info' % job_id)
            #print('Calibration:', result)

        return stat

    def job_calib_result(self, job_id):
        result = self.send_request('jobs/%s/calibration' % job_id)
        #print('Calibration:', result)

        return result

    def sub_status(self, sub_id, justdict=False):
        result = self.send_request('submissions/%s' % sub_id)
        if justdict:
            return result
        return result.get('status')

    def jobs_by_tag(self, tag, exact):
        exact_option = 'exact=yes' if exact else ''
        result = self.send_request(
            'jobs_by_tag?query=%s&%s' % (quote(tag.strip()), exact_option),
            {},
        )
        return result

def read_radec_from_FITS(fname):
    """Read RA/DEC coordinate from a FITS file header

    Parameters
    ----------
    fname - str
        Name of FITS file

    Returns
    -------
    radec : SkyCoord
        RA/DEC read from FITS header - assumes J2000.
    """
    hdulist = pyfits.open(fname)
    prihdr = hdulist[0].header
    hdulist.close()

    try:
        obj_ra_str = prihdr["OBJCTRA"]
    except:
        return None

    try:
        obj_dec_str = prihdr["OBJCTDEC"]
    except:
        return None

    logging.debug(f"read_radec_from_FITS: {obj_ra_str} {obj_dec_str}")

    try:
        radec = SkyCoord(obj_ra_str + ' ' + obj_dec_str, frame='fk5', unit=(u.hourangle, u.deg), equinox='J2000')
    except Exception as err:
        logging.error(f"read_radec_from_file: {err}")
        return None

    return radec

def read_image_info_from_FITS(fname):
    """Read RA/DEC coordinate from a FITS file header

    Parameters
    ----------
    fname - str
        Name of FITS file

    Returns
    -------
    width, height : int
        Width/height of image.
    bining_x, binning_y : int
        Binning along X/Y axis
    """
    try:
        hdulist = pyfits.open(fname)
    except Exception as err:
        logging.error(f"read_image_info_from_FITS: error opening {fname} - {err}")
        return None

    prihdr = None
    try:
        prihdr = hdulist[0].header
    except Exception as err:
        logging.error(f"read_image_info_from_FITS: error opening {fname} - {err}")

    hdulist.close()
    if prihdr is None:
        return None

    keys = ['NAXIS1', 'NAXIS2', 'XBINNING', 'YBINNING']
    retval = ()

    for k in keys:
        try:
            retval = retval + (int(prihdr[k]),)
        except:
            logging.error(f"read_image_info_from_FITS: error reading key {k} from file {fname}")
            return None

    logging.debug(f"read_image_info_from_FITS: {retval}")

    return retval

#def convert_ra_deg_to_hour(ra_deg):
#    hour = int(ra_deg/15.0)
#    frac = (ra_deg - hour*15.0)/15.0
#
#    print("hour", hour)
#    print("frac", frac)
#
#    return hour+frac

def precess_J2000_to_JNOW(pos_J2000):
    """Precess J2000 coordinates to JNOW

    Parameters
    ----------
    pos_J2000 - SkyCoord
        J2000 sky coordinate to precess

    Returns
    -------
    pos_JNOW : SkyCoord
        JNow coordinate
    """
    time_now = Time(datetime.utcnow(), scale='utc')
    return pos_J2000.transform_to(FK5(equinox=Time(time_now.jd, format="jd", scale="utc")))

def precess_JNOW_to_J2000(pos_JNOW):
    """Precess J2000 coordinates to JNOW

    Parameters
    ----------
    pos_JNOW - SkyCoord
        JNow sky coordinate to precess

    Returns
    -------
    pos_J2000 : SkyCoord
        J2000 coordinate
    """
    return pos_JNOW.transform_to(FK5(equinox='J2000'))

class PlateSolveParameters:
    """Contains parameters needed to prime a plate solve engine"""

    def __init__(self):
        """Creates object contains plate solve parameters"""
        self.pixel_scale = None
        self.radec = None
        self.fov_x = None
        self.fov_y = None
        self.width = None
        self.height = None
        self.bin_x = None
        self.bin_y = None

    def __repr__(self):
        retstr = f"radec: {self.radec.to_string('hmsdms', sep=':')} " + \
                 f"fov: {self.fov_x} x {self.fov_y} " + \
                 f"size: {self.width} x {self.height} " + \
                 f"bin:{self.bin_x} x {self.bin_y}"  + \
                 f"pixel_scale: {self.pixel_scale}"

        return retstr


class ProgramSettings:
    """Stores program settings which can be saved persistently"""
    def __init__(self):
        """Set some defaults for program settings"""
        self._config = ConfigObj(unrepr=True, file_error=True, raise_errors=True)
        self._config.filename = self._get_config_filename()

        #self.telescope_driver = None
        #self.camera_driver = None
        #self.pixel_scale_arcsecpx = 1.0

        self.astrometry_timeout = 90
        self.astrometry_downsample_factor = 2
        self.astrometry_apikey = ''
        self.camera_exposure = 5
        self.camera_binning = 2
        self.precise_slew_limit = 600.0
        self.precise_slew_tries = 5
        self.max_allow_sep = 5

        # set some defaults based on OS as to which plate solver is the default
        if os.name == 'nt':
            self.backend = 'ASCOM'
            self.platesolve2_location = "PlateSolve2.exe"
            self.platesolve2_regions = 999
            self.platesolve2_wait_time = 10
        elif os.name == 'posix':
            self.backend = 'INDI'
            self.astrometrynetlocal_location = '/usr/bin/solve-field'
            self.astrometrynetlocal_downsample = 2
            self.astrometrynetlocal_search_rad_deg = 10
            self.ASTAP_location = '/usr/local/bin/astap'
        else:
            raise Exception("Sorry: no implementation for your platform ('%s') available" % os.name)

    # FIXME This will break HORRIBLY unless passed an attribute already
    #       in the ConfigObj dictionary
    #
    def __getattr__(self, attr):
        #logging.info(f'{self.__dict__}')
        if not attr.startswith('_'):
            return self._config[attr]
        else:
            return super().__getattribute__(attr)

    def __setattr__(self, attr, value):
        #logging.info(f'setattr: {attr} {value}')
        if not attr.startswith('_'):
            self._config[attr] = value
        else:
            super().__setattr__(attr, value)

#    def _get_config_dir(self):
#        # by default config file in .config/pyfocusstars directory under home directory
#        homedir = os.path.expanduser("~")
#        return os.path.join(homedir, ".config", "pyastrometry_cli")
    def _get_config_dir(self):
        if os.name == 'nt':
            config_dir = os.path.expandvars('%APPDATA%\pyastrometry_cli')
        elif os.name == 'posix':
            homedir = os.path.expanduser('~')
            config_dir = os.path.join(homedir, '.config', 'pyastrometry_cli')
        else:
            logging.error('ProgramSettings: Unable to determine OS for config_dir loc!')
            config_dir = None
        return config_dir

    def _get_config_filename(self):
        return os.path.join(self._get_config_dir(), 'default.ini')

    def write(self):
        # NOTE will overwrite existing without warning!
        logging.debug(f'Configuration files stored in {self._get_config_dir()}')
#        self.config['pixel_scale_arcsec'] = self.pixel_scale_arcsecpx
#        config['platesolve2_location'] = self.platesolve2_location
#        config['platesolve2_regions'] = self.platesolve2_regions
#        config['platesolve2_wait_time'] = self.platesolve2_wait_time
#        config['astrometry_timeout'] = self.astrometry_timeout

        # check if config directory exists
        if not os.path.isdir(self._get_config_dir()):
            if os.path.exists(self._get_config_dir()):
                logging.error(f'write settings: config dir {self._get_config_dir()}' + \
                              f' already exists and is not a directory!')
                return False
            else:
                logging.debug(f'write settings: creating config dir {self._get_config_dir()}')
                os.mkdir(self._get_config_dir())

        logging.debug(f'{self._config.filename}')
        self._config.write()

    def read(self):
        logging.debug(f'ProgramSettings.read(): filename = {self._get_config_filename()}')
        try:
            config = ConfigObj(self._get_config_filename(), unrepr=True,
                               file_error=True, raise_errors=True)
        except:
            logging.error('Error creating config object in read()', exc_info=True)
            config = None

        if config is None:
            logging.error('failed to read config file!')
            return False

        self._config.merge(config)

        return True

class MyApp:
    def __init__(self):

        # FIXME need to store somewhere else
        self.settings = ProgramSettings()
        self.settings.read()

        logging.debug(f'startup settings: {self.settings}')

        # FIXME This is an ugly section of code
#        self.backend = Backend()
#
#        rc = self.backend.connect()
#        if not rc:
#            logging.error('Failed to connect to backend!')
#            sys.exit(-1)
#
#        self.cam = None
#
#        if BACKEND == 'ASCOM':
#            self.cam = MaximDL_Camera()
#        elif BACKEND == 'INDI':
#            self.cam = INDI_Camera(self.backend)
#        else:
#            logging.error(f'Unknown BACKEND = {BACKEND}!')
#            sys.exit(1)
#
#        # telescope
#        # FIXME Shouldn't have to make separate call for ASCOM!!
#        if BACKEND == 'ASCOM':
#            self.tel = Telescope()
#        elif BACKEND == 'INDI':
#            self.tel = Telescope(self.backend)

#        self.camera_driver = None
#        self.telescope_driver = None

        # init vars
        self.solved_j2000 = None

        self.target_j2000 = None

        self.camera_binning = self.settings.camera_binning

        # platesolve2
        if os.name == 'nt':
            from pyastrometry.PlateSolve2 import PlateSolve2
            self.platesolve2 = PlateSolve2(self.settings.platesolve2_location)

            from pyastrometry.ASTAP import ASTAP
            self.ASTAP = ASTAP(self.settings.astap_location)

        # astrometry.net local
        if os.name == 'posix':
            from pyastrometry.AstrometryNetLocal import AstrometryNetLocal
            from pyastrometry.ASTAP import ASTAP
            self.astrometrynetlocal = AstrometryNetLocal(self.settings.astrometrynetlocal_location)
            self.astrometrynetlocal.probe_solve_field_revision()
            self.ASTAP = ASTAP(self.settings.astap_location)

    def parse_operation(self):
        logging.debug('parse_operation()')
        parser = argparse.ArgumentParser(description='Astromentry CLI',
                                         usage='''pyastrometry_cli <operation> [<args>]

The accepted commands are:
   getpos   Return current RA/DEC of mount
   solvepos     Take an image and solve current position
   solveimage <filename>    Solve position of an image file
   syncpos      Take an image, solve and sync mount
   slew <ra> <dec> Slew to position
   slewsolve  <ra> <dec>  Slew to position and plate solve and slew until within threshold
''')
        parser.add_argument('operation', type=str, help='Operation to perform')
       #parser.add_argument('solver', type=str, help='')

        if len(sys.argv) < 2:
            parser.print_help()
        args = parser.parse_args(sys.argv[1:2])

        return args.operation

    def parse_devices(self):
        logging.debug('parse_devices()')
        parser = argparse.ArgumentParser()
        parser.add_argument('--profile', type=str, help='Name of astro profile')
        parser.add_argument('--backend', type=str, help='Name of device backend')
        parser.add_argument('--mount', type=str, help='Name of mount driver')
        parser.add_argument('--camera', type=str, help='Name of camera driver')
        parser.add_argument('--exposure', type=float, help='Exposure time')
        parser.add_argument('--binning', type=int, help='Camera binning')
        args, unknown = parser.parse_known_args(sys.argv)

        if args.profile is not None:
            logging.info(f'Setting up device using astro profile {args.profile}')
            ap = AstroProfile()
            ap.read(args.profile)
            #equip_profile = EquipmentProfile('astroprofiles/equipment', args.profile)
            #equip_profile.read()
            self.backend_name = ap.equipment.backend.name
            logging.info(f'profile backend = {self.backend_name}')
            self.camera_driver = ap.equipment.camera.driver
            logging.info(f'profile camera driver = {self.camera_driver}')
            self.mount_driver = ap.equipment.mount.driver
            logging.info(f'profile mount driver = {self.mount_driver}')
            binning = ap.settings.platesolve.binning
            if binning is not None:
                self.camera_binning = binning
                logging.info(f'profile binning = {self.camera_binning}')
            solver = ap.settings.platesolve.solver
            if solver is not None:
                self.solver = solver
                logging.info(f'profile solver = {self.solver}')

        if args.backend is not None:
            self.backend_name = args.backend

        if args.camera is not None:
            self.camera_driver = args.camera

        if args.mount is not None:
            self.mount_driver = args.telescope

        if self.backend_name is None:
            logging.error('Must configure backend!')
            sys.exit(1)

        if self.mount_driver is None:
            logging.error('Must configure mount driver!')
            sys.exit(1)

        if self.camera_driver is None:
            logging.error('Must configure camera driver!')
            sys.exit(1)

        if args.exposure is not None:
            logging.debug(f'Set camera exposure to {args.exposure}')
            self.camera_exposure = args.exposure

        if args.binning is not None:
            logging.debug(f'Set camera binning to {args.binning}')
            self.camera_binning = args.binning

        logging.debug(f'Using device backend {self.backend_name}')
        logging.debug(f'Using camera_drver = {self.camera_driver}')
        logging.debug(f'Using mount_driver = {self.mount_driver}')
#        logging.info(f'Using camera_exposure = {self.camera_exposure}')
#        logging.info(f'Using camera_binning = {self.camera_binning}')

    def parse_solve_params(self):
        logging.debug('parse_solve_params')
        parser = argparse.ArgumentParser(description='Solve Parameters',
                                         usage='''
Valid solvers are:
    astrometryonline
    astrometrylocal
    platesolve2''')
        parser.add_argument('--profile', type=str, help='Name of astro profile')
        parser.add_argument('--solver', type=str, help='Solver to use')
        parser.add_argument('--pixelscale', type=float, help='Pixel scale (arcsec/pixel)')
        parser.add_argument('--downsample', type=int, help='Downsampling')
        parser.add_argument('--outfile', type=str, help='Output JSON file with solution')
        parser.add_argument('--force', action='store_true', help='Overwrite output file')
        args, unknown = parser.parse_known_args(sys.argv)

        if args.solver is None:
            if os.name == 'nt':
                self.solver = 'platesolve2'
            elif os.name == 'posix':
                self.solver = 'astrometrylocal'
            else:
                logging.error('No solver specified and no default found')
                sys.exit(1)
        else:
            self.solver = args.solver

        # FIXME This is duplicate from parse_devices() need to unify
        self.pixel_scale_arcsecpx = None
        if args.profile is not None:
            logging.debug(f'Setting up plate solve using astro profile {args.profile}')
            ap = AstroProfile()
            ap.read(args.profile)
            #equip_profile = EquipmentProfile('astroprofiles/equipment', args.profile)
            #equip_profile.read()
            self.pixel_scale_arcsecpx = ap.settings.platesolve.get('pixelscale', None)

        # let command line override
        if args.pixelscale is not None:
            logging.debug(f'Setting pixel scale to {args.pixelscale}')
            self.pixel_scale_arcsecpx = args.pixelscale

        if self.pixel_scale_arcsecpx is None:
            logging.error('Pixel scale not defined on command line or profile!')
            sys.exit(1)

        if args.downsample is not None:
            logging.debug(f'Setting astrometry downsample to {args.downsample}')
            self.settings.astrometry_downsample_factor = args.downsample

        if args.outfile is not None:
            if os.path.isfile(args.outfile):
                if not args.force:
                    logging.error(f'Output file {args.outfile} already exists - please remove before running')
                    sys.exit(1)
                else:
                    logging.debug(f'Removing existing output file {args.outfile}')
                    os.unlink(args.outfile)

        return args.outfile

    def parse_filename(self):
        logging.debug('parse_solve_filename')
        parser = argparse.ArgumentParser()
        parser.add_argument('filename', type=str, help='Filename to solve')
        args, unknown = parser.parse_known_args(sys.argv[2:3])
        return args.filename

    def parse_sync(self):
        logging.debug('parse_sync')
        parser = argparse.ArgumentParser()
        parser.add_argument('--syncmaxsep', type=float, help='Max deviation to allow sync')
        parser.add_argument('--syncforce', action='store_true', help='Force sync no matter deviation')
        args, unknown = parser.parse_known_args(sys.argv)
        if args.syncforce:
            logging.warning('Will force sync no matter how large the separation')
            self.settings.max_allow_sep = 999
        elif args.syncmaxsep is not None:
            logging.debug(f'Setting max_all_sep to {args.syncmaxsep}')
            self.settings.max_allow_sep = args.syncmaxsep

    def parse_slew(self):
        logging.debug('parse_slew')
        parser = argparse.ArgumentParser()
        parser.add_argument('ra', type=str, help='Target RA (J2000)')
        parser.add_argument('dec', type=str, help='Target DEC (J2000)')
        parser.add_argument('--slewthreshold', type=float, help='Cutoff for precise clew (in arcsec)')
        parser.add_argument('--slewtries', type=int, help='Number of tries to reach target')
        args, unknown = parser.parse_known_args(sys.argv[2:4])
        if args.ra is None or args.dec is None:
            logging.error('Must supply target RA and DEC (J2000)!')
            sys.exit(1)

        target_str = args.ra + " "
        target_str += args.dec
        logging.debug(f"target_str = {target_str}")

        try:
            target = SkyCoord(target_str, unit=(u.hourangle, u.deg), frame='fk5', equinox='J2000')
        except ValueError:
            logging.error("Cannot GOTO invalid target POSITION!")
            sys.exit(1)

        logging.debug(f'Settings target_j2000 to {target}')
        self.target_j2000 = target

        if args.slewthreshold is not None:
            logging.debug(f'Setting slew threshold to {args.slewthreshold}')
            self.settings.precise_slew_limit = args.slewthreshold

        if args.slewtries is not None:
            logging.debug(f'Setting # of slew tries to {args.slewtries}')
            self.settings.precise_slew_tries = args.slewtries

    def run(self):
        operation = self.parse_operation()
        logging.debug(f'operation = {operation}')

        outfile = self.parse_solve_params()
        logging.debug(f'Using solver {self.solver}')
        needdevs = operation in ['solvepos', 'syncpos', 'slewsolve', 'getpos', 'slew']
        if needdevs:
            self.parse_devices()

            logging.debug(f'self.backend_name = {self.backend_name}')
            rc = self.connect_backend()
            if not rc:
                logging.error(f'Could not connec to backend {self.backend_name}!')
                sys.exit(1)
            else:
                logging.debug(f'Backend {self.backend_name} connected')

            logging.debug(f'camera/mount = {self.camera_driver} {self.mount_driver}')

            rc = self.connect_mount()
            if not rc:
                logging.error(f'Could not connec to mount {self.mount_driver}!')
                sys.exit(1)
            else:
                logging.debug(f'{self.mount_driver} connected')

            if operation not in ['getpos', 'slew']:
                rc = self.connect_camera()
                if not rc:
                    logging.error(f'Could not connect to camera {self.camera_driver}!')
                    sys.exit(1)
                else:
                    logging.debug(f'{self.camera_driver} connected')

        if operation == 'solvepos' or operation == 'syncpos':
            logging.debug(f'operation {operation}')
            self.run_solve_image()
            if self.solved_j2000 is not None:
                logging.info('Plate solve suceeded')
                s = self.json_print_plate_solution(self.solved_j2000)
                logging.info(f'{s}')

                if outfile is not None:
                    logging.info(f'Writing solution to file {outfile}')
                    f = open(outfile, 'w')
                    s = self.json_print_plate_solution(self.solved_j2000)
                    f.write(s + '\n')
                    f.close()

                if operation == 'syncpos':
                    self.parse_sync()
                    logging.info('Syncing position')
                    self.sync_pos()
        elif operation == 'solveimage':
            logging.debug('operation solveimage')
            fname = self.parse_filename()
            logging.debug(f'Solving file {fname}')
            if fname is None:
                logging.error(f'Need filename of image to solve')
                sys.exit(1)
            self.run_solve_file(fname)
            if self.solved_j2000 is not None:
                logging.info('Plate solve suceeded')
                s = self.json_print_plate_solution(self.solved_j2000)
                logging.info(f'{s}')
        elif operation == 'slewsolve':
            logging.debug('operation slewsolve')
            self.target_j2000 = None
            self.parse_sync()
            self.parse_slew()
            self.target_precise_goto()
        elif operation == 'getpos':
            logging.debug('operation getpos')
            pos = self.tel.get_position_j2000()
            # sys.stdout.write('Position read from mount:\n')
            # s =  json.dumps({
                # 'ra2000' : pos.ra.to_string(u.hour, sep=":", pad=True),
                # 'dec2000' : pos.dec.to_string(alwayssign=True, sep=":", pad=True),
                # })
            # sys.stdout.write(s + '\n')
            logging.info('Position read from mount:')
            s =  json.dumps({
                             'ra2000' : pos.ra.to_string(u.hour, sep=":", pad=True),
                             'dec2000' : pos.dec.to_string(alwayssign=True, sep=":", pad=True),
                           })
            logging.info(f'{s}')

            if outfile is not None:
                logging.info(f'Writing solution to file {outfile}')
                f = open(outfile, 'w')
                f.write(s + '\n')
                f.close()
        elif operation == 'slew':
            logging.debug('operation slew')
            self.parse_slew()
            self.target_goto()
        else:
            logging.error(f'Unknown operation {operation}!')
            sys.exit(1)

        logging.info('Operation complete - exiting')
        self.backend.disconnect()
        self.settings.write()
        sys.exit(0)

    def connect_backend(self):
#        if self.backend_name == 'ASCOM':
#            from pyastrobackend.ASCOMBackend import DeviceBackend as Backend
#        elif self.backend_name == 'RPC':
#            from pyastrobackend.RPCBackend import DeviceBackend as Backend
#        elif self.backend_name == 'INDI':
#            from pyastrobackend.INDIBackend import DeviceBackend as Backend
#        else:
#            raise Exception(f'Unknown backend {self.backend_name} - choose ASCOM/RPC/INDI')
#
#        logging.info(f'Connecting to backend {self.backend_name}')
#        self.backend = Backend()
#        return self.backend.connect()

        self.backend = get_backend(self.backend_name)
        return self.backend.connect()

    def connect_mount(self):
#        if self.backend_name == 'ASCOM':
#            from pyastrobackend.ASCOM.Mount import Mount as MountClass
#        elif self.backend_name == 'RPC':
#            from pyastrobackend.RPC.Mount import Mount as MountClass
#        elif self.backend_name == 'INDI':
#            from pyastrobackend.INDIBackend import Mount as MountClass
#        else:
#            raise Exception(f'Unknown backend {self.backend_name} - choose ASCOM/RPC/INDI')

        # find class of mount type and make a new class including extra functionality
        # create Telescope class on the fly
        mount_dev = self.backend.newMount()
        TelescopeClass = type('Telescope', (Telescope, type(mount_dev)), {})
        self.tel = TelescopeClass(self.backend)
        return self.tel.connect_to_telescope(self.mount_driver)

    def connect_camera(self):
        logging.debug(f'connect_camera: self.camera_driver = {self.camera_driver}')
#        if self.backend_name == 'ASCOM':
#            if self.camera_driver == 'MaximDL':
#                from pyastrobackend.MaximDL.Camera import Camera as MaximDL_Camera
#                logging.debug(f'Loading MaximDL for camera')
#                self.cam = MaximDL_Camera()
#            else:
#                raise Exception(f'connect_camera(): unknown camera driver {self.camera_driver}')
#        elif self.backend_name == 'RPC':
#                from pyastrobackend.RPC.Camera import Camera as RPC_Camera
#                logging.debug(f'Loading RPC for camera')
#                self.cam = RPC_Camera()
#        elif self.backend_name == 'INDI':
#            from pyastrobackend.INDIBackend import Camera as INDI_Camera
#            logging.debug(f'Loading INDI for camera')
#            self.cam = INDI_Camera(self.backend)

        self.cam = self.backend.newCamera()

        rc = self.cam.connect(self.camera_driver)

        logging.debug(f'connect returned {rc}')
        return rc

    def json_print_plate_solution(self, sol):
        return json.dumps({
                        'ra2000' : sol.radec.ra.to_string(u.hour, sep=":", pad=True),
                        'dec2000' : sol.radec.dec.to_string(alwayssign=True, sep=":", pad=True),
                        'angle' : sol.angle.degree,
                        'pixelscale' : sol.pixel_scale,
                        'binning' : sol.binning
                        })

    def sync_pos(self):
        if self.solved_j2000 is None:
            logging.error('Cannot SYNC no solved POSITION!')
            return

        logging.debug(f'sync_pos(): J2000 pos is ' \
                      f'{self.solved_j2000.radec.ra.to_string(u.hour, sep=":", pad=True)} ' \
                      f'{self.solved_j2000.radec.dec.to_string(alwayssign=True, sep=":", pad=True)}')

        # convert to jnow
        solved_jnow = precess_J2000_to_JNOW(self.solved_j2000.radec)

        logging.debug(f'sync_pos(): JNow pos is ' \
                      f'{solved_jnow.ra.to_string(u.hour, sep=":", pad=True)} ' \
                      f'{solved_jnow.dec.to_string(alwayssign=True, sep=":", pad=True)}')

        # TEST force it to be too far away
#        offpos = solved_jnow
#        offpos.dec.degree = offpos.dec.degree - 10
#        self.tel.sync(offpos)

        sep = self.solved_j2000.radec.separation(self.tel.get_position_j2000()).degree
        logging.info(f'Sync pos is {sep} degrees from current pos')

        # check if its WAY OFF
        if sep > self.settings.max_allow_sep:
            logging.error(f'Sync pos is more than {self.settings.max_allow_sep} degrees off - skipping sync')
            # should this raise an error?  Something like precise slew will never
            # finish if sync is skipped+
        else:
            if not self.tel.sync(solved_jnow):
                logging.error('Error occurred syncing mount!')
                sys.exit(1)

    def target_precise_goto(self):
        target = self.target_j2000
        if target is None:
            logging.error('target_precise_goto(): target_j2000 is None!')
            sys.exit(1)

        logging.info('Slewing to target initially!')
        self.target_goto()

        ntries = 0
        while ntries < self.settings.precise_slew_tries:
            solve_tries = 0
            max_solve_tries = 3
            curpos_j2000 = None
            while solve_tries < max_solve_tries:
                logging.info('Precise slew - solving current position '
                            f'try {solve_tries+1} of {max_solve_tries}.')

                curpos_j2000 = self.run_solve_image()

                if curpos_j2000 is None:
                    solve_tries += 1
                    logging.error('Unable to solve current position on '
                                  f'try {solve_tries} of {max_solve_tries}.')
                    continue
                else:
                    logging.info('Precise slew complete')
                    logging.info(f'Solved position is (J2000) '
                                 f'{curpos_j2000.radec.to_string("hmsdms", sep=":")}')
                    break

            if curpos_j2000 is None:
               logging.error('Precise slew failed - unable to solve current '
                             f'position after {max_solve_tries} tries.')
               return False

            self.solved_j2000 = curpos_j2000
            sep = self.solved_j2000.radec.separation(target).degree
            logging.info(f'Distance from target is {sep}')

            # if too far ask before making correction
            # slew limit is in arcseconds so convert
            if sep < self.settings.precise_slew_limit/3600.0:
                logging.info(f'Sep {sep} < threshold {self.settings.precise_slew_limit/3600.0} so quitting')
                return True
#            elif sep > self.settings.max_allow_sep:
#                logging.error(f'Error in position is {sep:6.2f} degrees > limit of {self.settings.max_allow_sep}')
#                return

            # sync
            self.sync_pos()

            time.sleep(1) # just to let things happen

            # slew
            self.target_goto()

        logging.warning('fDid not reach precise slew threshold after {self.settings.precise_slew_tries}!')
        return False

    def run_solve_file(self, fname):
        self.solved_j2000 = self.plate_solve_file(fname)

    def run_solve_image(self):
        logging.info(f'Taking {self.settings.camera_exposure} second image')

        if not self.setup_ccd_frame_binning():
            logging.error('run_solve_image: Unable to setup camera!')
            return

        with tempfile.TemporaryDirectory() as tmpdirname:

            #ff = os.path.join(os.getcwd(), "plate_solve_image.fits")
            ff = os.path.join(tmpdirname, 'plate_solve_image.fits')

            focus_expos = self.settings.camera_exposure

            # reset frame to full sensor
            self.cam.set_binning(1, 1)
            width, height = self.cam.get_size()
            self.cam.set_frame(0, 0, width, height)
            logging.debug(f'setting binning to {self.camera_binning}')
            self.cam.set_binning(self.camera_binning, self.camera_binning)
            self.cam.start_exposure(focus_expos)

            # give things time to happen (?) I get Maxim not ready errors so slowing it down
            #time.sleep(0.25)

            elapsed = 0
            while not self.cam.check_exposure():
                logging.debug(f'exposure elapsed = {elapsed} of {focus_expos}')
                time.sleep(0.5)
                elapsed += 0.5
                if elapsed > focus_expos:
                    elapsed = focus_expos

            # give it some time seems like Maxim isnt ready if we hit it too fast
            #time.sleep(0.5)

            logging.info(f'Saving image to {ff}')
            if os.name == 'posix':
                # FIXME need better way to handle saving image to file!
                image_data = self.cam.get_image_data()
                # this is an hdulist
                image_data.writeto(ff, overwrite=True)
            else:
                self.cam.save_image_data(ff)

            self.solved_j2000 = self.plate_solve_file(ff)

        return self.solved_j2000

    def setup_ccd_frame_binning(self):
        # set camera dimensions to full frame and 1x1 binning
        result = self.cam.get_size()
        if not result:
            return False

        (maxx, maxy) = result
        logging.debug("Sensor size is %d x %d", maxx, maxy)

        width = maxx
        height = maxy

        self.cam.set_frame(0, 0, width, height)

        self.cam.set_binning(self.camera_binning, self.camera_binning)

        logging.debug("CCD size: %d x %d ", width, height)
        logging.debug("CCD bin : %d x %d ", self.camera_binning, self.camera_binning)

        return True

    def plate_solve_file(self, fname):
        """Solve file using user selected method

        Parameter
        ---------
        fname : str
            Filename of image to be solved.

        Returns
        -------
        pos_j2000 : PlateSolveSolution
            Solution to plate solve or None if it failed.
        """
        if self.solver == 'astrometryonline':
            return self.plate_solve_file_astrometry(fname)
        # FIXME This is ugly overloading platesolve2 radio button!
        elif self.solver == 'astrometrylocal':
            return self.plate_solve_file_astromentrynetlocal(fname)
        elif self.solver == 'platesolve2':
            return self.plate_solve_file_platesolve2(fname)
        elif self.solver == 'astap':
            return self.plate_solve_file_ASTAP(fname)
        else:
            logging.error('plate_solve_file: Unknown solver selected!!')
            return None

    def plate_solve_file_platesolve2(self, fname):
        logging.info('Solving with PlateSolve2...')

        radec_pos = read_radec_from_FITS(fname)
        img_info = read_image_info_from_FITS(fname)

        logging.debug(f'{img_info}')

        if radec_pos is None or img_info is None:
            logging.error(f'plate_solve_file_platesolve2: error reading radec from FITS file {radec_pos} {img_info}')
            return None

        (img_width, img_height, img_binx, img_biny) = img_info

        logging.info('Starting PlateSolve2')

        # convert fov from arcsec to degrees
        solve_params = PlateSolveParameters()
        fov_x = self.pixel_scale_arcsecpx*img_width*img_binx/3600.0*u.deg
        fov_y = self.pixel_scale_arcsecpx*img_height*img_biny/3600.0*u.deg
        solve_params.fov_x = Angle(fov_x)
        solve_params.fov_y = Angle(fov_y)
        solve_params.radec = radec_pos
        solve_params.width = img_width
        solve_params.height = img_height
        solve_params.bin_x = img_binx
        solve_params.bin_y = img_biny

        logging.debug(f'plate_solve_file_platesolve2: solve_parms = {solve_params}')

        solved_j2000 = self.platesolve2.solve_file(fname, solve_params,
                                                   nfields=self.settings.platesolve2_regions)

        if solved_j2000 is None:
            logging.error('Plate solve failed!')
            return None

        logging.info('Plate solve succeeded')
        return solved_j2000

    def plate_solve_file_ASTAP(self, fname):
        logging.info('Solving with ASTAP...')

        radec_pos = read_radec_from_FITS(fname)
        img_info = read_image_info_from_FITS(fname)

        logging.debug(f'{img_info}')

        if radec_pos is None or img_info is None:
            logging.error(f'plate_solve_file_AASTAP: error reading radec from FITS file {radec_pos} {img_info}')
            return None

        (img_width, img_height, img_binx, img_biny) = img_info

        logging.info('Starting ASTAP')

        # convert fov from arcsec to degrees
        solve_params = PlateSolveParameters()
        fov_x = self.pixel_scale_arcsecpx*img_width*img_binx/3600.0*u.deg
        fov_y = self.pixel_scale_arcsecpx*img_height*img_biny/3600.0*u.deg
        solve_params.fov_x = Angle(fov_x)
        solve_params.fov_y = Angle(fov_y)
        solve_params.radec = radec_pos
        solve_params.width = img_width
        solve_params.height = img_height
        solve_params.bin_x = img_binx
        solve_params.bin_y = img_biny

        logging.debug(f'plate_solve_file_ASTAP: solve_parms = {solve_params}')

        solved_j2000 = self.ASTAP.solve_file(fname, solve_params,
                                                   )
        if solved_j2000 is None:
            logging.error('Plate solve failed!')
            return None

        logging.info('Plate solve succeeded')
        return solved_j2000

    def plate_solve_file_astromentrynetlocal(self, fname):
        logging.info('Solving with astrometry.net locally...')

        radec_pos = read_radec_from_FITS(fname)
        img_info = read_image_info_from_FITS(fname)

        logging.debug(f'{img_info}')

        if radec_pos is None or img_info is None:
            logging.error(f'plate_solve_file_astromentrynetlocal: error reading radec from FITS file {radec_pos} {img_info}')
            return None

        (img_width, img_height, img_binx, img_biny) = img_info

        logging.info('Starting solve-field')

        # convert fov from arcsec to degrees
        solve_params = PlateSolveParameters()
        fov_x = self.pixel_scale_arcsecpx*img_width*img_binx/3600.0*u.deg
        fov_y = self.pixel_scale_arcsecpx*img_height*img_biny/3600.0*u.deg
        solve_params.pixel_scale = self.pixel_scale_arcsecpx*img_binx
        solve_params.fov_x = Angle(fov_x)
        solve_params.fov_y = Angle(fov_y)
        solve_params.radec = radec_pos
        solve_params.width = img_width
        solve_params.height = img_height
        solve_params.bin_x = img_binx
        solve_params.bin_y = img_biny

        down_val = self.settings.astrometrynetlocal_downsample

        logging.debug(f'plate_solve_file_astromentrynetlocal: solve_parms = {solve_params}')

        solved_j2000 = self.astrometrynetlocal.solve_file(fname, solve_params,
                                                          downsample=down_val,
                                                          search_rad=self.settings.astrometrynetlocal_search_rad_deg)

        if solved_j2000 is None:
            logging.error('Plate solve failed!')
            return None

        logging.info('Plate solve succeeded')
        return solved_j2000

    def plate_solve_file_astrometry(self, fname):

        # connect
        # FIXME this might leak since we create it each plate solve attempt?
        self.astroclient = Client()

        logging.info('Logging into astrometry.net...')

        try:
            self.astroclient.login(self.settings.astrometry_apikey)
        except RequestError as e:
            logging.error(f'Failed to login to astromentry.net -> {e}')
            return None

        time_start = time.time()
        timeout = self.settings.astrometry_timeout

#        timeout = 120  # timeout in seconds

        logging.info('Uploading image to astrometry.net...')

        kwargs = {}
        kwargs['scale_units'] = 'arcsecperpix'
        kwargs['scale_est'] = self.pixel_scale_arcsecpx

        # if image already binned lets skip having astrometry.net downsample
        downsample = self.settings.astrometry_downsample_factor
        img_info = read_image_info_from_FITS(fname)
        if img_info is None:
            logging.warning('plate_solve_file_astrometry: couldnt read image info!')
        else:
            (_, _, binx, biny) = img_info
            if binx != 1 and biny != 1:
                logging.info('plate_solve_file_astrometry: overriding downsample to 1')
                downsample = 1

        kwargs['downsample_factor'] = downsample

        upres = self.astroclient.upload(fname, **kwargs)
        logging.info(f'upload result = {upres}')

        if upres['status'] != 'success':
            logging.error('upload failed!')
            return None

        logging.info('Upload successful')

        sub_id = upres['subid']

        loop_count = 0
        if sub_id is not None:
            while True:
                msgstr = "Checking job status"
                for i in range(0, loop_count % 4):
                    msgstr = msgstr + '.'
                if (loop_count % 5) == 0:
                    logging.debug(msgstr)

                if (loop_count % 10) == 0:
                    stat = self.astroclient.sub_status(sub_id, justdict=True)
    #                print('Got sub status:', stat)
                    jobs = stat.get('jobs', [])
                    if len(jobs):
                        for j in jobs:
                            if j is not None:
                                break
                        if j is not None:
                            logging.info(f'Selecting job id {j}')
                            solved_id = j
                            break

                loop_count += 1
                if loop_count > 30:
                    loop_count = 0

                if time.time() - time_start > timeout:
                    logging.error('astrometry.net solve timeout!')
                    return None

                time.sleep(0.5)

        logging.info(f'Job started - id = {solved_id}')

        while True:
            job_stat = self.astroclient.job_status(solved_id)

            if job_stat == 'success':
                break

            if time.time() - time_start > timeout:
                logging.error('astrometry.net solve timeout!')
                return None

            time.sleep(5)

        final = self.astroclient.job_status(solved_id)

#        print("final job status =", final)

        if final != 'success':
            logging.error("Plate solve failed!")
            logging.error(final)
            return None

        final_calib = self.astroclient.job_calib_result(solved_id)
        logging.info(f'final_calib = {final_calib}')

        logging.info(f'Plate solve succeeded')

        radec = SkyCoord(ra=final_calib['ra']*u.degree, dec=final_calib['dec']*u.degree, frame='fk5', equinox='J2000')

        _, _, binx, _ = img_info
        return PlateSolveSolution(radec, pixel_scale=final_calib['pixscale'],
                                  angle=Angle(final_calib['orientation']*u.deg),
                                  binning = binx)

    def target_goto(self):
        target = self.target_j2000

        if target is None:
            logging.error('target_goto(): No target specified!')
            sys.exit(1)

        self.target_j2000 = target

        #logging.info(f"target = {target}")
        logging.debug(f'target_goto()): Target J2000 ' \
                      f'{target.ra.to_string(u.hour, sep=":", pad=True)} ' \
                      f'{target.dec.to_string(alwayssign=True, sep=":", pad=True)}')

        target_jnow = precess_J2000_to_JNOW(target)
        logging.debug(f'target_goto()): Target JNOW ' \
                      f'{target_jnow.ra.to_string(u.hour, sep=":", pad=True)} ' \
                      f'{target_jnow.dec.to_string(alwayssign=True, sep=":", pad=True)}')

        self.tel.goto(target_jnow)

        logging.info("Slew started!")

        while True:
            logging.debug(f"Slewing = {self.tel.is_slewing()}")
            if not self.tel.is_slewing():
                logging.info("Slew done!")
                break
            time.sleep(1)


if __name__ == '__main__':
    # FIXME assumes tz is set properly in system?
    now = datetime.now()
    logfilename = 'pyastrometry_cli-' + now.strftime('%Y%m%d%H%M%S') + '.log'

#    FORMAT = '%(asctime)s %(levelname)-8s %(message)s'
    #FORMAT = '[%(filename)20s:%(lineno)3s - %(funcName)20s() ] %(levelname)-8s %(message)s'
    FORMAT = '%(asctime)s [%(filename)20s:%(lineno)3s - %(funcName)20s() ] %(levelname)-8s %(message)s'

    logging.basicConfig(filename=logfilename,
                        filemode='a',
                        level=logging.DEBUG,
                        format=FORMAT,
                        datefmt='%Y-%m-%d %H:%M:%S')

    # add to screen as well
    LOG = logging.getLogger()
    #FORMAT_CONSOLE = '%(asctime)s %(levelname)-8s %(message)s'
    FORMAT_CONSOLE = '[%(filename)20s:%(lineno)3s - %(funcName)20s() ] %(levelname)-8s %(message)s'
    #FORMAT_CONSOLE = '[%(pathname)s %(module)s %(filename)20s:%(lineno)3s - %(funcName)20s() ] %(levelname)-8s %(message)s'


    formatter = logging.Formatter(FORMAT_CONSOLE)
    CH = logging.StreamHandler()
    CH.setLevel(logging.INFO)
    CH.setFormatter(formatter)
    LOG.addHandler(CH)

    logging.info(f'pyastrometry_cli starting')
    app = MyApp()
    app.run()




