#!/usr/bin/python
# even on windows this 'tricks' conda into wrapping script so it will
# execute like it would have in bash
import os
import sys
import time
import json
import argparse
import logging
import subprocess
from datetime import datetime
from configobj import ConfigObj
import win32com.client      #needed to load COM objects

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

from pyastrometry.DeviceBackendASCOM import DeviceBackendASCOM as Backend


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
    """

    def __init__(self, exec_path):
        """Initialize object so it is ready to handle solve requests

        Parameters
        ----------
        exec_path : str
            Path to the PlateSolve2 executable
        """
        self.exec_path = exec_path

    #def solve_file(self, fname, radec, fov_x, fov_y, nfields=99, wait=1):

    def set_exec_path(self, exec_path):
        self.exec_path = exec_path

    def solve_file(self, fname, solve_params, nfields=99, wait=1):
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

        cmd_line = f'{solve_params.radec.ra.radian},'
        cmd_line += f'{solve_params.radec.dec.radian},'
        cmd_line += f'{solve_params.fov_x.radian},'
        cmd_line += f'{solve_params.fov_y.radian},'
        cmd_line += f'{nfields},'
        cmd_line += fname + ','
        cmd_line += f'{wait}'

        print(cmd_line)

        runargs = [self.exec_path, cmd_line]

        #runargs = ['PlateSolve2.exe', '5.67,1.00,0.025,0.017,99,'+fname+',1']

        ps2_proc = subprocess.Popen(runargs,
                                    stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    universal_newlines=True)
        poll_value = None
        while True:
            poll_value = ps2_proc.poll()

            if poll_value is not None:
                break

        (base, ext) = os.path.splitext(fname)

        print(base, ext)

        apm_fname = base + '.apm'
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
            return PlateSolveSolution(radec, pixel_scale=solved_scale, angle=Angle(solved_angle*u.deg))
        else:
            return None

class Pinpoint:
    def __init__(self, catalog_path):
        logging.info("FIXME Need to make pinpoint params NOT hard coded!!")
        self.SigmaAboveMean = 2.0      # Amount above noise : default = 4.0
        self.minimumBrightness = 1000     # Minimum star brightness: default = 200
        self.CatalogMaximumMagnitude = 12.5     #Maximum catalog magnitude: default = 20.0
        self.CatalogExpansion = 0.3      # Area expansion of catalog to account for misalignment: default = 0.3
        self.MinimumStarSize = 2        # Minimum star size in pixels: default = 2
        self.Catalog = 3        # GSC-ACT; accurate and easy to use
        self.CatalogPath = catalog_path         #"N:\\Astronomy\\GSCDATA\\GSC"

        # setup PinPoint
        self.pinpoint = win32com.client.Dispatch("PinPoint.Plate")
        self.pinpoint.SigmaAboveMean = self.SigmaAboveMean
        self.pinpoint.minimumBrightness = self.minimumBrightness
        self.pinpoint.CatalogMaximumMagnitude = self.CatalogMaximumMagnitude
        self.pinpoint.CatalogExpansion = self.CatalogExpansion
        self.pinpoint.MinimumStarSize = self.MinimumStarSize
        self.pinpoint.Catalog = self.Catalog
        self.pinpoint.CatalogPath = self.CatalogPath

    def solve(self, fname, curpos, pixscale):
        self.pinpoint.AttachFITS(fname)

        cur_ra = curpos.ra.degree
        cur_dec = curpos.dec.degree

        logging.info(f"{cur_ra} {cur_dec}")
        self.pinpoint.RightAscension = cur_ra
        self.pinpoint.Declination = cur_dec

        self.pinpoint.ArcSecPerPixelHoriz = pixscale
        self.pinpoint.ArcSecPerPixelVert = pixscale

        logging.info('Pinpoint - Finding stars')
        self.pinpoint.FindImageStars()

        stars = self.pinpoint.ImageStars
        logging.info(f'Pinpoint - Found {stars.count} image stars')

        self.pinpoint.FindCatalogStars()
        stars = self.pinpoint.CatalogStars

        logging.info(f'Pinpoint - Found {stars.count} catalog stars')
        self.pinpoint.Solve()

        logging.info(f"Plate Solve (J2000)  RA: {self.pinpoint.RightAscension}")
        logging.info(f"                    DEC: {self.pinpoint.Declination}")

class Telescope_OBSOLETE:
    def __init__(self):
        self.tel = None
        self.connected = False

    def show_chooser(self, last_choice):
        chooser = win32com.client.Dispatch("ASCOM.Utilities.Chooser")
        chooser.DeviceType="Telescope"
        mount = chooser.Choose(last_choice)
        logging.info(f'choice = {mount}')
        return mount

    def connect_to_telescope(self, driver):
        if self.connected:
            logging.warning('connect_to_telescope: already connected!')

        logging.info(f"Connect to telescope driver {driver}")
        self.tel = win32com.client.Dispatch(driver)

        if self.tel.Connected:
            logging.info("	->Telescope was already connected")
        else:
            self.tel.Connected = True
            if self.tel.Connected:
                logging.info("	Connected to telescope now")
            else:
                logging.error("	Unable to connect to telescope, expect exception")
                return False

        self.connected = True
        return True

    def is_connected(self):
        return self.connected

    def get_position_jnow(self):
        if not self.connected:
            return None
        time_now = Time(datetime.utcnow(), scale='utc')
        return SkyCoord(ra=self.tel.RightAscension*u.hour, dec=self.tel.Declination*u.degree, frame='fk5', equinox=Time(time_now.jd, format="jd", scale="utc"))

    def get_position_j2000(self):
        if not self.connected:
            return None
        pos_jnow = self.get_position_jnow()
        return precess_JNOW_to_J2000(pos_jnow)

# These give errors when I try to use them
#    def get_target_jnow(self):
#        try:
#            time_now = Time(datetime.utcnow(), scale='utc')
#            return SkyCoord(ra=self.tel.TargetRightAscension*u.hour, dec=self.tel.TargetDeclination*u.degree, frame='fk5', equinox=Time(time_now.jd, format="jd", scale="utc"))
#        except:
#            logging.info("Error reading target jnow!")
#            return None
#
#    def get_target_j2000(self):
#        pos_jnow = self.get_target_jnow()
#        if pos_jnow is not None:
#            return precess_JNOW_to_J2000(pos_jnow)
#        else:
#            return None

    def sync(self, pos):
        if not self.connected:
            return False

        logging.info(f"Syncing to {pos.ra.hour}  {pos.dec.degree}")
        try:
            self.tel.SyncToCoordinates(pos.ra.hour, pos.dec.degree)
        except Exception as e:
            logging.error('sync() Exception ->', exc_info=True)
            return False

        return True

    def goto(self, pos):
        if not self.connected:
            return False
        logging.info(f"Goto to {pos.ra.hour}  {pos.dec.degree}")
        self.tel.SlewToCoordinatesAsync(pos.ra.hour, pos.dec.degree)
        return True

    def is_slewing(self):
        if not self.connected:
            return None
        return self.tel.Slewing

class Camera_OBSOLETE:
    def __init__(self):
        pass

    def connectCamera(self):
        import pythoncom
        pythoncom.CoInitialize()
        import win32com.client
        self.cam = win32com.client.Dispatch("MaxIm.CCDCamera")
        self.cam.LinkEnabled = True
        self.cam.DisableAutoShutDown = True

        return True

    def takeframeCamera(self, expos):
        logging.info(f'Exposing image for {expos} seconds')

        self.cam.Expose(expos, 1, -1)

        return True

    def checkexposureCamera(self):
        return self.cam.ImageReady

    def saveimageCamera(self, path):
        # FIXME make better temp name
        # FIXME specify cwd as path for file - otherwise not sure where it goes!
        logging.info(f"saveimageCamera: saving to {path}")

        try:
            self.cam.SaveImage(path)
        except:
            exc_type, exc_value = sys.exc_info()[:2]
            logging.info('saveimageCamera %s exception with message "%s"' % \
                              (exc_type.__name__, exc_value))
            logging.error(f"Error saving {path} in saveimageCamera()!")
            return False

        return True

    def closeimageCamera(self):
        # not all backends need this
        # MAXIM does
        if self.mainThread:
            # import win32com.client
            # app = win32com.client.Dispatch("MaxIm.Application")
            # app.CurrentDocument.Close

            # alt way
            self.cam.Document.Close
        else:
            # in other threads this is a noop
            pass

    def getbinningCamera(self):
        return (self.cam.BinX, self.cam.BinY)

    def setbinningCamera(self, binx, biny):
        self.cam.BinX = binx
        self.cam.BinY = biny
        return True

    def getsizeCamera(self):
        return (self.cam.CameraXSize, self.cam.CameraYSize)

    def getframeCamera(self):
        return(self.cam.StartX, self.cam.StartY, self.cam.NumX, self.cam.NumY)

    def setframeCamera(self, minx, miny, width, height):
        self.cam.StartX = minx
        self.cam.StartY = miny
        self.cam.NumX = width
        self.cam.NumY = height

        return True

class PlateSolveParameters:
    """Contains parameters needed to prime a plate solve engine"""

    def __init__(self):
        """Creates object contains plate solve parameters"""
        self.pixel_scale = None
        self.radec = None
        self.fov_x = None
        self.fov_y = None

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


class PlateSolveSolution:
    """Stores solution from plate solve engine"""
    def __init__(self, radec, pixel_scale, angle):
        """Create solution object

        Parameters
        ----------
        radec : SkyCoord
            RA/DEC of center of image.
        pixel_scale : float
            Pixel scale in arc-seconds/pixel
        angle : Angle
            Sky roll angle of image.
        """
        self.radec = radec
        self.pixel_scale = pixel_scale
        self.angle = angle

class ProgramSettings:
    """Stores program settings which can be saved persistently"""
    def __init__(self):
        """Set some defaults for program settings"""
        self._config = ConfigObj(unrepr=True, file_error=True, raise_errors=True)
        self._config.filename = self._get_config_filename()

        self.telescope_driver = None
        self.camera_driver = None
        self.pixel_scale_arcsecpx = 1.0
        self.platesolve2_location = "PlateSolve2.exe"
        self.platesolve2_regions = 999
        self.platesolve2_wait_time = 10
        self.astrometry_timeout = 90
        self.astrometry_downsample_factor = 2
        self.astrometry_apikey = ''
        self.camera_exposure = 5
        self.camera_binning = 2
        self.precise_slew_limit = 600.0

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

        self.app = app
        self.args = args

        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        self.ui.telescope_driver_select.pressed.connect(self.select_telescope)
        self.ui.telescope_driver_connect.pressed.connect(self.connect_telescope)

#        self.ui.camera_driver_select.pressed.connect(self.select_camera)

        if self.settings.camera_driver == 'MaximDL':
            self.ui.camera_driver_maxim.setChecked(True)
        elif self.settings.camera_driver == 'RPC':
            self.ui.camera_driver_rpc.setChecked(True)
        else:
            logging.warning('camera driver not set!  Defaulting to MaximDL')
            self.settings.camera_driver = 'MaximDL'
            self.ui.camera_driver_maxim.setChecked(True)

        self.ui.camera_driver_connect.pressed.connect(self.connect_camera)

        self.setWindowTitle('pyastrometry v' + VERSION)

        # telescope
        self.tel = Backend.Telescope()
        #self.tel.connect_to_telescope(self.args.telescope)
        self.ui.telescope_driver_label.setText(self.settings.telescope_driver)

        # connect to camera
        self.cam = Backend.Camera()
        #self.cam.connectCamera(self.settings.camera_driver)

        # connect to astrometry.net
        # FIXME Fix so we only login when needed
        # FIXME Fix so with no internet this doesnt take a long time to fail
        # FIXME put API KEY in config file
#        self.astroclient = Client()
#        self.astroclient.login('***REMOVED***')

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
        self.ui.use_platesolve2_radio_button.setChecked(True)

        # platesolve2
        self.platesolve2 = PlateSolve2(self.settings.platesolve2_location)

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
        self.ui.solve_roll_angle_label.setText(f"{pos_j2000.angle.degree:6.2f}")

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

        mount_choice = self.tel.show_chooser(last_choice)
        if len(mount_choice) > 0:
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

    def select_camera(self):
        if self.settings.camera_driver:
            last_choice = self.settings.camera_driver
        else:
            last_choice = ''

        camera_choice = self.cam.show_chooser(last_choice)
        if len(camera_choice) > 0:
            self.settings.camera_driver = camera_choice
            self.settings.write()
            self.ui.camera_driver_label.setText(camera_choice)

    def connect_camera(self):
        if self.ui.camera_driver_maxim.isChecked():
            driver = 'MaximDL'
        elif self.ui.camera_driver_rpc.isChecked():
            driver = 'RPC'
        else:
            logging.error('connect_camera(): UNKNOWN camera driver result from radio buttons!')
            return

        logging.info(f'connect_camera: driver = {driver}')

        rc = self.cam.connect(driver)
        if not rc:
            QtWidgets.QMessageBox.critical(None, 'Error', 'Unable to connect to camera!',
                                           QtWidgets.QMessageBox.Ok)
            return

        self.settings.camera_driver = driver
        self.settings.write()

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
                result = YesNoDialog(f'Error in position is {sep:6.2f} degrees.  Slew to correct?')

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

        self.setupCCDFrameBinning()

        ff = os.path.join(os.getcwd(), "plate_solve_image.fits")

        focus_expos = self.settings.camera_exposure
        self.cam.takeframeCamera(focus_expos, ff)

        # give things time to happen (?) I get Maxim not ready errors so slowing it down
        time.sleep(0.25)

        elapsed = 0
        while not self.cam.checkexposureCamera():
            self.ui.statusbar.showMessage(f"Taking image with camera {elapsed} of {focus_expos} seconds")
            self.app.processEvents()
            time.sleep(0.5)
            elapsed += 0.5
            if elapsed > focus_expos:
                elapsed = focus_expos

        # give it some time seems like Maxim isnt ready if we hit it too fast
        time.sleep(0.5)

        # screwy interface for camera
        # MaximDl will take frame and then we tell it to save
        # RPC will take frame and save it in one action!
        # So we only save here if the camera driver didnt save to file
        # in takeframe
        if not self.cam.takeframe_saves_file():
            logging.info(f"Saving image to {ff}")
            self.cam.saveimageCamera(ff)

        self.solved_j2000 = self.plate_solve_file(ff)
        if self.solved_j2000 is not None:
            self.set_solved_position_labels(self.solved_j2000)

        return self.solved_j2000

    def setupCCDFrameBinning(self):
        # set camera dimensions to full frame and 1x1 binning
        (maxx, maxy) = self.cam.getsizeCamera()
        logging.info("Sensor size is %d x %d", maxx, maxy)

        width = maxx
        height = maxy

        self.cam.setframeCamera(0, 0, width, height)

        self.cam.setbinningCamera(self.settings.camera_binning, self.settings.camera_binning)

        logging.info("CCD size: %d x %d ", width, height)
        logging.info("CCD bin : %d x %d ", self.settings.camera_binning, self.settings.camera_binning)

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
        elif self.ui.use_platesolve2_radio_button.isChecked():
            return self.plate_solve_file_platesolve2(fname)
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
            return

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

        return PlateSolveSolution(radec, pixel_scale=final_calib['pixscale'], angle=Angle(final_calib['orientation']*u.deg))

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
                self.ui.setup_platesolve2_loc_button.pressed.connect(self.select_platesolve2dir)

            def select_platesolve2dir(self):
                ps2_dir = self.ui.platesolve2_exec_path_lbl.text()
                new_ps2_dir, select_filter = QtWidgets.QFileDialog.getOpenFileName(None,
                                                                   'PlateSolve2.exe Location',
                                                                    ps2_dir,
                                                                    "Programs (*.exe)",
                                                                    None)

                logging.info(f'select new_ps2_dir: {new_ps2_dir}')

                if len(new_ps2_dir) < 1:
                    return

                self.ui.platesolve2_exec_path_lbl.setText(new_ps2_dir)

        dlg = EditDialog()
        dlg.ui.astrometry_timeout_spinbox.setValue(self.settings.astrometry_timeout)
        dlg.ui.astrometry_downsample_spinbox.setValue(self.settings.astrometry_downsample_factor)
        dlg.ui.astrometry_apikey.setPlainText(self.settings.astrometry_apikey)
        dlg.ui.pixelscale_spinbox.setValue(self.settings.pixel_scale_arcsecpx)
        dlg.ui.platesolve2_waittime_spinbox.setValue(self.settings.platesolve2_wait_time)
        dlg.ui.platesolve2_num_regions_spinbox.setValue(self.settings.platesolve2_regions)
        dlg.ui.platesolve2_exec_path_lbl.setText(self.settings.platesolve2_location)
        dlg.ui.plate_solve_camera_binning_spinbox.setValue(self.settings.camera_binning)
        dlg.ui.plate_solve_camera_exposure_spinbox.setValue(self.settings.camera_exposure)
        dlg.ui.plate_solve_precise_slew_limit_spinbox.setValue(self.settings.precise_slew_limit)

        result = dlg.exec_()

        logging.info(f'{result}')
        if result:
            self.settings.platesolve2_location = dlg.ui.platesolve2_exec_path_lbl.text()
            self.settings.platesolve2_regions = dlg.ui.platesolve2_num_regions_spinbox.value()
            self.settings.platesolve2_wait_time = dlg.ui.platesolve2_waittime_spinbox.value()
            self.settings.pixel_scale_arcsecpx = dlg.ui.pixelscale_spinbox.value()
            self.settings.astrometry_timeout = dlg.ui.astrometry_timeout_spinbox.value()
            self.settings.astrometry_downsample_factor = dlg.ui.astrometry_downsample_spinbox.value()
            self.settings.astrometry_apikey = dlg.ui.astrometry_apikey.toPlainText()
            self.settings.camera_binning = dlg.ui.plate_solve_camera_binning_spinbox.value()
            self.settings.camera_exposure = dlg.ui.plate_solve_camera_exposure_spinbox.value()
            self.settings.precise_slew_limit = dlg.ui.plate_solve_precise_slew_limit_spinbox.value()
            self.settings.write()

            self.platesolve2.set_exec_path(self.settings.platesolve2_location)

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
