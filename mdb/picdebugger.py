import os
import sys
import time
import struct
import java.lang.String
import java.lang.System as System
import com.microchip.mplab.util.observers
import com.microchip.mplab.mdbcore.debugger.Debugger
from StructParser import StructParser
from SymbolParser import SymbolParser
from DeviceFinder import DeviceFinder
from MemoryInterface import MemoryInterface
from BreakpointManager import BreakpointManager
from com.microchip.mplab.comm import MPLABCommProvider
from com.microchip.mplab.mdbcore.assemblies.assemblyfactory import MCAssemblyFactory
from com.microchip.mplab.mdbcore.debugger import Debugger
from com.microchip.mplab.mdbcore.debugger import DebugException
from com.microchip.mplab.mdbcore.debugger import ToolEvent
from com.microchip.mplab.mdbcore.loader import Loader
from com.microchip.mplab.mdbcore.loader import LoadException
from com.microchip.mplab.mdbcore.translator.interfaces import ITranslator
from com.microchip.mplab.mdbcore.disasm import DisAsm
from com.microchip.mplab.mdbcore.memory.memorytypes import ProgramMemory
from com.microchip.mplab.mdbcore.memory.memorytypes import FileRegisters
from com.microchip.mplab.mdbcore.objectfileparsing.exception import ProgramFileParsingException
from com.microchip.mplab.mdbcore.symbolview.interfaces import SymbolViewProvider
from com.microchip.mplab.mdbcore.objectfileparsing import Dwarf
from com.microchip.mplab.mdbcore.objectfileparsing import MDBFileMagic
from com.microchip.mplab.mdbcore.ControlPointMediator import ControlPointMediator

System.setProperty("crownking.stream.verbosity", "quiet")

class picdebugger(com.microchip.mplab.util.observers.Observer):
    class StepType:
        IN = 0
        OVER = 1
        INSTR = 2
    
    def __init__(self):
        self.isHalted = True
        self.factory = MCAssemblyFactory()
        self.provider = MPLABCommProvider()
        self.mdb = None
        self.structParser = None
        self.memoryIface = None
        self.assembly = None
        self.breakpointManager = None
        self.symbolParser = None
        self.deviceFinder = None

    def selectTarget(self, targetstr):
        """Select PIC target"""
        self.assembly = self.factory.Create(targetstr)
        self.deviceFinder = DeviceFinder(self.provider, self.factory, self.assembly)

    def connect(self):
        """Connect to the debugger hardware"""
        self.assembly.SetHeader("");
        self.mdb = self.assembly.getLookup().lookup(Debugger)

        print "Connecting to debugger..."
        try:
            self.mdb.Attach(self, None)
            self.mdb.Connect(Debugger.CONNECTION_TYPE.DEBUGGER)
        except DebugException:
            print "Failed to connect to debugger."
            return False
        return True

    def disconnect(self):
        """Disconnect from target"""
        if self.mdb:
            self.mdb.Disconnect()

    def load(self, file):
        """Load a file onto target, and prepare all data for it."""
        loader = self.assembly.getLookup().lookup(Loader)
        try:
            loader.Load(file)
            self.mdb.Program(Debugger.PROGRAM_OPERATION.AUTO_SELECT)
            
            # Get ELF parser to find filenames and paths
            dwarf = Dwarf(MDBFileMagic(file))
            comp_units = dwarf.getCompilationUnits()
            filenames = [x.getSourceFileAbsolutePath() for x in comp_units]

            translator = self.assembly.getLookup().lookup(ITranslator)
            fr = self.assembly.getLookup().lookup(FileRegisters)
            disassembler = self.assembly.getLookup().lookup(DisAsm)
            progMem = self.assembly.getLookup().lookup(ProgramMemory).GetVirtualMemory()
            cpm = self.assembly.getLookup().lookup(ControlPointMediator)
            sv = self.assembly.getLookup().lookup(SymbolViewProvider)

            self.memoryIface = MemoryInterface(fr, translator, disassembler, progMem)
            self.structParser = StructParser(dwarf, self.memoryIface)            
            self.breakpointManager = BreakpointManager(cpm, translator, filenames)
            self.symbolParser = SymbolParser(sv, self.memoryIface, self.structParser)
            
        except DebugException:
            print "Failed to load ELF onto target."
            return False
        except LoadException:
            print "File not found."
            return False
        return True

    def reset(self):
        """Reset target to start address."""
        self.mdb.Reset(True)

    def run(self):
        """Tell debugger to free-run until stopped or breakpoint."""
        self.mdb.Run()

    def waitForHalt(self):
        """Spin loop until debugger halts"""
        while not self.isHalted:
            time.sleep(0.1)

    def Update(self, obj):
        """Callback when debugger experiences an event."""
        if obj.GetEvent() == ToolEvent.EVENTS.HALT:
            self.isHalted = True
        elif obj.GetEvent() == ToolEvent.EVENTS.RUN:
            self.isHalted = False

    def step(self, type=StepType.OVER):
        """Step the target."""
        try:
            if type == self.StepType.OVER:
                self.mdb.StepOver()
            elif type == self.StepType.IN:
                self.mdb.StepIn()
            else:
                self.mdb.StepInstr()
        except DebugException:
            print "Lost communication with debugger or target!"
            return
        print self.getCurrentLineDisassembly()

    def getPC(self):
        """Return current Program Counter (integer)"""
        return self.mdb.GetPC()
        

    # This needs to be fixed.  These have all been moved to
    # other classes.
    def setBreakpoint(self, addr):
        return self.breakpointManager.setBreakpoint(addr)
    def breakpointIndexForAddress(self, addr):
        return self.breakpointManager.breakpointIndexForAddress(addr)
    def allBreakpoints(self):
        return self.breakpointManager.allBreakpoints()
    def findFile(self, filename):
        return self.breakpointManager.findFile(filename)
    def findBreakableAddressInFile(self, filename, line):
        return self.breakpointManager.findBreakableAddressInFile(filename,line)
    def addressToSourceLine(self, addr, stripdir=True):
        return self.breakpointManager.addressToSourceLine(addr, stripdir)
    def getFunctionAddress(self, funcname):
        return self.symbolParser.getFunctionAddress(funcname)
    def getSymbolValue(self, symbol):
        return self.symbolParser.getSymbolValue(symbol)
    def enumerateDevices(self):
        self.deviceFinder.enumerateDevices()
    def connectedDeviceStrings(self):
        self.deviceFinder.connectedDeviceStrings()
    def selectDebugger(self):
        self.deviceFinder.selectDebugger()

    def getCurrentLineDisassembly(self):
        return self.memoryIface.getCurrentLineDisassembly(self.getPC())


