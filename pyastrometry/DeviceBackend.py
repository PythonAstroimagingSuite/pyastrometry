# This shouldnt be used any more!
#
# Only here for reference!
#

import warnings

warnings.filterwarnings('error', category=ImportWarning)

warnings.warn('DeviceBackend is not long supported!', ImportWarning)

class DeviceBackend:
    def __init__(self):
        pass



    def connect(self):
        pass
