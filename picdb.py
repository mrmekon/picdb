import os
import sys
import pdb
import bdb
import time
import string
import signal
import operator

from mdb.picdebugger import picdebugger

class CommandHandler:
    def __init__(self, quitCB):
        self.dbg = picdebugger()
        self._quitCB = quitCB
        self._commandMap = {
        "connect": {'fn': self.cmdConnect, 'help': "Conects to a PIC target."},
        "load": {'fn': self.cmdLoad, 'help': "Load ELF file onto target."},
        "step": {'fn': self.cmdStep, 'help': "Step over next source line."},
        "quit": {'fn': self.cmdQuit, 'help': "Quits this program."},
        "help": {'fn': self.cmdHelp, 'help': "Displays this help."},
        "debug": {'fn': self.cmdDebug, 'help': "Drop to Python console."},
        "break": {'fn': self.cmdBreak, 'help': "Set breakpoint."},
        "continue": {'fn': self.cmdContinue, 'help': "Continue running target."},
        "print": {'fn': self.cmdPrint, 'help': "Print variable."},
        "breakpoints": {'fn': self.cmdBreakpoints, 'help': "List breakpoints."},
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
        '''
Prints a variable or register.
Usage: print <variable or register>
Supported registers:
 * $pc
'''
        if args.lower() == "$pc":
            print "PC: 0x%X" % self.dbg.getPC()

    def cmdDebug(self, args):
        '''
Drops to a Python prompt for debug-level introspection.
Usage: debug
'''
        pdb.set_trace()
            
    def cmdLoad(self, args):
        '''
Load an ELF file onto target board.
Usage: load <file>
<file> can be a full absolute path, or relative to the working directory.
'''
        self.dbg.load(args)
        self.dbg.reset()

    def cmdBreak(self, args):
        '''
Set a breakpoint
Usage: break <address>
<address> is a memory address specified in decimal, or hexadecimal with an '0x'
prefix.
'''
        addr = int(args,0)
        self.dbg.setBreakpoint(addr)

    def cmdBreakpoints(self, args):
        '''
List all set breakpoints.  Outputs a numbered list of breakpoints, their memory
address, their source file and line, and an asterisk if they are enabled.
Usage: breakpoints
'''
        self.dbg.listBreakpoints()
        
    def cmdContinue(self, args):
        '''
Continue running target from current PC.
Usage: continue
'''
        self.dbg.run()
        self.dbg.waitForHalt() # block

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
        '''
Step target over one line of source.
Usage: step
'''
        self.dbg.step()
        
    def cmdQuit(self, args):
        '''
Quit debugger.
Usage: quit
'''
        self._quitCB()
        
    def cmdHelp(self, args):
        '''
Request list of commands, or help on a specific command.
Usage: help [command]
'''
        if len(args) == 0:
            print "Type 'help <topic>' for help."
            print
            for x,info in sorted(self._commandMap.iteritems(),key=operator.itemgetter(0)):
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
        signal.signal(signal.SIGINT, self.sigIntHandler)

    def stopInputLoop(self):
        '''Set main loop to stop running.'''
        self.running = False

    def _cleanShutdown(self):
        '''Disconnect from debugger and quit.'''
        self._handler.dbg.disconnect()
        sys.exit(0) # this will interrupt raw_input()

    def sigIntHandler(self, sig, frame):
        '''Quit cleanly on ^C.'''
        self.stopInputLoop()
        self._cleanShutdown()

    def _displayPrompt(self):
        '''Display the debugger prompt.'''
        sys.stdout.write("PICdb> ")
        sys.stdout.flush()
        
    def _readUserInput(self):
        '''Wait for (and return) input from user.  EOF terminates.'''
        try:
            user_input = raw_input()
            return user_input.strip()
        except EOFError:
            self.stopInputLoop()
            return ""

    def _stringStartsWithCmd(self, str, cmd):
        '''Determine if string from user starts with a known command.'''
        matches = False
        n = len(cmd)
        m = len(str)
        if str[0:n].lower() == cmd.lower():
            if m == n or (m > n and str[n] not in string.ascii_letters):
                matches = True
        return matches

    
    def _mainLoop(self):
        '''Main loop listening for commands from user.'''
        while self.running:
            self._displayPrompt()
            user_input = self._readUserInput()
            if user_input == "":
                continue
            for cmd,info in self._handler._commandMap.iteritems():
                if self._stringStartsWithCmd(user_input, cmd):
                    info['fn'](user_input[len(cmd):].strip())
        print
        
    
    def run(self):
        '''Run debugger.'''
        self.running = True
        # Wrap the whole main loop in an outer loop here so we can catch
        # exceptions from the pdb debugger.
        while self.running:
            try:
                self._mainLoop()
            except bdb.BdbQuit:
                pass # pdb quit, but we're still runnin'
        self._cleanShutdown()

if __name__ == "__main__":
    interp = CommandInterpreter()
    interp.run()

