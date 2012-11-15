MPLABX_ROOT=/Applications/microchip/mplabx
MPLAB_JAR_PATH="$MPLABX_ROOT/mplab_ipe.app/Contents/Resources/Java/lib"
#NETBEANS_JAR_PATH="$MPLABX_ROOT/mplab_ide.app/Contents/Resources/mplab_ide/ide/modules"
NETBEANS_JAR_PATH=
#JAVAARGS=-J-javaagent:/Users/trevor/Downloads/intrace-agent.jar
JAVAARGS=
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
CLASSPATH=$(echo "$MPLAB_JAR_PATH/"*.jar "$NETBEANS_JAR_PATH/"*.jar | tr ' ' ':') jython $JAVAARGS "$DIR"/picdb.py "$@"

