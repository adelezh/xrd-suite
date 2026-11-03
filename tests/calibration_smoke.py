"""Exercise stock pyFAI's fit AND ring rendering without importing Integration."""
import faulthandler
import time


def main():
    faulthandler.dump_traceback_later(45)
    from silx.gui import qt
    import silx.gui.utils.matplotlib  # Match pyFAI's application import order.
    import numpy as np
    from pyFAI.calibrant import CALIBRANT_FACTORY
    from pyFAI.detectors import detector_factory
    from pyFAI.gui.CalibrationContext import CalibrationContext
    from pyFAI.gui.tasks.GeometryTask import GeometryTask
    from pyFAI.gui.model.PeakModel import PeakModel

    app = qt.QApplication([])
    context = CalibrationContext()
    parent = qt.QMainWindow()
    context.setParent(parent)
    model = context.getCalibrationModel()
    settings = model.experimentSettingsModel()
    detector = detector_factory('PerkinElmer')
    calibrant = CALIBRANT_FACTORY('CeO2')
    calibrant.wavelength = .18e-10
    settings.detectorModel().setDetector(detector)
    settings.calibrantModel().setCalibrant(calibrant)
    settings.wavelength().setValue(calibrant.wavelength)
    settings.image().setValue(np.zeros(detector.shape, dtype=np.float32))
    azimuth = np.linspace(0, 2*np.pi, 30, endpoint=False)
    center = detector.shape[0] * detector.pixel1 / 2
    for ring, angle in enumerate(calibrant.get_2th()[:4]):
        radius = .3 * np.tan(angle)
        rows = (center + radius*np.sin(azimuth))/detector.pixel1 - .5
        cols = (center + radius*np.cos(azimuth))/detector.pixel2 - .5
        peak = PeakModel()
        peak.setName(chr(97+ring))
        peak.setRingNumber(ring+1)
        peak.setCoords(np.column_stack((rows, cols)))
        peak.setColor(qt.QColor('red'))
        model.peakSelectionModel().append(peak)

    started = time.monotonic()
    task = GeometryTask()
    task.setModel(model)
    # Invoke the same handlers used by pyFAI's geometry screen. These include
    # the expensive contour creation and plot updates missed by solver tests.
    task._GeometryTask__invalidatePeakSelection()
    task._GeometryTask__initGeometry()
    task._GeometryTask__fitGeometry()
    app.processEvents()
    fit = model.fittedGeometry()
    assert fit.isValid()
    assert abs(fit.distance().value() - .3) < 1e-4
    assert abs(fit.poni1().value() - center) < 1e-4
    assert abs(fit.poni2().value() - center) < 1e-4
    print(f'Stock pyFAI GUI fit completed in {time.monotonic()-started:.2f} s', flush=True)
    faulthandler.cancel_dump_traceback_later()
    task.close()
    parent.close()


if __name__ == '__main__':
    main()
