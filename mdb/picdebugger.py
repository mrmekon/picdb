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
from com.microchip.mplab.mdbcore.objectfileparsing.dwarfconsts import ATTR
from com.microchip.mplab.mdbcore.objectfileparsing.dwarfconsts import LEOE

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

    def initDwarfSymbols(self):
        '''Cache a global list of ALL known DWARF entries from all compilation units.'''
        self.dwarfEntries = [(entry,unit) for unit in self.comp_units
                             for entry in unit.getEntries()]
        # TODO: Only recurse once here.  Is that enough?
        self.dwarfEntries.extend(
            [(child,unit) for unit in self.comp_units
             for entry in unit.getEntries()
                for child in entry.children])

    def structEntryAddress(self, entry):
        '''Extract address from DWARF entry.  Returns 0 if none available.'''
        addr = entry.getAttributeValue(ATTR.DW_AT_location)
        # Not all entries have addresses:
        if not addr: 
            return 0
        # Entries that have addresses should start with the addr operation
        if LEOE.get(addr[0]) != LEOE.DW_OP_addr:
            print "WARNING: Struct entry address is malformed."
            return 0
        # Unpack the address as 4-byte, little endian word.
        # TODO: Architecture dependency!
        return struct.unpack("<I", addr[1:])[0]


    def dwarfResolveEntryType(self, dwarfEntry, dwarfCU):
        '''Returns tuple (type,compilation unit) with type of given entry.'''
        typeOffset = dwarfEntry.getAttributeValue(ATTR.DW_AT_type)
        if not typeOffset:
            return (dwarfEntry, dwarfCU)
        idx = dwarfCU.unit_offset + typeOffset
        entries = [(x,cu) for (x,cu) in self.dwarfEntries
                   if x.fileRefference == idx]
        if not entries:
            return (None, None)
        return entries[0]

    def dwarfEntryFromNameAndAddress(self, name, address):
        '''Returns DWARF entry for symbol with given name at given address'''
        declsWithName = [(x,cu) for (x,cu) in self.dwarfEntries
                         if x.getName() == name]
        if not declsWithName:
            return (None, None)
        declsWithAddress = [(x,cu) for (x,cu) in declsWithName
                            if self.structEntryAddress(x) == address]
        if not declsWithAddress:
            return (None, None)
        return declsWithAddress[0]

    def dwarfEntryTypeTree(self, dwarfEntry, dwarfCU, maxdepth=15, tree=[]):
        '''Returns list of DWARF elements with all types for given entry.

        A DWARF entry, |dwarfEntry|, can consist of a long line of struct
        or typedef types.  This function traverses down the chain of types
        until it finds a 'primitive' type, and then returns the chain in
        reverse.

        Returns a list of tuples in format (dwarfEntry, dwarfCU).

        Ex:
        Definitions: typedef struct myType_t {...} myType; myType myVar;
        Start entry: |dwarfEntry| represents myVar
        Returns: [myType_t pair, myType pair, myVar pair]

        Definitions: typedef ULONG unsigned long; ULONG myLong;
        Start entry: |dwarfEntry| represents myLong
        Returns: [unsigned long pair, ULONG pair, myLong pair]
        
        '''
        if not maxdepth or not dwarfEntry.getAttributeValue(ATTR.DW_AT_type):
            return tree + [(dwarfEntry, dwarfCU)]
        (x,y) = self.dwarfResolveEntryType(dwarfEntry, dwarfCU)
        return self.dwarfEntryTypeTree(x,y,maxdepth-1,tree) + [(dwarfEntry,dwarfCU)]
        

    def traverseStruct(self, symbol):
        (entry, cu) = self.dwarfEntryFromNameAndAddress(symbol.Name(), symbol.Address())
        typeTree = self.dwarfEntryTypeTree(entry,cu)
        return typeTree[0]

    def structMembersForSymbol(self, symbolStr):
        sv = self.assembly.getLookup().lookup(SymbolViewProvider)
        symbol = sv.getRawSymbol(symbolStr)
        (sEntry, sCU) = self.traverseStruct(symbol)
        if not sEntry or not sCU:
            print "Couldn't find structure details."
            return
        return [x.getName() for x in sEntry.members]

        
    def recursiveEntryTraverse(self, entry):
        '''Debug function.'''
        print hex(entry.getFileRefference())
        for child in entry.children:
            self.recursiveEntryTraverse(child)

    def debugNotes(self):
        from com.microchip.mplab.mdbcore.symbolview.interfaces import SymbolViewProvider
        from com.microchip.mplab.mdbcore.objectfileparsing.dwarfconsts import ATTR
        from com.microchip.mplab.mdbcore.objectfileparsing.dwarfconsts import LEOE
        sv = self.dbg.assembly.getLookup().lookup(SymbolViewProvider)
        symbol = sv.getRawSymbol("AppConfig")
        (entry,cu) = self.dbg.dwarfEntryFromNameAndAddress(symbol.Name(),symbol.Address())
        self.dbg.dwarfEntryTypeTree(entry, cu)
        
        self.dbg.initDwarfSymbols()
        typedef = symbol.typeDefName()
        alldecls = [x for (x,_) in self.dbg.dwarfDecls if x.getName() == symbol.Name()]
        decls = [x for x in alldecls if self.dbg.structEntryAddress(x) == symbol.Address()]
        import struct
        decs = [struct.unpack("<I", x.getAttributeValue(ATTR.DW_AT_location)[1:])[0] for x in decls if x.getAttributeValue(ATTR.DW_AT_location)]
        if not decs:
            print "Symbol not found in DWARF info."
            return
        decl = decs[0]

        self.dbg.dwarfEntries[1][0]
        sEntry.members[8]
        sEntry.members[11] 
        
        
    def getAppStruct(self):
        decs = [x.getDeclarations() for x in self.comp_units]
        configs = [b for c in decs for b in c if b and b.getName() == "AppConfig"]
        configs[0].getTypeDef()
        configs[0].tag # DW_TAG_variable
        [x.getDeclarationFilePath() for x in configs]

        ents = [x.getEntries() for x in self.comp_units]
        
        aconfs = [entry for unit in self.dbg.comp_units
                  for entry in unit.getEntries()
                  if entry.getName() == "APP_CONFIG"]
        aconfs[0].getType()
        aconfs[0].tag # DW_TAG_typedef
        
        astructs = [(entry,unit) for unit in self.dbg.comp_units
                    for entry in unit.getEntries()
                    if entry.getName() == "appConfigStruct"]
        astructs[0][0].tag # DW_TAG_structure_type
        members = astructs[0][0].getMembers()
        members[0].getType() # DWORD_VAL

        mac = [x for x in members if x.getName() == "MyMACAddr"][0]
        mac.getTypeDef() # MAC_ADDR

        flags = [x for x in members if x.getName() == "Flags"][0]
        flags.getType() # ''
        from com.microchip.mplab.mdbcore.objectfileparsing.dwarfconsts import ATTR
        flags.getAttributeValue(ATTR.DW_AT_type) # 0x114b -- address of anonymous struct

        # Offset into parent structure in bytes:
        from com.microchip.mplab.mdbcore.objectfileparsing.dwarfconsts import LEOE
        (op, offset) = flags.getAttributeValue(ATTR.DW_AT_data_member_location)
        LEOE.get(op) == LEOE.DW_OP_plus_uconst

        # Search for an entry by type.
        from com.microchip.mplab.mdbcore.objectfileparsing.dwarfconsts import TAG
        [entry for unit in self.dbg.comp_units for entry in unit.getEntries() if entry.kind == TAG.DW_TAG_typedef and entry.getAttributeValue(ATTR.DW_AT_type) == 0x114b]

        # The type of flag (an anonymous struct, 0x114b) doesn't exist in the comp units.
        
        stask = self.dwarf.getCompilationUnit("Microchip/TCPIP Stack/StackTsk.c") 
        struct = [x for x in stask.getEntries() if x.getName() == "appConfigStruct"][0]
        struct.getChildren()

    def load(self, file):
        # Load ELF file onto target
        self.loader = self.assembly.getLookup().lookup(Loader)
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
            self.initDwarfSymbols()
            
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
        addr = info.lStartAddr
        return addr

    def testSourceLookup(self):
        sourcefile = "/path/to/MainDemo.c"
        line = 248
        info = self.translator.sourceLineToAddress(sourcefile, line)
        print "%s:%d ==> 0x%X" % (sourcefile.split("/")[-1], line, info.lStartAddr)

    def reset(self):
        # Reset to main
        self.mdb.Reset(True)

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

    def getFunctionAddress(self, funcname):
        sv = self.assembly.getLookup().lookup(SymbolViewProvider)
        info = sv.getRawSymbol(funcname)
        if not info or info.Type() != 64: # 64 is magic number found by inspection
            return None
        return info.Address()

    def getStructSymbol(self, symbol):
        # struct type VarType.ST_STRUCT (8)
        # local symbols:
        #x = sv.resolve(symbol, pc, False)
        from com.microchip.mplab.mdbcore.symbolview import SymbolInfoDefault
        y = SymbolInfoDefault(info)
        sv.readIntegralMemberValuesOnly(y)
        sv.readValueInformation(y)
        pc = getPC()
        sv.getLocalSymbols(pc)
        pass

    def getSymbolValue(self, symbol):
        sv = self.assembly.getLookup().lookup(SymbolViewProvider)
        info = sv.getRawSymbol(symbol)
        if not info:
            return None
        vartype = info.Type()

        if VarType.get(vartype) == VarType.ST_STRUCT:
            return self.structMembersForSymbol(symbol)
        
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

