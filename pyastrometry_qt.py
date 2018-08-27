# -*- coding: utf-8 -*-
"""
Created on Sat Aug 25 15:26:52 2018

@author: msf
"""
import os
import sys
import time
import json
import argparse
import logging
from datetime import datetime

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
from astropy import units as u
from astropy.time import Time
from astropy.coordinates import SkyCoord
from astropy.coordinates import FK5

import win32com.client      #needed to load COM objects

from PyQt5 import QtCore, QtWidgets
from pyastrometry_qt_uic import Ui_MainWindow


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

def read_FITS_header(fname):

    hdulist = pyfits.open(fname)
    prihdr = hdulist[0].header

    try:
        dateobs = prihdr["DATE-OBS"]
    except:
        dateobs = None

    if dateobs is None:
        # no date just put in now 2017-10-06T04:01:07.058
        print("No DATE-OBS - putting in current time!")
        dateobs = time.strftime("%Y-%m-%dT%H:%M:%S")

    print("DATE-OBS", dateobs)

def convert_ra_deg_to_hour(ra_deg):
    hour = int(ra_deg/15.0)
    frac = (ra_deg - hour*15.0)/15.0

    print("hour", hour)
    print("frac", frac)

    return hour+frac

def precess_J2000_to_JNOW(pos_J2000):
    time_now = Time(datetime.utcnow(), scale='utc')
    return pos_J2000.transform_to(FK5(equinox=Time(time_now.jd, format="jd", scale="utc")))

def precess_JNOW_to_J2000(pos_JNOW):
    return pos_JNOW.transform_to(FK5(equinox='J2000'))

# returns object containing all parsed command line options
def parse_command_line():
    parser = argparse.ArgumentParser()
    parser.add_argument('--telescope', type=str, help="Name of ASCOM driver to use for telescope")

    args = parser.parse_args()

    return args

class FocusProgressDialog:
    def __init__(self, title_text=None, label_text="", button_text="Cancel", minval=0, maxval=100):
        self.run_focus_dlg = QtWidgets.QProgressDialog(label_text, button_text, minval, maxval)
        self.run_focus_dlg.setWindowModality(QtCore.Qt.WindowModal)
        self.setValues(title_text, label_text, button_text, minval, maxval)
        self.run_focus_dlg.show()

    def setValues(self, title_text=None, label_text=None, button_text=None, minval=None, maxval=None):
        if title_text is not None:
            self.run_focus_dlg.setWindowTitle(title_text)
        if label_text is not None:
            self.run_focus_dlg.setLabelText(label_text)
        if button_text is not None:
            self.run_focus_dlg.setCancelButtonText(button_text)
        if minval is not None:
            self.run_focus_dlg.setMinimum(minval)
        if maxval is not None:
            self.run_focus_dlg.setMaximum(maxval)

    def updateFocusDialog(self, val, label_text):
        self.run_focus_dlg.setLabelText(label_text)
        self.run_focus_dlg.setValue(val)

    def cancelFocusDialog(self):
        self.run_focus_dlg.cancel()

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
        self.pinpoint.ArcSecPerPixelVert  = pixscale

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

class Telescope:
    def __init__(self):
        pass

    def connect_to_telescope(self, driver):
        logging.info(f"Connect to telescope driver {driver}")
        self.tel = win32com.client.Dispatch(driver)
        print(self.tel, self.tel.RightAscension, self.tel.Declination)

        if self.tel.Connected:
            logging.info("	->Telescope was already connected")
        else:
            self.tel.Connected = True
            if self.tel.Connected:
                logging.info("	Connected to telescope now")
            else:
                logging.error("	Unable to connect to telescope, expect exception")

    def get_position_jnow(self):
        time_now = Time(datetime.utcnow(), scale='utc')
        return SkyCoord(ra=self.tel.RightAscension*u.hour, dec=self.tel.Declination*u.degree, frame='fk5', equinox=Time(time_now.jd, format="jd", scale="utc"))

    def get_position_j2000(self):
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
        logging.info(f"Syncing to {pos.ra.hour}  {pos.dec.degree}")
        self.tel.SyncToCoordinates(pos.ra.hour, pos.dec.degree)

    def goto(self, pos):
        logging.info(f"Goto to {pos.ra.hour}  {pos.dec.degree}")
        self.tel.SlewToCoordinatesAsync(pos.ra.hour, pos.dec.degree)

    def is_slewing(self):
        return self.tel.Slewing

class Camera:
    def __init__(self):
        pass

    def connectCamera(self, name):
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

class MyApp(QtWidgets.QMainWindow):
    def __init__(self, app, args):

        super().__init__()

        self.app = app
        self.args = args

        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        # connect to telescope
        self.tel = Telescope()
        self.tel.connect_to_telescope(self.args.telescope)
        self.ui.telescope_driver_label.setText(self.args.telescope)

        # connect to camera
        self.cam = Camera()
        self.cam.connectCamera('MaximDL')

        # connect to astrometry.net
        self.astroclient = Client()
        self.astroclient.login('***REMOVED***')

        self.ui.solve_file_button.clicked.connect(self.solve_file_cb)
        self.ui.sync_pos_button.clicked.connect(self.sync_pos_cb)
        self.ui.solve_image_button.clicked.connect(self.solve_image_cb)

        self.ui.target_use_solved_button.clicked.connect(self.target_use_solved_cb)
        self.ui.target_goto_button.clicked.connect(self.target_goto_cb)
#        self.ui.target_enter_manual_button.clicked.connect(self.target_enter_manual_cb)

        # init vars
        self.solved_j2000 = None

#        self.solved_j2000 = SkyCoord("1h12m43.2s +1d12m43s", frame='fk5', unit=(u.deg, u.hourangle), equinox="J2000")
#        self.set_solved_position_labels(self.solved_j2000)

        self.target_j2000 = None

        # pinpoint
#        self.pinpoint = Pinpoint("N:\\Astronomy\\GSCDATA\\GSC")

        # used for status bar
        self.activity_bar = QtWidgets.QProgressBar()
        self.activity_bar.setRange(0, 0)
        self.activity_bar.resize(75, 20)

        # poll for focus pos
        self.curpospoller = QtCore.QTimer()
        self.curpospoller.timeout.connect(self.poll_curpos_CB)
        self.curpospoller.start(1000)

    def poll_curpos_CB(self):
        self.set_current_position_labels(self.tel.get_position_j2000())
        #self.set_target_position_labels(self.tel.get_target_j2000())

    def show_activity_bar(self):
        self.ui.statusbar.addPermanentWidget(self.activity_bar)

    def hide_activity_bar(self):
        self.ui.statusbar.removeWidget(self.activity_bar)

    def set_current_position_labels(self, pos_j2000):
        self.store_skycoord_to_label(pos_j2000, self.ui.cur_ra_j2000_label, self.ui.cur_dec_j2000_label)
        pos_jnow = precess_J2000_to_JNOW(pos_j2000)
        self.store_skycoord_to_label(pos_jnow, self.ui.cur_ra_jnow_label, self.ui.cur_dec_jnow_label)

    def set_solved_position_labels(self, pos_j2000):
        self.store_skycoord_to_label(pos_j2000, self.ui.solve_ra_j2000_label, self.ui.solve_dec_j2000_label)
        pos_jnow = precess_J2000_to_JNOW(pos_j2000)
        self.store_skycoord_to_label(pos_jnow, self.ui.solve_ra_jnow_label, self.ui.solve_dec_jnow_label)

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

    def sync_pos_cb(self):
        if self.solved_j2000 is None:
            logging.error("Cannot SYNC no solved POSITION!")
            err =  QtWidgets.QMessageBox()
            err.setIcon(QtWidgets.QMessageBox.Critical)
            err.setInformativeText("Cannot sync mount - must solve position first!")
            err.setStandardButtons(QtWidgets.QMessageBox.Ok)
            err.exec()
            return

        # convert to jnow
        solved_jnow = precess_J2000_to_JNOW(self.solved_j2000)

        sep = self.solved_j2000.separation(self.tel.get_position_j2000()).degree
        logging.info(f"Sync pos is {sep} degrees from current pos")

        # get confirmation
        yesno = QtWidgets.QMessageBox()
        yesno.setIcon(QtWidgets.QMessageBox.Question)
        yesno.setInformativeText(f"Do you want to sync the mount?\n\n" + \
                                 f"Position (J2000): \n" + \
                                 f"     {self.solved_j2000.to_string('hmsdms', sep=':')}\n\n" + \
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
            self.tel.sync(solved_jnow)
        else:
            logging.info("User declined to sync mount")

    def solve_file_cb(self):
        fname, retcode = QtWidgets.QFileDialog.getOpenFileName(self, "Select file to solve:")
        logging.info(f"solve_file_cb: User selected file {fname}")
        if len(fname) < 1:
            logging.warning("solve_file_cb: User aborted file open")
            return

        self.solved_j2000 = self.plate_solve_file(fname)
        self.set_solved_position_labels(self.solved_j2000)

    def solve_image_cb(self):
        logging.info("Taking image")
        self.ui.statusbar.showMessage("Taking image with camera...")
        self.app.processEvents()

        self.setupCCDFrameBinning()

        focus_expos = 5
        self.cam.takeframeCamera(focus_expos)

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

        ff = os.path.join(os.getcwd(), "plate_solve_image.fits")

        # give it some time seems like Maxim isnt ready if we hit it too fast
        time.sleep(0.5)

        logging.info(f"Saving image to {ff}")
        self.cam.saveimageCamera(ff)
        self.solved_j2000 = self.plate_solve_file(ff)
        self.set_solved_position_labels(self.solved_j2000)

    def setupCCDFrameBinning(self):
        # set camera dimensions to full frame and 1x1 binning
        (maxx, maxy) = self.cam.getsizeCamera()
        logging.info("Sensor size is %d x %d", maxx, maxy)

        width = maxx
        height = maxy

        self.cam.setframeCamera(0, 0, width, height)

        xbin = 2
        ybin = 2

        self.cam.setbinningCamera(xbin, ybin)

        logging.info("CCD size: %d x %d ", width, height)
        logging.info("CCD bin : %d x %d ", xbin, ybin)

    def plate_solve_file(self, fname):

        # FIXME activity progress bar doesnt work and is too big!
        #self.show_activity_bar()

        self.ui.statusbar.showMessage("Uploading image to astrometry.net...")
        self.app.processEvents()

        upres = self.astroclient.upload(fname)
        logging.info(f"upload result = {upres}")

        if upres['status'] != 'success':
            logging.error('upload failed!')
            self.ui.statusbar.showMessage("Uploading image failed!!!")
            err =  QtWidgets.QMessageBox()
            err.setIcon(QtWidgets.QMessageBox.Critical)
            err.setInformativeText("Error uploading image to astrometry.net!")
            err.setStandardButtons(QtWidgets.QMessageBox.Ok)
            err.exec()
            return

        self.ui.statusbar.showMessage("Upload successful")
        self.app.processEvents()

        sub_id = upres['subid']

#        print("sub_id=", sub_id)

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
                            print('Selecting job id', j)
                            solved_id = j
                            break

                loop_count += 1
                if loop_count > 30:
                    loop_count = 0

                time.sleep(0.5)

        self.ui.statusbar.showMessage(f"Job started - id = {solved_id}")
        self.app.processEvents()

        while True:
            job_stat = self.astroclient.job_status(solved_id)

#            print("job_stat", job_stat)

            if job_stat == 'success':
                break

            time.sleep(5)

        final = self.astroclient.job_status(solved_id)

#        print("final job status =", final)

        if final != 'success':
            print("Plate solve failed!")
            print(final)
            self.ui.statusbar.showMessage("Plate solve failed!")
            err =  QtWidgets.QMessageBox()
            err.setIcon(QtWidgets.QMessageBox.Critical)
            err.setInformativeText("Plate solve failed!")
            err.setStandardButtons(QtWidgets.QMessageBox.Ok)
            err.exec()
            return

        final_calib = self.astroclient.job_calib_result(solved_id)
        print("final_calib=", final_calib)

        self.ui.statusbar.showMessage("Plate solve succeeded")
        self.app.processEvents()

        solved_j2000 = SkyCoord(ra=final_calib['ra']*u.degree, dec=final_calib['dec']*u.degree, frame='fk5', equinox='J2000')

        return solved_j2000

    def store_skycoord_to_label(self, pos, lbl_ra, lbl_dec):
        lbl_ra.setText('  ' + pos.ra.to_string(u.hour, sep=":", pad=True))
        lbl_dec.setText(pos.dec.to_string(alwayssign=True, sep=":", pad=True))

    def target_use_solved_cb(self):
        self.target_j2000 = self.solved_j2000
        self.set_target_position_labels(self.target_j2000)

    def target_goto_cb(self):
        target_str = self.ui.target_ra_j2000_entry.toPlainText() + " "
        target_str += self.ui.target_dec_j2000_entry.toPlainText()
        logging.info(f"target_str = {target_str}")

        try:
            target = SkyCoord(target_str, unit=(u.hourangle, u.deg), frame='fk5', equinox='J2000')
        except ValueError:
            logging.error("Cannot GOTO invalid target POSITION!")
            err =  QtWidgets.QMessageBox()
            err.setIcon(QtWidgets.QMessageBox.Critical)
            err.setInformativeText(f"Invalid target coordinates!")
            err.setStandardButtons(QtWidgets.QMessageBox.Ok)
            err.exec()
            return

#        if target is None:
#            logging.error("Cannot GOTO no target POSITION!")
#            err =  QtWidgets.QMessageBox()
#            err.setIcon(QtWidgets.QMessageBox.Critical)
#            err.setInformativeText("Cannot GOTO - must enter target position first!")
#            err.setStandardButtons(QtWidgets.QMessageBox.Ok)
#            err.exec()
#            return

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

        self.tel.goto(target)

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


if __name__ == '__main__':
    logging.basicConfig(filename='pyastrometry_qt.log',
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

    logging.info('pyastrometry_qt starting')

    ARGS = parse_command_line()

    app = QtWidgets.QApplication(sys.argv)
    window = MyApp(app, ARGS)
    window.show()
    sys.exit(app.exec_())



