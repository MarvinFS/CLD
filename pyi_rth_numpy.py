# PyInstaller runtime hook for numpy circular import fix
# This must be imported before any other module uses numpy.fft
import numpy.fft._pocketfft_umath  # noqa: F401
import numpy.fft._pocketfft  # noqa: F401
import numpy.fft  # noqa: F401
