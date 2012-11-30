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
        elements = symbol.replace(".","-.").split("-")
        if len(elements) > 1:
            print "Compound symbol!"

        info = self.sv.getRawSymbol(symbol)
        if not info:
            return None

        if VarType.get(info.Type()) == VarType.ST_STRUCT:
            return self.structParser.getStructAsString(info.Name(), info.Address())

        return self.structParser.getSymbolAsString(info.Name(), info.Address())
