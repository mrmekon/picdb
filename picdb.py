import sys
import time
import string
import signal
from select import select

from mdb.picdebugger import picdebugger

class CommandHandler:
    def __init__(self, quitCB):
        self.quitCB = quitCB
        self.dbg = picdebugger()
        self._commandMap = {
            "connect": {'fn': self.cmdConnect, 'help': "Conects to a PIC target."},
            "load": {'fn': self.cmdLoad, 'help': "Load ELF file onto target."},
            "step": {'fn': self.cmdStep, 'help': "Step over next source line."},
            "quit": {'fn': self.cmdQuit, 'help': "Quits this program."},
            "help": {'fn': self.cmdHelp, 'help': "Displays this help."},
            "break": {'fn': self.cmdBreak},
            "continue": {'fn': self.cmdContinue},
            "print": {'fn': self.cmdPrint},
            "breakpoints": {'fn': self.cmdBreakpoints},
        }
        
    def cmdConnect(self, args):
        '''
Connects to a PIC target.
Usage: connect <PIC device>
ex: connect PIC32MX150F128B
'''
        splitargs = args.split(None)
        if len(splitargs) < 1:
            print "Not enough arguments"
        self.dbg.selectDevice(args)
        self.dbg.enumerateDevices()
        self.dbg.selectDebugger()
        self.dbg.connect()

    def cmdPrint(self, args):
        if args.lower() == "pc":
            print "PC: 0x%X" % self.dbg.getPC()
            
    def cmdLoad(self, args):
        self.dbg.load(args)
        self.dbg.reset()

    def cmdBreak(self, args):
        addr = int(args,0)
        self.dbg.setBreakpoint(addr)

    def cmdBreakpoints(self, args):
        self.dbg.listBreakpoints()
        
    def cmdContinue(self, args):
        self.dbg.run()
        self.dbg.waitForHalt()

        # It doesn't know where it is immediately after stopping.
        # But it also LIES.
        # Ask, wait, ask again.  It'll figure it out.
        # Hopefully.
        pc = self.dbg.getPC()
        time.sleep(1.0)
        pc = self.dbg.getPC()
        bp = self.dbg.breakpointIndexForAddress(pc)
        (file,line) = self.dbg.addressToSourceLine(pc)
        print "%sStopped at 0x%X (%s:%d)" % ("" if bp < 0 else "Breakpoint %d: " % bp,
                                             pc,file,line)

    def cmdStep(self, args):
        self.dbg.step()
        
    def cmdQuit(self, args):
        self.quitCB()
        
    def cmdHelp(self, args):
        if len(args) == 0:
            print "Type 'help <topic>' for help."
            print
            for x,info in self._commandMap.iteritems():
                line = x.ljust(20)
                if info.has_key('help'):
                    line += info['help']
                print line[0:80]
            print
        else:
            try:
                fn = self._commandMap[args]['fn']
                print fn.__doc__
            except KeyError:
                print "Nothing found for topic: %s" % args


class CommandInterpreter:
    def __init__(self):
        self.running = False
        self._handler = CommandHandler(self.stopInputLoop)

    def stopInputLoop(self):
        self.running = False
        signal.alarm(1)

    def _displayPrompt(self):
        sys.stdout.write("PICdb> ")
        sys.stdout.flush()
        
    def _readUserInput(self):
        try:
            user_input = raw_input()
            return user_input.strip()
        except EOFError:
            self.running = False
            return ""

    def _stringStartsWithCmd(self, str, cmd):
        matches = False
        n = len(cmd)
        m = len(str)
        if str[0:n].lower() == cmd.lower():
            if m == n or (m > n and str[n] not in string.ascii_letters):
                matches = True
        return matches
    
    def runInputLoop(self):
        signal.signal(signal.SIGINT, lambda x,y: self.stopInputLoop())
        self.running = True
        while self.running:
            self._displayPrompt()
            user_input = self._readUserInput()
            if user_input == "":
                continue
            for cmd,info in self._handler._commandMap.iteritems():
                if self._stringStartsWithCmd(user_input, cmd):
                    info['fn'](user_input[len(cmd):].strip())
        print
        self._handler.dbg.disconnect()

interp = CommandInterpreter()
interp.runInputLoop()

