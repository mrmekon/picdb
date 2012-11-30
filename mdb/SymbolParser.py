from StructParser import StructParser
from com.microchip.mplab.mdbcore.common.debug.SymbolType import eFundamentalType as VarType

class SymbolParser:
    def __init__(self, symbolProvider, memoryInterface, structParser):
        self.sv = symbolProvider
        self.memoryIface = memoryInterface
        self.structParser = structParser

    def getFunctionAddress(self, funcname):
        info = self.sv.getRawSymbol(funcname)
        if not info or info.Type() != 64: # 64 is magic number found by inspection
            return None
        return info.Address()

    def getSymbolValue(self, symbol):
        info = self.sv.getRawSymbol(symbol)
        if not info:
            return None
        vartype = info.Type()

        if VarType.get(vartype) == VarType.ST_STRUCT:
            (entry,cu) = self.structParser.dwarfEntryFromNameAndAddress(info.Name(),info.Address())
            members = self.structParser.structMembersForStructEntry(entry,cu)
            #self.printStructMembers(members)
            structstr = "{\n"
            for member in members:
                structstr += "    %s = %s,\n" % (member['name'],
                                               self.structParser.structMemberValue(info.Address(), member))
            #return members
            structstr += "}"
            return structstr
        
        varlength = info.ByteLength()
        data = self.memoryIface.getMemoryContents(info.Address(), varlength, virtual=True)
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
    
