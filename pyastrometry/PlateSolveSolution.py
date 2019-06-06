class PlateSolveSolution:
    """
    Stores solution from plate solve engine

    :param SkyCoord radec: RA/DEC of center of image.
    :param float pixel_scale: Pixel scale in arc-seconds/pixel
    :param Angle angle: Sky roll angle of image.
    """
    def __init__(self, radec, pixel_scale, angle, binning):
        """Create solution object

        """
        self.radec = radec
        self.pixel_scale = pixel_scale
        self.angle = angle
        self.binning = binning
