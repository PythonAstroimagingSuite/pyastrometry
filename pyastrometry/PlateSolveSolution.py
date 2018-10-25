class PlateSolveSolution:
    """Stores solution from plate solve engine"""
    def __init__(self, radec, pixel_scale, angle, binning):
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
        self.binning = binning
