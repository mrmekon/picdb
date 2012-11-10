import os
import sys
import time
import struct
import jarray
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
from com.microchip.mplab.mdbcore.loader import LoadException
from com.microchip.mplab.mdbcore.translator.interfaces import ITranslator
from com.microchip.mplab.mdbcore.translator.exceptions import TranslatorException
from com.microchip.mplab.mdbcore.disasm import DisAsm
from com.microchip.mplab.mdbcore.memory.memorytypes import ProgramMemory
from com.microchip.mplab.mdbcore.memory.memorytypes import FileRegisters
from com.microchip.mplab.mdbcore.objectfileparsing.exception import ProgramFileParsingException
from com.microchip.mplab.mdbcore.platformtool import PlatformToolMetaManager
from com.microchip.mplab.mdbcore.symbolview.interfaces import SymbolViewProvider
from com.microchip.mplab.mdbcore.common.debug.SymbolType import eFundamentalType as VarType
from com.microchip.mplab.mdbcore.objectfileparsing import Dwarf
from com.microchip.mplab.mdbcore.objectfileparsing import MDBFileMagic

from com.microchip.mplab.mdbcore.ControlPointMediator.ControlPoint import BreakType
from com.microchip.mplab.mdbcore.ControlPointMediator import ControlPointMediator

System.setProperty("crownking.stream.verbosity", "quiet")

class picdebugger(com.microchip.mplab.util.observers.Observer):
    class StepType:
        IN = 0
        OVER = 1
        INSTR = 2
    
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
        alltools = PlatformToolMetaManager.getAllTools()
        # Name mangling, because they report stupid strings
        devname = self.devices[0].split(":=")[6] # name is 6th entry in device string
        if devname.find("PICkit") == 0:
            devname = devname.replace(" ", "") # damn tools report the wrong name
        elif devname.lower().find("real ice") >= 0:
            devname = "Real ICE"
        tool = [x for x in alltools if x.getName() == devname][0]
        self.factory.ChangeTool(self.assembly,
                                tool.getConfigurationObjectID(),
                                tool.getClassName(),
                                tool.getFlavor(),
                                self.devices[0])
        self.factory.SetToolProperties(self.assembly,None)

    def connect(self):
        # Connect to debugger
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

            # Get ELF parser to find filenames and paths
            self.file_magic = MDBFileMagic(file)
            self.dwarf = Dwarf(self.file_magic)
            self.comp_units = self.dwarf.getCompilationUnits()
            self.filenames = [x.getSourceFileAbsolutePath() for x in self.comp_units]
            
            
        except DebugException:
            print "Failed to load ELF onto target."
            return False
        except LoadException:
            print "File not found."
            return False
        return True

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
        print "%s:%d ==> 0x%X" % (fullpath.split("/")[-1], line+i, info.lStartAddr)
        addr = info.lStartAddr
        return addr

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

    def getDeviceFamily(self):
        bits = assembly.GetDevice().getFamilyCode()
        return assembly.GetDevice().getSubFamily()

    def getMemoryContents(self, addr, length, virtual=False):
        fr = self.assembly.getLookup().lookup(FileRegisters)
        data = jarray.zeros(length, "b")
        if virtual:
            mem = fr.GetVirtualMemory()
        else:
            mem = fr.GetPhysicalMemory()
        mem.RefreshFromTarget(addr, length)
        if mem.Read(addr, length, data) == length:
            return data        
        return None

    def getSymbolValue(self, symbol):
        sv = self.assembly.getLookup().lookup(SymbolViewProvider)
        info = sv.getRawSymbol(symbol)
        if not info:
            return None
        vartype = info.Type()
        varlength = info.ByteLength()
        data = self.getMemoryContents(info.Address(), varlength, virtual=True)
        if not data:
            return None

        # Unpack array into variable based on type
        fmtMap = {1: "b", 2: "h", 4: "i", 8: "q"}
        # TODO: fill out map of types and their signedness
        signMap = {VarType.ST_ULONG.value(): False,
                   VarType.ST_LONG.value(): True,
                   }
        if varlength > 8:
            # TODO: Handle complex symbols.  Struct or string or something.
            print "Symbol type not handled!"
            return None
        fmt = fmtMap[varlength]
        if vartype in signMap:
            fmt = fmt.lower() if signMap[vartype] else fmt.upper()
        # Special cases:
        if vartype == VarType.ST_FLOAT:
            fmt = "f"
        elif vartype == VarType.ST_DOUBLE:
            fmt = "d"
        return struct.unpack(fmt, data.tostring())[0]
        
        

    def addressToSourceLine(self, addr, stripdir=True):
        try:
            info = self.translator.addressToSourceLine(addr)
            f = info.file
            if stripdir:
                f = info.file.split("/")[-1]                
            return (f, info.lLine)
        except TranslatorException:
            return ("unknown",0)

    def step(self, type=StepType.OVER):
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

