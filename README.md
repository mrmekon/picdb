## picdb
=====

Command-line debugger for Microchip PIC processors

Debugger written in jython.  Interacts with the Java API provided by Microchip in the MPLAB X installation.

For now this is an early demonstration, working only with the PICkit3 and PIC32MX150F128B processor.

Verify path to JARs is correct in picdb.sh, and run picdb.sh.


## Example session
=====
```
$ picdb.sh 
PICdb> connect PIC32MX150F128B    
content/mplab/mplab.deviceSupport
content/mplab/MPHeader.xml
content/mplab/PluginBoardSupport.xml
Connecting to PICkit3...
Nov 8, 2012 4:09:08 PM com.microchip.mplab.mdbcore.RealICETool.RIMessages OutputMessage
INFO: 

PICdb> load test.elf
Loading ELF file...
Resetting target...
PC: 0xBFC00000
PICdb> break 0x9D00B8C8
New breakpoint at 0x9D00B8C8 (MainDemo.c:431)
PICdb> break 0x9D00B982
New breakpoint at 0x9D00B982 (MainDemo.c:534)
PICdb> breakpoints
All breakpoints:
0: 0x9D00B8C8 (MainDemo.c:431) *
1: 0x9D00B982 (MainDemo.c:534) *
PICdb> continue
Breakpoint 1: Stopped at 0x9D00B982 (MainDemo.c:534)
PICdb> step
PC: 0x9D00B982  (MainDemo.c:534)  (LW V0, -32416(S0))
PICdb> print pc
PC: 0x9D00B9AC
PICdb> continue
Breakpoint 0: Stopped at 0x9D00B8C8 (MainDemo.c:431)
PICdb> 
PICdb> help
Type 'help <topic>' for help.

print               
continue            
step                Step over next source line.
break               
connect             Conects to a PIC target.
breakpoints         
help                Displays this help.
quit                Quits this program.
load                Load ELF file onto target.

PICdb> help connect

Connects to a PIC target.
Usage: connect <PIC device>
ex: connect PIC32MX150F128B

PICdb>   
```

## Reverse engineering notes
=====

Get public methods from classes in a jar:
$ i=debugger; javap -classpath com-microchip-mplab-open-hid.jar -s $(jar -tf com-microchip-mplab-open-hid.jar |grep class |sed 's/.class//g') |less

Save all public methods into text files:
$ for i in `ls *.jar`;do echo $i; javap -classpath $i -s $(jar -tf $i |grep class |sed 's/.class//g') > ~/pic_classes/$i.txt; done

Microchip's terrible command-line interface:
$ /Applications/microchip/mplabx/mplab_ide.app/Contents/Resources/mplab_ide/bin/mdb.sh

Edit mdb.sh to launch with:
$jvm -javaagent:/Users/trevor/Downloads/intrace-agent.jar ...

Trace java method calls with InTrace.app

Examples and some documentation available in PIC SDK.  Must register here:
http://www.opensource4pic.org/
