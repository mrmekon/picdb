import jarray
from com.microchip.mplab.mdbcore.disasm import DisAsm
from com.microchip.mplab.mdbcore.translator.exceptions import TranslatorException

class MemoryInterface:
    def __init__(self, fileRegisters, translator, disassembler,programMemory):
        self._fileRegs = fileRegisters
        self.translator = translator
        self.disassembler = disassembler
        self.mem = programMemory
        
    def getMemoryContents(self, addr, length, virtual=False):
        data = jarray.zeros(length, "b")
        if virtual:
            mem = self._fileRegs.GetVirtualMemory()
        else:
            mem = self._fileRegs.GetPhysicalMemory()
        mem.RefreshFromTarget(addr, length)
        if mem.Read(addr, length, data) == length:
            return data        
        return None

    def getCurrentLineDisassembly(self, pc):
        result = "PC: 0x%X" % pc
        try:
            info = self.translator.addressToSourceLine(pc)
            result += " (%s:%d)" % (info.file.split("/")[-1], info.lLine)
            lines = self.translator.sourceLinesFromAddress(pc, True)
            for sl in lines.result:
                ins = self.disassembler.Disassemble(
                    self.mem.ReadWord(sl.Address()),
                    self.mem.ReadWord(sl.Address() + sl.AddressIncrement()),
                    sl.Address() | (1 if sl.AddressIncrement() == 2 else 0),
                    DisAsm.OPTIONS.FULL_SYMBOLS,
                    None)
                result += " (%s)" % ins.instruction
        except TranslatorException:
            result += " Unknown line."
        return result
