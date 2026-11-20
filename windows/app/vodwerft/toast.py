"""Windows-Benachrichtigung (Toast) anzeigen, ohne zusätzliche Programme: über Windows PowerShell.

Der Text geht als verschlüsselter Befehl (-EncodedCommand) hinein, damit Anführungszeichen, Umlaute und Zeilenumbrüche
nie das Skript verändern können. Die Benachrichtigung erscheint unter dem Namen von Windows PowerShell (so ist sie
ohne Registrierung einer eigenen App möglich). Ein Fehler hier darf nie etwas anderes stören.
"""
import base64
import subprocess
import sys
from xml.sax.saxutils import escape

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
SCRIPT = """
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('{xml}')
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{app}').Show($toast)
"""


def toast_xml(title, text):
    """XML der Benachrichtigung. Alles wird maskiert; der Text wird auf eine sinnvolle Länge gekürzt."""
    lines = [escape(str(title)[:80]), *(escape(line[:120]) for line in str(text).splitlines()[:2])]
    body = "".join(f"<text>{line}</text>" for line in lines)
    return f'<toast><visual><binding template="ToastGeneric">{body}</binding></visual></toast>'


def command(title, text):
    """Argumente für powershell.exe (zum Testen getrennt vom Start)."""
    xml = toast_xml(title, text).replace("'", "''")  # PowerShell: ein Apostroph in '…' wird verdoppelt
    script = SCRIPT.format(xml=xml, app=APP_ID)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded]


def show(title, text, run=subprocess.Popen):
    """Zeigt die Benachrichtigung (startet PowerShell im Hintergrund, wartet nicht). True, wenn gestartet."""
    if sys.platform != "win32":
        return False
    try:
        run(command(title, text), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            creationflags=NO_WINDOW)
    except (OSError, ValueError):
        return False
    return True
