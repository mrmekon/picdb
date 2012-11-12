MPLAB_JAR_PATH=/Applications/microchip/mplabx/mplab_ipe.app/Contents/Resources/Java/lib
JAVAARGS=
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
CLASSPATH=$(echo "$MPLAB_JAR_PATH/"*.jar | tr ' ' ':') jython $JAVAARGS "$DIR"/picdb.py "$@"

