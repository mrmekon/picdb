import sys
import time
import java.lang.String
import java.lang.System as System
import com.microchip.mplab.util.observers
import com.microchip.mplab.mdbcore.debugger.Debugger
from com.microchip.mplab.comm import MPLABCommProvider
from com.microchip.mplab.mdbcore.assemblies.assemblyfactory import MCAssemblyFactory
from com.microchip.mplab.mdbcore.debugger import Debugger
from com.microchip.mplab.mdbcore.debugger import DebugException
from com.microchip.mplab.mdbcore.debugger import ToolEvent
from com.microchip.mplab.mdbcore.loader import Loader
from com.microchip.mplab.mdbcore.translator.interfaces import ITranslator
from com.microchip.mplab.mdbcore.translator.exceptions import TranslatorException
from com.microchip.mplab.mdbcore.disasm import DisAsm
from com.microchip.mplab.mdbcore.memory.memorytypes import ProgramMemory

from com.microchip.mplab.mdbcore.ControlPointMediator.ControlPoint import BreakType
from com.microchip.mplab.mdbcore.ControlPointMediator import ControlPointMediator

System.setProperty("crownking.stream.verbosity", "quiet")

class picdebugger(com.microchip.mplab.util.observers.Observer):
    def __init__(self):
        self.mdb = None
        self._breakpoints = []
        self.isHalted = True

    def Update(self, obj):
        if obj.GetEvent() == ToolEvent.EVENTS.HALT:
            self.isHalted = True
        elif obj.GetEvent() == ToolEvent.EVENTS.RUN:
            self.isHalted = False

    def waitForHalt(self):
        while not self.isHalted:
            pass

    def getPC(self):
        return self.mdb.GetPC()
        
    def selectDevice(self, devstr):
        # Register PIC target device
        self.factory = MCAssemblyFactory()
        self.assembly = self.factory.Create(devstr)
        self.provider = MPLABCommProvider()

    def enumerateDevices(self):
        # Enumerate USB debuggers
        try:
            self.devices = self.provider.GetCurrentToolList(None, "USB","04D8", None)
            if not self.devices:
                print "No USB debugger found."
        except DebugException:
            print "Failed to enumerate USB devices."
            return False
        return True

    def run(self):
        self.mdb.Run()

    def setBreakpoint(self, addr):
        self.cpm = self.assembly.getLookup().lookup(ControlPointMediator)
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
            print "New breakpoint at 0x%X (%s:%d)" % (bp.getBreakAddress(), file, line)
            return True
        return False

    def breakpointIndexForAddress(self, addr):
        result = -1
        for i,bp in enumerate(self._breakpoints):
            if bp.getBreakAddress() == addr:
                result = i
                break
        return result

    def listBreakpoints(self):
        print "All breakpoints:"
        for i,bp in enumerate(self._breakpoints):
            print "%d: 0x%X (%s:%d) %c" % (i, bp.getBreakAddress(),
                bp.getFileName(), bp.getFileLine(),
                '*' if bp.getEnabled() else ' ')

    def selectDebugger(self):
        # Select PICkit3 debugger
        self.factory.ChangeTool(self.assembly,
                                "PICkit3PlatformTool",
                                "com.microchip.mplab.mdbcore.PICKit3Tool.PICkit3DbgToolManager",
                                "debuggerProgrammer",
                                self.devices[0])
        self.factory.SetToolProperties(self.assembly,None)

    def connect(self):
        # Connect to debugger
        self.assembly.SetHeader("");
        self.mdb = self.assembly.getLookup().lookup(Debugger)

        print "Connecting to PICkit3..."
        try:
            self.mdb.Attach(self, None)
            self.mdb.Connect(Debugger.CONNECTION_TYPE.DEBUGGER)
        except DebugException:
            print "Failed to connect to debugger."
            return False
        return True

    def load(self, file):
        # Load ELF file onto target
        self.loader = self.assembly.getLookup().lookup(Loader)
        print "Loading ELF file..."
        try:
            self.loader.Load(file)
            self.mdb.Program(Debugger.PROGRAM_OPERATION.AUTO_SELECT)
            self.translator = self.assembly.getLookup().lookup(ITranslator)
            self.disassembler = self.assembly.getLookup().lookup(DisAsm)
            self.mem = self.assembly.getLookup().lookup(ProgramMemory).GetVirtualMemory()
        except DebugException:
            print "Failed to load ELF onto target."
            return False
        return True

    def testSourceLookup(self):
        sourcefile = "/path/to/MainDemo.c"
        line = 248
        info = self.translator.sourceLineToAddress(sourcefile, line)
        print "%s:%d ==> 0x%X" % (sourcefile.split("/")[-1], line, info.lStartAddr)

    def reset(self):
        # Reset to main
        print "Resetting target..."
        self.mdb.Reset(True)
        pc = self.mdb.GetPC()
        print "PC: 0x%X" % pc

    def disconnect(self):
        if self.mdb:
            self.mdb.Disconnect()

    def addressToSourceLine(self, addr):
        try:
            info = self.translator.addressToSourceLine(addr)
            return (info.file.split("/")[-1], info.lLine)
        except TranslatorException:
            return ("unknown",0)

    def step(self):
        try:
            self.mdb.StepOver()
        except DebugException:
            print "Lost communication with debugger or target!"
            return
        pc = self.mdb.GetPC()
        print "PC: 0x%X" % pc,
        try:
            info = self.translator.addressToSourceLine(pc)
            print " (%s:%d)" % (info.file.split("/")[-1], info.lLine),
            lines = self.translator.sourceLinesFromAddress(pc, True)
            for sl in lines.result:
                ins = self.disassembler.Disassemble(
                    self.mem.ReadWord(sl.Address()),
                    self.mem.ReadWord(sl.Address() + sl.AddressIncrement()),
                    sl.Address() | (1 if sl.AddressIncrement() == 2 else 0),
                    DisAsm.OPTIONS.FULL_SYMBOLS,
                    None)
                print " (%s)" % ins.instruction,
        except TranslatorException:
            print " Unknown line.",
        print

