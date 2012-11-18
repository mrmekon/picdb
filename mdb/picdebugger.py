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
from com.microchip.mplab.mdbcore.objectfileparsing.dwarfconsts import TAG

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

    def entryOffset(self, entry):
        '''Return byte offset from DWARF entry's attributes.'''
        bytes = entry.getAttributeValue(ATTR.DW_AT_data_member_location)
        if not bytes or len(bytes) < 2:
            return 0
        return struct.unpack("B", bytes[1:2])[0]
    

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
        """Returns list of DWARF elements with all types for given entry.

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
        
        """
        if not maxdepth or not dwarfEntry.getAttributeValue(ATTR.DW_AT_type):
            return tree + [(dwarfEntry, dwarfCU)]
        (x,y) = self.dwarfResolveEntryType(dwarfEntry, dwarfCU)
        return self.dwarfEntryTypeTree(x,y,maxdepth-1,tree) + [(dwarfEntry,dwarfCU)]
        

    def findArrayLengthInEntry(self, entry):
        '''Return length of array if |entry| is an array.'''
        if (not entry
            or entry.tag != TAG.DW_TAG_array_type
            or not entry.hasChildren()):
            return 0
        for child in entry.children:
            if child.tag != TAG.DW_TAG_subrange_type:
                continue
            # 'count' is what we want, if it exists
            count = child.getAttributeValue(ATTR.DW_AT_count)
            if count:
                return count
            # 'upperBound' is guaranteed (I think) if 'count' isn't defined
            upperBound = child.getAttributeValue(ATTR.DW_AT_upper_bound)
            if not upperBound:
                return 0
            # 'lowerBound' is not required, defaults to 0 if missing.
            lowerBound = child.getAttributeValue(ATTR.DW_AT_lower_bound)
            lowerBound = 0 if not lowerBound else lowerBound
            return upperBound - lowerBound + 1

    def printStructMembers(self, memberArray, indent=0):
        '''Print formatted description of a structure.'''
        print "%s%s %s %s %s %s %s" % (
            ''.ljust(indent), "NAME".ljust(20),
            "OFF.".ljust(6), "SIZE".ljust(6), "ARRAY".ljust(6),
            "BITS".ljust(6), "CHLD".ljust(6))
        for member in memberArray:
            isBitfield = member['isBitfield']
            bitOffset = member['bitOffset']
            bitCount = member['bitCount']
            bitStr = "N/A".ljust(6) if not isBitfield else "%.2d-%.2d " % (bitOffset,bitOffset+bitCount)
            isArray = member['isArray']
            arrayLength = member['arrayLength']
            print "%s%s 0x%.4X 0x%.4X %s %s %s" % (
                ''.ljust(indent),
                member['name'][0:20].ljust(20),
                member['offset'],
                member['size'],
                "N/A".ljust(6) if not isArray else ("%d"%arrayLength).ljust(6),
                bitStr.ljust(6),
                str(member['hasChildren']).ljust(6))
            if member['hasChildren'] and member['children']:
                self.printStructMembers(member['children'], indent+4)

    def structMembersForStructEntry(self, entry, compUnit, maxdepth=3):
        '''Returns an array of dictionaries representing a struct.

        Given a DWARF entry |entry| which resolves eventually into a struct
        (i.e. variable, typedef, or struct), this function returns a list of
        dictionaries, one dictionary per struct member, with important
        attributes of the member stored in the dictionary.

        This function recursively resolves structs and arrays among the
        members, with a maximum depth of |maxdepth|.
        
        '''
        typeTree = self.dwarfEntryTypeTree(entry, compUnit)
        if not typeTree:
            return []
        (sEntry, sCU) = typeTree[0]
        if not sEntry.members:
            return []
            
        members = []            
        for member in sEntry.members:
            if member.tag == TAG.DW_TAG_null:
                break
            types = self.dwarfEntryTypeTree(member, sCU)
            children = []
            if (maxdepth > 0 and types[0][0].hasChildren()
                and types[0][0].kind == TAG.DW_TAG_structure_type):
                children = self.structMembersForStructEntry(types[0][0], compUnit, maxdepth-1)

            # Bit offsets are a special case.  These will be found in the second entry
            # of the tree (last entry before the primitive type).
            bitOffset = types[1][0].getAttributeValue(ATTR.DW_AT_bit_offset)
            bitCount = types[1][0].getAttributeValue(ATTR.DW_AT_bit_size)
            isBitfield = bitOffset or bitCount
            isArray = False
            arrayLength = 0
            for (t,cu) in types:
                if t.kind == TAG.DW_TAG_array_type:
                    isArray = True
                    arrayLength = self.findArrayLengthInEntry(t)
            members.append({
                "name": member.getName(),
                "offset": self.entryOffset(member),
                "size": types[0][0].getAttributeValue(ATTR.DW_AT_byte_size),
                "encoding": member.getAttributeValue(ATTR.DW_AT_encoding),
                "hasChildren": types[0][0].hasChildren(),
                "typeTree": types,
                "isUnion": types[0][0].kind == TAG.DW_TAG_union_type,
                "isStruct": types[0][0].kind == TAG.DW_TAG_structure_type,
                "isArray": isArray,
                "arrayLength": arrayLength,
                "isBitfield": isBitfield,
                "bitOffset": bitOffset,
                "bitCount": bitCount,
                "children": children
            })
        return members


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
            (entry,cu) = self.dwarfEntryFromNameAndAddress(info.Name(),info.Address())
            members = self.structMembersForStructEntry(entry,cu)
            self.printStructMembers(members)
            #return members
            return None
        
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

