import logging
import win32com.client      #needed to load COM objects

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
