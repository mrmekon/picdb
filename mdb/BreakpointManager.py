import os
from com.microchip.mplab.mdbcore.ControlPointMediator.ControlPoint import BreakType

class BreakpointManager:
    def __init__(self, controlPointMediator, translator, filenames):
        self.cpm = controlPointMediator
        self.translator = translator
        self.filenames = filenames
        self._breakpoints = []

    def findFile(self, filename):
        abspaths = [x for x in self.filenames if x.rfind(filename) >= 0]
        for path in abspaths:
            if os.path.exists(path):
                return path
        return None

    def findBreakableAddressInFile(self, filename, line):
        fullpath = self.findFile(filename)
        if fullpath is None:
            print "File not found."
            return None
        addr = None
        for i in range(20):
            try:
                info = self.translator.sourceLineToAddress(fullpath, line+i)
                if info:
                    break
            except TranslatorException:
                continue
        addr = info.lStartAddr
        return addr

    def addressToSourceLine(self, addr, stripdir=True):
        try:
            info = self.translator.addressToSourceLine(addr)
            f = info.file
            if stripdir:
                f = info.file.split("/")[-1]                
            return (f, info.lLine)
        except TranslatorException:
            return ("unknown",0)

    def setBreakpoint(self, addr):
        wcps = self.cpm.getWritableControlPointStore()
        if wcps.getNumberAvailableProgramControlPoints() > 0:
            bp = wcps.getNewControlPoint()
            bp.setBreakType(BreakType.PROGRAM)
            bp.setBreakAddress(addr)
            bp.setEnabled(True)
            (file,line) = self.addressToSourceLine(addr)
            bp.setFileNameAndLine(file, line)
            self._breakpoints.append(bp)
            self.cpm.commitAndReleaseWritableControlPointStore(wcps)
            return True
        return False

    def breakpointIndexForAddress(self, addr):
        result = -1
        for i,bp in enumerate(self._breakpoints):
            if bp.getBreakAddress() == addr:
                result = i
                break
        return result

    def allBreakpoints(self):
        return [(i,bp.getBreakAddress(),bp.getFileName(),
                 bp.getFileLine(), bp.getEnabled())
                for (i,bp) in enumerate(self._breakpoints)]

