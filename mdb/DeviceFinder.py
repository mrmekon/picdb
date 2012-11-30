from com.microchip.mplab.mdbcore.platformtool import PlatformToolMetaManager

class DeviceFinder:
    def __init__(self, provider, factory, assembly):
        self.provider = provider
        self.factory = factory
        self.assembly = assembly
        self.devices = []

    def enumerateDevices(self):
        """Enumerate USB debuggers."""
        try:
            self.devices = self.provider.GetCurrentToolList(None, "USB","04D8", None)
            if not self.devices:
                print "No USB debugger found."
        except DebugException:
            print "Failed to enumerate USB devices."
            return False
        return True

    def connectedDeviceStrings(self):
        devs = []
        for i in self.devices:
            dev = self.devices[i]
            sn = dev.split(":=")[7]
            devID = ''.join(["0x",dev.split(":=")[3]])
            tool = [x for x in PlatformToolMetaManager.getAllTools()
                    if devID in x.USBProductIDs][0]
            devs.append("%d: %s (%s)" % (i, tool.getName(), sn))
        return devs

    def selectDebugger(self):
        alltools = PlatformToolMetaManager.getAllTools()
        devid = ''.join(["0x",self.devices[0].split(":=")[3]])
        tool = [x for x in alltools if devid in x.USBProductIDs][0]
        self.factory.ChangeTool(self.assembly,
                                tool.getConfigurationObjectID(),
                                tool.getClassName(),
                                tool.getFlavor(),
                                self.devices[0])
        self.factory.SetToolProperties(self.assembly,None)

    def getDeviceFamily(self):
        """Returns string describing target device"""
        bits = self.assembly.GetDevice().getFamilyCode()
        return self.assembly.GetDevice().getSubFamily()
