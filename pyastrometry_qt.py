# -*- coding: utf-8 -*-
"""
Created on Sat Aug 25 15:26:52 2018

@author: msf
"""

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

    def sync(self, pos):
        rc = self.tel.SyncToCoordinates(pos.ra.hour, pos.dec.degree)

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

        # connect to astrometry.net
        self.astroclient = Client()
        self.astroclient.login('***REMOVED***')

        self.ui.solve_file_button.clicked.connect(self.solve_file_cb)
        self.ui.sync_pos_button.clicked.connect(self.sync_pos_cb)

        # init vars
        self.solved_j2000 = None

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

        # get confirmation
        yesno = QtWidgets.QMessageBox()
        yesno.setIcon(QtWidgets.QMessageBox.Question)
        yesno.setInformativeText(f"Do you want to sync the mount?\n\nPostition: {solved_jnow.to_string('hmsdms')}")
        yesno.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        result = yesno.exec()
        print(result)

        if result == QtWidgets.QMessageBox.Yes:
            print("YES")

            # check if its WAY OFF
            sep = self.solved_j2000.separation(self.tel.get_position_j2000())
            logging.info(f"Sync pos is {sep.degree} degrees from current pos")

            if sep.degree > 10:
                yesno = QtWidgets.QMessageBox()
                yesno.setIcon(QtWidgets.QMessageBox.Question)
                yesno.setInformativeText(f"The sync position is {sep.degree:6.2f} degrees from current position!\nDo you REALLY want to sync the mount?")
                yesno.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
                result = yesno.exec()

                if result == QtWidgets.QMessageBox.Yes:
                    print("YES")
                    self.tel.sync(solved_jnow)
                else:
                    print("NO")
        else:
            print("NO")

    def solve_file_cb(self):
        fname, retcode = QtWidgets.QFileDialog.getOpenFileName(self, "Select file to solve:")
        logging.info(f"solve_file_cb: User selected file {fname}")
        if len(fname) < 1:
            logging.warning("solve_file_cb: User aborted file open")
            return

        self.solved_j2000 = self.plate_solve_file(fname)
        self.set_solved_position_labels(self.solved_j2000)

    def plate_solve_file(self, fname):

        # FIXME activity progress bar doesnt work and is too big!
        #self.show_activity_bar()

        self.ui.statusbar.showMessage("Uploading image to astrometry.net...")
        self.app.processEvents()

        upres = self.astroclient.upload('Focus.fit')
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
                for i in range(0, loop_count):
                    msgstr = msgstr + '.'
                logging.info(msgstr)
                self.ui.statusbar.showMessage("Upload successful - " + msgstr)
                self.app.processEvents()

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
                if loop_count > 3:
                    loop_count = 0

                time.sleep(5)


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

        solved_j2000 = SkyCoord(ra=final_calib['ra']*u.hour, dec=final_calib['dec']*u.degree, frame='fk5', equinox='J2000')

        return solved_j2000

    def store_skycoord_to_label(self, pos, lbl_ra, lbl_dec):
        lbl_ra.setText('  ' + pos.ra.to_string(u.hour, pad=True))
        lbl_dec.setText(pos.dec.to_string(alwayssign=True, pad=True))


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



