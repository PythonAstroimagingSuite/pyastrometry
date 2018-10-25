#!/usr/bin/python
# even on windows this 'tricks' conda into wrapping script so it will
# execute like it would have in bash
import os
import sys
import time
import json
import argparse
import logging
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

from PyQt5 import QtCore, QtWidgets

#from pyastrometry.DeviceBackendASCOM import DeviceBackendASCOM as Backend

# FIXME This is confusing to call it Telescope when rest of
# drivers I have call it Mount

from pyastroimageview.BackendConfig import get_backend_for_os

BACKEND = get_backend_for_os()

from pyastrobackend.RPC.Camera import Camera as RPC_Camera

if BACKEND == 'ASCOM':
    import pyastrobackend.ASCOMBackend.DeviceBackend as Backend
elif BACKEND == 'INDI':
    from pyastrobackend.INDIBackend import DeviceBackend as Backend
else:
    raise Exception(f'Unknown backend {BACKEND} - choose ASCOM or INDI in BackendConfig.py')

if BACKEND == 'ASCOM':
    from pyastrobackend.MaximDL.Camera import Camera as MaximDL_Camera
elif BACKEND == 'INDI':
    from pyastrobackend.INDIBackend import Camera as INDI_Camera
else:
    raise Exception(f'Unknown backend {BACKEND} - choose ASCOM or INDI in BackendConfig.py')

from pyastrometry.Telescope import Telescope


from pyastrometry.PlateSolveSolution import PlateSolveSolution
if BACKEND == 'ASCOM':
    from pyastrometry.PlateSolve2 import PlateSolve2
if BACKEND == 'INDI':
    from pyastrometry.AstrometryNetLocal import AstrometryNetLocal
from pyastrometry.uic.pyastrometry_uic import Ui_MainWindow
from pyastrometry.uic.pyastrometry_settings_uic import Ui_Dialog as Ui_SettingsDialog

# FIXME Need better VERSION system
# this has to match yaml
import importlib

# see if we injected a version at conda build time
if importlib.util.find_spec('pyastrometry.build_version'):
    from pyastrometry.build_version import VERSION
else:
    VERSION='UNKNOWN'


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

            logging.info(f"send_request: {json}")  # MSF

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
            print('HTTPError', e)
            txt = e.read()
            open('err.html', 'wb').write(txt)
            print('Wrote error text to err.html')

    def login(self, apikey):
        args = {'apikey' : apikey}
        result = self.send_request('login', args)
        sess = result.get('session')
        print('Got session:', sess)
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
                print('File %s does not exist' % fn)
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
        print('Calibration:', result)

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

    logging.info(f"read_radec_from_FITS: {obj_ra_str} {obj_dec_str}")

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

    logging.info(f"read_image_info_from_FITS: {retval}")

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

def parse_command_line():
    """Parses comand line

    Parameters
    ----------
    None

    Returns
    -------
    args : argparse.parse_args() return value
        argparse.parse_args() return value
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--telescope', type=str, help="Name of ASCOM driver to use for telescope")

    args = parser.parse_args()

    return args

#class FocusProgressDialog:
#    def __init__(self, title_text=None, label_text="", button_text="Cancel", minval=0, maxval=100):
#        self.run_focus_dlg = QtWidgets.QProgressDialog(label_text, button_text, minval, maxval)
#        self.run_focus_dlg.setWindowModality(QtCore.Qt.WindowModal)
#        self.setValues(title_text, label_text, button_text, minval, maxval)
#        self.run_focus_dlg.show()
#
#    def setValues(self, title_text=None, label_text=None, button_text=None, minval=None, maxval=None):
#        if title_text is not None:
#            self.run_focus_dlg.setWindowTitle(title_text)
#        if label_text is not None:
#            self.run_focus_dlg.setLabelText(label_text)
#        if button_text is not None:
#            self.run_focus_dlg.setCancelButtonText(button_text)
#        if minval is not None:
#            self.run_focus_dlg.setMinimum(minval)
#        if maxval is not None:
#            self.run_focus_dlg.setMaximum(maxval)
#
#    def updateFocusDialog(self, val, label_text):
#        self.run_focus_dlg.setLabelText(label_text)
#        self.run_focus_dlg.setValue(val)
#
#    def cancelFocusDialog(self):
#        self.run_focus_dlg.cancel()


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

#    def set_fov(self, fov_x, fov_y):
#        """Set the fov specification for plate solver.
#
#        Parameters
#        ----------
#
#        fov_x : Angle
#            Field of view of image along X axis
#        fov_y : Angle
#            Field of view of image along Y axis
#        """
#        self.fov_x = fov_x
#        self.fov_y = fov_y
#
#    def set_pixel_scale(self, scale):
#        """Set the pixel scale specification for plate solver.
#
#        Parameters
#        ----------
#        pixel_scale : float
#            Pixel scale of image in arc-seconds/pixel
#        """
#        self.pixel_scale = scale
#
#    def set_radec(self, radec):
#        """Set the center RA/DEC estimate for plate solver.
#
#        Parameters
#        ----------
#        pixel_scale : float
#            Pixel scale of image in arc-seconds/pixel
#        """
#        self.radec = radec
#
#    def __str__(self):
#        retstr = f"radec: {self.radec.to_string('hmsdms', sep=':')} " + \
#                 f"fov: {self.fov_x} x {self.fov_y} " + \
#                 f"pixel_scale: {self.pixel_scale}"
#
#        return retstr



class ProgramSettings:
    """Stores program settings which can be saved persistently"""
    def __init__(self):
        """Set some defaults for program settings"""
        self._config = ConfigObj(unrepr=True, file_error=True, raise_errors=True)
        self._config.filename = self._get_config_filename()

        self.telescope_driver = None
        self.camera_driver = None
        self.pixel_scale_arcsecpx = 1.0

        self.astrometry_timeout = 90
        self.astrometry_downsample_factor = 2
        self.astrometry_apikey = ''
        self.camera_exposure = 5
        self.camera_binning = 2
        self.precise_slew_limit = 600.0

        if BACKEND == 'ASCOM':
            self.platesolve2_location = "PlateSolve2.exe"
            self.platesolve2_regions = 999
            self.platesolve2_wait_time = 10
        elif BACKEND == 'INDI':
            self.astrometrynetlocal_location = '/usr/bin/solve-field'
            self.astrometrynetlocal_search_rad_deg = 10

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

    def _get_config_dir(self):
        # by default config file in .config/pyfocusstars directory under home directory
        homedir = os.path.expanduser("~")
        return os.path.join(homedir, ".config", "pyastrometry")

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
                logging.info('write settings: creating config dir {self._get_config_dir()}')
                os.mkdir(self._get_config_dir())

        logging.info(f'{self._config.filename}')
        self._config.write()

    def read(self):
        try:
            config = ConfigObj(self._get_config_filename(), unrepr=True,
                               file_error=True, raise_errors=True)
        except:
            config = None

        if config is None:
            logging.error('failed to read config file!')
            return False

        self._config.merge(config)
        return True

class YesNoDialog:
    def __init__(self, info_text=''):
        self.yesno = QtWidgets.QMessageBox()
        self.yesno.setIcon(QtWidgets.QMessageBox.Question)
        self.yesno.setInformativeText(info_text)
        self.yesno.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)

    def exec(self):
        return self.yesno.exec() == QtWidgets.QMessageBox.Yes

class CriticalDialog:
    def __init__(self, error_text=''):
        self.err = QtWidgets.QMessageBox()
        self.err.setIcon(QtWidgets.QMessageBox.Critical)
        self.err.setInformativeText(error_text)
        self.err.setStandardButtons(QtWidgets.QMessageBox.Ok)

    def exec(self):
        self.err.exec()

class MyApp(QtWidgets.QMainWindow):
    def __init__(self, app, args):

        super().__init__()

        # FIXME need to store somewhere else
        self.settings = ProgramSettings()
        self.settings.read()

        logging.info(f'startup settings: {self.settings}')

        self.app = app
        self.args = args

        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        # 'system' option just means use the 'default for the
        # platform.  Maxim/DL for Windows/ASCOM and INDI for Linux
        if BACKEND == 'INDI':
            self.ui.camera_driver_system.setText('INDI')
        elif BACKEND == 'ASCOM':
             self.ui.camera_driver_system.setText('Maxim/DL')

        self.ui.telescope_driver_select.pressed.connect(self.select_telescope)
        self.ui.telescope_driver_connect.pressed.connect(self.connect_telescope)

        # FIXME This is an ugly section of code
        self.backend = Backend()

        rc = self.backend.connect()
        if not rc:
            logging.error('Failed to connect to backend!')
            sys.exit(-1)

        logging.info(f'Configured camera driver is {self.settings.camera_driver}')

        self.cam = None
        if self.settings.camera_driver == 'RPC':
            self.ui.camera_driver_rpc.setChecked(True)
            self.cam = RPC_Camera()
        else:
            if BACKEND == 'ASCOM':
                if self.settings.camera_driver is None:
                    logging.warning('camera driver not set!  Defaulting to MaximDL')
                    self.settings.camera_driver = 'MaximDL'

                if self.settings.camera_driver == 'MaximDL':
                    self.ui.camera_driver_system.setChecked(True)
                    self.cam = MaximDL_Camera()

                self.set_enable_INDI_camera_controls(False)
            elif BACKEND == 'INDI':
                if self.settings.camera_driver is None:
                    logging.warning('camera driver not set!  Defaulting to INDI')
                    self.settings.camera_driver = 'INDICamera'

                if self.settings.camera_driver.startswith('INDICamera'):
                    # We store the actual driver like this:
                    #
                    #  'INDICamera:<driver name>
                    #
                    # so now pull off driver
                    if ':' in self.settings.camera_driver:
                        indi_driver = self.settings.camera_driver.split(':')[1]
                        self.ui.camera_driver_indi_driver_label.setText(indi_driver)
                    self.ui.camera_driver_system.setChecked(True)
                    self.cam = INDI_Camera(self.backend)

                self.ui.camera_driver_indi_select.pressed.connect(self.select_indi_camera)

                self.set_enable_INDI_camera_controls(True)

        if self.cam is None:
            logging.error(f'Unknown camera driver in config file {self.settings.camera_driver}')
            logging.error('Please correct the config file and rerun.')
            sys.exit(-1)

        self.ui.camera_driver_connect.pressed.connect(self.connect_camera)

        self.setWindowTitle('pyastrometry v' + VERSION)

        # telescope
        self.tel = Telescope(self.backend)

        self.ui.telescope_driver_label.setText(self.settings.telescope_driver)

        self.ui.solve_file_button.clicked.connect(self.solve_file_cb)
        self.ui.sync_pos_button.clicked.connect(self.sync_pos_cb)
        self.ui.solve_image_button.clicked.connect(self.solve_image_cb)

        self.ui.target_use_solved_button.clicked.connect(self.target_use_solved_cb)
        self.ui.target_goto_button.clicked.connect(self.target_goto_cb)
        self.ui.target_precise_goto_button.clicked.connect(self.target_precise_goto_cb)

        self.ui.plate_solve_setup_button.clicked.connect(self.edit_settings_cb)

        # init vars
        self.solved_j2000 = None

        self.target_j2000 = None

        # choice which solver
        # FIXME make user configurable
        self.ui.use_localsolver_radio_button.setChecked(True)

        # platesolve2
        if BACKEND == 'ASCOM':
            self.platesolve2 = PlateSolve2(self.settings.platesolve2_location)

        # astrometry.net local
        if BACKEND == 'INDI':
            self.astrometrynetlocal = AstrometryNetLocal(self.settings.astrometrynetlocal_location)
            self.astrometrynetlocal.probe_solve_field_revision()
        # used for status bar
        self.activity_bar = QtWidgets.QProgressBar()
        self.activity_bar.setRange(0, 0)
        self.activity_bar.resize(75, 20)

        # poll for focus pos
        self.curpospoller = QtCore.QTimer()
        self.curpospoller.timeout.connect(self.poll_curpos_CB)
        self.curpospoller.start(1000)

    def poll_curpos_CB(self):
        if self.tel.is_connected():
            self.set_current_position_labels(self.tel.get_position_j2000())
        #self.set_target_position_labels(self.tel.get_target_j2000())

        # set button states
        self.ui.telescope_driver_connect.setEnabled(not self.tel.is_connected())
        self.ui.telescope_driver_select.setEnabled(not self.tel.is_connected())
        self.ui.camera_driver_connect.setEnabled(not self.cam.is_connected())

    def set_enable_INDI_camera_controls(self, enable):
        self.ui.camera_driver_indi_label.setEnabled(enable)
        self.ui.camera_driver_indi_driver_label.setEnabled(enable)
        self.ui.camera_driver_indi_select.setEnabled(enable)

    def show_activity_bar(self):
        self.ui.statusbar.addPermanentWidget(self.activity_bar)

    def hide_activity_bar(self):
        self.ui.statusbar.removeWidget(self.activity_bar)

    def set_current_position_labels(self, pos_j2000):
        self.store_skycoord_to_label(pos_j2000, self.ui.cur_ra_j2000_label, self.ui.cur_dec_j2000_label)
        pos_jnow = precess_J2000_to_JNOW(pos_j2000)
        self.store_skycoord_to_label(pos_jnow, self.ui.cur_ra_jnow_label, self.ui.cur_dec_jnow_label)

    def set_solved_position_labels(self, pos_j2000):
        self.store_skycoord_to_label(pos_j2000.radec, self.ui.solve_ra_j2000_label, self.ui.solve_dec_j2000_label)
        pos_jnow = precess_J2000_to_JNOW(pos_j2000.radec)
        self.store_skycoord_to_label(pos_jnow, self.ui.solve_ra_jnow_label, self.ui.solve_dec_jnow_label)
        self.ui.solve_pixel_scale_label.setText(f'{pos_j2000.pixel_scale:5.2f} @ bin x {int(pos_j2000.binning)}')
        self.ui.solve_roll_angle_label.setText(f'{pos_j2000.angle.degree:6.2f}')

    def set_target_position_labels(self, pos_j2000):
        self.ui.target_ra_j2000_entry.setPlainText('  ' + pos_j2000.ra.to_string(u.hour, sep=":", pad=True))
        self.ui.target_dec_j2000_entry.setPlainText(pos_j2000.dec.to_string(alwayssign=True, sep=":", pad=True))

#        if pos_j2000 is not None:
#            self.store_skycoord_to_label(pos_j2000, self.ui.target_ra_j2000_label, self.ui.target_dec_j2000_label)
#            pos_jnow = precess_J2000_to_JNOW(pos_j2000)
#            self.store_skycoord_to_label(pos_jnow, self.ui.target_ra_jnow_label, self.ui.target_dec_jnow_label)
#        else:
#            for l in [self.ui.target_ra_j2000_label, self.ui.target_dec_j2000_label, self.ui.target_ra_jnow_label, self.ui.target_dec_jnow_label]:
#                l.setText("--:--:--")

    def select_telescope(self):
        if self.settings.telescope_driver:
            last_choice = self.settings.telescope_driver
        else:
            last_choice = ''

        if self.tel.has_chooser():
            mount_choice = self.tel.show_chooser(last_choice)
            if len(mount_choice) > 0:
                self.settings.telescope_driver = mount_choice
                self.settings.write()
                self.ui.telescope_driver_label.setText(mount_choice)
        else:
            choices = self.backend.getDevicesByClass('telescope')
            logging.info(f'Possiuble Telescope choices = {choices}')

            if len(choices) < 1:
                QtWidgets.QMessageBox.critical(None, 'Error', 'No telescope available!',
                                               QtWidgets.QMessageBox.Ok)
                return

            if last_choice in choices:
                selection = choices.index(last_choice)
            else:
                selection = 0

            mount_choice, ok = QtWidgets.QInputDialog.getItem(None, 'Choose Telescope Driver',
                                                               'Driver', choices, selection)
            if ok:
                logging.info(f'Telescope choice = {mount_choice}')
                self.settings.telescope_driver = mount_choice
                self.settings.write()
                self.ui.telescope_driver_label.setText(mount_choice)

    def connect_telescope(self):
        if self.settings.telescope_driver:
            rc = self.tel.connect_to_telescope(self.settings.telescope_driver)
            if not rc:
                QtWidgets.QMessageBox.critical(None, 'Error', 'Unable to connect to mount!',
                                               QtWidgets.QMessageBox.Ok)
                return

    def select_indi_camera(self):

        last_choice = ''
        if self.settings.camera_driver:
            # We store the actual driver like this:
            #
            #  'INDICamera:<driver name>
            #
            # so now pull off driver
            if ':' in self.settings.camera_driver:
                last_choice = self.settings.camera_driver.split(':')[1]

        choices = self.backend.getDevicesByClass('ccd')

        if len(choices) < 1:
            QtWidgets.QMessageBox.critical(None, 'Error', 'No cameras available!',
                                           QtWidgets.QMessageBox.Ok)
            return

        if last_choice in choices:
            selection = choices.index(last_choice)
        else:
            selection = 0

        camera_choice, ok = QtWidgets.QInputDialog.getItem(None, 'Choose Camera Driver',
                                                           'Driver', choices, selection)
        if ok:
            self.settings.camera_driver = 'INDICamera:'+camera_choice
            self.settings.write()
            self.ui.camera_driver_indi_driver_label.setText(camera_choice)

    def connect_camera(self):
        if BACKEND == 'ASCOM':
            if self.ui.camera_driver_system.isChecked():
                driver = 'MaximDL'
                self.cam = MaximDL_Camera()
            elif self.ui.camera_driver_rpc.isChecked():
                driver = 'RPC'
                self.cam = RPC_Camera()
            else:
                logging.error('connect_camera(): UNKNOWN camera driver result from radio buttons!')
                return
        elif BACKEND == 'INDI':
            if self.ui.camera_driver_system.isChecked():
                driver = 'INDICamera'
                self.cam = INDI_Camera(self.backend)
            elif self.ui.camera_driver_rpc.isChecked():
                driver = 'RPC'
                self.cam = RPC_Camera()
            else:
                logging.error('connect_camera(): UNKNOWN camera driver result from radio buttons!')
                return

        logging.info(f'connect_camera: driver = {driver}')

        if driver == 'INDICamera':
            if ':' in self.settings.camera_driver:
                indi_cam_driver = self.settings.camera_driver.split(':')[1]
                rc = self.cam.connect(indi_cam_driver)
            else:
                QtWidgets.QMessageBox.critical(None, 'Error', 'Must configure INDI camera driver first!',
                                               QtWidgets.QMessageBox.Ok)
                return
        else:
            rc = self.cam.connect(driver)
        if not rc:
            QtWidgets.QMessageBox.critical(None, 'Error', 'Unable to connect to camera!',
                                           QtWidgets.QMessageBox.Ok)
            return

#        self.settings.camera_driver = driver
#        self.settings.write()

    def sync_pos_cb(self):
        if self.solved_j2000 is None:
            logging.error("Cannot SYNC no solved POSITION!")
            CriticalDialog('Cannot sync mount - must solve position first!').exec()
#            err = QtWidgets.QMessageBox()
#            err.setIcon(QtWidgets.QMessageBox.Critical)
#            err.setInformativeText("Cannot sync mount - must solve position first!")
#            err.setStandardButtons(QtWidgets.QMessageBox.Ok)
#            err.exec()
            return

        # convert to jnow
        solved_jnow = precess_J2000_to_JNOW(self.solved_j2000.radec)

        sep = self.solved_j2000.radec.separation(self.tel.get_position_j2000()).degree
        logging.info(f"Sync pos is {sep} degrees from current pos")

        # get confirmation
        yesno = QtWidgets.QMessageBox()
        yesno.setIcon(QtWidgets.QMessageBox.Question)
        yesno.setInformativeText(f"Do you want to sync the mount?\n\n" + \
                                 f"Position (J2000): \n" + \
                                 f"     {self.solved_j2000.radec.to_string('hmsdms', sep=':')}\n\n" + \
                                 f"Position (JNow): \n" + \
                                 f"     {solved_jnow.to_string('hmsdms', sep=':')}\n\n" + \
                                 f"This is {sep:6.2f} degrees from current position.")
        yesno.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        result = yesno.exec()
        print(result)

        if result == QtWidgets.QMessageBox.Yes:
            # check if its WAY OFF
            if sep > 10:
                yesno = QtWidgets.QMessageBox()
                yesno.setIcon(QtWidgets.QMessageBox.Question)
                yesno.setInformativeText(f"The sync position is {sep:6.2f} " + \
                                         f"degrees from current position!\n" + \
                                         f"Do you REALLY want to sync the mount?")
                yesno.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
                result = yesno.exec()

                if result != QtWidgets.QMessageBox.Yes:
                    logging.info("User declined to sync mount")
                    return

            logging.info("Syncing mount")
            self.ui.statusbar.showMessage("Synced")
            self.app.processEvents()
            if not self.tel.sync(solved_jnow):
                CriticalDialog('Error occurred syncing mount!').exec()
        else:
            logging.info("User declined to sync mount")


    def target_precise_goto_cb(self):
        target = self.get_target_pos()
        if target is None:
            return

        while True:
            logging.info('Precise slew - solving current position')

            self.ui.statusbar.showMessage('Precise slew - solving current position')
            self.app.processEvents()

            curpos_j2000 = self.run_solve_image()

            self.ui.statusbar.showMessage('Precise slew - position solved')
            self.app.processEvents()

            logging.info(f'solved position is {curpos_j2000}')

            if curpos_j2000 is None:
               CriticalDialog('Precise slew failed - unable to solve current position.')
               return

            self.solved_j2000 = curpos_j2000
            sep = self.solved_j2000.radec.separation(target).degree
            logging.info(f'Distance from target is {sep}')

            # if too far ask before making correction
            # slew limit is in arcseconds so convert
            if sep < self.settings.precise_slew_limit/3600.0:
                logging.info(f'Sep {sep} < threshold {self.settings.precise_slew_limit/3600.0} so quitting')
                self.ui.statusbar.showMessage(f'Precise slew complete - offset is {sep*3600:5.1f} arc-seconds')
                self.app.processEvents()
                return
            elif sep > 5:
                result = YesNoDialog(f'Error in position is {sep:6.2f} degrees.  Slew to correct?').exec()

                if not result:
                    logging.info('User elected to stop precise slew correction')
                    return

            # sync
            self.sync_pos_cb()

            time.sleep(1) # just to let things happen

            # slew
            self.target_goto_cb()


    def solve_file_cb(self):
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select file to solve:")
        logging.info(f"solve_file_cb: User selected file {fname}")
        if len(fname) < 1:
            logging.warning("solve_file_cb: User aborted file open")
            return
        self.run_solve_file(fname)

    def run_solve_file(self, fname):
        self.solved_j2000 = self.plate_solve_file(fname)
        if self.solved_j2000 is not None:
            self.set_solved_position_labels(self.solved_j2000)

    def solve_image_cb(self):
        self.run_solve_image()

    def run_solve_image(self):
        logging.info("Taking image")
        self.ui.statusbar.showMessage("Taking image with camera...")
        self.app.processEvents()

        if not self.setupCCDFrameBinning():
            logging.error('run_solve_image: Unable to setup camera!')
            CriticalDialog('Could not setup camera!').exec()
            return

        ff = os.path.join(os.getcwd(), "plate_solve_image.fits")

        focus_expos = self.settings.camera_exposure
        self.cam.start_exposure(focus_expos)

        # give things time to happen (?) I get Maxim not ready errors so slowing it down
        time.sleep(0.25)

        elapsed = 0
        while not self.cam.check_exposure():
            self.ui.statusbar.showMessage(f"Taking image with camera {elapsed} of {focus_expos} seconds")
            self.app.processEvents()
            time.sleep(0.5)
            elapsed += 0.5
            if elapsed > focus_expos:
                elapsed = focus_expos

        # give it some time seems like Maxim isnt ready if we hit it too fast
        time.sleep(0.5)

        logging.info(f"Saving image to {ff}")
        if BACKEND == 'INDI':
            # FIXME need better way to handle saving image to file!
            image_data = self.cam.get_image_data()
            # this is an hdulist
            image_data.writeto(ff, overwrite=True)
        else:
            self.cam.save_image_data(ff)

        self.solved_j2000 = self.plate_solve_file(ff)
        if self.solved_j2000 is not None:
            self.set_solved_position_labels(self.solved_j2000)

        return self.solved_j2000

    def setupCCDFrameBinning(self):
        # set camera dimensions to full frame and 1x1 binning
        result = self.cam.get_size()
        if not result:
            return False

        (maxx, maxy) = result
        logging.info("Sensor size is %d x %d", maxx, maxy)

        width = maxx
        height = maxy

        self.cam.set_frame(0, 0, width, height)

        self.cam.set_binning(self.settings.camera_binning, self.settings.camera_binning)

        logging.info("CCD size: %d x %d ", width, height)
        logging.info("CCD bin : %d x %d ", self.settings.camera_binning, self.settings.camera_binning)

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
        if self.ui.use_astrometry_radio_button.isChecked():
            return self.plate_solve_file_astrometry(fname)
        # FIXME This is ugly overloading platesolve2 radio button!
        elif self.ui.use_localsolver_radio_button.isChecked():
            if BACKEND == 'ASCOM':
                return self.plate_solve_file_platesolve2(fname)
            elif BACKEND == 'INDI':
                return self.plate_solve_file_astromentrynetlocal(fname)
        else:
            logging.error("plate_solve_file: Unknown solver selected!!")
            return None

    def plate_solve_file_platesolve2(self, fname):
        self.ui.statusbar.showMessage("Solving with PlateSolve2...")
        self.app.processEvents()

        radec_pos = read_radec_from_FITS(fname)
        img_info = read_image_info_from_FITS(fname)

        logging.info(f'{img_info}')

        if radec_pos is None or img_info is None:
            logging.error(f'plate_solve_file_platesolve2: error reading radec from FITS file {radec_pos} {img_info}')
            self.ui.statusbar.showMessage("Error reading FITS file!")
            err = QtWidgets.QMessageBox()
            err.setIcon(QtWidgets.QMessageBox.Critical)
            err.setInformativeText('Error reading FITS file!')
            err.setStandardButtons(QtWidgets.QMessageBox.Ok)
            err.exec()
            return None

        (img_width, img_height, img_binx, img_biny) = img_info

        self.ui.statusbar.showMessage('Starting PlateSolve2')
        self.app.processEvents()

        # convert fov from arcsec to degrees
        solve_params = PlateSolveParameters()
        fov_x = self.settings.pixel_scale_arcsecpx*img_width*img_binx/3600.0*u.deg
        fov_y = self.settings.pixel_scale_arcsecpx*img_height*img_biny/3600.0*u.deg
        solve_params.fov_x = Angle(fov_x)
        solve_params.fov_y = Angle(fov_y)
        solve_params.radec = radec_pos
        solve_params.width = img_width
        solve_params.height = img_height
        solve_params.bin_x = img_binx
        solve_params.bin_y = img_biny

        logging.info(f'plate_solve_file_platesolve2: solve_parms = {solve_params}')

        solved_j2000 = self.platesolve2.solve_file(fname, solve_params,
                                                   nfields=self.settings.platesolve2_regions)

        if solved_j2000 is None:
            logging.error('Plate solve failed!')
            self.ui.statusbar.showMessage('Plate solve failed!')
            err = QtWidgets.QMessageBox()
            err.setIcon(QtWidgets.QMessageBox.Critical)
            err.setInformativeText('Plate solve failed!')
            err.setStandardButtons(QtWidgets.QMessageBox.Ok)
            err.exec()
            return None

        self.ui.statusbar.showMessage("Plate solve succeeded")
        self.app.processEvents()

        return solved_j2000

    def plate_solve_file_astromentrynetlocal(self, fname):
        self.ui.statusbar.showMessage("Solving with astrometry.net locally...")
        self.app.processEvents()

        radec_pos = read_radec_from_FITS(fname)
        img_info = read_image_info_from_FITS(fname)

        logging.info(f'{img_info}')

        if radec_pos is None or img_info is None:
            logging.error(f'plate_solve_file_astromentrynetlocal: error reading radec from FITS file {radec_pos} {img_info}')
            self.ui.statusbar.showMessage("Error reading FITS file!")
            err = QtWidgets.QMessageBox()
            err.setIcon(QtWidgets.QMessageBox.Critical)
            err.setInformativeText('Error reading FITS file!')
            err.setStandardButtons(QtWidgets.QMessageBox.Ok)
            err.exec()
            return None

        (img_width, img_height, img_binx, img_biny) = img_info

        self.ui.statusbar.showMessage('Starting solve-field')
        self.app.processEvents()

        # convert fov from arcsec to degrees
        solve_params = PlateSolveParameters()
        fov_x = self.settings.pixel_scale_arcsecpx*img_width*img_binx/3600.0*u.deg
        fov_y = self.settings.pixel_scale_arcsecpx*img_height*img_biny/3600.0*u.deg
        solve_params.pixel_scale = self.settings.pixel_scale_arcsecpx*img_binx
        solve_params.fov_x = Angle(fov_x)
        solve_params.fov_y = Angle(fov_y)
        solve_params.radec = radec_pos
        solve_params.width = img_width
        solve_params.height = img_height
        solve_params.bin_x = img_binx
        solve_params.bin_y = img_biny

        logging.info(f'plate_solve_file_astromentrynetlocal: solve_parms = {solve_params}')

        solved_j2000 = self.astrometrynetlocal.solve_file(fname, solve_params,
                                                          search_rad=self.settings.astrometrynetlocal_search_rad_deg)

        if solved_j2000 is None:
            logging.error('Plate solve failed!')
            self.ui.statusbar.showMessage('Plate solve failed!')
            err = QtWidgets.QMessageBox()
            err.setIcon(QtWidgets.QMessageBox.Critical)
            err.setInformativeText('Plate solve failed!')
            err.setStandardButtons(QtWidgets.QMessageBox.Ok)
            err.exec()
            return None

        self.ui.statusbar.showMessage("Plate solve succeeded")
        self.app.processEvents()

        return solved_j2000

    def plate_solve_file_astrometry(self, fname):

        # connect
        # FIXME this might leak since we create it each plate solve attempt?
        self.astroclient = Client()

        self.ui.statusbar.showMessage("Logging into astrometry.net...")
        self.app.processEvents()

        try:
            self.astroclient.login(self.settings.astrometry_apikey)
        except RequestError as e:
            logging.error(f'Failed to login to astromentry.net -> {e}')
            CriticalDialog(f'Login to astrometry.net failed -> {e}').exec()
            self.ui.statusbar.showMessage("Login failed")
            self.app.processEvents()
            return None

        time_start = time.time()
        timeout = self.settings.astrometry_timeout

#        timeout = 120  # timeout in seconds

        self.ui.statusbar.showMessage("Uploading image to astrometry.net...")
        self.app.processEvents()

        kwargs = {}
        kwargs['scale_units'] = 'arcsecperpix'
        kwargs['scale_est'] = self.settings.pixel_scale_arcsecpx

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
        logging.info(f"upload result = {upres}")

        if upres['status'] != 'success':
            logging.error('upload failed!')
            self.ui.statusbar.showMessage("Uploading image failed!!!")
            err = QtWidgets.QMessageBox()
            err.setIcon(QtWidgets.QMessageBox.Critical)
            err.setInformativeText("Error uploading image to astrometry.net!")
            err.setStandardButtons(QtWidgets.QMessageBox.Ok)
            err.exec()
            return None

        self.ui.statusbar.showMessage("Upload successful")
        self.app.processEvents()

        sub_id = upres['subid']

        loop_count = 0
        if sub_id is not None:
            while True:
                msgstr = "Checking job status"
                for i in range(0, loop_count % 4):
                    msgstr = msgstr + '.'
                if (loop_count % 5) == 0:
                    logging.info(msgstr)
                self.ui.statusbar.showMessage("Upload successful - " + msgstr)
                self.app.processEvents()

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
                    logging.error("astrometry.net solve timeout!")
                    self.ui.statusbar.showMessage("Astrometry.net timeout!")
                    err = QtWidgets.QMessageBox()
                    err.setIcon(QtWidgets.QMessageBox.Critical)
                    err.setInformativeText("Astrometry.net took too long to respond")
                    err.setStandardButtons(QtWidgets.QMessageBox.Ok)
                    err.exec()
                    return None

                time.sleep(0.5)

        self.ui.statusbar.showMessage(f"Job started - id = {solved_id}")
        self.app.processEvents()

        while True:
            job_stat = self.astroclient.job_status(solved_id)

            if job_stat == 'success':
                break

            if time.time() - time_start > timeout:
                logging.error("astrometry.net solve timeout!")
                self.ui.statusbar.showMessage("Astrometry.net timeout!")
                err = QtWidgets.QMessageBox()
                err.setIcon(QtWidgets.QMessageBox.Critical)
                err.setInformativeText("Astrometry.net took too long to respond")
                err.setStandardButtons(QtWidgets.QMessageBox.Ok)
                err.exec()
                return None

            time.sleep(5)

        final = self.astroclient.job_status(solved_id)

#        print("final job status =", final)

        if final != 'success':
            print("Plate solve failed!")
            print(final)
            self.ui.statusbar.showMessage("Plate solve failed!")
            err = QtWidgets.QMessageBox()
            err.setIcon(QtWidgets.QMessageBox.Critical)
            err.setInformativeText("Plate solve failed!")
            err.setStandardButtons(QtWidgets.QMessageBox.Ok)
            err.exec()
            return None

        final_calib = self.astroclient.job_calib_result(solved_id)
        print("final_calib=", final_calib)

        self.ui.statusbar.showMessage("Plate solve succeeded")
        self.app.processEvents()

        radec = SkyCoord(ra=final_calib['ra']*u.degree, dec=final_calib['dec']*u.degree, frame='fk5', equinox='J2000')

        _, _, binx, _ = img_info
        return PlateSolveSolution(radec, pixel_scale=final_calib['pixscale'],
                                  angle=Angle(final_calib['orientation']*u.deg),
                                  binning = binx)

    def store_skycoord_to_label(self, pos, lbl_ra, lbl_dec):
        lbl_ra.setText('  ' + pos.ra.to_string(u.hour, sep=":", pad=True))
        lbl_dec.setText(pos.dec.to_string(alwayssign=True, sep=":", pad=True))

    def target_use_solved_cb(self):
        if self.solved_j2000 is None:
            CriticalDialog('No solution exists yet!').exec()
            return

        self.target_j2000 = self.solved_j2000.radec
        self.set_target_position_labels(self.target_j2000)

    def get_target_pos(self):
        target_str = self.ui.target_ra_j2000_entry.toPlainText() + " "
        target_str += self.ui.target_dec_j2000_entry.toPlainText()
        logging.info(f"target_str = {target_str}")

        try:
            target = SkyCoord(target_str, unit=(u.hourangle, u.deg), frame='fk5', equinox='J2000')
        except ValueError:
            logging.error("Cannot GOTO invalid target POSITION!")
            CriticalDialog('Invalid target coordinates!').exec()
            return None

        return target

    def target_goto_cb(self):
        target = self.get_target_pos()

        if target is None:
            return

        self.target_j2000 = target

        logging.info(f"target = {target}")

        yesno = QtWidgets.QMessageBox()
        yesno.setIcon(QtWidgets.QMessageBox.Question)

        final_str = target.ra.to_string(u.hour, sep=":", pad=True) + " "
        final_str += target.dec.to_string(alwayssign=True, sep=":", pad=True)

        yesno.setInformativeText(f"Do you want to slew to the position\n\n" + \
                                 f"{final_str}")
        yesno.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        result = yesno.exec()
        if result != QtWidgets.QMessageBox.Yes:
            logging.info("User cancelled GOTO!")
            return

        self.tel.goto(precess_J2000_to_JNOW(target))

        logging.info("goto started!")

        while True:
            self.ui.statusbar.showMessage("Slewing...")
            self.app.processEvents()
            logging.info(f"Slewing = {self.tel.is_slewing()}")
            if not self.tel.is_slewing():
                logging.info("Slew done!")
                self.ui.statusbar.showMessage("Slew complete")
                self.app.processEvents()
                break
            time.sleep(1)

    def edit_settings_cb(self):
        class EditDialog(QtWidgets.QDialog):
            def __init__(self):
                QtWidgets.QDialog.__init__(self)

                self.ui = Ui_SettingsDialog()
                self.ui.setupUi(self)

                if BACKEND == 'ASCOM':
                    self.ui.setup_platesolve2_loc_button.pressed.connect(self.select_platesolve2dir)
                    self.ui.astrometrynetlocal_groupbox.setVisible(False)
                elif BACKEND == 'INDI':
                    self.ui.setup_astrometrynetlocal_loc_button.pressed.connect(self.select_astrometrynetlocaldir)
                    self.ui.platesolve2_groupbox.setVisible(False)

                # FIXME YUCK when hiding group box need window
                # to shrink!
                self.layout().setSizeConstraint(QtWidgets.QLayout.SetFixedSize)


#                self.ui.formLayout.invalidate()
#                for i in range(0, 10):
#                    QtWidgets.QApplication.processEvents()

            def select_platesolve2dir(self):
                ps2_dir = self.ui.platesolve2_exec_path_lbl.text()
                new_ps2_dir, select_filter = QtWidgets.QFileDialog.getOpenFileName(None,
                                                                   'PlateSolve2.exe Location',
                                                                    ps2_dir,
                                                                    'Programs (*.exe)',
                                                                    None)

                logging.info(f'select new_ps2_dir: {new_ps2_dir}')

                if len(new_ps2_dir) < 1:
                    return

                self.ui.platesolve2_exec_path_lbl.setText(new_ps2_dir)

            def select_astrometrynetlocaldir(self):
                anet_dir = self.ui.astrometrynetlocal_exec_path_lbl.text()
                new_anet_dir, select_filter = QtWidgets.QFileDialog.getOpenFileName(None,
                                                                   'Astrometry.net (local) solve-field Location',
                                                                    anet_dir,
                                                                    '',
                                                                    None)
        #dlg.setOption(QtWidgets.QFileDialog.DontUseNativeDialog, True)
        #dlg.setFilter(QtWidgets.QDir.Executable)
                logging.info(f'select new_anet_dir: {new_anet_dir}')

                if len(new_anet_dir) < 1:
                    return

                self.ui.astrometrynetlocal_exec_path_lbl.setText(new_anet_dir)

        print(self.settings)

        dlg = EditDialog()
        dlg.ui.astrometry_timeout_spinbox.setValue(self.settings.astrometry_timeout)
        dlg.ui.astrometry_downsample_spinbox.setValue(self.settings.astrometry_downsample_factor)
        dlg.ui.astrometry_apikey.setPlainText(self.settings.astrometry_apikey)
        dlg.ui.pixelscale_spinbox.setValue(self.settings.pixel_scale_arcsecpx)

        dlg.ui.plate_solve_camera_binning_spinbox.setValue(self.settings.camera_binning)
        dlg.ui.plate_solve_camera_exposure_spinbox.setValue(self.settings.camera_exposure)
        dlg.ui.plate_solve_precise_slew_limit_spinbox.setValue(self.settings.precise_slew_limit)
        if BACKEND == 'ASCOM':
            dlg.ui.platesolve2_waittime_spinbox.setValue(self.settings.platesolve2_wait_time)
            dlg.ui.platesolve2_num_regions_spinbox.setValue(self.settings.platesolve2_regions)
            dlg.ui.platesolve2_exec_path_lbl.setText(self.settings.platesolve2_location)
        elif BACKEND == 'INDI':
            dlg.ui.astrometrynetlocal_exec_path_lbl.setText(self.settings.astrometrynetlocal_location)
            dlg.ui.setup_astrometrynetlocal_search_rad_deg.setValue(self.settings.astrometrynetlocal_search_rad_deg)

        result = dlg.exec_()

        logging.info(f'{result}')
        if result:
            self.settings.pixel_scale_arcsecpx = dlg.ui.pixelscale_spinbox.value()
            self.settings.astrometry_timeout = dlg.ui.astrometry_timeout_spinbox.value()
            self.settings.astrometry_downsample_factor = dlg.ui.astrometry_downsample_spinbox.value()
            self.settings.astrometry_apikey = dlg.ui.astrometry_apikey.toPlainText()
            self.settings.camera_binning = dlg.ui.plate_solve_camera_binning_spinbox.value()
            self.settings.camera_exposure = dlg.ui.plate_solve_camera_exposure_spinbox.value()
            self.settings.precise_slew_limit = dlg.ui.plate_solve_precise_slew_limit_spinbox.value()
            self.settings.write()

            if BACKEND == 'ASCOM':
                self.settings.platesolve2_location = dlg.ui.platesolve2_exec_path_lbl.text()
                self.settings.platesolve2_regions = dlg.ui.platesolve2_num_regions_spinbox.value()
                self.settings.platesolve2_wait_time = dlg.ui.platesolve2_waittime_spinbox.value()
                self.platesolve2.set_exec_path(self.settings.platesolve2_location)
            elif BACKEND == 'INDI':
                self.settings.astrometrynetlocal_location = dlg.ui.astrometrynetlocal_exec_path_lbl.text()
                self.astrometrynetlocal.set_exec_path(self.settings.astrometrynetlocal_location)
                self.settings.astrometrynetlocal_search_rad_deg = dlg.ui.setup_astrometrynetlocal_search_rad_deg.value()


if __name__ == '__main__':
    logging.basicConfig(filename='pyastrometry.log',
                        filemode='w',
                        level=logging.DEBUG,
                        format='%(asctime)s %(levelname)-8s %(message)s',
                        datefmt='%Y-%m-%d %H:%M:%S')

    # add to screen as well
    LOG = logging.getLogger()
    formatter = logging.Formatter('%(asctime)s %(levelname)-8s %(message)s')
    CH = logging.StreamHandler()
    CH.setLevel(logging.INFO)
    CH.setFormatter(formatter)
    LOG.addHandler(CH)

    logging.info(f'pyastrometry v {VERSION} starting')

    ARGS = parse_command_line()

    app = QtWidgets.QApplication(sys.argv)
    window = MyApp(app, ARGS)
    window.show()
    sys.exit(app.exec_())
