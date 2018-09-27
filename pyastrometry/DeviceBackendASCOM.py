
import sys
import json
import time
import logging
from datetime import datetime
import win32com.client

from threading import current_thread

from astropy.time import Time
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.coordinates import FK5

from PyQt5 import QtNetwork, QtWidgets

from pyfocusstars4.DeviceBackend import DeviceBackend

class MaximDLCamera:
    def __init__(self):
        self.cam = None

    def connectCamera(self):
#        logging.info(f"connectCamera name = {name}")
        # setup Maxim/CCD

        logging.info("connectCamera main thread")
#        import pythoncom
#        logging.info("connectCamera - calling CoInitialize()")
#        pythoncom.CoInitialize()
        self.cam = win32com.client.Dispatch("MaxIm.CCDCamera")
        self.cam.LinkEnabled = True
        self.cam.DisableAutoShutDown = True

        return True

    # FIXME ignores filename passed to RPC server -
    # probably ought to put saveImage here and use filename?
    def takeframeCamera(self, expos, filename=None):
        logging.info(f'Exposing image for {expos} seconds')

        self.cam.Expose(expos, 1, -1)

        # ignore filename for now!
#        if filename is not None:
#            self.saveimageCamera(filename)

        return True

    def takeframe_saves_file(self):
        return False

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
            logging.info('saveimageCamera %s exception with message "%s" in %s' % \
                              (exc_type.__name__, exc_value, current_thread().name))
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

class RPCCamera:
    def __init__(self, mainThread=True):
        self.mainThread = mainThread
        self.socket = None
        self.json_id = 0
        self.port = 8800

        # FIXME can only handle one method/response outstanding
        # at a time!
        self.outstanding_reqid = None
        self.outstanding_complete = False

        self.roi = None
        self.binning = 1
        self.frame_width = None
        self.frame_height = None

    def connectCamera(self):
        logging.info(f'connectCamera: Connecting to RPCServer 127.0.0.1:{self.port}')

        # FIXME Does this leak sockets?  Need to investigate why
        # setting self.socket = None causes SEGV when disconnected
        # (ie PHD2 closes).
        self.socket = QtNetwork.QTcpSocket()
        self.socket.connectToHost('127.0.0.1', self.port)

        logging.info('waiting')

        # should be quick so we connect synchronously
        if not self.socket.waitForConnected(5000):
            logging.error('Could not connect to RPCServer')
            self.socket = None
            return False

        self.socket.readyRead.connect(self.process)

        return True

    def disconnectCamera(self):
        self.socket.disconnectFromHost()
        self.socket = None

    def process(self):
        if not self.socket:
            logging.error('server not connected!')
            return False

        logging.info(f'process(): {self.socket}')

        while True:
            resp = self.socket.readLine(2048)

            if len(resp) < 1:
                break

            logging.info(f'server sent {resp}')

            try:
                j = json.loads(resp)

            except Exception as e:
                logging.error(f'RPCServer_client_test - exception message was {resp}!')
                logging.error('Exception ->', exc_info=True)
                continue

            logging.info(f'json = {j}')

            if 'Event' in j:
                if j['Event'] == 'Connection':
                    servid = None
                    vers = None
                    if 'Server' in j:
                        servid = j['Server']
                    if 'Version' in j:
                        vers = j['Version']
                    logging.info(f'Server ack on connection: Server={servid} Version={vers}')
                elif j['Event'] == 'Ping':
                    logging.info('Server ping received')
            elif 'jsonrpc' in j:
                reqid = j['id']
                result = j['result']
                logging.info(f'result of request {reqid} was {result} {type(result)}')
                if reqid == self.outstanding_reqid:
                    self.outstanding_complete = True
                    self.outstanding_result = result

        return

    def send_server_request(self, req, paramsdict=None):
        reqdict = {}
        reqdict['method'] = req

        if paramsdict is not None:
            reqdict['params'] = paramsdict

        return self.__send_json_message(reqdict)

    def __send_json_message(self, cmd):
        # don't use 0 for an id since we return id as success code
#        if self.json_id == 0:
#            self.json_id = 1
        cmd['id'] = self.json_id
        self.json_id += 1

        cmdstr = json.dumps(cmd) + '\n'
        logging.info(f'__send_json_message->{bytes(cmdstr, encoding="ascii")}')

        try:
            self.socket.writeData(bytes(cmdstr, encoding='ascii'))
        except Exception as e:
            logging.error(f'__send_json_message - cmd was {cmd}!')
            logging.error('Exception ->', exc_info=True)
            return False

        return (True, cmd['id'])

    # FIXME this is different than MaximDL where we take
    # frame and then call saveimageCamera() to save it!
    # Here we set exposure time and filename at start!
    def takeframeCamera(self, expos, filename):
        logging.info(f'Exposing image for {expos} seconds')

        paramdict = {}
        paramdict['exposure'] = expos
        paramdict['binning'] = self.binning
        paramdict['roi'] = self.roi
        paramdict['filename'] = filename
        rc = self.send_server_request('take_image', paramdict)

        if not rc:
            logging.error('RPC:takeframeCamera - error')
            return False

        _, reqid = rc

        # FIXME this is clunky
        self.outstanding_reqid = reqid
        self.outstanding_complete = False

        return True

    def takeframe_saves_file(self):
        return True

    def checkexposureCamera(self):
        # connect to response from RPC server in process()
        # FIXME this could break so many ways as it doesnt
        # link up to the actual id expected for method result
        return self.outstanding_complete

    def saveimageCamera(self, path):
        # this does nothing since RPC Server saves image to a name
        # for us when we request an exposure
        return True

    def closeimageCamera(self):
        # this does nothing
        return True

    def getbinningCamera(self):
        # cache values we will use when takes exposure
        # we don't actually inquire RPCServer for current values!
        return (self.binning, self.binning)

    def setbinningCamera(self, binx, biny):
        # just ignore biny
        # cache for when we are going to take an exposure
        self.binning = binx

        if not self.frame_width or not self.frame_height:
            self.get_camera_settings()

        self.roi = (0, 0, self.frame_width/self.binning, self.frame_height/self.binning)
        return True

    def get_camera_settings(self):
        rc = self.send_server_request('get_camera_info', None)

        if not rc:
            logging.error('RPC get_camera_settigns: error sending json request!')
            return False

        _, reqid = rc

        # I suppose the response could get back before this next
        # line is run??  So in process() we'd miss it?
        self.outstanding_reqid = reqid

        # FIXME this shouldn't be a problem unless RPC Server dies
        # FIXME add timeout
        # block until we get answer
        while not self.outstanding_complete:
            time.sleep(0.1)

            # FIXME YUCK wont get response if QtNetwork isnt
            # getting cycles
            QtWidgets.QApplication.processEvents()
            pass

        resp = self.outstanding_result

        logging.info(f'RPC get_camera_setting resp = {resp}')

        if 'framesize' in resp:
            w, h = resp['framesize']
            self.frame_width = w
            self.frame_height = h
        if 'binning' in resp:
            self.setbinningCamera(resp['binning'], resp['binning'])
        if 'roi' in resp:
            self.roi = resp['roi']

    def getsizeCamera(self):
        if not self.frame_width or not self.frame_height:
            self.get_camera_settings()

        return (self.frame_width, self.frame_height)

    def getframeCamera(self):
        return self.roi

    def setframeCamera(self, minx, miny, width, height):
        self.roi = (minx, miny, width, height)
        return True


class DeviceBackendASCOM(DeviceBackend):

    def __init__(self):
#        self.cam = None
 #       self.cam_name = None
#        self.focus = None
        self.connected = False
#        self.mainThread = mainThread


    def connect(self):
        self.connected = True

    def isConnected(self):
        return self.connected

    class Camera:
        def __init__(self):
            self.cam = None
            self.connected = False

        def is_connected(self):
            return self.connected

        def connect(self, name):
            logging.info(f"connectCamera name = {name}")
            # setup Maxim/CCD

            if name == 'MaximDL':
                self.driver = MaximDLCamera()
            elif name == 'RPC':
                self.driver = RPCCamera()
            else:
                logging.error(f'ASCOM:connectCamera - known camera name {name}')
                return False

            self.driver.connectCamera()
            self.connected = True

            return True

        def takeframeCamera(self, expos, filename):
            logging.info(f'Exposing image for {expos} seconds')

            self.driver.takeframeCamera(expos, filename)

            return True

        def takeframe_saves_file(self):
            return self.driver.takeframe_saves_file()

        def checkexposureCamera(self):
            return self.driver.checkexposureCamera()

        def saveimageCamera(self, path):
            return self.driver.saveimageCamera(path)

        def closeimageCamera(self):
            return self.driver.closeimageCamera()

        def getbinningCamera(self):
            return self.driver.getbinningCamera()

        def setbinningCamera(self, binx, biny):
            return self.driver.setbinningCamera(binx, biny)

        def getsizeCamera(self):
            return self.driver.getsizeCamera()

        def getframeCamera(self):
            return self.driver.getframeCamera()

        def setframeCamera(self, minx, miny, width, height):
            return self.driver.setframeCamera(minx, miny, width, height)

    class Focuser:
        def __init__(self):
            self.focus = None
            self.connected = False

        def connectFocuser(self, name):
#            import pythoncom
#            logging.info("connectFocuser - calling CoInitialize()")
#            pythoncom.CoInitialize()
            logging.info(f'focuser = {name}')
            self.focus = win32com.client.Dispatch(name)
            logging.info(f"self.focus = {self.focus}")
            if self.focus.Connected:
                logging.info('	-> Focuser was already connected')
            else:
                self.focus.Connected = True

            if self.focus.Connected:
                logging.info(f'	Connected to focuser {name} now')
            else:
                logging.info('	Unable to connect to focuser, expect exception')

            # check focuser works in absolute position
            if not self.focus.Absolute:
                logging.info('ERROR - focuser does not use absolute position!')

            return True

        def is_connected(self):
            return self.connected

        def getabsposFocuser(self):
            return self.focus.Position

        def setabsposFocuser(self, abspos):
            self.focus.Move(abspos)

            return True

        def ismovingFocuser(self):
            return self.focus.isMoving

    class Telescope:
        def __init__(self):
            self.tel = None
            self.connected = False

        @staticmethod
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
            return pos_J2000.transform_to(FK5(equinox=Time(time_now.jd, format='jd', scale='utc')))

        @staticmethod
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
            return self.precess_JNOW_to_J2000(pos_jnow)

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
