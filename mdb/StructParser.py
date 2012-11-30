import os
import sys
import struct
from com.microchip.mplab.mdbcore.objectfileparsing.dwarfconsts import ATTR
from com.microchip.mplab.mdbcore.objectfileparsing.dwarfconsts import ATE
from com.microchip.mplab.mdbcore.objectfileparsing.dwarfconsts import LEOE
from com.microchip.mplab.mdbcore.objectfileparsing.dwarfconsts import TAG

class StructParser:
    def __init__(self, dwarf, memoryInterface):
        self.dwarfEntries = self.initDwarfSymbols(dwarf.getCompilationUnits())
        self.memoryIface = memoryInterface
        
    def initDwarfSymbols(self, comp_units):
        '''Cache a global list of ALL known DWARF entries from all compilation units.'''
        dwarfEntries = [(entry,unit) for unit in comp_units
                        for entry in unit.getEntries()]
        # TODO: Only recurse once here.  Is that enough?
        dwarfEntries.extend(
            [(child,unit) for unit in comp_units
             for entry in unit.getEntries()
                for child in entry.children])
        return dwarfEntries
        
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
            isPointer = False
            pointerSize = 0
            for (t,cu) in types:
                if t.kind == TAG.DW_TAG_pointer_type:
                    isPointer = True
                    pointerSize = t.getAttributeValue(ATTR.DW_AT_byte_size)
            members.append({
                "name": str(member.getName()),
                "offset": self.entryOffset(member),
                "size": types[0][0].getAttributeValue(ATTR.DW_AT_byte_size),
                "encoding": types[0][0].getAttributeValue(ATTR.DW_AT_encoding),
                "hasChildren": types[0][0].hasChildren(),
                "typeTree": types,
                "isUnion": types[0][0].kind == TAG.DW_TAG_union_type,
                "isStruct": types[0][0].kind == TAG.DW_TAG_structure_type,
                "isArray": isArray,
                "isPointer": isPointer,
                "pointerSize": pointerSize,
                "arrayLength": arrayLength,
                "isBitfield": isBitfield,
                "bitOffset": bitOffset,
                "bitCount": bitCount,
                "children": children
            })
        return members

    def structMemberValue(self, baseAddress, member):
        if member['isStruct']:
            return "{...}"
        if member['isUnion']:
            return "{...}"
        addr = baseAddress + member['offset']
        varlength = member['size']
        readlength = varlength
        if member['isArray']:
            readlength = readlength * member['arrayLength']
        elif member['isPointer']:
            varlength = member['pointerSize']
            readlength = member['pointerSize']
        data = self.memoryIface.getMemoryContents(addr, readlength, virtual=True)
        fmt = "%s"
        if member['isPointer']:
            fmt = ("(%s*) " % str(member['typeTree'][0][0].getAttributeValue(ATTR.DW_AT_name))) + "0x%x" + fmt
        elif member['encoding'] == ATE.DW_ATE_unsigned_char:
            fmt = "'%c'" + fmt
        else:
            fmt = "%d" + fmt
        result = ""
        if member['isArray']:
            result += "["
        intArray = self.dataArrayToInts(data, varlength, member['encoding'])
        intCount = len(intArray)
        for idx,val in enumerate(intArray):
            result += fmt % (val, ', ' if (idx < intCount-1) else '')
        if member['isArray']:
            result += "]"
        return result
        

    def dataArrayToInts(self, data, intSize, encoding):
        """Given a list of bytes |data|, return a list of ints of |intSize| bytes.
        
If |value| is not divisible by intSize, returns array of 1-byte ints."""
        fmtMap = {1: "<B", 2: "<H", 4: "<I", 8: "<Q"}
        if len(data) % intSize != 0 or intSize not in fmtMap:
            intSize = 1
        fmt = fmtMap[intSize]
        fmt = fmt.lower() if (encoding == ATE.DW_ATE_signed or
                              encoding == ATE.DW_ATE_signed_char) else fmt.upper()
        result = []
        for val in [data[x:x+intSize] for x in xrange(0, len(data), intSize)]:
            result.append(struct.unpack(fmt, val.tostring())[0])
        return result
