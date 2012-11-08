picdb
=====

Command-line debugger for Microchip PIC processors


Reverse engineering notes
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
