import os
import shutil
import sys

# Post-build cleanup: remove unused Qt6 binaries/qml/plugins from onedir bundle.
# Target: Qt Widgets-only app (no Quick/Quick3D/Pdf/3D/Designer/Multimedia/...)
# All these modules are bundled by the PyQt6-Qt6 wheel but never imported.

ROOT = os.path.join('dist', 'DeployTool', '_internal', 'PyQt6', 'Qt6')
BIN = os.path.join(ROOT, 'bin')
QML = os.path.join(ROOT, 'qml')
PLUGINS = os.path.join(ROOT, 'plugins')
TRANS = os.path.join(ROOT, 'translations')
QSCI = os.path.join(ROOT, 'qsci')

# These Qt modules are NOT used by a Widgets-only PyQt6 app.
UNUSED_PREFIXES = (
    'Qt6Quick', 'Qt6Qml', 'Qt6Pdf', 'Qt6Designer', 'Qt6Multimedia',
    'Qt6WebEngine', 'Qt6Sql', 'Qt6Svg', 'Qt6Help', 'Qt6RemoteObjects',
    'Qt6DBus', 'Qt6Xml', 'Qt6PrintSupport', 'Qt6Test', 'Qt6SerialPort',
    'Qt6Bluetooth', 'Qt6Nfc', 'Qt6Positioning', 'Qt6Location', 'Qt6Sensors',
    'Qt6Charts', 'Qt6DataVisualization', 'Qt6StateMachine', 'Qt6TextToSpeech',
    'Qt6SpatialAudio', 'Qt6Concurrent', 'Qt6QmlIntegration',
    'Qt6ShaderTools', 'Qt6OpenGL', 'Qt6OpenGLWidgets', 'Qt6SvgWidgets',
    'avcodec', 'avformat', 'avutil', 'swscale',
    'opengl32sw', 'd3dcompiler_47',
)

# QML root modules not used
UNUSED_QML_DIRS = (
    'QtQml', 'QtQuick', 'QtQuick3D', 'QtPdf', 'QtMultimedia',
    'QtWebChannel', 'QtWebSockets', 'QtSensors', 'QtTest',
    'QtTextToSpeech', 'QtRemoteObjects', 'QtCharts',
    'QtPositioning', 'QtLocation', 'QtBluetooth', 'QtNfc',
    'QtSql', 'QtSvg',
    'QtDesigner', 'QtStudio3D', 'QtStateMachine', 'QtDataVisualization',
    'QtWayland', 'QtMultimediaQuick', 'QtSensorsQuick', 'QtPdfQuick',
    'QtPositioningQuick', 'QtTextToSpeech',
)

# Plugin subdirs not used
UNUSED_PLUGIN_DIRS = (
    'assetimporters', 'geometryloaders', 'help', 'multimedia',
    'networkinformation', 'qmllint', 'qmlls', 'renderers',
    'sceneparsers', 'scxmldatamodel', 'sensors', 'sqldrivers',
    'styles', 'wayland', 'wayland-shell-integration',
    'wayland-decoration', 'wayland-graphics-integration-client',
    'xcbglintegrations', 'tls', 'egldeviceintegrations',
)

removed_bytes = 0
removed_files = 0

def remove_unused_files(directory, predicate):
    if not os.path.isdir(directory):
        return
    global removed_bytes, removed_files
    for name in os.listdir(directory):
        p = os.path.join(directory, name)
        if not os.path.isfile(p):
            continue
        if predicate(name):
            sz = os.path.getsize(p)
            try:
                os.remove(p)
                removed_bytes += sz
                removed_files += 1
            except Exception as e:
                print('  skip: %s (%s)' % (name, e))

def remove_dir_matching(root, names):
    if not os.path.isdir(root):
        return
    global removed_bytes, removed_files
    for n in names:
        p = os.path.join(root, n)
        if os.path.isdir(p):
            sz = 0
            for dp, _, fns in os.walk(p):
                for fn in fns:
                    fp = os.path.join(dp, fn)
                    if os.path.isfile(fp):
                        sz += os.path.getsize(fp)
            try:
                shutil.rmtree(p)
                removed_bytes += sz
                print('  rmdir: %s (%.1fMB)' % (n, sz / 1024 / 1024))
            except Exception as e:
                print('  skip rmdir: %s (%s)' % (n, e))

print('=== Cleaning unused Qt6 binaries ===')
remove_unused_files(BIN, lambda n: any(n.startswith(p) and (n.endswith('.dll') or n.endswith('.pyd')) for p in UNUSED_PREFIXES))
print('=== Cleaning unused QML modules ===')
remove_dir_matching(QML, UNUSED_QML_DIRS)
print('=== Cleaning unused plugins ===')
remove_dir_matching(PLUGINS, UNUSED_PLUGIN_DIRS)
print('=== Cleaning translations (zh_CN, en_US) ===')
if os.path.isdir(TRANS):
    keep_langs = {'en', 'en_US', 'zh_CN', 'zh'}
    for n in os.listdir(TRANS):
        if n.startswith('qt_') and not any(lang in n for lang in keep_langs):
            p = os.path.join(TRANS, n)
            if os.path.isfile(p):
                os.remove(p)
                removed_bytes += os.path.getsize(p) if os.path.exists(p) else 0
print('=== Cleaning qsci (API files for QScintilla, unused) ===')
if os.path.isdir(QSCI):
    shutil.rmtree(QSCI)
print()
print('Cleanup done: removed %d files, %.1fMB total' % (removed_files, removed_bytes / 1024 / 1024))
